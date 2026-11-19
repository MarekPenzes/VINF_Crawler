"""Unit testy Lucene indexu a vyhladavania (lucene_index.py, lucene_search.py).

Prevod filtra veku na rozsah datumov narodenia a polia dokumentu su cisty Python a bezia vsade.
Testy s PyLucene si postavia maly index v pamati (ByteBuffersDirectory) z vymyslenych hracov,
data/lucene nepotrebuju. Bez PyLucene (Windows) sa preskocia, cele sa spustia v kontajneri:
lucene.cmd test

Spustenie z korena projektu: py -m unittest discover -s tests -v"""
import importlib.util
import operator
import unittest
from datetime import date, timedelta

from extractor import PLAYER_COLS
from filters import FilterError, age, birth_date_range, born_by, parse_filter
from lucene_index import list_values, player_fields
from lucene_search import INT_MAX, age_bounds

HAS_LUCENE = importlib.util.find_spec("lucene") is not None
MODRIC = "Luka Modri" + chr(0x107)          # c s carkou, test vyhladavania bez diakritiky
AGE_OPERATORS = {"=": operator.eq, ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


def born(years):
    """Datum narodenia hraca, ktory ma dnes presne `years` rokov (nie tesne pri narodeninach)."""
    return (born_by(years) - timedelta(days=100)).isoformat()


def player(pid, name, position="", club="", nationality="", birth_date="", height="", bio=""):
    row = dict.fromkeys(PLAYER_COLS, "")
    row.update(id=str(pid), name=name, position=position, club=club, nationality=nationality,
               birth_date=birth_date, height_cm=str(height), bio=bio)
    return row


class TestBirthDateRange(unittest.TestCase):
    TODAYS = [date(2026, 11, 19), date(2028, 2, 29), date(2027, 2, 28), date(2028, 3, 1)]

    def test_range_matches_age(self):
        """Datum je v rozsahu prave vtedy, ked vek splna filter, aj pri narodeninach a 29. 2."""
        for today in self.TODAYS:
            for op, compare in AGE_OPERATORS.items():
                low, high = birth_date_range(op, 20, today)
                day, last = born_by(23, today), born_by(17, today)
                while day <= last:
                    inside = (low is None or day >= low) and (high is None or day <= high)
                    self.assertEqual(inside, compare(age(day.isoformat(), today), 20), (today, op, day))
                    day += timedelta(days=1)

    def test_born_by_leap_day(self):
        self.assertEqual(born_by(1, date(2028, 2, 29)), date(2027, 2, 28))
        self.assertEqual(born_by(4, date(2028, 2, 29)), date(2024, 2, 29))

    def test_not_equal_is_not_a_range(self):
        with self.assertRaises(FilterError):
            birth_date_range("!=", 20)

    def test_age_bounds_as_numbers(self):
        self.assertEqual(age_bounds("<", 20, date(2026, 11, 19)), (20061120, INT_MAX))
        self.assertEqual(age_bounds("=", 20, date(2026, 11, 19)), (20051120, 20061119))


class TestPlayerFields(unittest.TestCase):
    def test_list_values_without_years_and_stats(self):
        self.assertEqual(list_values("2012-2016 St Patrick's; 2016- Ajax (45/1)"), ["St Patrick's", "Ajax"])
        self.assertEqual(list_values(""), [])

    def test_fields(self):
        p = player(1, MODRIC, "Midfielder", "Real Madrid", "Croatia", "1985-09-09")
        wiki = {"wiki_url": "https://en.wikipedia.org/wiki/Luka_Modric", "wiki_height_cm": "172",
                "wiki_birth_place": "Zadar, Croatia", "wiki_youth_clubs": "2002-2003 Dinamo Zagreb"}
        fields = player_fields(p, ["Dinamo Zagreb", "Real Madrid"], ["LaLiga"], wiki)
        self.assertEqual(fields["keys"]["name_key"], "luka modric")
        self.assertNotIn("foot_key", fields["keys"])                     # prazdne pole nema kluc
        self.assertEqual(fields["numbers"], {"height_cm": 172, "birth_date": 19850909})   # vyska z wiki
        self.assertEqual(fields["text"]["youth_clubs"], ["Dinamo Zagreb"])
        self.assertEqual(fields["text"]["bio"], [])                      # prazdny text sa do indexu neprida
        self.assertEqual(fields["stored"]["wiki_url"], wiki["wiki_url"])

    def test_own_height_wins(self):
        fields = player_fields(player(1, "A", height=180), wiki={"wiki_height_cm": "175"})
        self.assertEqual(fields["numbers"]["height_cm"], 180)


# (hrac, kluby z kariery, riadok z joined.tsv alebo None)
DATA = [
    (player(1, MODRIC, "Midfielder", "Real Madrid", "Croatia", born(40), 172, "Ballon d'Or winner."),
     ["Dinamo Zagreb", "Real Madrid", "Tottenham Hotspur"],
     {"wiki_url": "https://en.wikipedia.org/wiki/Luka_Modric", "wiki_birth_place": "Zadar, Croatia",
      "wiki_youth_clubs": "2002-2003 Dinamo Zagreb"}),
    (player(2, "Jude Bellingham", "Midfielder", "Real Madrid", "England", born(23), 186),
     ["Birmingham City", "Borussia Dortmund", "Real Madrid"], None),
    # dva kluby, ktore by bez medzery 100 pozicii spojila fraza "real madrid"
    (player(3, "Max Tester", "Attacker", "CD Real", "Spain", born(20), 180), ["CD Real", "Madrid City"], None),
    (player(4, "Manuel Keeper", "Goalkeeper", "Bayern Munich", "Germany", born(35), 193,
            "He saved a penalty in the final."), ["Bayern Munich"], None),
    (player(5, "Nomad Keeper", "Goalkeeper"), [], None),          # bez klubu, krajiny, veku a vysky
]


@unittest.skipUnless(HAS_LUCENE, "PyLucene nie je nainstalovane, spustit cez lucene.cmd test")
class TestLuceneSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lucene_index import init_lucene, make_analyzer, make_document
        init_lucene()
        from org.apache.lucene.index import IndexWriter, IndexWriterConfig
        from org.apache.lucene.store import ByteBuffersDirectory
        from lucene_search import LuceneEngine

        directory = ByteBuffersDirectory()
        writer = IndexWriter(directory, IndexWriterConfig(make_analyzer()))
        for row, teams, wiki in DATA:
            writer.addDocument(make_document(player_fields(row, teams, (), wiki)))
        writer.close()
        cls.engine = LuceneEngine(directory, {int(row["id"]): row for row, _, _ in DATA})

    def ids(self, text, *filters):
        return [doc_id for doc_id, _ in self.engine.search(text, [parse_filter(f) for f in filters])]

    def test_phrase_does_not_join_two_values(self):
        self.assertEqual(set(self.ids('"real madrid"')), {1, 2})
        self.assertEqual(set(self.ids("real madrid")), {1, 2, 3})       # bez uvodzoviek OR

    def test_fuzzy_and_diacritics(self):
        self.assertEqual(self.ids("modrc~"), [1])
        self.assertEqual(self.ids("modric"), [1])

    def test_field_query(self):
        self.assertEqual(self.ids("birth_place:zadar"), [1])
        self.assertEqual(self.ids("birth_place:zagreb"), [])           # Zagreb je iba v kluboch
        self.assertEqual(self.ids("zagreb"), [1])

    def test_boolean_and_not_and_stemming(self):
        self.assertEqual(set(self.ids("goalkeeper penalty")), {4, 5})
        self.assertEqual(self.ids("+goalkeeper +saves"), [4])           # saves = saved (Porter)
        self.assertEqual(self.ids("goalkeeper -nationality:germany"), [5])

    def test_text_filters(self):
        self.assertEqual(self.ids("", "nationality=croatia"), [1])
        self.assertEqual(set(self.ids("", "club~madrid")), {1, 2})
        self.assertEqual(set(self.ids("", "nationality!=croatia")), {2, 3, 4})   # 5 krajinu nema

    def test_numeric_filters(self):
        self.assertEqual(set(self.ids("", "height>=186")), {2, 4})
        self.assertEqual(set(self.ids("", "height!=172")), {2, 3, 4})

    def test_age_filters(self):
        self.assertEqual(set(self.ids("", "age<30")), {2, 3})
        self.assertEqual(self.ids("", "age=23"), [2])
        self.assertEqual(set(self.ids("", "age!=23")), {1, 3, 4})

    def test_filter_does_not_change_score(self):
        scores = dict(self.engine.search("midfielder"))
        filtered = self.engine.search("midfielder", [parse_filter("nationality=england")])
        self.assertEqual([doc_id for doc_id, _ in filtered], [2])
        self.assertAlmostEqual(filtered[0][1], scores[2], places=5)

    def test_only_filters_sorted_by_name(self):
        self.assertEqual(self.engine.search("", [parse_filter("position=goalkeeper")]), [(4, None), (5, None)])
        self.assertEqual(self.engine.search(""), [])

    def test_top_and_count(self):
        self.assertEqual(self.engine.count("real madrid"), 3)
        self.assertEqual(len(self.engine.search("real madrid", top=2)), 2)
        total, rows = self.engine.answer("real madrid", top=2)
        self.assertEqual((total, len(rows)), (3, 2))
        self.assertEqual(self.engine.count(""), 0)

    def test_invalid_query(self):
        from lucene_search import QueryError
        with self.assertRaises(QueryError):
            self.engine.search('"real madrid')


if __name__ == "__main__":
    unittest.main()
