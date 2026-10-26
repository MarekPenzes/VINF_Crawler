"""Vyhladavanie hracov: text dopytu sa zoradi podla kosinusovej podobnosti TF-IDF vektorov,
filtre (filters.py) pred tym obmedzia, ktori hraci do vysledku vobec mozu patrit.

Pouzitie: py search.py "left footed winger eredivisie" nationality=spain age>19 --idf prob"""
import argparse
import math
import sys
from collections import Counter, defaultdict

from config import PLAYERS_FILE
from filters import FilterError, age, is_filter, matches, parse_filter
from indexer import load_index
from tokenizer import tokenize
from tsv import read_tsv

TOP_K = 10


def idf_classic(n, df):
    """Klasicke idf: log(N / df). Term vo vsetkych dokumentoch ma vahu 0."""
    return math.log(n / df)


def idf_smooth(n, df):
    """Vyhladene idf: log((N + 1) / (df + 1)) + 1. Ziadny term nema vahu 0."""
    return math.log((n + 1) / (df + 1)) + 1


def idf_probabilistic(n, df):
    """Pravdepodobnostne idf: max(0, log((N - df) / df)) (Manning a kol., Introduction to IR).
    Term aspon v polovici dokumentov ma vahu 0, zriedkavy term vyzdvihne podobne ako classic."""
    if 2 * df >= n:
        return 0.0
    return math.log((n - df) / df)


IDF_METHODS = {"classic": idf_classic, "smooth": idf_smooth, "prob": idf_probabilistic}


def tf_weight(tf):
    """Logaritmicka vaha vyskytu: 10 vyskytov neznamena 10x vacsiu dolezitost."""
    return 1 + math.log(tf)


class SearchEngine:
    """Nacita index a hracov raz a potom odpoveda na lubovolny pocet dopytov."""

    def __init__(self):
        self.index, self.docs = load_index()
        self.players = {int(p["id"]): p for p in read_tsv(PLAYERS_FILE)}
        n = len(self.docs)
        # idf a dlzky (normy) vektorov dokumentov su pre kazdu metodu ine, rataju sa raz
        self.idf = {name: {term: method(n, len(postings)) for term, postings in self.index.items()}
                    for name, method in IDF_METHODS.items()}
        self.norms = {name: self.doc_norms(idf) for name, idf in self.idf.items()}

    def doc_norms(self, idf):
        """doc_id -> dlzka TF-IDF vektora dokumentu (menovatel kosinusovej podobnosti)."""
        squares = defaultdict(float)
        for term, postings in self.index.items():
            for doc_id, tf in postings.items():
                squares[doc_id] += (tf_weight(tf) * idf[term]) ** 2
        return {doc_id: math.sqrt(total) for doc_id, total in squares.items()}

    def filtered_ids(self, filters):
        return {doc_id for doc_id, player in self.players.items() if matches(player, filters)}

    def search(self, query, filters=(), method="classic"):
        """Vsetky vyhovujuce dokumenty ako [(doc_id, skore)], najlepsie prve.
        Bez textu dopytu sa vratia hraci splnajuci filtre zoradeni podla mena (skore None)."""
        allowed = self.filtered_ids(filters) if filters else None
        terms = Counter(term for term in tokenize(query) if term in self.index)
        if not terms:
            if allowed is None:
                return []
            return [(doc_id, None) for doc_id in sorted(allowed, key=lambda d: self.players[d]["name"])]

        idf = self.idf[method]
        query_weights = {term: tf_weight(tf) * idf[term] for term, tf in terms.items()}
        query_norm = math.sqrt(sum(w * w for w in query_weights.values()))
        if query_norm == 0:          # vsetky termy dopytu maju idf 0 (su v kazdom dokumente)
            return []

        scores = defaultdict(float)
        for term, query_weight in query_weights.items():
            for doc_id, tf in self.index[term].items():
                if allowed is None or doc_id in allowed:
                    scores[doc_id] += query_weight * tf_weight(tf) * idf[term]
        norms = self.norms[method]
        results = [(doc_id, score / (query_norm * norms[doc_id])) for doc_id, score in scores.items()]
        return sorted(results, key=lambda item: (-item[1], item[0]))

    def describe(self, doc_id):
        """Kratky popis hraca do vypisu: meno (pozicia, klub, krajina, vek)."""
        p = self.players[doc_id]
        years = f"{age(p['birth_date'])} r." if p["birth_date"] else "vek ?"
        return f"{p['name']} ({p['position']}, {p['club']}, {p['nationality']}, {years})"


def split_query(args):
    """Argumenty z prikazoveho riadku -> (text dopytu, filtre ako text, rozparsovane filtre)."""
    words, raw_filters = [], []
    for arg in args:
        if is_filter(arg):
            raw_filters.append(arg)
        else:
            words.append(arg)
    return " ".join(words), raw_filters, [parse_filter(arg) for arg in raw_filters]


def print_results(engine, results, top=TOP_K):
    print(f"Najdenych hracov: {len(results)}")
    for rank, (doc_id, score) in enumerate(results[:top], 1):
        score_text = f"{score:.4f}" if score is not None else "  -   "
        print(f"{rank:3}. {score_text}  {engine.describe(doc_id)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Vyhladavanie hracov v indexe (TF-IDF + filtre).")
    parser.add_argument("query", nargs="+", help='slova dopytu a filtre, napr. "striker" nationality=spain age>19')
    parser.add_argument("--idf", choices=IDF_METHODS, default="classic", help="metoda vypoctu idf")
    parser.add_argument("--top", type=int, default=TOP_K, help="kolko vysledkov vypisat")
    args = parser.parse_args(argv)
    try:
        text, raw_filters, filters = split_query(args.query)
    except FilterError as error:
        parser.error(str(error))

    sys.stdout.reconfigure(encoding="utf-8")   # mena s diakritikou aj v konzole Windows (cp1252)
    engine = SearchEngine()
    unknown = [term for term in tokenize(text) if term not in engine.index]
    print(f'Dopyt: "{text}" | filtre: {" ".join(raw_filters) or "-"} | idf: {args.idf}')
    if unknown:
        print(f"Termy, ktore nie su v indexe (ignoruju sa): {', '.join(unknown)}")
    print_results(engine, engine.search(text, filters, args.idf), args.top)


if __name__ == "__main__":
    main()
