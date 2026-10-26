"""Unit testy regex extraktora (bonus): 20 ulozenych stranok hracov a male testy pomocnych funkcii.

Ocakavane hodnoty su rucne skontrolovane v ulozenych strankach data/html (nie na zivom webe,
ten sa medzitym meni). Stranky su vybrane tak, aby pokryli okrajove pripady: chybajuca vyska,
noha, datum narodenia ci reprezentacia, diakritika a apostrof v mene, mladeznicka reprezentacia
pred A-timom, najdlhsia kariera a hrac s jedinym riadkom kariery.

Spustenie z korena projektu: py -m unittest discover -s tests -v"""
import os
import unittest

from config import HTML_DIR
from extractor import (EMPTY_VALUES, RE_LD_NAME, cell_text, extract_player, find_json, main_team,
                       team_rows)

# subor -> ocakavane hodnoty; career_rows = pocet riadkov do career.tsv, bio_start = prvych 8 slov bio
EXPECTED = {
    "20811_j-bellingham-20811.html": {
        "name": "Jude Bellingham", "position": "Midfielder", "club": "Real Madrid", "nationality": "England",
        "birth_date": "2003-06-29", "height_cm": "186", "foot": "Right",
        "club_apps": "325", "club_goals": "77", "club_assists": "60",
        "national_team": "England", "nat_apps": "60", "nat_goals": "14",
        "career_rows": 55, "bio_start": "Born in Stourbridge on 29 June 2003, Jude"},
    "20802_r-silva-de-goes.html": {
        "name": "Rodrygo", "position": "Attacker", "club": "Real Madrid", "nationality": "Brazil",
        "birth_date": "2001-01-09", "height_cm": "174", "foot": "Right",
        "club_apps": "377", "club_goals": "88", "club_assists": "58",
        "national_team": "Brazil", "nat_apps": "37", "nat_goals": "9",
        "career_rows": 57, "bio_start": "Rodrygo Silva de Goes, known as Rodrygo, was"},
    "21362_l-modri.html": {
        "name": "Luka Modri\u0107", "position": "Midfielder", "club": "AC Milan", "nationality": "Croatia",
        "birth_date": "1985-09-09", "height_cm": "172", "foot": "Right",
        "club_apps": "778", "club_goals": "59", "club_assists": "105",
        "national_team": "Croatia", "nat_apps": "149", "nat_goals": "23",
        "career_rows": 111, "bio_start": "From Zadar, Croatia, Luka Modri\u0107 turned professional through"},
    "10883_m-neuer.html": {
        "name": "Manuel Neuer", "position": "Goalkeeper", "club": "FC Bayern M\u00fcnchen", "nationality": "Germany",
        "birth_date": "1986-03-27", "height_cm": "193", "foot": "Right",
        "club_apps": "777", "club_goals": "0", "club_assists": "4",
        "national_team": "Germany", "nat_apps": "111", "nat_goals": "0",
        "career_rows": 107, "bio_start": "A Schalke 04 academy graduate born in Gelsenkirchen"},
    "21663_m-svilar.html": {
        "name": "Mile Svilar", "position": "Goalkeeper", "club": "Roma", "nationality": "Serbia",
        "birth_date": "1999-08-27", "height_cm": "189", "foot": "Right",
        "club_apps": "232", "club_goals": "0", "club_assists": "0",
        "national_team": "Serbia", "nat_apps": "1", "nat_goals": "0",
        "career_rows": 38, "bio_start": "Antwerp-born goalkeeper Mile Svilar came through Wilrijk, Beerschot"},
    "49_k-smit-49.html": {
        "name": "Kees Smit", "position": "Midfielder", "club": "AZ Alkmaar", "nationality": "Netherlands",
        "birth_date": "2006-01-20", "height_cm": "185", "foot": "Right",
        "club_apps": "142", "club_goals": "21", "club_assists": "25",
        "national_team": "Netherlands", "nat_apps": "1", "nat_goals": "0",
        "career_rows": 24, "bio_start": "Born in Heiloo on 20 January 2006, Kees"},
    "36_m-de-wit.html": {
        "name": "Mees de Wit", "position": "Defender", "club": "AZ Alkmaar", "nationality": "Netherlands",
        "birth_date": "1998-04-17", "height_cm": "181", "foot": "Left",
        "club_apps": "162", "club_goals": "15", "club_assists": "16",
        "national_team": "", "nat_apps": "", "nat_goals": "",
        "career_rows": 23, "bio_start": "Born in Weesp on 17 April 1998, Mees"},
    "67_k-de-leeuw.html": {
        "name": "Karst de Leeuw", "position": "Goalkeeper", "club": "Willem II", "nationality": "Netherlands",
        "birth_date": "2004-04-19", "height_cm": "", "foot": "",
        "club_apps": "5", "club_goals": "0", "club_assists": "0",
        "national_team": "", "nat_apps": "", "nat_goals": "",
        "career_rows": 2, "bio_start": "Karst de Leeuw is a Willem II goalkeeper"},
    "63_a-et-taibi.html": {
        "name": "Amine Et-Ta\u00efbi", "position": "Defender", "club": "Willem II", "nationality": "Morocco",
        "birth_date": "2003-02-05", "height_cm": "", "foot": "Right",
        "club_apps": "94", "club_goals": "5", "club_assists": "6",
        "national_team": "Morocco U23", "nat_apps": "3", "nat_goals": "0",
        "career_rows": 12, "bio_start": "Amine Et-Ta\u00efbi joined Willem II from Mechelen in"},
    "106_o-gloukh.html": {
        "name": "Oscar Gloukh", "position": "Midfielder", "club": "Ajax", "nationality": "Israel",
        "birth_date": "2004-04-01", "height_cm": "171", "foot": "",
        "club_apps": "185", "club_goals": "46", "club_assists": "42",
        "national_team": "Israel", "nat_apps": "33", "nat_goals": "5",
        "career_rows": 37, "bio_start": "Oscar Gloukh was born in Rehovot on 1"},
    "1042_d-evangelista-pereira.html": {
        "name": "Denner", "position": "Defender", "club": "Chelsea U21", "nationality": "Brazil",
        "birth_date": "2008-02-25", "height_cm": "175", "foot": "Left",
        "club_apps": "", "club_goals": "", "club_assists": "",
        "national_team": "Brazil U17", "nat_apps": "2", "nat_goals": "0",
        "career_rows": 1, "bio_start": "Denner Alves Evangelista Pereira, known as Denner, was"},
    "242811_y-kone.html": {
        "name": "Yacouba Kone", "position": "Attacker", "club": "Troyes", "nationality": "Spain",
        "birth_date": "", "height_cm": "", "foot": "",
        "club_apps": "5", "club_goals": "0", "club_assists": "0",
        "national_team": "", "nat_apps": "", "nat_goals": "",
        "career_rows": 1, "bio_start": "Ivorian centre-forward Yacouba Kon\u00e9 arrived at ESTAC Troyes"},
    "23214_f-croci.html": {
        "name": "Federico Croci", "position": "Attacker", "club": "Fiorentina", "nationality": "Italy",
        "birth_date": "2010-07-01", "height_cm": "", "foot": "Left",
        "club_apps": "10", "club_goals": "43", "club_assists": "0",
        "national_team": "Italy U17", "nat_apps": "5", "nat_goals": "1",
        "career_rows": 7, "bio_start": "Bibbiena-born centre-forward Federico Croci (born 1 July 2010)"},
    "121_b-willumsson.html": {
        "name": "Brynj\u00f3lfur Willumsson", "position": "Attacker", "club": "FC Groningen", "nationality": "Iceland",
        "birth_date": "2000-08-12", "height_cm": "185", "foot": "Right",
        "club_apps": "191", "club_goals": "39", "club_assists": "15",
        "national_team": "Iceland", "nat_apps": "12", "nat_goals": "1",
        "career_rows": 31, "bio_start": "Brynj\u00f3lfur Willumsson was born in K\u00f3pavogur, Iceland, on"},
    "167_a-roalds-y.html": {
        "name": "Alwande Roalds\u00f8y", "position": "Midfielder", "club": "Sparta Rotterdam", "nationality": "Norway",
        "birth_date": "2004-06-09", "height_cm": "193", "foot": "Right",
        "club_apps": "91", "club_goals": "9", "club_assists": "5",
        "national_team": "Norway U21", "nat_apps": "0", "nat_goals": "0",
        "career_rows": 25, "bio_start": "Norwegian midfielder Alwande Roalds\u00f8y was born in L\u00f8renskog"},
    "39_m-n.html": {
        "name": "Mat\u011bj \u0160\u00edn", "position": "Midfielder", "club": "ADO Den Haag", "nationality": "Czechia",
        "birth_date": "2004-06-02", "height_cm": "180", "foot": "",
        "club_apps": "140", "club_goals": "20", "club_assists": "10",
        "national_team": "Czech Republic", "nat_apps": "1", "nat_goals": "0",
        "career_rows": 26, "bio_start": "Growing up in Ostrava, Mat\u011bj \u0160\u00edn started at"},
    "46_r-owusu-oduro.html": {
        "name": "Rome-Jayden Owusu-Oduro", "position": "Goalkeeper", "club": "AZ Alkmaar", "nationality": "Netherlands",
        "birth_date": "2004-07-02", "height_cm": "190", "foot": "Right",
        "club_apps": "136", "club_goals": "0", "club_assists": "2",
        "national_team": "Netherlands U21", "nat_apps": "5", "nat_goals": "0",
        "career_rows": 23, "bio_start": "Born in Purmerend on 2 July 2004, Rome-Jayden"},
    "65_n-tjoe-a-on.html": {
        "name": "Nathan Tjoe-A-On", "position": "Defender", "club": "Willem II", "nationality": "Netherlands",
        "birth_date": "2001-12-22", "height_cm": "182", "foot": "Left",
        "club_apps": "114", "club_goals": "3", "club_assists": "4",
        "national_team": "Indonesia", "nat_apps": "14", "nat_goals": "0",
        "career_rows": 22, "bio_start": "Nathan Tjoe-A-On joined Willem II on a free"},
    "1022_n-oreilly.html": {
        "name": "Nico O'Reilly", "position": "Defender", "club": "Manchester City", "nationality": "England",
        "birth_date": "2005-03-21", "height_cm": "193", "foot": "Left",
        "club_apps": "163", "club_goals": "41", "club_assists": "30",
        "national_team": "England", "nat_apps": "13", "nat_goals": "0",
        "career_rows": 34, "bio_start": "Born in Manchester on 21 March 2005, Nico"},
    "139745_m-santos.html": {
        "name": "Marc Santos", "position": "Defender", "club": "Levante", "nationality": "Spain",
        "birth_date": "2010-11-09", "height_cm": "", "foot": "Left",
        "club_apps": "1", "club_goals": "0", "club_assists": "0",
        "national_team": "", "nat_apps": "", "nat_goals": "",
        "career_rows": 1, "bio_start": "From Massanassa in the Valencian Community, Marc Santos"},
}


