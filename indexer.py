"""Indexer: data/players.tsv + data/career.tsv -> data/index.tsv (invertovany index s TF)
                                                 data/docs.tsv  (zoznam dokumentov a ich dlzky)

Dokument = jeden hrac. Jeho text tvoria textove polia z players.tsv a nazvy timov a sutazi
z career.tsv (kazdy nazov raz, aby hrac s 15 sezonami v jednom klube nemal 15x vyssie TF).
Index sa stavia cely naraz (batch) po kazdom spusteni extraktora."""
import argparse
from collections import Counter, defaultdict

from config import CAREER_FILE, DOCS_FILE, INDEX_FILE, PLAYERS_FILE
from tokenizer import tokenize
from tsv import read_tsv, tsv_header, tsv_line

TEXT_FIELDS = ["name", "position", "club", "nationality", "national_team", "foot", "bio"]
CAREER_FIELDS = ["team", "competition"]
INDEX_COLS = ["term", "df", "postings"]   # postings = "doc_id:tf doc_id:tf ..."
DOC_COLS = ["doc_id", "name", "length"]   # length = pocet termov dokumentu


def career_names():
    """player_id -> mnozina nazvov timov a sutazi z jeho kariery."""
    names = defaultdict(set)
    for row in read_tsv(CAREER_FILE):
        for field in CAREER_FIELDS:
            if row[field]:
                names[row["player_id"]].add(row[field])
    return names


def player_documents():
    """Postupne vracia (doc_id, meno, text dokumentu) pre kazdeho hraca."""
    career = career_names()
    for player in read_tsv(PLAYERS_FILE):
        parts = [player[field] for field in TEXT_FIELDS]
        parts += sorted(career.get(player["id"], ()))
        yield int(player["id"]), player["name"], " ".join(parts)


def build_index(documents):
    """Vrati (index term -> {doc_id: tf}, zoznam dokumentov)."""
    index = defaultdict(dict)
    docs = []
    for doc_id, name, text in documents:
        counts = Counter(tokenize(text))
        for term, tf in counts.items():
            index[term][doc_id] = tf
        docs.append({"doc_id": doc_id, "name": name, "length": sum(counts.values())})
    return index, docs


def save_index(index, docs):
    with open(INDEX_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(tsv_header(INDEX_COLS))
        for term in sorted(index):
            postings = index[term]
            cells = " ".join(f"{doc_id}:{tf}" for doc_id, tf in sorted(postings.items()))
            f.write(tsv_line({"term": term, "df": len(postings), "postings": cells}, INDEX_COLS))
    with open(DOCS_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(tsv_header(DOC_COLS))
        for doc in docs:
            f.write(tsv_line(doc, DOC_COLS))


def load_index():
    """Nacita index zo suboru: (index term -> {doc_id: tf}, docs doc_id -> {name, length})."""
    index = {}
    for row in read_tsv(INDEX_FILE):
        postings = (item.split(":") for item in row["postings"].split())
        index[row["term"]] = {int(doc_id): int(tf) for doc_id, tf in postings}
    docs = {int(row["doc_id"]): {"name": row["name"], "length": int(row["length"])}
            for row in read_tsv(DOCS_FILE)}
    return index, docs


def run():
    index, docs = build_index(player_documents())
    save_index(index, docs)
    n_postings = sum(len(postings) for postings in index.values())
    avg_length = sum(doc["length"] for doc in docs) / len(docs) if docs else 0
    print(f"Hotovo: {len(docs)} dokumentov, {len(index)} termov, {n_postings} zaznamov (term, dokument)")
    print(f"Priemerna dlzka dokumentu: {avg_length:.1f} termov -> {INDEX_FILE}, {DOCS_FILE}")


def main(argv=None):
    argparse.ArgumentParser(description="Invertovany index z players.tsv a career.tsv.").parse_args(argv)
    run()


if __name__ == "__main__":
    main()
