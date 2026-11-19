"""Lucene index (PyLucene): players.tsv + career.tsv + joined.tsv (wiki) -> data/lucene/.

Dokument = jeden hrac. Typy poli:
- TextField: fulltext s analyzou (meno, kluby, sutaze, bio a texty z wiki), hladaju sa slova,
  frazy a preklepy,
- StringField: presna hodnota bez analyzy, kluce filtrov (nationality=germany -> nationality_key),
- IntPoint: cisla na range dopyty (vyska, zapasy, goly, asistencie, datum narodenia pre vek),
- StoredField: hodnoty na vypis, SortedDocValuesField: zoradenie podla mena.

Dva analyzery (oba: standard tokenizer, male pismena, bez diakritiky, Modric = Modric s diakritikou):
- NAME pre vlastne mena (hraci, kluby, sutaze, miesta) bez stemmingu, aby sa nazvy nemenili,
- TEXT pre anglicky text (bio, abstract, kategorie) navyse so stop slovami a Porter stemmingom
  ("scored", "scores" -> "score").
Viac hodnot jedneho pola (kluby v kariere, kategorie) ma medzi sebou medzeru 100 pozicii, aby
fraza "real madrid" nespojila koniec jedneho klubu so zaciatkom dalsieho.

PyLucene nema balik pre Windows, spusta sa v Docker kontajneri: lucene.cmd lucene-index"""
import argparse
import os
import re
import shutil
import time
from collections import defaultdict

from config import CAREER_FILE, JOIN_FILE, LUCENE_DIR, PLAYERS_FILE
from filters import TEXT_FIELDS as KEY_FIELDS
from tokenizer import normalize
from tsv import read_tsv
from wikitext import LIST_SEP

POSITION_GAP = 100
# pole -> vaha pri hladani textu dopytu vo viacerych poliach naraz (MultiFieldQueryParser)
BOOSTS = {
    "name": 3.0,            # meno je najpresnejsi identifikator hraca
    "full_name": 2.0,       # cele meno z wiki (Rodri = Rodrigo Hernandez Cascante)
    "club": 1.5,            # sucasny klub je dolezitejsi ako kluby v minulosti
    "teams": 1.0, "competitions": 1.0, "national_team": 1.0, "nationality": 1.0,
    "position": 1.0, "foot": 1.0, "birth_place": 1.0, "youth_clubs": 1.0,
    "bio": 1.0, "abstract": 1.0,
    "categories": 0.5,      # dlhe zoznamy kategorii z wiki, slabsi signal
}
TEXT_ANALYZED = {"bio", "abstract", "categories"}          # ostatne polia v BOOSTS: NAME analyzer
# cisla na range dopyty: pole indexu -> stlpec players.tsv
NUMERIC = {"height_cm": "height_cm", "club_apps": "club_apps", "club_goals": "club_goals",
           "club_assists": "club_assists", "nat_apps": "nat_apps", "nat_goals": "nat_goals",
           "nat_assists": "nat_assists"}
DATE_FIELD = "birth_date"                                   # IntPoint YYYYMMDD, filter veku
RE_YEARS = re.compile(r"^-?\d{4}(?:-\d{4}|-)?\s+")          # "2012-2016 Ajax" -> "Ajax"
RE_STATS = re.compile(r"\s*\(\d+/\d+\)$")                   # "Ajax (45/1)" -> "Ajax"


def init_lucene():
    """Spusti JVM raz za proces (dalsie vlakna sa k nemu iba pripoja)."""
    import lucene
    if lucene.getVMEnv() is None:
        lucene.initVM(vmargs=["-Djava.awt.headless=true"])
    else:
        lucene.getVMEnv().attachCurrentThread()


def make_analyzer():
    """PerFieldAnalyzerWrapper: TEXT pre polia v TEXT_ANALYZED, NAME pre ostatne."""
    from java.util import HashMap
    from org.apache.lucene.analysis.custom import CustomAnalyzer
    from org.apache.lucene.analysis.miscellaneous import PerFieldAnalyzerWrapper

    def build(*filters):
        builder = CustomAnalyzer.builder().withTokenizer("standard", HashMap())
        for name in filters:
            builder = builder.addTokenFilter(name, HashMap())
        return builder.withPositionIncrementGap(POSITION_GAP).build()

    names = build("lowercase", "asciiFolding")
    text = build("englishPossessive", "lowercase", "asciiFolding", "stop", "porterStem")
    per_field = HashMap()
    for field in BOOSTS:
        per_field.put(field, text if field in TEXT_ANALYZED else names)
    return PerFieldAnalyzerWrapper(names, per_field)


def date_int(value):
    """"2003-06-29" -> 20030629 (poradie cisel = poradie datumov)."""
    return int(value.replace("-", ""))


