"""Spark verzia extraktora: data/html/*.html -> data/players.tsv, data/career.tsv.

Spark rozdeli zoznam stranok hracov (cca 18.8 tis. suborov, 8.7 GB) do particii a kazdy task
ich paralelne nacita a sparsuje tymi istymi regex funkciami ako extractor.py, takze vystup je
rovnaky. Subory cita priamo Python worker: Hadoop citanie (wholeTextFiles) je na Windows pri
mnozstve malych suborov velmi pomale (200 suborov 47 s). Vysledok (cca 30 MB) zapise driver."""
import argparse
import time

from extractor import extract_file, player_files, save
from spark_utils import MASTER, PARTITIONS, spark_session


def run(limit=None, master=MASTER):
    start = time.time()
    files = player_files()[:limit]
    spark = spark_session("vinf-extract", master)
    results = (spark.sparkContext.parallelize(files, PARTITIONS)
               .map(lambda item: extract_file(*item))
               .collect())
    spark.stop()
    save(results)                          # player_files() su zoradene podla id, collect poradie zachova
    print(f"Cas (Spark, {master}): {time.time() - start:.0f} s")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spark extrakcia data/html -> players.tsv, career.tsv.")
    parser.add_argument("--limit", type=int, default=None, help="spracovat len prvych N stranok (na skusku)")
    parser.add_argument("--master", default=MASTER, help=f"Spark master (default {MASTER})")
    args = parser.parse_args(argv)
    run(args.limit, args.master)


if __name__ == "__main__":
    main()
