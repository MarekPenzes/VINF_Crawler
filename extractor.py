"""Regex extraktor: data/html/*.html -> data/players.tsv (1 riadok = 1 hrac)
                                      data/career.tsv  (1 riadok = sezona x tim x sutaz)"""
import argparse
import html
import json
import os
import re

from config import CAREER_FILE, HTML_DIR, PLAYERS_FILE
from tsv import RE_SPACE, tsv_header, tsv_line

PLAYER_COLS = ["id", "name", "position", "club", "nationality", "birth_date",
               "height_cm", "foot", "club_apps", "club_goals", "club_assists",
               "national_team", "nat_apps", "nat_goals", "nat_assists", "url", "bio"]
CAREER_COLS = ["player_id", "section", "season", "team", "competition", "apps", "lineups",
               "sub_on", "sub_off", "goals", "penalties", "assists", "yellow", "second_yellow",
               "red", "rating"]

# subor data/html/{id}_{slug}.html
RE_FILE = re.compile(r"^(\d+)_(.+)\.html$")

# zakladne udaje: JSON-LD blok typu Person v hlavicke stranky
RE_PERSON = re.compile(r'<script type="application/ld\+json">'
                       r'(\{"@context":"https://schema.org","@type":"Person".*?)</script>')
JSON_STR = r'"((?:[^"\\]|\\.)*)"'                # JSON retazec vratane escape (\" \n \u00e9)
RE_LD_NAME = re.compile(r'"name":' + JSON_STR)  # prve "name" v bloku = meno hraca
RE_LD_URL = re.compile(r'"url":' + JSON_STR)
RE_LD_BIRTH = re.compile(r'"birthDate":"(\d{4}-\d{2}-\d{2})"')
RE_LD_NATION = re.compile(r'"nationality":' + JSON_STR)
RE_LD_CLUB = re.compile(r'"memberOf":\{[^}]*"name":' + JSON_STR)
RE_LD_POSITION = re.compile(r'"jobTitle":' + JSON_STR)

# hlavicka stranky: vyska a noha (v JSON-LD nie su)
RE_HERO_META = re.compile(r'class="page-hero__meta">(.*?)</div>', re.S)
RE_HEIGHT = re.compile(r">(\d{3}) cm<")
RE_FOOT = re.compile(r">(Left|Right|Both)-footed<")

# bio: odstavce <p> v bloku id="player-bio-copy" (konci tlacidlom "Read more" alebo datumom)
RE_BIO_BLOCK = re.compile(r'id="player-bio-copy"[^>]*>(.*?)'
                          r'(?:<button class="player-bio-toggle"|<p class="player-bio-updated"|</section>)', re.S)
RE_PARAGRAPH = re.compile(r"<p>(.*?)</p>", re.S)

# tabulky kariery: kazda je v paneli id="career-{club|national}-{team|season|detailed}-panel"
RE_PANEL = re.compile(r'id="career-(club|national)-(team|detailed)-panel"(.*?)</table>', re.S)
RE_TH = re.compile(r"(<th[^>]*>.*?</th>)", re.S)
RE_TH_TITLE = re.compile(r'^<th[^>]*title="([^"]+)"')
RE_SORT_FACE = re.compile(r'class="data-table__sort-face">([^<]+)<')
RE_TBODY = re.compile(r"<tbody[^>]*>(.*?)</tbody>", re.S)
RE_TFOOT = re.compile(r"<tfoot[^>]*>(.*?)</tfoot>", re.S)
RE_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
RE_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
RE_TITLE_SPAN = re.compile(r'<span title="([^"]+)"')  # plny nazov timu/sutaze (text byva skrateny)
RE_TAG = re.compile(r"<[^>]+>")
# mladeznicky alebo rezervny tim: "Belgium U21", "Brazil Olympic", "Austria Wien II" (chyba webu
# v tabulke reprezentacii)
RE_YOUTH_TEAM = re.compile(r"\bU\d{2}\b|\bOlympic\b|\bII\b")