class TestPlayerPages(unittest.TestCase):
    """Jeden test na kazdu stranku z EXPECTED (metody test_<id>_<slug> doplni add_page_tests)."""

    def check_page(self, file_name, expected):
        path = os.path.join(HTML_DIR, file_name)
        if not os.path.exists(path):
            self.skipTest(f"stranka {file_name} nie je stiahnuta")
        with open(path, encoding="utf-8") as f:
            player, rows = extract_player(f.read(), int(file_name.split("_")[0]))

        expected = dict(expected)
        self.assertEqual(len(rows), expected.pop("career_rows"), "pocet riadkov kariery")
        self.assertTrue(player["bio"].startswith(expected.pop("bio_start")), "zaciatok bio")
        for field, value in expected.items():
            with self.subTest(field=field):
                self.assertEqual(player[field], value)


def add_page_tests():
    """Pre kazdu stranku vytvori samostatnu testovaciu metodu, aby vystup ukazal 20 testov."""
    def make_test(file_name, expected):
        def test(self):
            self.check_page(file_name, expected)
        return test

    for file_name, expected in EXPECTED.items():
        name = "test_" + file_name.removesuffix(".html").replace("-", "_")
        setattr(TestPlayerPages, name, make_test(file_name, expected))


add_page_tests()


class TestHelpers(unittest.TestCase):
    """Pomocne funkcie extraktora na malych kusoch HTML."""

    def test_cell_text_empty_values(self):
        for value in EMPTY_VALUES:
            with self.subTest(value=value):
                self.assertEqual(cell_text(value), "")

    def test_cell_text_prefers_full_name_from_title(self):
        self.assertEqual(cell_text('<span title="Manchester United">Man. Utd.</span>'), "Manchester United")

    def test_cell_text_strips_tags_and_entities(self):
        self.assertEqual(cell_text("<b>Brighton</b> &amp;\n Hove"), "Brighton & Hove")

    def test_find_json_decodes_escapes(self):
        self.assertEqual(find_json(RE_LD_NAME, r'"name":"Kevin \"KDB\" De Bruyne"'), 'Kevin "KDB" De Bruyne')

    def test_team_rows_maps_columns_by_header(self):
        table = ('<th title="Team"></th><th title="Period"></th><th title="Appearances"></th>'
                 '<th title="Goals"></th><tbody><tr><td>England</td><td>2020</td><td>60</td><td>14</td></tr>'
                 '</tbody>')
        self.assertEqual(team_rows(table), [{"team": "England", "apps": "60", "goals": "14"}])

    def test_main_team_prefers_senior_team(self):
        rows = [{"team": "Belgium U21", "apps": "5"}, {"team": "Serbia", "apps": "1"}]
        self.assertEqual(main_team(rows), {"team": "Serbia", "apps": "1"})

    def test_main_team_only_youth_teams(self):
        rows = [{"team": "Italy U17", "apps": "5"}, {"team": "Italy U16", "apps": "2"}]
        self.assertEqual(main_team(rows), {"team": "Italy U17", "apps": "5"})

    def test_main_team_empty_table(self):
        self.assertEqual(main_team([]), {})


if __name__ == "__main__":
    unittest.main()
