"""Vyhladavanie v Lucene indexe (skore BM25). Text dopytu je v syntaxi Lucene QueryParser,
filtre su rovnake ako pri starom indexe (filters.py) a prekladaju sa na Lucene dopyty.

Typy dopytov:
- Boolean: slova sa hladaju vo vsetkych poliach z lucene_index.BOOSTS naraz (OR), medzi slovami
  aj AND, OR, NOT, +slovo (musi byt), -slovo (nesmie byt),
- Phrase: "real madrid" (slova tesne za sebou),
- Fuzzy: modrc~ (preklep, najviac 2 zmeny znakov),
- pole:hodnota: youth_clubs:ajax, birth_place:zagreb (iba jedno pole),
- Range: filtre age<23 height>=195 nat_goals>=60 -> IntPoint range,
- Term a Wildcard: filtre nationality=germany (presna hodnota), club~madrid (obsahuje).
Filtre su v BooleanQuery ako FILTER: obmedzia vysledky, ale neovplyvnia skore.

Pouzitie: lucene.cmd lucene-serve, potom py main.py search "\\"real madrid\\"" nationality=england --index lucene"""
from config import LUCENE_DIR, PLAYERS_FILE
from filters import NUMERIC_FIELDS, TEXT_FIELDS, birth_date_range
from lucene_index import BOOSTS, DATE_FIELD, date_int, init_lucene, make_analyzer
from search import describe_player
from tsv import read_tsv

INT_MIN, INT_MAX = -2**31, 2**31 - 1


class QueryError(ValueError):
    """Text dopytu nie je platna syntax Lucene (napr. neuzavreta fraza "real madrid)."""


def numeric_bounds(op, value):
    """Ciselny filter -> rozsah (od, do) vratane; != sa riesi ako negacia =."""
    return {"=": (value, value), ">": (value + 1, INT_MAX), ">=": (value, INT_MAX),
            "<": (INT_MIN, value - 1), "<=": (INT_MIN, value)}[op]


def age_bounds(op, years, today=None):
    """Filter veku -> rozsah datumov narodenia ako cisla YYYYMMDD."""
    low, high = birth_date_range(op, years, today)
    return (date_int(low.isoformat()) if low else INT_MIN,
            date_int(high.isoformat()) if high else INT_MAX)


def filter_query(field, op, value, today=None):
    """Jeden filter z filters.parse_filter -> Lucene dopyt."""
    from org.apache.lucene.document import IntPoint
    from org.apache.lucene.index import Term
    from org.apache.lucene.search import BooleanClause, BooleanQuery, PrefixQuery, TermQuery, WildcardQuery

    def not_equal(exists, equal):
        # hrac bez hodnoty filter nesplni (ako v starom indexe), preto MUST exists + MUST_NOT =
        builder = BooleanQuery.Builder()
        builder.add(exists, BooleanClause.Occur.MUST)
        builder.add(equal, BooleanClause.Occur.MUST_NOT)
        return builder.build()

    if field in TEXT_FIELDS:
        key = f"{field}_key"
        if op == "~":
            return WildcardQuery(Term(key, f"*{value}*"))
        equal = TermQuery(Term(key, value))
        return not_equal(PrefixQuery(Term(key, "")), equal) if op == "!=" else equal

    point = DATE_FIELD if field == "age" else NUMERIC_FIELDS[field]
    bounds = (lambda o: age_bounds(o, value, today)) if field == "age" else (lambda o: numeric_bounds(o, value))
    if op == "!=":
        return not_equal(IntPoint.newRangeQuery(point, INT_MIN, INT_MAX),
                         IntPoint.newRangeQuery(point, *bounds("=")))
    return IntPoint.newRangeQuery(point, *bounds(op))


class LuceneEngine:
    """Rovnake rozhranie ako search.SearchEngine: search() vrati [(doc_id, skore)], describe()."""

    def __init__(self, directory=None, players=None):
        init_lucene()
        from java.lang import Float
        from java.nio.file import Paths
        from java.util import HashMap
        from org.apache.lucene.index import DirectoryReader
        from org.apache.lucene.queryparser.classic import MultiFieldQueryParser
        from org.apache.lucene.search import IndexSearcher
        from org.apache.lucene.store import FSDirectory

        if directory is None:
            directory = FSDirectory.open(Paths.get(LUCENE_DIR))
        self.reader = DirectoryReader.open(directory)
        self.searcher = IndexSearcher(self.reader)
        self.stored = self.searcher.storedFields()
        boosts = HashMap()
        for field, boost in BOOSTS.items():
            boosts.put(field, Float(boost))
        self.parser = MultiFieldQueryParser(list(BOOSTS), make_analyzer(), boosts)
        if players is None:
            players = {int(p["id"]): p for p in read_tsv(PLAYERS_FILE)}
        self.players = players

    def query(self, text, filters=()):
        """Text + filtre -> BooleanQuery (text MUST a urcuje skore, filtre FILTER)."""
        import lucene
        from org.apache.lucene.queryparser.classic import MultiFieldQueryParser
        from org.apache.lucene.search import BooleanClause, BooleanQuery, MatchAllDocsQuery
        builder = BooleanQuery.Builder()
        try:
            # PyLucene: staticke parse() v MultiFieldQueryParser zakryva instancnu metodu, preto takto
            main = MultiFieldQueryParser.parse(self.parser, text) if text.strip() else MatchAllDocsQuery()
        except lucene.JavaError as error:            # ParseException z QueryParsera
            raise QueryError(f"Neplatny Lucene dopyt: {error.getJavaException().getMessage()}") from None
        builder.add(main, BooleanClause.Occur.MUST)
        for field, op, value in filters:
            builder.add(filter_query(field, op, value), BooleanClause.Occur.FILTER)
        return builder.build()

    def search(self, query, filters=(), top=None):
        """Najlepsich `top` vysledkov (None = vsetky) ako [(doc_id, skore)], najlepsie prve.
        Bez textu dopytu sa vratia hraci splnajuci filtre zoradeni podla mena (skore None)."""
        from org.apache.lucene.search import Sort, SortField
        if not query.strip() and not filters:
            return []
        lucene_query = self.query(query, filters)
        limit = top or max(1, self.reader.numDocs())
        if query.strip():
            hits = self.searcher.search(lucene_query, limit).scoreDocs
            return [(self.doc_id(hit.doc), hit.score) for hit in hits]
        hits = self.searcher.search(lucene_query, limit, Sort(SortField("name_sort", SortField.Type.STRING))).scoreDocs
        return [(self.doc_id(hit.doc), None) for hit in hits]

    def count(self, query, filters=()):
        """Pocet vsetkych vysledkov bez citania dokumentov (IndexSearcher.count)."""
        if not query.strip() and not filters:
            return 0
        return self.searcher.count(self.query(query, filters))

    def answer(self, text, filters=(), top=10):
        """(pocet vsetkych vysledkov, [(skore, popis hraca)] pre prvych top) na vypis a pre server.
        Cita sa iba top dokumentov, nie vsetky vysledky (pri sirokom dopyte ich su tisice)."""
        results = self.search(text, filters, top)
        return self.count(text, filters), [(score, self.describe(doc_id)) for doc_id, score in results]

    def doc_id(self, lucene_doc):
        return int(self.stored.document(lucene_doc).get("id"))

    def describe(self, doc_id):
        return describe_player(self.players[doc_id])
