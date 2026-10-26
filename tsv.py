"""Citanie a zapis TSV suborov s hlavickou (bez pandas, podla pravidiel predmetu)."""
import re

RE_SPACE = re.compile(r"\s+")


def tsv_header(cols):
    return "\t".join(cols) + "\n"


def tsv_line(record, cols):
    """Slovnik -> riadok TSV; tabulatory a nove riadky v hodnotach sa nahradia medzerou."""
    return "\t".join(RE_SPACE.sub(" ", str(record.get(c, ""))) for c in cols) + "\n"


def read_tsv(path):
    """Postupne vracia riadky TSV suboru ako slovniky {stlpec: hodnota}.
    Zvlada konce riadkov \\n aj \\r\\n (crawl_log.tsv zapisuje crawler v textovom rezime Windows)."""
    with open(path, encoding="utf-8", newline="") as f:
        cols = f.readline().rstrip("\r\n").split("\t")
        for line in f:
            yield dict(zip(cols, line.rstrip("\r\n").split("\t")))