def list_values(value):
    """Zoznam z wiki "2009-2010 Benfica; 2010- Ajax (45/1)" -> ["Benfica", "Ajax"]."""
    items = (RE_STATS.sub("", RE_YEARS.sub("", item)).strip() for item in value.split(LIST_SEP))
    return [item for item in items if item]


def career_names():
    """player_id -> (mnozina timov, mnozina sutazi) z career.tsv."""
    teams, competitions = defaultdict(set), defaultdict(set)
    for row in read_tsv(CAREER_FILE):
        if row["team"]:
            teams[row["player_id"]].add(row["team"])
        if row["competition"]:
            competitions[row["player_id"]].add(row["competition"])
    return teams, competitions


def player_fields(player, teams=(), competitions=(), wiki=None):
    """Hodnoty dokumentu ako {"text": {pole: [hodnoty]}, "keys", "numbers", "stored"}.
    Cisty Python bez Lucene, aby sa dal skontrolovat aj bez kontajnera."""
    wiki = wiki or {}
    text = {
        "name": [player["name"]], "club": [player["club"]], "national_team": [player["national_team"]],
        "nationality": [player["nationality"]], "position": [player["position"]], "foot": [player["foot"]],
        "teams": sorted(teams), "competitions": sorted(competitions), "bio": [player["bio"]],
        "full_name": [wiki.get("wiki_full_name", "")], "birth_place": [wiki.get("wiki_birth_place", "")],
        "youth_clubs": list_values(wiki.get("wiki_youth_clubs", "")),
        "categories": wiki.get("wiki_categories", "").split(LIST_SEP),
        "abstract": [wiki.get("wiki_abstract", "")],
    }
    numbers = {field: int(player[col]) for field, col in NUMERIC.items() if player[col]}
    if "height_cm" not in numbers and wiki.get("wiki_height_cm"):
        numbers["height_cm"] = int(wiki["wiki_height_cm"])         # vyska z wiki, ak u nas chyba
    if player["birth_date"]:
        numbers[DATE_FIELD] = date_int(player["birth_date"])
    return {
        "text": {field: [v for v in values if v] for field, values in text.items()},
        "keys": {f"{field}_key": normalize(player[field]) for field in KEY_FIELDS if player[field]},
        "numbers": numbers,
        "stored": {"id": player["id"], "name": player["name"], "wiki_url": wiki.get("wiki_url", "")},
    }


def make_document(fields):
    from org.apache.lucene.document import (Document, Field, IntPoint, SortedDocValuesField,
                                            StoredField, StringField, TextField)
    from org.apache.lucene.util import BytesRef
    doc = Document()
    doc.add(StringField("id", fields["stored"]["id"], Field.Store.YES))
    doc.add(StoredField("name_stored", fields["stored"]["name"]))
    if fields["stored"]["wiki_url"]:
        doc.add(StoredField("wiki_url", fields["stored"]["wiki_url"]))
    doc.add(SortedDocValuesField("name_sort", BytesRef(normalize(fields["stored"]["name"]))))
    for field, values in fields["text"].items():
        for value in values:
            doc.add(TextField(field, value, Field.Store.NO))
    for field, value in fields["keys"].items():
        doc.add(StringField(field, value, Field.Store.NO))
    for field, value in fields["numbers"].items():
        doc.add(IntPoint(field, value))
        doc.add(StoredField(field, value))
    return doc


def documents():
    """Postupne vracia polia dokumentov vsetkych hracov (wiki iba pre pripojenych)."""
    teams, competitions = career_names()
    wiki = {row["player_id"]: row for row in read_tsv(JOIN_FILE)} if os.path.exists(JOIN_FILE) else {}
    for player in read_tsv(PLAYERS_FILE):
        pid = player["id"]
        yield player_fields(player, teams.get(pid, ()), competitions.get(pid, ()), wiki.get(pid))


def dir_size(path):
    return sum(os.path.getsize(os.path.join(path, name)) for name in os.listdir(path))


def run():
    init_lucene()
    from java.nio.file import Paths
    from org.apache.lucene.index import IndexWriter, IndexWriterConfig
    from org.apache.lucene.store import FSDirectory

    start = time.time()
    shutil.rmtree(LUCENE_DIR, ignore_errors=True)
    config = IndexWriterConfig(make_analyzer())
    config.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
    writer = IndexWriter(FSDirectory.open(Paths.get(LUCENE_DIR)), config)
    n = with_wiki = 0
    for fields in documents():
        writer.addDocument(make_document(fields))
        n += 1
        with_wiki += bool(fields["stored"]["wiki_url"])
    writer.commit()
    writer.close()
    print(f"Hotovo: {n} dokumentov (z toho {with_wiki} s wiki), {dir_size(LUCENE_DIR) / 2**20:.1f} MB "
          f"-> {LUCENE_DIR} ({time.time() - start:.1f} s)")


def main(argv=None):
    argparse.ArgumentParser(description="Lucene index z players.tsv, career.tsv a joined.tsv.").parse_args(argv)
    run()


if __name__ == "__main__":
    main()
