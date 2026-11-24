"""Evaluacia: nase vyhladavanie (stary TF-IDF aj Lucene index) na dopytoch s jasnou informacnou
potrebou. Pre kazdy dopyt vypise top 5 oboch indexov s udajmi na posudenie relevancie (pozicia,
klub, krajina, vek, vyska, z wiki miesto narodenia, mladez a kluby, zdroj) a dopyty, ktore sa rucne
zadaju do Google (site:worldfootball.com) a do vyhladavania na worldfootball.com.

Pouzitie: lucene.cmd evaluate > data\\evaluation.txt"""
import argparse
import sys

from config import JOIN_FILE
from filters import age, parse_filter
from lucene_compare import plain_text
from lucene_index import doc_key, list_values
from lucene_search import LuceneEngine
from search import SearchEngine
from tsv import read_tsv

TOP_K = 5
WIKI_EXTRA = ("wiki_birth_place", "wiki_youth_clubs", "wiki_clubs")
# informacna potreba, dopyt pre nas index (text v syntaxi Lucene + filtre), Google a vyhladavanie domeny
EVAL_QUERIES = [
    {"need": "Anglicania, ktori hraju alebo hrali za Real Madrid",
     "text": '"real madrid"', "filters": ["nationality=england"],
     "google": "site:worldfootball.com english players real madrid", "domain": "real madrid"},
    {"need": "Nemecki brankari vyssi ako 195 cm",
     "text": "goalkeeper", "filters": ["nationality=germany", "height>=195"],
     "google": "site:worldfootball.com german goalkeeper height 195 cm", "domain": "goalkeeper"},
    {"need": "Odchovanci Ajaxu mladsi ako 23 rokov",
     "text": "youth_clubs:ajax", "filters": ["age<23"],
     "google": "site:worldfootball.com ajax academy players under 23", "domain": "ajax"},
    {"need": "Hraci narodeni v Zahrebe",
     "text": "birth_place:zagreb", "filters": [],
     "google": "site:worldfootball.com players born in zagreb", "domain": "zagreb"},
    {"need": "Luka Modric napisany s preklepom",
     "text": "modrc~", "filters": [],
     "google": "site:worldfootball.com modrc", "domain": "modrc"},
    {"need": "Vitazi Zlatej lopty (Ballon d'Or)",
     "text": "\"ballon d'or\"", "filters": [],
     "google": "site:worldfootball.com ballon d'or winners", "domain": "ballon d'or"},
]


def wiki_extras():
    """id dokumentu -> (miesto narodenia, mladez, kluby) z wiki; iba tieto stlpce, joined.tsv ma stovky MB."""
    return {doc_key(row): tuple(row[col] for col in WIKI_EXTRA) for row in read_tsv(JOIN_FILE) if row["wiki_id"]}


def details(new, extras, key):
    """Jeden riadok s udajmi hraca, podla ktorych sa posudi, ci splna informacnu potrebu."""
    record = new.record(key)
    birth_place, youth, clubs = extras.get(key, ("", "", ""))
    parts = [record["position"], record["club"], record["nationality"],
             f"{age(record['birth_date'])} r." if record["birth_date"] else "",
             f"{record['height_cm']} cm" if record["height_cm"] else "",
             f"narodeny: {birth_place}" if birth_place else "",
             f"mladez: {', '.join(list_values(youth))}" if youth else "",
             f"kluby: {', '.join(list_values(clubs))}" if clubs else ""]
    return " | ".join([record["name"], *(part or "?" for part in parts), f"zdroj: {record['source']}"])


def evaluate_query(old, new, extras, number, query, top):
    filters = [parse_filter(arg) for arg in query["filters"]]
    old_text = plain_text(query["text"])
    print(f"\n=== {number}. {query['need']} ===")
    print(f"  Lucene:        {' '.join(filter(None, [query['text'], *query['filters']]))}")
    print(f"  Stary index:   {' '.join(filter(None, [old_text, *query['filters']]))}")
    print(f"  Google:        {query['google']}")
    print(f"  worldfootball: {query['domain']}")

    old_results = old.search(old_text, filters)
    sections = [("Lucene (BM25)", new.count(query["text"], filters), new.search(query["text"], filters, top)),
                ("Stary index (TF-IDF)", len(old_results), [(str(d), s) for d, s in old_results[:top]])]
    for title, count, results in sections:
        print(f"\n  {title}, {count} hracov:")
        for rank, (key, _) in enumerate(results, 1):
            print(f"    {rank}. {details(new, extras, key)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Top vysledky oboch indexov na evaluacne dopyty.")
    parser.add_argument("--top", type=int, default=TOP_K, help="kolko vysledkov vypisat")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    old = SearchEngine()
    new = LuceneEngine()
    extras = wiki_extras()
    for number, query in enumerate(EVAL_QUERIES, 1):
        evaluate_query(old, new, extras, number, query, args.top)


if __name__ == "__main__":
    main()
