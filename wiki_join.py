"""Spark job: join hracov z worldfootball (players.tsv) so strankami futbalistov z wiki
(wiki_players.tsv) -> data/joined.tsv.

Kluc joinu: datum narodenia (presna zhoda) a zhoda mena. worldfootball nema odkaz na wiki ani
Wikidata a samotne meno nestaci (menovci, mononymy ako Rodri, Raphinha). Datum narodenia ma
takmer kazdy hrac aj infobox, preto sa najprv spoja dvojice s rovnakym datumom (equi-join)
a az na nich sa porovnaju mena:
- tokeny mena bez diakritiky a velkych pismen ("Luka Modric" s diakritikou -> luka, modric),
  bez inicial a castic (al, de, van ...),
- zo strany wiki sa beru tokeny titulku (bez dovetku v zatvorke), mena aj celeho mena,
- token sedi presne alebo s toleranciou na prepis z inej abecedy (Gromov - Hromov,
  Artem - Artyom), podobnost meria difflib,
- viacslovne meno musi sediet aspon v dvoch tokenoch (samotne priezvisko nestaci: Paul Martin
  nie je John Martin), jednoslovne meno (Rodri, Alisson) presne s beznym menom na wiki,
- skore = priemerna podobnost nasich tokenov (presna zhoda = 1), presna zhoda tak vyhra nad podobnou.
Kazdemu hracovi sa priradi stranka s najvyssim skore; ak ich je viac s rovnakym skore, hrac sa
vynecha (nejednoznacne). To iste plati opacne, jedna stranka patri jednemu hracovi. Vynimkou je
remiza so skore 1: to su duplicitne profily toho isteho hraca na worldfootball (Mauricio Benitez
s diakritikou aj bez), tie ostanu vsetky."""
import argparse
import time
from difflib import SequenceMatcher

from config import JOIN_FILE, PLAYERS_FILE, WIKI_FILE
from spark_utils import MASTER, read_tsv_df, spark_session
from tokenizer import RE_WORD, normalize
from tsv import tsv_header, tsv_line
from wikitext import title_name

MIN_TOKEN = 2
# casti mien, ktore sa neporovnavaju (Al-Thani, de Jong, van Dijk, bin Ali ...)
PARTICLES = frozenset("al el de da das do dos di del della van von der den bin ibn".split())
SIMILAR = 0.7         # min. podobnost tokenov (difflib ratio): Georgiy - Heorhiy 0.71, Gromov - Hromov 0.83
SIMILAR_LEN = 4       # kratsie tokeny sa porovnavaju iba presne alebo ako predpona
PREFIX_LEN = 3        # skratene meno: Rob - Robert
PREFIX_SCORE = 0.9
# stlpce vystupu: nase id a meno, potom stlpce z wiki s predponou wiki_
WIKI_ATTRS = ["id", "title", "url", "full_name", "birth_place", "height_cm", "position",
              "current_club", "youth_clubs", "clubs", "national_teams", "categories", "abstract"]
JOIN_COLS = ["player_id", "name", "birth_date", "match_score"] + [f"wiki_{c}" for c in WIKI_ATTRS]


def name_tokens(text):
    """Tokeny mena v poradi: male pismena bez diakritiky, bez inicial a castic."""
    return [token for token in RE_WORD.findall(normalize(text or ""))
            if len(token) >= MIN_TOKEN and token not in PARTICLES]


def token_similarity(token, wiki_tokens):
    """1 = token je na wiki presne, inak podobnost najblizsieho tokenu, 0 = ziadny podobny."""
    if token in wiki_tokens:
        return 1.0
    best = 0.0
    for other in wiki_tokens:
        shorter = min(len(token), len(other))
        if shorter >= PREFIX_LEN and (token.startswith(other) or other.startswith(token)):
            best = max(best, PREFIX_SCORE)
        elif shorter >= SIMILAR_LEN:
            ratio = SequenceMatcher(None, token, other).ratio()
            if ratio >= SIMILAR:
                best = max(best, ratio)
    return best