# hlavicka stlpca tabulky po timoch -> kluc riadku
TEAM_HEADERS = {"Team": "team", "Appearances": "apps", "Goals": "goals", "Assists": "assists"}
# hlavicka stlpca podrobnej tabulky -> nazov stlpca v career.tsv
DETAILED_HEADERS = {"Season": "season", "Team": "team", "Competition": "competition",
                    "Appearances": "apps", "Line-ups": "lineups", "Substituted on": "sub_on",
                    "Substituted off": "sub_off", "Goals": "goals", "Penalties": "penalties",
                    "Assists": "assists", "Yellow cards": "yellow",
                    "Second yellow cards": "second_yellow", "Red cards": "red",
                    "Average rating": "rating"}
EMPTY_VALUES = {"?", "-", "\u2013", "\u2014"}    # stranka tak oznacuje neznamu hodnotu -> ""
GROUP_COLS = ["season", "team"]                  # zoskupene stlpce, prazdna bunka = ako riadok vyssie


def clean(text):
    """HTML -> cisty text na jeden riadok (bez tagov, entit, tabulatorov a novych riadkov)."""
    return RE_SPACE.sub(" ", html.unescape(RE_TAG.sub(" ", text))).strip()


def find(regex, text):
    m = regex.search(text)
    return m.group(1) if m else ""


def find_json(regex, text):
    """Ako find, ale hodnotu dekoduje ako JSON retazec (\\" \\n \\u00e9 -> znaky)."""
    value = find(regex, text)
    return json.loads(f'"{value}"') if value else ""


def cell_text(td):
    """Text bunky; ak ma bunka plny nazov v title (napr. "Man. Utd." -> Manchester United), berie ten."""
    title = RE_TITLE_SPAN.search(td)
    value = html.unescape(title.group(1)) if title else clean(td)
    return "" if value in EMPTY_VALUES else value


def header_name(th):
    """Nazov stlpca: atribut title na <th> (ciselne stlpce), inak text tlacidla (Season, Team ...)."""
    return find(RE_TH_TITLE, th) or find(RE_SORT_FACE, th)


def extract_person(page):
    """Udaje z JSON-LD bloku a hlavicky stranky."""
    ld = find(RE_PERSON, page)
    meta = find(RE_HERO_META, page)
    return {"name": find_json(RE_LD_NAME, ld),
            "position": find_json(RE_LD_POSITION, ld),
            "club": find_json(RE_LD_CLUB, ld),
            "nationality": find_json(RE_LD_NATION, ld),
            "birth_date": find(RE_LD_BIRTH, ld),
            "height_cm": find(RE_HEIGHT, meta),
            "foot": find(RE_FOOT, meta),
            "url": find_json(RE_LD_URL, ld)}


def extract_bio(page):
    block = find(RE_BIO_BLOCK, page)
    return " ".join(clean(p) for p in RE_PARAGRAPH.findall(block))


def extract_totals(table):
    """Riadok "Career total" tabulky po timoch: tim+prestup | obdobie | zapasy | goly | asistencie | ..."""
    tfoot = find(RE_TFOOT, table)
    cells = [cell_text(td) for td in RE_TD.findall(tfoot)]
    if len(cells) < 5:
        return {"apps": "", "goals": "", "assists": ""}
    return {"apps": cells[2], "goals": cells[3], "assists": cells[4]}


def team_rows(table):
    """Riadky tabulky po timoch (bez Career total) ako {team, apps, goals, assists} podla hlavicky."""
    headers = [TEAM_HEADERS.get(header_name(th)) for th in RE_TH.findall(table)]
    rows = []
    for tr in RE_TR.findall(find(RE_TBODY, table)):
        rows.append({col: cell_text(td) for col, td in zip(headers, RE_TD.findall(tr)) if col})
    return rows


def main_team(rows):
    """Riadok hlavneho timu: prvy seniorsky (bez U17, U21, Olympic, II), inak prvy riadok, {} ak nie je.
    Stranka moze mat mladeznicky tim na prvom mieste aj pri hracovi, ktory hra za A-tim."""
    seniors = [row for row in rows if not RE_YOUTH_TEAM.search(row.get("team", ""))]
    return (seniors or rows or [{}])[0]


