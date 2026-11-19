"""Evaluacia: nase vyhladavanie (stary TF-IDF aj Lucene index) na dopytoch s jasnou informacnou
potrebou. Pre kazdy dopyt vypise top 5 oboch indexov s udajmi na posudenie relevancie (pozicia,
klub, krajina, vek, vyska, miesto narodenia a mladeznicke kluby z wiki) a dopyty, ktore sa rucne
zadaju do Google (site:worldfootball.com) a do vyhladavania na worldfootball.com.

Pouzitie: lucene.cmd evaluate > data\\evaluation.txt"""
import argparse
import sys

from config import JOIN_FILE
from filters import age, parse_filter
from lucene_compare import plain_text
from lucene_index import list_values
from lucene_search import LuceneEngine
from search import SearchEngine
from tsv import read_tsv

TOP_K = 5
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


def details(player, wiki):
    """Jeden riadok s udajmi hraca, podla ktorych sa posudi, ci splna informacnu potrebu."""
    parts = [player["position"], player["club"], player["nationality"],
             f"{age(player['birth_date'])} r." if player["birth_date"] else "",
             f"{player['height_cm']} cm" if player["height_cm"] else ""]
    if wiki:
        parts.append(f"narodeny: {wiki['wiki_birth_place']}" if wiki["wiki_birth_place"] else "")
        youth = list_values(wiki["wiki_youth_clubs"])
        parts.append(f"mladez: {', '.join(youth)}" if youth else "")
    return " | ".join([player["name"], *(part or "?" for part in parts)])


def evaluate_query(old, new, wiki, number, query, top):
    filters = [parse_filter(arg) for arg in query["filters"]]
    old_text = plain_text(query["text"])
    print(f"\n=== {number}. {query['need']} ===")
    print(f"  Lucene:        {' '.join(filter(None, [query['text'], *query['filters']]))}")
    print(f"  Stary index:   {' '.join(filter(None, [old_text, *query['filters']]))}")
    print(f"  Google:        {query['google']}")
    print(f"  worldfootball: {query['domain']}")

    old_results = old.search(old_text, filters)
    sections = [("Lucene (BM25)", new.count(query["text"], filters), new.search(query["text"], filters, top)),
                ("Stary index (TF-IDF)", len(old_results), old_results[:top])]
    for title, count, results in sections:
        print(f"\n  {title}, {count} hracov:")
        for rank, (doc_id, _) in enumerate(results, 1):
            print(f"    {rank}. {details(old.players[doc_id], wiki.get(doc_id))}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Top vysledky oboch indexov na evaluacne dopyty.")
    parser.add_argument("--top", type=int, default=TOP_K, help="kolko vysledkov vypisat")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    old = SearchEngine()
    new = LuceneEngine(players=old.players)
    wiki = {int(row["player_id"]): row for row in read_tsv(JOIN_FILE)}
    for number, query in enumerate(EVAL_QUERIES, 1):
        evaluate_query(old, new, wiki, number, query, args.top)


if __name__ == "__main__":
    main()
