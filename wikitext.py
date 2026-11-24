"""Regex parser stranok z wiki dumpu: infobox futbalistu, sucet z tabulky Career statistics,
uvodny text clanku a kategorie.

Vstup je jeden zaznam <page>...</page> z XML dumpu, text clanku (wikitext) je v <text> a XML
entity (&lt; &amp; ...) sa najprv dekoduju. Vnorene sablony {{...}} a odkazy [[...]] samotny
regex nezvladne, preto sa pri infoboxe hladaju tokeny {{ }} [[ ]] | a pocita sa hlbka vnorenia
a pri cisteni textu sa opakovane nahradzaju najvnorenejsie sablony a odkazy."""
import html
import re

WIKI_COLS = ["id", "title", "name", "full_name", "birth_date", "birth_place", "height_cm",
             "position", "current_club", "youth_clubs", "clubs", "national_teams",
             "national_team", "nat_apps", "nat_goals", "club_apps", "club_goals", "categories",
             "abstract", "url"]
WIKI_URL = "https://en.wikipedia.org/wiki/"
LIST_SEP = "; "                                   # oddelovac poloziek v jednom stlpci (kluby ...)

# stranka v XML dumpe
RE_TITLE = re.compile(r"<title>([^<]*)</title>")
RE_PAGE_ID = re.compile(r"<id>(\d+)</id>")       # prve <id> = id stranky (dalsie su revizia, autor)
RE_NS = re.compile(r"<ns>(\d+)</ns>")
RE_TEXT = re.compile(r"<text[^>]*>(.*?)</text>", re.S)

# infobox a jeho polia
RE_INFOBOX = re.compile(r"\{\{\s*Infobox[ _]football[ _]biography[^|}]*", re.I)
RE_TOKEN = re.compile(r"\{\{|\}\}|\[\[|\]\]|\|")
RE_NUMBERED = re.compile(r"^([a-z_]+?)(\d+)$")   # clubs3 -> ("clubs", "3")
FIELD = r"^\s*\|\s*{}\s*=([^\n]*)"               # pole kdekolvek v texte (nadradeny infobox)

# cistenie wikitextu
RE_COMMENT = re.compile(r"<!--.*?-->", re.S)
RE_REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
RE_TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}")    # najvnorenejsia sablona (bez dalsich {{ }} vnutri)
RE_LINK = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")   # najvnorenejsi odkaz [[ciel|text]]
RE_SKIP_LINK = re.compile(r"^\s*:?\s*(?:File|Image|Category)\s*:", re.I)
RE_TABLE = re.compile(r"\{\|.*?\|\}", re.S)
RE_TAG = re.compile(r"<[^>]+>")
RE_QUOTES = re.compile(r"'{2,}")                 # ''kurziva'', '''tucne'''
RE_MAGIC = re.compile(r"__[A-Z]+__")             # __NOTOC__ ...
RE_SPACE = re.compile(r"\s+")
RE_HEADING = re.compile(r"^=+[^=\n]+=+\s*$", re.M)
RE_CATEGORY = re.compile(r"\[\[\s*Category\s*:\s*([^\]|]+)", re.I)
RE_PAREN = re.compile(r"\s*\([^)]*\)\s*$")       # "Rodri (footballer, born 1996)" -> "Rodri"
RE_NUMBER = re.compile(r"(\d+)")

# riadok "Career total" tabulky Career statistics, bunky na jednom alebo viacerych riadkoch
RE_CAREER_TOTAL = re.compile(r"^[!|][^\n]*?career\s+total\b(.*?)(?=\n\|-|\n\|\}|\Z)", re.I | re.M | re.S)
RE_CELL_SEP = re.compile(r"\n[!|]|!!|\|\|")
MAX_APPS = 1500                                   # viac zapasov = chyba v tabulke
# reprezentacia, ktora nie je A-tim: England U21, Spain Under-19, Brazil Olympic, England B
RE_YOUTH_TEAM = re.compile(r"\s*\b(?:U-?\d{2}|Under-?\s?\d{2}|Olympic|B|XI|Amateurs?|Youth)\b", re.I)

# sablony, z ktorych sa ponecha text argumentov (ostatne sa zmazu: flagicon, cite, efn ...)
KEEP_ARGS = {"nowrap", "small", "nobold", "nobr", "br entries", "ubl", "unbulleted list", "plainlist",
             "flatlist", "hlist", "bulleted list", "sortname", "abbr"}
