"""Spolocne cesty k suborom projektu (absolutne, aby nezalezalo, odkial sa skript spusti)."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# vystup crawlera
HTML_DIR = os.path.join(DATA_DIR, "html")
CRAWL_LOG_FILE = os.path.join(DATA_DIR, "crawl_log.tsv")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

# vystup extraktora
PLAYERS_FILE = os.path.join(DATA_DIR, "players.tsv")
CAREER_FILE = os.path.join(DATA_DIR, "career.tsv")

# vystup indexera
INDEX_FILE = os.path.join(DATA_DIR, "index.tsv")
DOCS_FILE = os.path.join(DATA_DIR, "docs.tsv")

# vystup statistik
STATS_FILE = os.path.join(DATA_DIR, "stats.tsv")

# wiki dump a vystupy Spark jobov
WIKI_DIR = os.path.join(DATA_DIR, "wiki")
WIKI_DUMP = os.path.join(WIKI_DIR, "enwiki-latest-pages-articles.xml.bz2")
WIKI_PAGES_DIR = os.path.join(WIKI_DIR, "football")   # stranky futbalistov vyfiltrovane z dumpu
WIKI_FILE = os.path.join(DATA_DIR, "wiki_players.tsv")
JOIN_FILE = os.path.join(DATA_DIR, "joined.tsv")

# Lucene index (PyLucene, bezi v Docker kontajneri, pozri lucene.cmd)
LUCENE_DIR = os.path.join(DATA_DIR, "lucene")
LUCENE_PORT = 8765                                   # lucene_server.py, rovnaky port mapuje lucene.cmd
LUCENE_URL = f"http://127.0.0.1:{LUCENE_PORT}/search"
