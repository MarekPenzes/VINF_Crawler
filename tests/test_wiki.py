"""Unit testy regex parsera wiki stranok (wikitext.py) a porovnavania mien pri joine (wiki_join.py).

Vstupy su male kusy wikitextu podla skutocnych stranok z dumpu (zjednodusene), testy preto
nepotrebuju stiahnuty dump ani Spark.

Spustenie z korena projektu: py -m unittest discover -s tests -v"""
import unittest

from wiki_join import name_score
from wikitext import (clean, head_of, infobox, lead, month_number, parse_date, parse_height,
                      parse_page, title_name)

# stranka v tvare z XML dumpu (text clanku ma XML entity &lt; &gt;)
PAGE = """<page>
    <title>Conor Bradley</title>
    <ns>0</ns>
    <id>67804380</id>
    <revision>
      <id>1234567</id>
      <text bytes="1" xml:space="preserve">{{Short description|Northern Irish footballer}}
{{Infobox football biography
| name = Conor Bradley
| full_name = Conor Bradley&lt;ref&gt;{{cite web|title=Squad list}}&lt;/ref&gt;
| birth_date = {{birth date and age|2003|7|9|df=y}}
| birth_place = [[Castlederg]], [[County Tyrone]], Northern Ireland
| height = {{height|m=1.80}}
| position = [[Defender (association football)#Full-back|Right-back]]
| currentclub = [[Liverpool F.C.|Liverpool]]
| youthyears1 = 2012\u20132016 | youthclubs1 = St Patrick's
| years1 = 2021\u2013 | clubs1 = [[Liverpool F.C.|Liverpool]] | caps1 = 45 | goals1 = 1
| years2 = 2022\u20132023 | clubs2 = \u2192 [[Bolton Wanderers F.C.|Bolton Wanderers]] (loan) | caps2 = 41 | goals2 = 5
| nationalyears1 = 2021\u2013 | nationalteam1 = [[Northern Ireland national football team|Northern Ireland]]
| nationalcaps1 = 30 | nationalgoals1 = 4
}}
'''Conor Bradley''' (born 9 July 2003) is a Northern Irish professional [[association football|footballer]] who plays as a [[Defender (association football)#Full-back|right-back]] for [[Premier League]] club [[Liverpool F.C.|Liverpool]].&lt;ref&gt;{{cite web|title=Profile}}&lt;/ref&gt;

==Club career==
Bradley joined Liverpool in 2019.

[[Category:2003 births]]
[[Category:Liverpool F.C. players]]</text>
    </revision>
  </page>"""

# vnoreny infobox futbalistu (embed = yes): datum narodenia a vyska su v nadradenom infoboxe osoby
EMBEDDED = """<page><title>Pele</title><ns>0</ns><id>99</id><revision><text>{{Infobox person
| name = Pele
| birth_date = {{birth date|1940|10|23}}
| height = 1.73 m
| module = {{Infobox football biography | embed = yes
| position = [[Forward (association football)|Forward]]
| years1 = 1956\u20131974 | clubs1 = [[Santos FC|Santos]] | caps1 = 412 | goals1 = 381
}}
}}
'''Pele''' was a Brazilian footballer.</text></revision></page>"""


class TestParsePage(unittest.TestCase):
    """Cela stranka z dumpu -> zaznam do wiki_players.tsv."""

    @classmethod
    def setUpClass(cls):
        cls.player = parse_page(PAGE)

    def test_fields(self):
        expected = {
            "id": "67804380", "title": "Conor Bradley", "name": "Conor Bradley", "full_name": "Conor Bradley",
            "birth_date": "2003-07-09", "birth_place": "Castlederg, County Tyrone, Northern Ireland",
            "height_cm": "180", "position": "Right-back", "current_club": "Liverpool",
            "categories": "2003 births; Liverpool F.C. players",
            "url": "https://en.wikipedia.org/wiki/Conor_Bradley",
        }
        for field, value in expected.items():
            with self.subTest(field=field):
                self.assertEqual(self.player[field], value)

    def test_career_rows(self):
        self.assertEqual(self.player["youth_clubs"], "2012-2016 St Patrick's")
        self.assertEqual(self.player["clubs"], "2021- Liverpool (45/1); 2022-2023 Bolton Wanderers (loan) (41/5)")
        self.assertEqual(self.player["national_teams"], "2021- Northern Ireland (30/4)")

    def test_abstract_is_clean_lead(self):
        self.assertEqual(self.player["abstract"],
                         "Conor Bradley (born 9 July 2003) is a Northern Irish professional footballer who "
                         "plays as a right-back for Premier League club Liverpool.")

    def test_embedded_infobox_uses_parent_fields(self):
        player = parse_page(EMBEDDED)
        self.assertEqual(player["birth_date"], "1940-10-23")
        self.assertEqual(player["height_cm"], "173")
        self.assertEqual(player["clubs"], "1956-1974 Santos (412/381)")

    def test_not_article_or_without_infobox(self):
        self.assertIsNone(parse_page(PAGE.replace("<ns>0</ns>", "<ns>2</ns>")))
        self.assertIsNone(parse_page("<page><title>X</title><ns>0</ns><id>1</id><text>No box.</text></page>"))


