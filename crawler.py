import argparse
import json
import os
import random
import re
import time
from datetime import datetime

from curl_cffi import requests as cffi   # py -m pip install curl_cffi

from config import CRAWL_LOG_FILE, HTML_DIR, STATE_FILE

BASE = "https://worldfootball.com"
SEEDS = ["/people/b-saka/640", "/europe/england/teams/arsenal/37",
         "/europe/england/competitions/premier-league",
         "/europe/spain/competitions/la-liga",
         "/europe/germany/competitions/bundesliga",
         "/europe/italy/competitions/serie-a",
         "/europe/france/competitions/ligue-1"]

IMPERSONATE = "chrome"                   # curl_cffi: TLS odtlacok + hlavicky ako Chrome
TIMEOUT = 20
DELAY = (2.0, 3.0)                       # nahodny delay medzi requestami [s]
COOLDOWN = [10, 30, 60, 120]             # pauza pri bloku podla poctu blokov za sebou [s]
SAVE_EVERY = 10                          # ulozit stav kazdych N stranok
TEAM_EVERY = 25                          # kazda 25. stranka je tim (novi hraci z inych klubov)
COMP_EVERY = 200                         # kazda 200. stranka je sutaz (nove timy)

# typy URL: hrac (ukladame), tim a sutaz (iba zdroj linkov)
RE_PLAYER = re.compile(r"^/people/[^/]+/\d+$")
RE_TEAM = re.compile(r"^/[a-z-]+(?:/[a-z-]+)?/teams/[^/]+/\d+$")
RE_COMP = re.compile(r"^/[a-z-]+/[a-z-]+/competitions/[^/]+$")
RE_HREF = re.compile(r'href="(/[^"#?]*)"')
RE_BLOCK = re.compile(r"Just a moment|cf-chl|Attention Required")
# statusy v logu, ktore sa na konci skusia znova (CF = challenge stranka so statusom 200)
RETRY_STATUS = re.compile(r"^(CF|None|403|429|5\d\d)$")
FORBIDDEN = ("/api/", "/cms", "/healthz", "/ops")
# ukladame iba hracov s bio a tabulkou statistik (nie trenerov, personal ...)
RE_BIO = re.compile(r'class="player-bio[^"]*"[^>]*>\s*<p>\s*[^<\s]')
RE_STATS = re.compile(r'class="[^"]*player-career-table')


def is_player(html):
    return bool(RE_BIO.search(html) and RE_STATS.search(html))


def kind(path):
    if RE_PLAYER.match(path):
        return "player"
    if RE_TEAM.match(path):
        return "team"
    if RE_COMP.match(path):
        return "comp"
    return None


