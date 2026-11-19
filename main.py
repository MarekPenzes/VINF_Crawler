"""Spolocny vstup projektu: py main.py <prikaz> [argumenty prikazu]
Prikazy:
  crawl          stiahne stranky hracov do data/html      py main.py crawl --target 6000
  extract        regex extrakcia -> players.tsv, career.tsv
  spark-extract  ta ista extrakcia cez Spark              py main.py spark-extract --limit 1000
  index          invertovany index -> index.tsv, docs.tsv
  search         vyhladavanie, TF-IDF alebo Lucene        py main.py search "left footed winger" "age<23" --idf prob
  compare        porovnanie idf metod na dopytoch         py main.py compare
  wiki           Spark: wiki dump -> wiki_players.tsv     py main.py wiki --parse-only
  join           Spark: players.tsv x wiki -> joined.tsv  py main.py join
  lucene-index   PyLucene index -> data/lucene            lucene.cmd lucene-index
  lucene-serve   server pre search --index lucene         lucene.cmd lucene-serve
  lucene-compare porovnanie TF-IDF a Lucene indexu        lucene.cmd lucene-compare
  stats          statistiky a tokeny (tiktoken)           py main.py stats --html
  test           unit testy (extraktor, wiki, Lucene)     py main.py test -v
  all            extract, index a test po sebe (bez crawlu, wiki a statistik)
Argumenty za prikazom dostane priamo dany modul, napr. py main.py search --help.
Prikazy lucene-* potrebuju PyLucene, na Windows bezia v Docker kontajneri cez lucene.cmd.
Lucene vyhladavanie: lucene.cmd lucene-serve, potom py main.py search goalkeeper "height>=195" --index lucene"""

import importlib
import os
import sys
import unittest

from config import BASE_DIR

TESTS_DIR = os.path.join(BASE_DIR, "tests")
# prikaz -> modul s funkciou main(argv); importuje sa az pri pouziti, aby napr. vyhladavanie
# nepotrebovalo curl_cffi (crawler), tiktoken (statistiky), pyspark (Spark joby) ani PyLucene
COMMANDS = {"crawl": "crawler", "extract": "extractor", "spark-extract": "spark_extract",
            "index": "indexer", "search": "search", "compare": "compare",
            "wiki": "wiki_extract", "join": "wiki_join",
            "lucene-index": "lucene_index", "lucene-serve": "lucene_server",
            "lucene-compare": "lucene_compare", "stats": "stats"}
PIPELINE = ["extract", "index", "test"]   # prikaz all


def run_tests(argv):
    """Unit testy z priecinka tests (argumenty ako pri unittest, napr. -v); True ak vsetky presli."""
    program = unittest.main(module=None, argv=["main.py test", "discover", "-s", TESTS_DIR, *argv],
                            exit=False)
    return program.result.wasSuccessful()


def run_command(name, argv):
    """Spusti jeden prikaz; vrati True, ak skoncil uspesne."""
    if name == "test":
        return run_tests(argv)
    importlib.import_module(COMMANDS[name]).main(argv)
    return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in [*COMMANDS, "test", "all"]:
        print(__doc__)
        return 0 if not argv or argv[0] in ("-h", "--help") else 2
    name, rest = argv[0], argv[1:]
    if name != "all":
        return 0 if run_command(name, rest) else 1
    for step in PIPELINE:
        print(f"\n=== {step} ===")
        if not run_command(step, []):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
