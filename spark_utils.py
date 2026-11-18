"""Spolocne pomocky pre Spark joby: session a zapis vystupu po particiach.

Spark na Windows bez winutils.exe nevie zapisovat cez Hadoop writer (df.write), preto kazda
particia zapise svoj subor obycajnym Pythonom (paralelne) a driver ich na konci spoji.
Funguje to v lokalnom rezime alebo na clustri so zdielanym diskom."""
import os
import shutil
import sys

from config import BASE_DIR
from tsv import tsv_header, tsv_line

MASTER = "local[*]"        # vsetky jadra pocitaca; na clustri napr. spark://host:7077
DRIVER_MEMORY = "4g"
# radsej menej velkych particii: na Windows Spark nepouziva Python workery znova, kazdy task
# spusta novy proces (cca 1 s a starty idu po jednom)
PARTITIONS = 16
# Python worker na Windows cita data z JVM so socket timeoutom (default 15 s); pri filtri dumpu
# moze JVM dlhsie nenajst ziadnu stranku futbalistu a worker by spadol ("crashed")
WORKER_TIMEOUT = "1h"


def spark_session(app, master=MASTER):
    from pyspark.sql import SparkSession
    # Python workery: ten isty interpreter a moduly projektu (extractor, wikitext ...)
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (BASE_DIR, os.environ.get("PYTHONPATH")) if p)
    spark = (SparkSession.builder.master(master).appName(app)
             .config("spark.driver.memory", DRIVER_MEMORY)
             .config("spark.sql.shuffle.partitions", PARTITIONS)
             .config("spark.python.authenticate.socketTimeout", WORKER_TIMEOUT)
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def read_tsv_df(spark, path):
    """TSV s hlavickou -> DataFrame (vsetky stlpce ako retazce, bez uvodzoviek; prazdne pole = null)."""
    return spark.read.csv(path, sep="\t", header=True, quote="", escape="")


def write_parts(rdd, out_dir, ext):
    """RDD retazcov -> out_dir/part-NNNNN.ext, kazda particia svoj subor. Vrati pocet zaznamov."""
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)

    def write(index, items):
        path = os.path.join(out_dir, f"part-{index:05d}.{ext}")
        n = 0
        with open(path, "w", encoding="utf-8", newline="") as f:
            for item in items:
                f.write(item)
                n += 1
        if not n:
            os.remove(path)
        yield n

    return sum(rdd.mapPartitionsWithIndex(write).collect())


def write_tsv(rdd, cols, path):
    """RDD slovnikov -> jeden TSV subor s hlavickou (particie paralelne, potom spojenie)."""
    parts_dir = path + ".parts"
    n = write_parts(rdd.map(lambda record: tsv_line(record, cols)), parts_dir, "tsv")
    with open(path, "w", encoding="utf-8", newline="") as out:
        out.write(tsv_header(cols))
        for name in sorted(os.listdir(parts_dir)):
            with open(os.path.join(parts_dir, name), encoding="utf-8", newline="") as f:
                shutil.copyfileobj(f, out)
    shutil.rmtree(parts_dir)
    return n
