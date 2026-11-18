"""Statistiky projektu: crawl (z crawl_log.tsv), velkost dat na disku, extrahovane data,
index, wiki a join a pocet tokenov podla tiktoken (bonus). Vysledok sa vypise a ulozi do
data/stats.tsv.

Pouzitie: py stats.py           (tokeny extrahovanych dat)
          py stats.py --html    (aj tokeny vsetkych HTML stranok, trva niekolko minut)"""
import argparse
import glob
import os
from collections import Counter
from datetime import datetime

import tiktoken

from config import (CAREER_FILE, CRAWL_LOG_FILE, DOCS_FILE, HTML_DIR, INDEX_FILE, JOIN_FILE,
                    PLAYERS_FILE, STATS_FILE, WIKI_DUMP, WIKI_FILE, WIKI_PAGES_DIR)
from tsv import read_tsv, tsv_header, tsv_line
from wikitext import WIKI_COLS

ENCODINGS = ["cl100k_base", "o200k_base"]   # tokenizery modelov GPT-4 a GPT-4o
HTML_BATCH = 100                             # kolko HTML stranok sa tokenizuje naraz
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
STATS_COLS = ["section", "metric", "value"]
TSV_FILES = [PLAYERS_FILE, CAREER_FILE, INDEX_FILE, DOCS_FILE, CRAWL_LOG_FILE]


def size_text(n_bytes):
    """Velkost v citatelnom tvare: 1536 -> "1.5 kB"."""
    for unit in ["B", "kB", "MB"]:
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.2f} GB"


def percent(part, whole):
    return f"{part / whole * 100:.1f} %" if whole else "-"


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def html_files():
    """Cesty k ulozenym HTML strankam hracov (crawler uklada len relevantnych hracov)."""
    return sorted(os.path.join(HTML_DIR, name) for name in os.listdir(HTML_DIR) if name.endswith(".html"))


def crawl_stats():
    rows = list(read_tsv(CRAWL_LOG_FILE))
    by_kind = Counter(row["kind"] for row in rows)
    by_status = Counter(row["status"] for row in rows)
    times = [datetime.strptime(row["time"], TIME_FORMAT) for row in rows]
    seconds = sum(float(row["seconds"]) for row in rows)
    # URL moze byt v logu viackrat (retry po 403/500), preto sa rataju unikatne
    ok_players = {row["url"] for row in rows if row["kind"] == "player" and row["status"] == "200"}
    n_saved = len(html_files())

    stats = [("requesty spolu", len(rows)), ("unikatne URL", len({row["url"] for row in rows}))]
    stats += [(f"requesty typu {kind}", count) for kind, count in by_kind.most_common()]
    stats += [(f"status {status}", count) for status, count in sorted(by_status.items())]
    stats += [
        ("stiahnute data", size_text(sum(int(row["bytes"]) for row in rows))),
        ("priemerny cas odpovede", f"{seconds / len(rows):.2f} s"),
        ("prvy request", f"{min(times):%Y-%m-%d %H:%M}"),
        ("posledny request", f"{max(times):%Y-%m-%d %H:%M}"),
        ("uspesne stiahnute stranky hracov", len(ok_players)),
        ("relevantni hraci (ulozene HTML)", n_saved),
        ("podiel relevantnych hracov", percent(n_saved, len(ok_players))),
    ]
    return stats


def disk_stats():
    files = html_files()
    html_bytes = sum(os.path.getsize(path) for path in files)
    stats = [
        ("HTML stranky hracov", len(files)),
        ("velkost HTML spolu", size_text(html_bytes)),
        ("priemerna velkost HTML stranky", size_text(html_bytes / len(files))),
    ]
    stats += [(f"velkost {os.path.basename(path)}", size_text(os.path.getsize(path))) for path in TSV_FILES]
    return stats


def data_stats():
    players = list(read_tsv(PLAYERS_FILE))
    career_ids = [row["player_id"] for row in read_tsv(CAREER_FILE)]
    stats = [
        ("hraci (players.tsv)", len(players)),
        ("riadky kariery (career.tsv)", len(career_ids)),
        ("hraci s aspon jednym riadkom kariery", len(set(career_ids))),
    ]
    for col in players[0]:
        if col != "id":
            filled = sum(1 for player in players if player[col])
            stats.append((f"vyplnene pole {col}", percent(filled, len(players))))
    return stats


def index_stats():
    dfs = [int(row["df"]) for row in read_tsv(INDEX_FILE)]
    lengths = [int(row["length"]) for row in read_tsv(DOCS_FILE)]
    return [
        ("dokumenty (hraci)", len(lengths)),
        ("unikatne termy", len(dfs)),
        ("zaznamy (term, dokument)", sum(dfs)),
        ("termy len v jednom dokumente (df = 1)", sum(1 for df in dfs if df == 1)),
        ("priemerna dlzka dokumentu", f"{sum(lengths) / len(lengths):.1f} termov"),
    ]


