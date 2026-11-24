"""Porovnanie stareho indexu (vlastny TF-IDF, kosinusova podobnost) a noveho Lucene indexu (BM25)
na rovnakych dopytoch: pocet vysledkov, cas dopytu, top vysledky vedla seba a prekryv top k.

Stary index nepozna syntax Lucene. Dostane rovnaky text bez nazvov poli (youth_clubs:ajax -> ajax),
uvodzovky, ~, + a - jeho tokenizer zahodi, takze fraza, preklep aj AND/NOT su pre neho obycajne OR.
Filtre (filters.py) funguju v oboch indexoch rovnako. Cas je najlepsi z --runs behov dopytu tak,
ako ho robi aplikacia (pocet vysledkov a top k): stary index vzdy oboduje a zoradi vsetkych
kandidatov, Lucene vrati iba top k a pocet zisti bez citania dokumentov (IndexSearcher.count).
Lucene index ma navyse hracov iba z wiki (full outer join), vo vypise maju znacku [w].

Pouzitie: lucene.cmd lucene-compare > data\\lucene_compare.txt
          lucene.cmd lucene-compare --top 10 --runs 5"""
import argparse
import os
import re
import sys
import time

from config import DOCS_FILE, INDEX_FILE, LUCENE_DIR
from filters import parse_filter
from lucene_index import dir_size, init_lucene
from lucene_search import LuceneEngine
from search import IDF_METHODS, SearchEngine

TOP_K = 5
RUNS = 3
NAME_WIDTH = 34
RE_FIELD = re.compile(r"\b[a-z_]+:")          # youth_clubs:ajax -> ajax
# (typ dopytu, text v syntaxi Lucene, filtre)
QUERIES = [
    ("Boolean OR + Term + Range", "goalkeeper", ["nationality=germany", "height>=195"]),
    ("Phrase + Term", '"real madrid"', ["nationality=england"]),
    ("Range bez textu", "", ["nat_goals>=60"]),
    ("Boolean OR", "young striker ajax academy", []),
    ("Boolean OR", "spanish defender premier league", []),
    ("Boolean OR", "goalkeeper penalty saves", []),
    ("Boolean AND", "+goalkeeper +penalty", []),
    ("Term", "ballon", []),
    ("Boolean NOT", "ballon -nationality:france", []),
    ("Fuzzy", "modrc~", []),
    ("Pole (wiki) + AND + Range (vek)", "+youth_clubs:ajax striker", ["age<23"]),
    ("Pole (wiki)", "birth_place:zagreb", []),
]


def plain_text(text):
    """Text dopytu pre stary index, ktory nema polia: bez "pole:"."""
    return RE_FIELD.sub("", text)


def timed(search, runs):
    """(vysledky, najlepsi cas v ms) z `runs` behov; prvy beh byva pomalsi (cache)."""
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        results = search()
        best = min(best, time.perf_counter() - start)
    return results, best * 1000


def lucene_name(new, key):
    """Meno hraca z Lucene dokumentu, hrac iba z wiki so znackou [w]."""
    record = new.record(key)
    return record["name"] + (" [w]" if record["source"] == "wiki" else "")


def cell(name, score):
    """Bunka tabulky: meno hraca (skratene) a skore; dopyt iba s filtrami skore nema."""
    score_text = f" ({score:.3f})" if score is not None else ""
    room = NAME_WIDTH - 2 - len(score_text)
    if len(name) > room:
        name = name[:room - 3] + "..."
    return f"{name}{score_text}".ljust(NAME_WIDTH)


