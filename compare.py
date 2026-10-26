"""Porovnanie troch idf metod na rovnakych dopytoch: idf kazdeho termu dopytu,
top 10 vysledkov vedla seba a prekryv vysledkov medzi metodami.

Pouzitie: py compare.py                               (predvolene dopyty)
          py compare.py "goalkeeper penalty saves" "young striker ajax academy" """
import argparse
import sys
from itertools import combinations

from search import IDF_METHODS, SearchEngine
from tokenizer import tokenize

TOP_K = 10
NAME_WIDTH = 30
DEFAULT_QUERIES = [
    "spanish defender premier league",
    "midfielder who scored goals in the champions league final",
    "young striker ajax academy",
    "goalkeeper penalty saves",
]


def print_term_idf(engine, text):
    """Tabulka df a idf pre kazdy term dopytu podla kazdej metody."""
    print(f"  {'term':<14}{'df':>6}" + "".join(f"{name:>10}" for name in IDF_METHODS))
    for term in dict.fromkeys(tokenize(text)):        # unikatne termy v poradi vyskytu
        if term not in engine.index:
            print(f"  {term:<14}{0:>6}   (nie je v indexe)")
            continue
        df = len(engine.index[term])
        print(f"  {term:<14}{df:>6}" + "".join(f"{engine.idf[name][term]:>10.3f}" for name in IDF_METHODS))


def cell(engine, result):
    """Jedna bunka tabulky: skratene meno hraca a skore."""
    doc_id, score = result
    name = engine.players[doc_id]["name"]
    if len(name) > NAME_WIDTH - 9:
        name = name[:NAME_WIDTH - 12] + "..."
    return f"{name} ({score:.3f})".ljust(NAME_WIDTH)


def compare_query(engine, text, top=TOP_K):
    print(f'\n=== Dopyt: "{text}" ===')
    print_term_idf(engine, text)

    tops = {name: engine.search(text, method=name)[:top] for name in IDF_METHODS}
    print(f"\n  {'#':>2}  " + "".join(name.ljust(NAME_WIDTH) for name in IDF_METHODS))
    for rank in range(top):
        cells = [cell(engine, tops[name][rank]) if rank < len(tops[name]) else " " * NAME_WIDTH
                 for name in IDF_METHODS]
        print(f"  {rank + 1:>2}  " + "".join(cells))

    overlaps = []
    for a, b in combinations(IDF_METHODS, 2):
        common = {doc_id for doc_id, _ in tops[a]} & {doc_id for doc_id, _ in tops[b]}
        overlaps.append(f"{a}-{b} {len(common)}/{top}")
    print(f"\n  Prekryv top {top}: " + ", ".join(overlaps))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Porovnanie idf metod (classic, smooth, prob).")
    parser.add_argument("queries", nargs="*", default=DEFAULT_QUERIES, help="textove dopyty na porovnanie")
    parser.add_argument("--top", type=int, default=TOP_K, help="kolko vysledkov porovnat")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    engine = SearchEngine()
    for text in args.queries:
        compare_query(engine, text, args.top)


if __name__ == "__main__":
    main()