class TestInfobox(unittest.TestCase):

    def test_splits_only_top_level_fields(self):
        text = ("{{Infobox football biography\n| name = X\n| birth_date = {{birth date|2000|1|2}}\n"
                "| clubs1 = [[A F.C.|A]]\n}}\nrest")
        start, end, fields = infobox(text)
        self.assertEqual(fields, {"name": "X", "birth_date": "{{birth date|2000|1|2}}", "clubs1": "[[A F.C.|A]]"})
        self.assertEqual((start, text[end:]), (0, "\nrest"))

    def test_missing_infobox(self):
        self.assertIsNone(infobox("{{Infobox person|name=X}}"))

    def test_lead_without_infobox_and_sections(self):
        text = "{{Infobox football biography|name=X}}\n'''X''' is a footballer.\n==Career==\nMore."
        head = head_of(text)
        self.assertEqual(lead(head, infobox(text)), "X is a footballer.")


class TestParseDate(unittest.TestCase):

    def test_formats(self):
        cases = {
            "{{birth date and age|2001|9|5|df=y}}": "2001-09-05",
            "{{birth date and age|df=yes|2001|9|5}}": "2001-09-05",
            "{{Birth date and age|2004|May|3|df=y}}": "2004-05-03",
            "{{Birth  date and age|1995|5|9}}": "1995-05-09",
            "{{bda|1990|1|2}}": "1990-01-02",
            "{{birth date and age|5 September 2001}}": "2001-09-05",
            "5 September 2001": "2001-09-05",
            "September 5, 2001": "2001-09-05",
            "{{birth date|1990|1|2}}<ref>{{cite web|date=3 March 2010}}</ref>": "1990-01-02",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_date(raw), expected)

    def test_incomplete_or_invalid(self):
        for raw in ["{{birth year and age|1990}}", "1880", "c. 1900", "{{birth date|1990|13|1}}", ""]:
            with self.subTest(raw=raw):
                self.assertEqual(parse_date(raw), "")

    def test_month_number(self):
        self.assertEqual([month_number(m) for m in ["5", "May", "sept", "ma", "abc"]], [5, 5, 9, 0, 0])


class TestParseHeight(unittest.TestCase):

    def test_formats(self):
        cases = {
            "{{height|m=1.85}}": "185",
            "{{height|ft=5|in=11}}": "180",
            "{{convert|185|cm|abbr=on}}": "185",
            "1.78 m": "178",
            "1,78 m": "178",
            "5 ft 11+1/2 in": "180",
            "2.50 m": "",                      # mimo rozsahu
            "": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_height(raw), expected)


class TestClean(unittest.TestCase):

    def test_markup(self):
        cases = {
            "[[Liverpool F.C.|Liverpool]]": "Liverpool",
            "[[Castlederg]], Northern Ireland": "Castlederg, Northern Ireland",
            "{{flagicon|ENG}} [[England national football team|England]]": "England",
            "{{nowrap|Real Madrid}}": "Real Madrid",
            "{{lang|es|Club Am\u00e9rica}}": "Club Am\u00e9rica",
            "Text<ref>{{cite web|title=x}}</ref> more<!-- comment -->": "Text more",
            "'''Bold''' and ''italic''": "Bold and italic",
            "[[File:Photo.jpg|thumb|caption]]Text": "Text",
            "Real&nbsp;Madrid": "Real Madrid",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean(raw), expected)

    def test_title_name(self):
        self.assertEqual(title_name("Rodri (footballer, born 1996)"), "Rodri")
        self.assertEqual(title_name("Rodri"), "Rodri")


class TestNameScore(unittest.TestCase):
    """name_score(nase meno, titulok, name z infoboxu, full_name z infoboxu)."""

    def test_exact_match_ignores_diacritics(self):
        self.assertEqual(name_score("Luka Modric", "Luka Modri\u0107", "Luka Modri\u0107", ""), 1.0)

    def test_full_name_tokens(self):
        self.assertEqual(name_score("Gabriel Martinelli Silva", "Gabriel Martinelli", "Gabriel Martinelli",
                                    "Gabriel Teodoro Martinelli Silva"), 1.0)

    def test_transliteration_is_lower_than_exact(self):
        score = name_score("Artem Gromov", "Artem Hromov", "Artem Hromov", "Artem Ihorovych Hromov")
        self.assertTrue(0.7 < score < 1.0, score)
        self.assertGreater(name_score("Georgiy Bushchan", "Heorhiy Bushchan", "", ""), 0)
        self.assertGreater(name_score("Rob Dickie", "Robert Dickie (footballer)", "", ""), 0)

    def test_surname_alone_is_not_enough(self):
        self.assertEqual(name_score("Paul Martin", "John Martin (footballer, born 1999)", "John Martin", ""), 0.0)
        self.assertEqual(name_score("Diogo Silva", "Joao Pedro (footballer, born 1997)", "Joao Pedro",
                                    "Joao Pedro Heinen Silva"), 0.0)

    def test_particles_are_ignored(self):
        self.assertEqual(name_score("Mees de Wit", "Mees de Wit", "", ""), 1.0)
        self.assertEqual(name_score("Jan de Boer", "Kees de Vries", "", ""), 0.0)

    def test_mononym_only_exact_common_name(self):
        self.assertEqual(name_score("Rodri", "Rodri (footballer, born 1996)", "Rodri",
                                    "Rodrigo Hernandez Cascante"), 1.0)
        self.assertEqual(name_score("Thiago", "Everton Messias", "Everton Messias",
                                    "Everton Tiago Barella de Souza Messias"), 0.0)


if __name__ == "__main__":
    unittest.main()