def wiki_stats():
    """Wiki dump, stranky futbalistov (wiki_players.tsv) a join s nasimi hracmi (joined.tsv)."""
    if not (os.path.exists(WIKI_FILE) and os.path.exists(JOIN_FILE)):
        return [("wiki_players.tsv alebo joined.tsv chyba", "spusti py main.py wiki a py main.py join")]
    wiki = list(read_tsv(WIKI_FILE))
    joined = list(read_tsv(JOIN_FILE))
    players = {player["id"]: player for player in read_tsv(PLAYERS_FILE)}
    with_date = sum(1 for player in players.values() if player["birth_date"])
    pages = glob.glob(os.path.join(WIKI_PAGES_DIR, "part-*.xml"))

    def filled(rows, col):
        return sum(1 for row in rows if row[col])

    def gained(col):
        """Pripojeni hraci, ktori pole col u nas nemaju a z wiki ho dostanu."""
        return sum(1 for row in joined if row[f"wiki_{col}"] and not players[row["player_id"]][col])

    stats = []
    if os.path.exists(WIKI_DUMP):
        stats.append(("velkost wiki dumpu (bz2)", size_text(os.path.getsize(WIKI_DUMP))))
    stats += [
        ("vyfiltrovane stranky futbalistov (XML)", size_text(sum(os.path.getsize(path) for path in pages))),
        ("velkost wiki_players.tsv", size_text(os.path.getsize(WIKI_FILE))),
        ("velkost joined.tsv", size_text(os.path.getsize(JOIN_FILE))),
        ("stranky futbalistov z wiki", len(wiki)),
        ("pripojeni hraci", len(joined)),
        ("podiel z hracov s datumom narodenia", percent(len(joined), with_date)),
        ("unikatne pripojene wiki stranky", len({row["wiki_id"] for row in joined})),
        ("presna zhoda mena (skore 1)", sum(1 for row in joined if float(row["match_score"]) == 1)),
        ("pripojeni bez bio, text z wiki (abstract)", sum(
            1 for row in joined if row["wiki_abstract"] and not players[row["player_id"]]["bio"])),
        ("pripojeni bez vysky, vyska z wiki", gained("height_cm")),
    ]
    # polia, ktore worldfootball nema vobec
    stats += [(f"pripojeni s {col} z wiki", filled(joined, f"wiki_{col}"))
              for col in ["full_name", "birth_place", "youth_clubs", "categories"]]
    stats += [(f"wiki: vyplnene pole {col}", percent(filled(wiki, col), len(wiki)))
              for col in WIKI_COLS if col not in ("id", "title", "url")]
    return stats


def count_tokens(encoding, texts):
    # encode_ordinary: text "<|endoftext|>" v HTML sa berie ako obycajny text, nie specialny token
    return sum(len(tokens) for tokens in encoding.encode_ordinary_batch(texts))


def html_tokens(encodings):
    """Tokeny vsetkych HTML stranok; kazda davka sa z disku cita len raz pre vsetky kodovania."""
    totals = Counter()
    files = html_files()
    for start in range(0, len(files), HTML_BATCH):
        texts = [read_text(path) for path in files[start:start + HTML_BATCH]]
        for name, encoding in encodings.items():
            totals[name] += count_tokens(encoding, texts)
        print(f"\r  tokenizujem HTML {start + len(texts)}/{len(files)}", end="", flush=True)
    print()
    return totals


def token_stats(include_html):
    encodings = {name: tiktoken.get_encoding(name) for name in ENCODINGS}
    sources = {
        "players.tsv": [read_text(PLAYERS_FILE)],
        "career.tsv": [read_text(CAREER_FILE)],
        "bio (text zivotopisov)": [player["bio"] for player in read_tsv(PLAYERS_FILE)],
    }
    stats = [(f"{source}, {name}", count_tokens(encoding, texts))
             for name, encoding in encodings.items() for source, texts in sources.items()]
    if include_html:
        stats += [(f"HTML stranky, {name}", count) for name, count in html_tokens(encodings).items()]
    return stats


def print_stats(rows):
    width = max(len(metric) for _, metric, _ in rows)
    section = None
    for row_section, metric, value in rows:
        if row_section != section:
            section = row_section
            print(f"\n[{section}]")
        print(f"  {metric:<{width}}  {value}")


def save_stats(rows):
    with open(STATS_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(tsv_header(STATS_COLS))
        for row in rows:
            f.write(tsv_line(dict(zip(STATS_COLS, row)), STATS_COLS))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Statistiky crawlu, dat, indexu a tokenov.")
    parser.add_argument("--html", action="store_true", help="spocitat aj tokeny surovych HTML stranok (pomale)")
    args = parser.parse_args(argv)

    sections = {
        "crawl": crawl_stats,
        "disk": disk_stats,
        "data": data_stats,
        "index": index_stats,
        "wiki": wiki_stats,
        "tokeny": lambda: token_stats(args.html),
    }
    rows = [(section, metric, value) for section, collect in sections.items() for metric, value in collect()]
    print_stats(rows)
    save_stats(rows)
    print(f"\nUlozene -> {STATS_FILE}")


if __name__ == "__main__":
    main()
