"""Tokenizer: text -> zoznam termov. Pouziva ho indexer aj vyhladavanie, aby sa dopyt
spracoval rovnako ako dokumenty (dopyt "brondby" najde aj klub Brondby IF napisany s danskym o)."""
import re
import unicodedata

MIN_LENGTH = 2   # jednoznakove tokeny ("c" z "C.F.", "o" z "O'Neil") nenesu vyznam

# pismena, ktore unicodedata nerozlozi na zakladne pismeno + diakritiku (kluc = kod znaku)
SPECIAL_LETTERS = {
    0x00F8: "o",    # o so skrtnutim (Brondby)
    0x0142: "l",    # polske l
    0x0131: "i",    # turecke i bez bodky (Kilic)
    0x0111: "d",    # chorvatske d
    0x00F0: "d",    # islandske eth
    0x00FE: "th",   # islandske thorn
    0x00DF: "ss",   # nemecke ostre s
    0x00E6: "ae",
    0x0153: "oe",
}

RE_WORD = re.compile(r"[a-z0-9]+")

# vlastny zoznam anglickych stop slov (NLTK je v predmete zakazane); bio je po anglicky
STOPWORDS = frozenset("""
a an and are as at be been but by for from had has have he her him his i if in into is it
its me my of on or our she so than that the their them then there these they this those to
up us was we were what when where which while who whom why will with you your
""".split())


def normalize(text):
    """Male pismena bez diakritiky: "Muller" s prehlaskou -> "muller", "Kilic" turecke -> "kilic"."""
    text = text.lower().translate(SPECIAL_LETTERS)
    decomposed = unicodedata.normalize("NFKD", text)   # e s dlznom -> e + samostatny dlzen
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokenize(text):
    """Zoznam termov v poradi vyskytu (s opakovaniami, aby sa dala spocitat TF)."""
    return [token for token in RE_WORD.findall(normalize(text))
            if len(token) >= MIN_LENGTH and token not in STOPWORDS]
