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
from config import LUCENE_DIR
from filters import NUMERIC_FIELDS, TEXT_FIELDS, age, birth_date_range
from lucene_index import BOOSTS, DATE_FIELD, DISPLAY_FIELDS, date_int, init_lucene, make_analyzer

INT_MIN, INT_MAX = -2**31, 2**31 - 1
SOURCE_LABELS = {"both": "oba", "worldfootball": "worldfootball", "wiki": "wiki"}


def describe_record(record):
    """Udaje dokumentu na jeden riadok: meno (pozicia, klub, krajina, vek) [zdroj]."""
    years = f"{age(record['birth_date'])} r." if record["birth_date"] else "vek ?"
    parts = [record["position"] or "-", record["club"] or "-", record["nationality"] or "-", years]
    return f"{record['name']} ({', '.join(parts)}) [{SOURCE_LABELS.get(record['source'], '?')}]"


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
    """Rovnake rozhranie ako search.SearchEngine: search() vrati [(id dokumentu, skore)], describe().
    ID dokumentu je text: id hraca z worldfootball ("123") alebo "w" + id wiki stranky."""

    def __init__(self, directory=None):
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

    def hits(self, query, filters=(), top=None):
        """Najlepsich `top` vysledkov (None = vsetky) ako [(cislo dokumentu v Lucene, skore)].
        Bez textu dopytu sa vratia hraci splnajuci filtre zoradeni podla mena (skore None)."""
        from org.apache.lucene.search import Sort, SortField
        if not query.strip() and not filters:
            return []
        lucene_query = self.query(query, filters)
        limit = top or max(1, self.reader.numDocs())
        if query.strip():
            return [(hit.doc, hit.score) for hit in self.searcher.search(lucene_query, limit).scoreDocs]
        by_name = Sort(SortField("name_sort", SortField.Type.STRING))
        return [(hit.doc, None) for hit in self.searcher.search(lucene_query, limit, by_name).scoreDocs]

    def search(self, query, filters=(), top=None):
        """Najlepsich `top` vysledkov (None = vsetky) ako [(id dokumentu, skore)], najlepsie prve."""
        return [(self.stored.document(doc).get("id"), score) for doc, score in self.hits(query, filters, top)]

    def count(self, query, filters=()):
        """Pocet vsetkych vysledkov bez citania dokumentov (IndexSearcher.count)."""
        if not query.strip() and not filters:
            return 0
        return self.searcher.count(self.query(query, filters))

    def answer(self, text, filters=(), top=10):
        """(pocet vsetkych vysledkov, [(skore, popis hraca)] pre prvych top) na vypis a pre server.
        Cita sa iba top dokumentov, nie vsetky vysledky (pri sirokom dopyte ich su tisice)."""
        rows = [(score, describe_record(self.stored_record(doc))) for doc, score in self.hits(text, filters, top)]
        return self.count(text, filters), rows

    def stored_record(self, doc):
        """Udaje na vypis ulozene v dokumente (show_*) ako {pole: hodnota}, chybajuce = ""."""
        document = self.stored.document(doc)
        return {"id": document.get("id"),
                **{field: document.get(f"show_{field}") or "" for field in DISPLAY_FIELDS}}

    def record(self, key):
        """Udaje na vypis pre id dokumentu ("123" alebo "w4567"), None ak taky dokument nie je."""
        from org.apache.lucene.index import Term
        from org.apache.lucene.search import TermQuery
        hits = self.searcher.search(TermQuery(Term("id", key)), 1).scoreDocs
        return self.stored_record(hits[0].doc) if hits else None

    def describe(self, key):
        return describe_record(self.record(key))
