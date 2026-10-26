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