def compare_query(old, new, number, kind, text, raw_filters, args):
    """Vypise porovnanie jedneho dopytu a vrati riadok do suhrnu."""
    filters = [parse_filter(arg) for arg in raw_filters]
    old_text = plain_text(text)
    old_results, old_ms = timed(lambda: old.search(old_text, filters, args.idf), args.runs)
    (new_count, new_top), new_ms = timed(
        lambda: (new.count(text, filters), new.search(text, filters, args.top)), args.runs)
    old_count = len(old_results)
    old_top = old_results[:args.top]
    # stary index ma cele cisla, Lucene text ("123", hrac iba z wiki "w4567")
    overlap = len({str(doc_id) for doc_id, _ in old_top} & {key for key, _ in new_top})
    columns = [[(old.players[doc_id]["name"], score) for doc_id, score in old_top],
               [(lucene_name(new, key), score) for key, score in new_top]]
    query = " ".join(filter(None, [text, *raw_filters]))

    print(f"\n=== {number}. {kind}: {query} ===")
    if old_text != text:
        print(f'  stary index dostal text "{old_text}"')
    print("      " + f"TF-IDF ({args.idf})".ljust(NAME_WIDTH) + "Lucene (BM25)")
    print("      " + f"{old_count} hracov, {old_ms:.1f} ms".ljust(NAME_WIDTH)
          + f"{new_count} hracov, {new_ms:.1f} ms")
    for rank in range(max(map(len, columns))):
        cells = [cell(*column[rank]) if rank < len(column) else " " * NAME_WIDTH for column in columns]
        print(f"  {rank + 1:>2}. " + "".join(cells).rstrip())
    print(f"  Prekryv top {args.top}: {overlap}/{args.top}")
    return {"number": number, "query": query, "old": old_count, "new": new_count,
            "old_ms": old_ms, "new_ms": new_ms, "overlap": overlap}


def print_indexes(old, new, old_load, jvm, new_load):
    """Velkost a cas nacitania oboch indexov."""
    old_size = os.path.getsize(INDEX_FILE) + os.path.getsize(DOCS_FILE)
    print(f"{'index':<8}{'dokumenty':>11}{'velkost':>11}{'nacitanie':>11}")
    print(f"{'TF-IDF':<8}{len(old.docs):>11}{old_size / 2**20:>8.1f} MB{old_load:>9.2f} s"
          f"  (index.tsv + docs.tsv, idf a normy pre {len(IDF_METHODS)} metody)")
    print(f"{'Lucene':<8}{new.reader.numDocs():>11}{dir_size(LUCENE_DIR) / 2**20:>8.1f} MB{new_load:>9.2f} s"
          f"  (+ start JVM {jvm:.2f} s)")


def print_summary(rows, top):
    width = max(len(row["query"]) for row in rows) + 2
    print("\n=== Suhrn ===")
    print(f"  {'#':>2}  {'dopyt':<{width}}{'TF-IDF':>8}{'Lucene':>8}{'TF-IDF ms':>11}{'Lucene ms':>11}"
          f"  prekryv top {top}")
    for row in rows:
        print(f"  {row['number']:>2}  {row['query']:<{width}}{row['old']:>8}{row['new']:>8}"
              f"{row['old_ms']:>11.1f}{row['new_ms']:>11.1f}  {row['overlap']}/{top}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Porovnanie stareho TF-IDF indexu a Lucene indexu na dopytoch.")
    parser.add_argument("--top", type=int, default=TOP_K, help="kolko vysledkov porovnat")
    parser.add_argument("--runs", type=int, default=RUNS, help="pocet behov pri merani casu, berie sa najlepsi")
    parser.add_argument("--idf", choices=IDF_METHODS, default="classic", help="idf metoda stareho indexu")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    start = time.perf_counter()
    old = SearchEngine()
    old_load = time.perf_counter() - start
    start = time.perf_counter()
    init_lucene()
    jvm = time.perf_counter() - start
    start = time.perf_counter()
    new = LuceneEngine()
    new_load = time.perf_counter() - start

    print_indexes(old, new, old_load, jvm, new_load)
    rows = [compare_query(old, new, number, kind, text, filters, args)
            for number, (kind, text, filters) in enumerate(QUERIES, 1)]
    print_summary(rows, args.top)


if __name__ == "__main__":
    main()