def extract_detailed(table, section):
    """Riadky podrobnej tabulky (sezona x tim x sutaz); stlpce sa mapuju podla hlavicky."""
    headers = [DETAILED_HEADERS.get(header_name(th)) for th in RE_TH.findall(table)]
    rows = []
    for tr in RE_TR.findall(find(RE_TBODY, table)):
        row = {"section": section}
        for col, td in zip(headers, RE_TD.findall(tr)):
            if col:
                row[col] = cell_text(td)
        for col in GROUP_COLS:                # rovnaka hodnota ako riadok vyssie -> stranka ju nevypise
            if not row.get(col) and rows:
                row[col] = rows[-1].get(col, "")
        rows.append(row)
    return rows


def extract_career(page):
    """Vrati (suhrn klubu a reprezentacie, riadky kariery).
    Klub: Career total za vsetky kluby. Reprezentacia: iba riadok hlavneho timu, lebo Career total
    by spocital A-tim spolu s mladeznickymi vybermi (England + England U21)."""
    totals, rows = {}, []
    for section, kind, table in RE_PANEL.findall(page):
        if kind == "detailed":
            rows += extract_detailed(table, section)
        elif section == "club":
            totals[section] = extract_totals(table)
        else:
            totals[section] = main_team(team_rows(table))
    return totals, rows


def extract_player(page, player_id):
    """Cela stranka hraca -> (zaznam do players.tsv, riadky do career.tsv)."""
    player = {"id": player_id, **extract_person(page)}
    totals, rows = extract_career(page)
    club = totals.get("club", {})
    nat = totals.get("national", {})
    player.update({"club_apps": club.get("apps", ""), "club_goals": club.get("goals", ""),
                   "club_assists": club.get("assists", ""),
                   "national_team": nat.get("team", ""), "nat_apps": nat.get("apps", ""),
                   "nat_goals": nat.get("goals", ""), "nat_assists": nat.get("assists", ""),
                   "bio": extract_bio(page)})
    for row in rows:
        row["player_id"] = player_id
    return player, rows


def player_files():
    """(id, cesta) pre vsetky stiahnute stranky hracov, zoradene podla id."""
    files = []
    for name in os.listdir(HTML_DIR):
        m = RE_FILE.match(name)
        if m:
            files.append((int(m.group(1)), os.path.join(HTML_DIR, name)))
    return sorted(files)


def run(limit=None):
    files = player_files()[:limit]
    missing = {c: 0 for c in PLAYER_COLS}           # kolko hracov nema dane pole (do statistiky)
    n_rows = 0
    with open(PLAYERS_FILE, "w", encoding="utf-8", newline="") as fp, \
            open(CAREER_FILE, "w", encoding="utf-8", newline="") as fc:
        fp.write(tsv_header(PLAYER_COLS))
        fc.write(tsv_header(CAREER_COLS))
        for i, (pid, path) in enumerate(files, 1):
            with open(path, encoding="utf-8", errors="replace") as f:
                player, rows = extract_player(f.read(), pid)
            fp.write(tsv_line(player, PLAYER_COLS))
            for row in rows:
                fc.write(tsv_line(row, CAREER_COLS))
            n_rows += len(rows)
            for c in PLAYER_COLS:
                if not player.get(c):
                    missing[c] += 1
            if i % 500 == 0:
                print(f"  {i}/{len(files)} hracov")
    print(f"Hotovo: {len(files)} hracov -> {PLAYERS_FILE}, {n_rows} riadkov kariery -> {CAREER_FILE}")
    print("Chybajuce polia (pocet hracov):",
          ", ".join(f"{c}={n}" for c, n in missing.items() if n) or "ziadne")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Regex extrakcia data/html -> players.tsv, career.tsv.")
    parser.add_argument("--limit", type=int, default=None, help="spracovat len prvych N stranok (na skusku)")
    args = parser.parse_args(argv)
    run(args.limit)


if __name__ == "__main__":
    main()