def name_score(name, title, wiki_name, full_name):
    """Zhoda nasho mena s menom na wiki (0 = ina osoba, 1 = vsetky nase tokeny su na wiki presne)."""
    ours = list(dict.fromkeys(name_tokens(name)))
    common = set(name_tokens(title_name(title or "")) + name_tokens(wiki_name))   # bezne meno
    if len(ours) == 1:
        return 1.0 if ours[0] in common else 0.0
    scores = [token_similarity(token, common | set(name_tokens(full_name))) for token in ours]
    if sum(1 for s in scores if s) < 2:
        return 0.0
    return round(sum(scores) / len(scores), 3)


def best_unique(df, key, keep_exact_ties=False):
    """Pre kazdu hodnotu key necha riadok s najvyssim skore; pri remize nenecha nic, okrem
    remizy so skore 1, ak keep_exact_ties (duplicitne profily jedneho hraca)."""
    from pyspark.sql import Window, functions as F
    w = Window.partitionBy(key)
    keep = F.count("*").over(w) == 1
    if keep_exact_ties:
        keep = keep | (F.col("match_score") == 1.0)
    return (df.withColumn("best", F.max("match_score").over(w))
            .where(F.col("match_score") == F.col("best"))
            .withColumn("keep", keep)
            .where(F.col("keep"))
            .drop("best", "keep"))


def join(spark):
    """Vrati (DataFrame pripojenych dvojic, pocty pre suhrn)."""
    from pyspark.sql import functions as F
    players = (read_tsv_df(spark, PLAYERS_FILE)
               .select(F.col("id").alias("player_id"), "name", "birth_date", "bio"))
    wiki = read_tsv_df(spark, WIKI_FILE)
    wiki = wiki.select("birth_date", *[F.col(c).alias(f"wiki_{c}") for c in wiki.columns if c != "birth_date"])
    score = F.udf(name_score, "double")
    pairs = (players.where(F.col("birth_date").isNotNull())
             .join(wiki.where(F.col("birth_date").isNotNull()), "birth_date")       # equi-join na datume
             .withColumn("match_score", score("name", "wiki_title", "wiki_name", "wiki_full_name"))
             .where(F.col("match_score") > 0)
             .cache())
    joined = best_unique(best_unique(pairs, "player_id"), "wiki_id", keep_exact_ties=True).cache()
    counts = {
        "hraci (players.tsv)": players.count(),
        "hraci s datumom narodenia": players.where(F.col("birth_date").isNotNull()).count(),
        "stranky futbalistov z wiki": wiki.count(),
        "stranky s datumom narodenia": wiki.where(F.col("birth_date").isNotNull()).count(),
        "dvojice so zhodou datumu aj mena": pairs.count(),
        "hraci s aspon jednym kandidatom": pairs.select("player_id").distinct().count(),
        "pripojeni hraci": joined.count(),
        "unikatne pripojene wiki stranky": joined.select("wiki_id").distinct().count(),
        "pripojeni hraci bez bio (text iba z wiki)": joined.where(F.col("bio").isNull()).count(),
    }
    return joined, counts


def save(rows):
    with open(JOIN_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(tsv_header(JOIN_COLS))
        for row in sorted(rows, key=lambda r: int(r["player_id"])):
            f.write(tsv_line({c: row[c] if row[c] is not None else "" for c in JOIN_COLS}, JOIN_COLS))


def run(master=MASTER):
    start = time.time()
    spark = spark_session("vinf-join", master)
    joined, counts = join(spark)
    rows = [row.asDict() for row in joined.select(*JOIN_COLS).collect()]
    spark.stop()
    save(rows)
    width = max(len(k) for k in counts)
    for key, value in counts.items():
        print(f"  {key:<{width}}  {value}")
    print(f"Hotovo: {len(rows)} hracov -> {JOIN_FILE} ({time.time() - start:.0f} s)")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spark join players.tsv x wiki_players.tsv -> joined.tsv.")
    parser.add_argument("--master", default=MASTER, help=f"Spark master (default {MASTER})")
    args = parser.parse_args(argv)
    run(args.master)


if __name__ == "__main__":
    main()
