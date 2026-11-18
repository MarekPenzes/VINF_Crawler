"""Spark job: wiki dump (enwiki pages-articles, cca 26 GB bz2) -> data/wiki_players.tsv.

Krok 1 (filter): dump sa cita po strankach (oddelovac </page>). bz2 sa da delit na bloky, takze
ho paralelne cita viac taskov. Filter na clanky s infoboxom futbalistu bezi v JVM, do Pythonu
ide iba malo stranok. Vyfiltrovane stranky sa ulozia do data/wiki/football/, aby sa 26 GB dump
nemusel citat znova pri kazdej zmene parsera.
Krok 2 (parse): regex parser z wikitext.py vytiahne z kazdej stranky infobox, uvodny text a
kategorie. Stranka na hranici dvoch blokov moze prist dvakrat, duplicity sa odstrania podla id.

Pouzitie: py wiki_extract.py                  (oba kroky, cely dump)
          py wiki_extract.py --parse-only     (iba krok 2 nad data/wiki/football/)
          py wiki_extract.py --dump data/wiki/sample.xml.bz2   (vzorka na skusku)"""
import argparse
import glob
import os
import time

from config import WIKI_DUMP, WIKI_FILE, WIKI_PAGES_DIR
from spark_utils import MASTER, PARTITIONS, spark_session, write_parts, write_tsv
from wikitext import WIKI_COLS, parse_page

PAGE_END = "</page>"
# predfilter v JVM (Java regex): clanok (namespace 0) s infoboxom futbalistu
JVM_ARTICLE = "<ns>0</ns>"
JVM_INFOBOX = r"(?i)\{\{\s*infobox[ _]football[ _]biography"


def read_pages(spark, paths):
    """XML subor(y) so strankami -> DataFrame, stlpec value = jedna stranka. Subory sa zadavaju
    zoznamom, lebo vypis priecinka cez Hadoop na Windows bez nativnych kniznic (winutils) zlyha."""
    return spark.read.option("lineSep", PAGE_END).text(paths)


def filter_dump(spark, dump):
    """Krok 1: stranky futbalistov z dumpu -> data/wiki/football/part-*.xml; vrati ich pocet."""
    from pyspark.sql import functions as F
    pages = read_pages(spark, dump)
    football = pages.where(F.col("value").contains(JVM_ARTICLE) & F.col("value").rlike(JVM_INFOBOX))
    # coalesce: menej Python taskov (na Windows kazdy startuje novy proces), citanie ostava paralelne
    return write_parts(football.rdd.coalesce(PARTITIONS).map(lambda row: row.value + PAGE_END + "\n"),
                       WIKI_PAGES_DIR, "xml")


def parse_pages(spark):
    """Krok 2: data/wiki/football/ -> data/wiki_players.tsv; vrati pocet hracov."""
    parts = sorted(glob.glob(os.path.join(WIKI_PAGES_DIR, "part-*.xml")))
    players = (read_pages(spark, parts).rdd
               .map(lambda row: parse_page(row.value))
               .filter(lambda player: player is not None)
               .map(lambda player: (player["id"], player))
               .reduceByKey(lambda a, b: a, PARTITIONS)          # duplicity na hraniciach blokov
               .values())
    return write_tsv(players, WIKI_COLS, WIKI_FILE)


def run(dump=WIKI_DUMP, parse_only=False, master=MASTER):
    spark = spark_session("vinf-wiki", master)
    if not parse_only:
        start = time.time()
        size = os.path.getsize(dump) / 2**30
        print(f"Krok 1: filter {dump} ({size:.1f} GB)")
        n = filter_dump(spark, dump)
        print(f"  {n} stranok s infoboxom futbalistu -> {WIKI_PAGES_DIR} ({time.time() - start:.0f} s)")
    start = time.time()
    print(f"Krok 2: parsovanie {WIKI_PAGES_DIR}")
    n = parse_pages(spark)
    print(f"  {n} hracov -> {WIKI_FILE} ({time.time() - start:.0f} s)")
    spark.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spark: wiki dump -> wiki_players.tsv (regex parser).")
    parser.add_argument("--dump", default=WIKI_DUMP, help="bz2 dump alebo vzorka (default cely dump)")
    parser.add_argument("--parse-only", action="store_true",
                        help="preskocit filter dumpu, parsovat uz vyfiltrovane stranky")
    parser.add_argument("--master", default=MASTER, help=f"Spark master (default {MASTER})")
    args = parser.parse_args(argv)
    run(args.dump, args.parse_only, args.master)


if __name__ == "__main__":
    main()