def hms(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


class Crawler:
    def __init__(self):
        os.makedirs(HTML_DIR, exist_ok=True)
        self.queues = {"player": [], "team": [], "comp": []}
        self.seen = set()      # vsetko co uz bolo vo fronte
        self.done = set()      # uspesne spracovane
        self.saved = 0         # hraci na disku (celkovo)
        self.bytes = 0
        self.picks = 0         # pocet vybrani z fronty (pre TEAM_EVERY / COMP_EVERY)
        self.retry = None      # neuspesne URL z logu (nacitaju sa, ked sa minu fronty)
        self.retry_only = False
        self.session = cffi.Session(impersonate=IMPERSONATE)  # drzi spojenie a cookies
        self.load_state()
        # seedy (aj nove, pridane neskor) idu na rad ako prve
        self.first = [p for p in SEEDS if p not in self.done]

    # --- stav (pokracovanie po pade) ---
    def load_state(self):
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                s = json.load(f)
            self.done = set(s["done"])
            self.seen = set(s["seen"])
            for k, q in s["queues"].items():
                self.queues[k].extend(q)
        for p in SEEDS:
            self.add(p)                        # pri pokracovani prida iba nove seedy
        # rozhoduje to co lezi na disku (stav sa nemusel stihnut ulozit)
        files = [f for f in os.listdir(HTML_DIR) if f.endswith(".html")]
        for f in files:
            pid, slug = f[:-5].split("_", 1)
            path = f"/people/{slug}/{pid}"
            self.done.add(path)
            self.seen.add(path)
        self.queues["player"] = [p for p in self.queues["player"] if p not in self.done]
        self.saved = len(files)
        self.bytes = sum(os.path.getsize(os.path.join(HTML_DIR, f)) for f in files)

    def save_state(self):
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"done": list(self.done), "seen": list(self.seen),
                       "queues": {k: list(q) for k, q in self.queues.items()}}, f)
        os.replace(tmp, STATE_FILE)

    # --- fronta: najprv seedy, potom hraci; kazda 25. stranka tim, kazda 200. sutaz ---
    # z fronty vyberam nahodne, aby sa mixovali hraci z roznych lig
    def add(self, path):
        path = path.rstrip("/")
        if path in self.seen or path.startswith(FORBIDDEN):
            return
        k = kind(path)
        if k:
            self.seen.add(path)
            self.queues[k].append(path)

    def next(self):
        if self.retry_only:                    # --retry: iba neuspesne URL z logu
            return (kind(self.retry[0]), self.retry.pop(0)) if self.retry else (None, None)
        while self.first:
            p = self.first.pop(0)
            k = kind(p)
            if p in self.queues[k]:
                self.queues[k].remove(p)
                return k, p
        self.picks += 1
        order = ("player", "team", "comp")
        if self.picks % COMP_EVERY == 0:
            order = ("comp", "team", "player")
        elif self.picks % TEAM_EVERY == 0:
            order = ("team", "comp", "player")
        for k in order:
            q = self.queues[k]
            while q:
                i = random.randrange(len(q))
                q[i], q[-1] = q[-1], q[i]
                p = q.pop()
                if p not in self.done:
                    return k, p
        # fronty su prazdne -> este raz skusit neuspesne URL z logu
        if self.retry is None:
            self.retry = self.failed_from_log()
            print(f"Fronty su prazdne - opakujem {len(self.retry)} neuspesnych URL z logu.")
        if self.retry:
            p = self.retry.pop(0)
            return kind(p), p
        return None, None

    def failed_from_log(self):
        """URL, ktore v logu maju status z RETRY_STATUS a stale nie su stiahnute."""
        failed = {}
        if os.path.exists(CRAWL_LOG_FILE):
            with open(CRAWL_LOG_FILE, encoding="utf-8") as f:
                next(f, None)                  # hlavicka
                for line in f:
                    cols = line.rstrip("\n").split("\t")
                    if len(cols) == 6 and RETRY_STATUS.match(cols[1]):
                        failed[cols[5]] = True
        return [p for p in failed if p not in self.done and kind(p)]

    # --- HTTP: curl_cffi napodobni Chrome (TLS odtlacok + hlavicky), urllib Cloudflare blokoval ---
    def fetch(self, path):
        """Vrati (status, html). Jeden pokus; challenge stranka Cloudflare -> status "CF"."""
        try:
            r = self.session.get(BASE + path, timeout=TIMEOUT)
            status, html = r.status_code, r.text
        except Exception as e:                 # timeout, vypadok siete -> status None
            status, html = None, str(e)
        if status == 200 and RE_BLOCK.search(html):
            status = "CF"
        return status, html

    # --- hlavna slucka ---
    def run(self, target, retry_only=False):
        q = self.queues
        if retry_only:
            self.retry_only = True
            self.retry = self.failed_from_log()
        print("=" * 80)
        if retry_only:
            print(f"Rezim --retry: opakujem {len(self.retry)} neuspesnych URL z logu")
        print(f"Ciel: {target or 'bez limitu (kym je co crawlovat)'} | "
              f"uz stiahnutych: {self.saved} hracov ({self.bytes / 2**20:.1f} MB)")
        print(f"Fronta: hraci {len(q['player'])}, timy {len(q['team'])}, sutaze {len(q['comp'])}")
        print("Zastavenie: Ctrl+C (pokracuje sa pri dalsom spusteni)")
        print("=" * 80)

        start = time.time()
        new = pages = errors = skipped = 0
        streak = 0                             # pocet blokov/chyb za sebou (pre COOLDOWN)
        log = open(CRAWL_LOG_FILE, "a", encoding="utf-8")
        if log.tell() == 0:
            log.write("time\tstatus\tkind\tbytes\tseconds\turl\n")
        try:
            while retry_only or not target or self.saved < target:
                k, path = self.next()
                if path is None:
                    print("Hotovo - vsetky neuspesne URL skusene." if retry_only
                          else "Fronta je prazdna - nie su dalsie odkazy.")
                    break
                t = time.time()
                status, html = self.fetch(path)
                dt = time.time() - t
                size = len(html.encode("utf-8"))
                pages += 1
                log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{status}\t{k}\t{size}\t{dt:.2f}\t{path}\n")
                log.flush()

                if status == 200:
                    for href in RE_HREF.findall(html):
                        self.add(href)
                    if k == "player" and not is_player(html):
                        k = "skip"             # bez bio alebo statistik -> neukladam
                        skipped += 1
                    elif k == "player":
                        _, slug, pid = path.split("/")[1:]
                        with open(os.path.join(HTML_DIR, f"{pid}_{slug}.html"), "w", encoding="utf-8") as f:
                            f.write(html)
                        self.saved += 1
                        self.bytes += size
                        new += 1
                    self.done.add(path)
                else:
                    errors += 1                # URL ostane v logu so statusom -> retry na konci

                pause = random.uniform(*DELAY)
                if RETRY_STATUS.match(str(status)):
                    streak += 1
                    pause = COOLDOWN[min(streak, len(COOLDOWN)) - 1]
                    print(f"  ! blok/chyba (status={status}) -> retry na konci, pauza {pause}s")
                else:
                    streak = 0

                el = time.time() - start
                if target:
                    left = max(target - self.saved, 0)
                    eta = hms(el / new * left) if new else "?"
                    head = (f"[{self.saved}/{target} {self.saved / target * 100:5.1f}%] "
                            f"zostava {left} | ETA {eta} | ")
                else:
                    head = f"[{self.saved} hracov] "
                print(f"{head}{self.bytes / 2**20:.1f} MB | "
                      f"beh: +{new} hracov, {skipped} preskocenych, {pages} stranok, {errors} chyb, "
                      f"{hms(el)} | "
                      f"fronta H{len(q['player'])} T{len(q['team'])} S{len(q['comp'])}")
                print(f"    {status} {k} {size / 1024:.0f} KB {path}")
                if pages % SAVE_EVERY == 0:
                    self.save_state()
                time.sleep(pause)
            else:
                print(f"Ciel {target} hracov dosiahnuty.")
        except KeyboardInterrupt:
            print("\nPrerusene (Ctrl+C).")
        finally:
            self.save_state()
            log.close()
            print(f"Stav ulozeny: {self.saved} hracov, {self.bytes / 2**20:.1f} MB "
                  f"(tento beh +{new}, {hms(time.time() - start)})")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Crawler hracov z worldfootball.com")
    ap.add_argument("--target", type=int, default=None,
                    help="celkovy pocet hracov (default: bez limitu, kym je co crawlovat)")
    ap.add_argument("--retry", action="store_true", help="iba zopakovat neuspesne URL z logu")
    a = ap.parse_args(argv)
    Crawler().run(a.target, a.retry)


if __name__ == "__main__":
    main()
