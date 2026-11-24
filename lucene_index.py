"""Lucene index (PyLucene): full outer join z joined.tsv + players.tsv + career.tsv -> data/lucene/.

Dokument = jeden riadok full outer joinu, teda hrac z oboch zdrojov, iba z worldfootball alebo
iba z wiki. Hrac z worldfootball ma polia z players.tsv a career.tsv (a z wiki, ak ma par),
hrac iba z wiki ma polia z infoboxu (pozicia sa prevedie na 4 kategorie ako na worldfootball,
narodnost = jeho hlavna reprezentacia). ID dokumentu: id hraca z worldfootball ("123"), hrac
iba z wiki "w" + id wiki stranky ("w4567").

Typy poli:
- TextField: fulltext s analyzou (meno, kluby, sutaze, bio a texty z wiki), hladaju sa slova,
  frazy a preklepy,
- StringField: presna hodnota bez analyzy, kluce filtrov (nationality=germany -> nationality_key),
- IntPoint: cisla na range dopyty (vyska, zapasy, goly, asistencie, datum narodenia pre vek),
- StoredField: udaje na vypis (show_*), SortedDocValuesField: zoradenie podla mena.

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
from collections import Counter, defaultdict

from config import CAREER_FILE, JOIN_FILE, LUCENE_DIR, PLAYERS_FILE
from filters import TEXT_FIELDS as KEY_FIELDS
from tokenizer import normalize
from tsv import read_tsv
from wikitext import LIST_SEP, title_name

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
# rovnake cisla z wiki (Career total, hlavna A-reprezentacia); hracovi z worldfootball doplnia iba chybajuce
WIKI_NUMERIC = {"height_cm": "wiki_height_cm", "club_apps": "wiki_club_apps", "club_goals": "wiki_club_goals",
                "nat_apps": "wiki_nat_apps", "nat_goals": "wiki_nat_goals"}
DATE_FIELD = "birth_date"                                   # IntPoint YYYYMMDD, filter veku
# udaje na vypis vysledku, ulozene ako show_<pole> (hrac iba z wiki nie je v players.tsv)
DISPLAY_FIELDS = ("source", "name", "position", "club", "nationality", "birth_date", "height_cm", "wiki_url")
WIKI_PREFIX = "w"
RE_YEARS = re.compile(r"^-?\d{4}(?:-\d{4}|-)?\s+")          # "2012-2016 Ajax" -> "Ajax"
RE_STATS = re.compile(r"\s*\(\d+/\d+\)$")                   # "Ajax (45/1)" -> "Ajax"
# wiki pozicia -> kategoria ako na worldfootball; vyhra slovo, ktore je v texte skor (pri zhode dlhsie):
# "Wing-back" -> Defender, "Attacking midfielder" -> Midfielder, "Forward, midfielder" -> Attacker
POSITION_WORDS = {
    "Goalkeeper": ("goalkeeper", "keeper"),
    "Defender": ("defender", "back", "wing-back", "wingback", "sweeper", "libero", "stopper", "centre-half"),
    "Midfielder": ("midfield", "playmaker", "regista", "half-back", "half back", "wing-half", "wing half"),
    "Attacker": ("forward", "striker", "winger", "wing", "attacker", "inside", "outside"),
}


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


def position_group(position):
    """Pozicia z wiki ("Right-back", "Striker") -> Goalkeeper, Defender, Midfielder, Attacker alebo ""."""
    text = position.lower()
    found = [(text.find(word), -len(word), group)
             for group, words in POSITION_WORDS.items() for word in words if word in text]
    return min(found)[2] if found else ""


def doc_key(row):
    """ID dokumentu pre riadok joined.tsv: id hraca z worldfootball alebo "w" + id wiki stranky."""
    return row["player_id"] or WIKI_PREFIX + row["wiki_id"]


def career_names():
    """player_id -> (mnozina timov, mnozina sutazi) z career.tsv."""
    teams, competitions = defaultdict(set), defaultdict(set)
    for row in read_tsv(CAREER_FILE):
        if row["team"]:
            teams[row["player_id"]].add(row["team"])
        if row["competition"]:
            competitions[row["player_id"]].add(row["competition"])
    return teams, competitions


def wiki_text(wiki):
    """Textove polia, ktore worldfootball nema: cele meno, miesto narodenia, mladez, kategorie, uvod clanku."""
    return {
        "full_name": [wiki.get("wiki_full_name", "")], "birth_place": [wiki.get("wiki_birth_place", "")],
        "youth_clubs": list_values(wiki.get("wiki_youth_clubs", "")),
        "categories": wiki.get("wiki_categories", "").split(LIST_SEP),
        "abstract": [wiki.get("wiki_abstract", "")],
    }


def wiki_numbers(wiki):
    return {field: int(wiki[col]) for field, col in WIKI_NUMERIC.items() if wiki.get(col)}


def fields_dict(text, keys, numbers, stored):
    """Spolocny tvar dokumentu pre make_document; prazdne hodnoty sa vynechaju."""
    return {
        "text": {field: [v for v in values if v] for field, values in text.items()},
        "keys": {field: normalize(value) for field, value in keys.items() if value},
        "numbers": numbers,
        "stored": stored,
    }


def player_fields(player, teams=(), competitions=(), wiki=None):
    """Hrac z worldfootball (s wiki, ak ma par) -> {"text", "keys", "numbers", "stored"}.
    Cisty Python bez Lucene, aby sa dal skontrolovat aj bez kontajnera."""
    wiki = wiki or {}
    text = {
        "name": [player["name"]], "club": [player["club"]], "national_team": [player["national_team"]],
        "nationality": [player["nationality"]], "position": [player["position"]], "foot": [player["foot"]],
        "teams": sorted(teams), "competitions": sorted(competitions), "bio": [player["bio"]],
        **wiki_text(wiki),
    }
    numbers = {**wiki_numbers(wiki),                                          # wiki doplni iba chybajuce
               **{field: int(player[col]) for field, col in NUMERIC.items() if player[col]}}
    if player["birth_date"]:
        numbers[DATE_FIELD] = date_int(player["birth_date"])
    stored = {"id": player["id"], "source": "both" if wiki else "worldfootball", "name": player["name"],
              "position": player["position"], "club": player["club"], "nationality": player["nationality"],
              "birth_date": player["birth_date"], "wiki_url": wiki.get("wiki_url", "")}
    keys = {f"{field}_key": player[field] for field in KEY_FIELDS}
    return fields_dict(text, keys, numbers, stored)


def wiki_fields(wiki):
    """Hrac iba z wiki (riadok joined.tsv so source = wiki) -> rovnaky tvar ako player_fields."""
    name = wiki.get("wiki_name") or title_name(wiki.get("wiki_title", ""))
    raw_position = wiki.get("wiki_position", "")
    position = position_group(raw_position)
    club = wiki.get("wiki_current_club", "")
    country = wiki.get("wiki_national_team", "")                 # narodnost = hlavna reprezentacia
    text = {
        "name": [name], "club": [club], "national_team": [country], "nationality": [country],
        "position": [raw_position, position] if position != raw_position else [raw_position],
        "teams": list_values(wiki.get("wiki_clubs", "")) + list_values(wiki.get("wiki_national_teams", "")),
        **wiki_text(wiki),
    }
    numbers = wiki_numbers(wiki)
    if wiki.get("wiki_birth_date"):
        numbers[DATE_FIELD] = date_int(wiki["wiki_birth_date"])
    stored = {"id": WIKI_PREFIX + wiki["wiki_id"], "source": "wiki", "name": name,
              "position": position or raw_position, "club": club, "nationality": country,
              "birth_date": wiki.get("wiki_birth_date", ""), "wiki_url": wiki.get("wiki_url", "")}
    keys = {"name_key": name, "position_key": position, "club_key": club,
            "nationality_key": country, "national_team_key": country}
    return fields_dict(text, keys, numbers, stored)


def make_document(fields):
    from org.apache.lucene.document import (Document, Field, IntPoint, SortedDocValuesField,
                                            StoredField, StringField, TextField)
    from org.apache.lucene.util import BytesRef
    stored = {**fields["stored"], "height_cm": str(fields["numbers"].get("height_cm", ""))}
    doc = Document()
    doc.add(StringField("id", stored["id"], Field.Store.YES))
    for field in DISPLAY_FIELDS:
        if stored.get(field):
            doc.add(StoredField(f"show_{field}", stored[field]))
    doc.add(SortedDocValuesField("name_sort", BytesRef(normalize(stored["name"]))))
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
    """Postupne vracia polia dokumentov: jeden na riadok full outer joinu (bez joined.tsv iba hraci)."""
    teams, competitions = career_names()
    players = {p["id"]: p for p in read_tsv(PLAYERS_FILE)}
    if not os.path.exists(JOIN_FILE):
        rows = ({"source": "worldfootball", "player_id": pid} for pid in players)
    else:
        rows = read_tsv(JOIN_FILE)
    for row in rows:
        if row["source"] == "wiki":
            yield wiki_fields(row)
        else:
            pid = row["player_id"]
            wiki = row if row["source"] == "both" else None
            yield player_fields(players[pid], teams.get(pid, ()), competitions.get(pid, ()), wiki)


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
    sources = Counter()
    for fields in documents():
        writer.addDocument(make_document(fields))
        sources[fields["stored"]["source"]] += 1
    writer.commit()
    writer.close()
    detail = ", ".join(f"{source} {count}" for source, count in sources.most_common())
    print(f"Hotovo: {sum(sources.values())} dokumentov ({detail}), {dir_size(LUCENE_DIR) / 2**20:.1f} MB "
          f"-> {LUCENE_DIR} ({time.time() - start:.1f} s)")


def main(argv=None):
    argparse.ArgumentParser(description="Lucene index z joined.tsv (full outer join), players.tsv a career.tsv."
                            ).parse_args(argv)
    run()


if __name__ == "__main__":
    main()