LAST_ARG = {"lang", "transl", "transliteration"}  # {{lang|es|text}} -> text
FIRST_ARG = {"ill", "interlanguage link"}          # {{ill|meno|de|...}} -> meno

# datum narodenia: {{birth date and age|2001|9|5|df=y}}, {{Birth date and age|2004|May|3}},
# {{bda|...}}, alebo text "5 September 2001"
RE_DATE_TEMPLATE = re.compile(r"\{\{\s*(?:birth[ _-]+date(?:[ _-]+and[ _-]+age)?|bda|dob)\s*\|([^{}]*)\}\}", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
MONTH = r"(" + "|".join(MONTHS) + r")"
RE_DMY = re.compile(r"\b(\d{1,2})\s+" + MONTH + r",?\s+(\d{4})\b", re.I)
RE_MDY = re.compile(r"\b" + MONTH + r"\s+(\d{1,2}),?\s+(\d{4})\b", re.I)


def m_to_cm(g):
    return float(g[0].replace(",", ".")) * 100


def ft_to_cm(g):
    return (int(g[0]) * 12 + float(g[1])) * 2.54


# vyska: {{height|m=1.85}}, {{height|ft=5|in=8}}, {{convert|185|cm|...}}, "1.85 m", "185 cm"
HEIGHT_PATTERNS = [
    (re.compile(r"\|\s*m\s*=\s*(\d[.,]\d{1,2})"), m_to_cm),
    (re.compile(r"\|\s*cm\s*=\s*(\d{3})"), lambda g: float(g[0])),
    (re.compile(r"\|\s*ft\s*=\s*(\d)\s*\|\s*in\s*=\s*(\d{1,2}(?:\.\d+)?)"), ft_to_cm),
    (re.compile(r"convert\s*\|\s*(\d[.,]\d{1,2})\s*\|\s*m\b", re.I), m_to_cm),
    (re.compile(r"convert\s*\|\s*(\d{3})\s*\|\s*cm\b", re.I), lambda g: float(g[0])),
    (re.compile(r"convert\s*\|\s*(\d)\s*\|\s*ft\s*\|\s*(\d{1,2}(?:\.\d+)?)\s*\|\s*in", re.I), ft_to_cm),
    (re.compile(r"(\d[.,]\d{1,2})\s*(?:m|metres?|meters?)\b"), m_to_cm),
    (re.compile(r"(\d{3})\s*cm\b"), lambda g: float(g[0])),
    (re.compile(r"(\d)\s*ft\s*(\d{1,2}(?:\.\d+)?)(?:\s*\+?\s*\d/\d)?\s*in"), ft_to_cm),   # 5 ft 11+1/2 in
]
HEIGHT_RANGE = (140, 215)                         # mimo rozsahu = chyba v zapise, ignoruje sa


def find(regex, text):
    m = regex.search(text)
    return m.group(1) if m else ""


def expand_template(match):
    """Najvnorenejsia sablona -> text (iba sablony, ktore nesu text mena alebo klubu)."""
    parts = [part.strip() for part in match.group(1).split("|")]
    name = parts[0].lower().replace("_", " ")
    args = [part for part in parts[1:] if "=" not in part]   # pozicne argumenty
    if name in KEEP_ARGS:
        return " ".join(args)
    if name in LAST_ARG and args:
        return args[-1]
    if name in FIRST_ARG and args:
        return args[0]
    return ""


def link_text(match):
    """[[ciel|text]] -> text, [[ciel]] -> ciel; obrazky a kategorie sa zmazu."""
    target, label = match.group(1), match.group(2)
    if RE_SKIP_LINK.match(target):
        return ""
    return target if label is None else label


def clean(text):
    """Wikitext -> cisty text na jeden riadok (bez sablon, odkazov, referencii a HTML)."""
    text = RE_REF.sub(" ", RE_COMMENT.sub("", text))
    while True:                                   # zvnutra von, kym sa este nieco meni
        new = RE_TEMPLATE.sub(expand_template, RE_LINK.sub(link_text, text))
        if new == text:
            break
        text = new
    text = RE_TABLE.sub(" ", text)
    text = RE_QUOTES.sub("", RE_MAGIC.sub("", RE_TAG.sub(" ", text)))
    return RE_SPACE.sub(" ", html.unescape(text)).strip()   # &nbsp; &ndash; v samotnom wikitexte


def infobox(text):
    """Najde infobox futbalistu. Vrati (zaciatok, koniec, {pole: surova hodnota}) alebo None.
    Polia sa delia znakom | iba na najvyssej urovni, vnorene sablony a odkazy sa preskocia."""
    m = RE_INFOBOX.search(text)
    if not m:
        return None
    depth, last, parts, end = 1, m.end(), [], len(text)
    for token in RE_TOKEN.finditer(text, m.end()):
        t = token.group()
        if t == "|":
            if depth == 1:
                parts.append(text[last:token.start()])
                last = token.end()
            continue
        depth += 1 if t in ("{{", "[[") else -1
        if depth == 0:
            parts.append(text[last:token.start()])
            end = token.end()
            break
    fields = {}
    for part in parts:
        key, sep, value = part.partition("=")
        if sep:
            fields[key.strip().lower().replace(" ", "_")] = value.strip()
    return m.start(), end, fields


def field(fields, head, *keys):
    """Surova hodnota pola infoboxu (prvy neprazdny z klucov). Vnoreny infobox futbalistu
    (embed = yes, napr. Pele) ma datum narodenia a vysku v nadradenom infoboxe osoby, preto sa
    pole hlada aj v uvodnej casti clanku."""
    for key in keys:
        if fields.get(key):
            return fields[key]
    for key in keys:
        value = find(re.compile(FIELD.format(key), re.M), head).strip()
        if value:
            return value
    return ""


def parse_date(raw):
    """Datum narodenia z hodnoty infoboxu -> "YYYY-MM-DD" (alebo "" ak nie je cely datum)."""
    raw = RE_REF.sub(" ", RE_COMMENT.sub("", raw))
    template = RE_DATE_TEMPLATE.search(raw)
    if template:
        args = [a.strip() for a in template.group(1).split("|") if "=" not in a]
        if len(args) >= 3 and args[0].isdigit() and args[2].isdigit() and month_number(args[1]):
            return valid_date(int(args[0]), month_number(args[1]), int(args[2]))
        raw = " ".join(args)                      # {{birth date and age|5 September 2001}}
    m = RE_DMY.search(raw)
    if m:
        return valid_date(int(m.group(3)), MONTHS.index(m.group(2).lower()) + 1, int(m.group(1)))
    m = RE_MDY.search(raw)
    if m:
        return valid_date(int(m.group(3)), MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
    return ""


def month_number(text):
    """Mesiac v sablone ako cislo alebo slovo ("5", "May", "Sept") -> 1-12, 0 ak nie je mesiac."""
    text = text.lower()
    if text.isdigit():
        return int(text)
    if len(text) >= 3:
        for number, month in enumerate(MONTHS, 1):
            if month.startswith(text):
                return number
    return 0


def valid_date(year, month, day):
    if 1850 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def parse_height(raw):
    """Vyska z hodnoty infoboxu -> cm ako text ("185"), "" ak sa neda urcit."""
    raw = RE_REF.sub(" ", RE_COMMENT.sub("", raw))
    for regex, to_cm in HEIGHT_PATTERNS:
        m = regex.search(raw)
        if m:
            cm = round(to_cm(m.groups()))
            return str(cm) if HEIGHT_RANGE[0] <= cm <= HEIGHT_RANGE[1] else ""
    return ""


def numbered(fields):
    """{"clubs1": .., "years1": .., "clubs2": ..} -> {1: {"clubs": .., "years": ..}, 2: {...}}."""
    rows = {}
    for key, value in fields.items():
        m = RE_NUMBERED.match(key)
        if m:
            rows.setdefault(int(m.group(2)), {})[m.group(1)] = value
    return [rows[i] for i in sorted(rows)]


def career_rows(rows, prefix=""):
    """Riadky kariery z ocislovanych poli -> [(roky, tim, zapasy, goly)], riadky bez timu sa vynechaju.
    prefix: "" pre kluby (years, clubs, caps, goals), "national" pre reprezentaciu, "youth" pre mladez."""
    team_key = {"": "clubs", "national": "nationalteam", "youth": "youthclubs"}[prefix]
    items = []
    for row in rows:
        team = clean(row.get(team_key, "")).replace("\u2192", "").strip()   # sipka = hostovanie
        if not team:
            continue
        years = clean(row.get(prefix + "years", "")).replace("\u2013", "-").replace(" ", "")   # pomlcka
        caps = find(RE_NUMBER, clean(row.get(prefix + "caps", "")))
        goals = find(RE_NUMBER, clean(row.get(prefix + "goals", "")))
        items.append((years, team, caps, goals or ("0" if caps else "")))
    return items


def career(rows, prefix=""):
    """Riadky kariery -> "2018-2021 Arsenal (70/12); ..." (roky, tim, zapasy/goly)."""
    items = []
    for years, team, caps, goals in career_rows(rows, prefix):
        stats = f" ({caps}/{goals})" if caps else ""
        items.append(f"{years} {team}{stats}".strip())
    return LIST_SEP.join(items)


def main_national_team(rows):
    """Hlavna reprezentacia ako na worldfootball: A-tim s najviac zapasmi -> (tim, zapasy, goly).
    Hrac iba s mladeznickymi vybermi dostane krajinu bez pripony (England U21 -> England) bez zapasov."""
    teams = career_rows(rows, "national")
    senior = [(team, caps, goals) for _, team, caps, goals in teams if not RE_YOUTH_TEAM.search(team)]
    if senior:
        return max(senior, key=lambda item: int(item[1] or 0))
    if teams:
        return RE_YOUTH_TEAM.sub("", teams[0][1]).strip(), "", ""
    return "", "", ""


def club_totals(text):
    """Zapasy a goly za kluby vo vsetkych sutaziach, rovnaky vyznam ako Career total na worldfootball.
    Beru sa z riadku "Career total" tabulky Career statistics, posledne dve cisla su stlpec Total.
    Infobox ma iba ligove zapasy, preto sa nepouzije. Ma tento riadok aj tabulka reprezentacie,
    berie sa riadok s najviac zapasmi (klubov je vzdy viac). ("", "") ak clanok tabulku nema."""
    best = None
    for m in RE_CAREER_TOTAL.finditer(text):
        numbers = []
        for cell in RE_CELL_SEP.split(m.group(1)):
            value = clean(cell).rsplit("|", 1)[-1].replace(",", "").strip()   # bez atributov colspan=2|
            if value.isdigit():
                numbers.append(int(value))
        if len(numbers) < 2:
            continue
        apps, goals = numbers[-2:]
        if 0 < apps <= MAX_APPS and goals <= apps and (best is None or apps > best[0]):
            best = (apps, goals)
    return (str(best[0]), str(best[1])) if best else ("", "")


def head_of(text):
    """Uvodna cast clanku pred prvym nadpisom ==...== (infoboxy a uvodny text)."""
    heading = RE_HEADING.search(text)
    return text[:heading.start()] if heading else text


def lead(head, box):
    """Uvodny text clanku bez infoboxu futbalistu, vycisteny od wiki znaciek."""
    if box[0] < len(head):
        head = head[:box[0]] + head[box[1]:]
    return clean(head)


def title_name(title):
    return RE_PAREN.sub("", title)


def parse_page(page):
    """Jedna stranka z dumpu -> zaznam do wiki_players.tsv, None ak nie je clanok s infoboxom."""
    m = RE_TEXT.search(page)
    if not m or find(RE_NS, page) != "0":
        return None
    text = html.unescape(m.group(1))
    box = infobox(text)
    if not box:
        return None
    fields = box[2]
    head = head_of(text)
    title = html.unescape(find(RE_TITLE, page))
    rows = numbered(fields)
    national_team, nat_apps, nat_goals = main_national_team(rows)
    club_apps, club_goals = club_totals(text)
    return {
        "id": find(RE_PAGE_ID, page),
        "title": title,
        "name": clean(fields.get("name", "")) or title_name(title),
        "full_name": clean(field(fields, head, "full_name", "fullname")),
        "birth_date": parse_date(field(fields, head, "birth_date")),
        "birth_place": clean(field(fields, head, "birth_place")),
        "height_cm": parse_height(field(fields, head, "height")),
        "position": clean(fields.get("position", "")),
        "current_club": clean(fields.get("currentclub") or fields.get("current_club", "")),
        "youth_clubs": career(rows, "youth"),
        "clubs": career(rows),
        "national_teams": career(rows, "national"),
        "national_team": national_team, "nat_apps": nat_apps, "nat_goals": nat_goals,
        "club_apps": club_apps, "club_goals": club_goals,
        "categories": LIST_SEP.join(c.strip() for c in RE_CATEGORY.findall(text)),
        "abstract": lead(head, box),
        "url": WIKI_URL + title.replace(" ", "_"),
    }
