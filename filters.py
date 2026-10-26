"""Filtre nad stlpcami players.tsv, napr. nationality=spain age>19 height>=190 club~manchester.

Filter ma tvar pole + operator + hodnota. Textove polia sa porovnavaju bez ohladu na velkost
pismen a diakritiku (rovnaky normalize ako v tokenizeri), ciselne polia ako cele cisla.
Hrac, ktoremu hodnota pola chyba, filter nesplni."""
import operator
import re
from datetime import date

from tokenizer import normalize

# dlhsie operatory musia byt skor, inak by sa ">=" rozpoznalo ako ">"
RE_FILTER = re.compile(r"^([a-z_]+)(>=|<=|!=|=|>|<|~)(.+)$")

TEXT_FIELDS = ["name", "position", "club", "nationality", "national_team", "foot"]
NUMERIC_FIELDS = {"age": "birth_date",           # vek sa pocita z datumu narodenia
                  "height": "height_cm",
                  "club_apps": "club_apps", "club_goals": "club_goals",
                  "club_assists": "club_assists",
                  "nat_apps": "nat_apps", "nat_goals": "nat_goals", "nat_assists": "nat_assists"}

TEXT_OPERATORS = {"=": operator.eq, "!=": operator.ne,
                  "~": lambda value, part: part in value}   # ~ = obsahuje
NUMERIC_OPERATORS = {"=": operator.eq, "!=": operator.ne, ">": operator.gt,
                     "<": operator.lt, ">=": operator.ge, "<=": operator.le}


class FilterError(ValueError):
    """Neplatny filter (nezname pole, operator alebo hodnota)."""


def is_filter(arg):
    return RE_FILTER.match(arg) is not None


def age(birth_date, today=None):
    """Vek v celych rokoch k dnesnemu dnu; birth_date je "YYYY-MM-DD"."""
    today = today or date.today()
    born = date.fromisoformat(birth_date)
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def parse_filter(arg):
    """Text "age>19" -> (pole, operator, porovnavana hodnota)."""
    m = RE_FILTER.match(arg)
    if not m:
        raise FilterError(f"'{arg}' nie je filter v tvare pole<operator>hodnota")
    field, op, value = m.groups()
    if field in TEXT_FIELDS:
        if op not in TEXT_OPERATORS:
            raise FilterError(f"textove pole '{field}' podporuje len {', '.join(TEXT_OPERATORS)}")
        return field, op, normalize(value.strip())
    if field in NUMERIC_FIELDS:
        if op not in NUMERIC_OPERATORS:
            raise FilterError(f"ciselne pole '{field}' podporuje len {', '.join(NUMERIC_OPERATORS)}")
        if not value.strip().isdigit():
            raise FilterError(f"pole '{field}' potrebuje cele cislo, nie '{value}'")
        return field, op, int(value)
    known = ", ".join(TEXT_FIELDS + list(NUMERIC_FIELDS))
    raise FilterError(f"nezname pole '{field}', povolene su: {known}")


def field_value(player, field):
    """Hodnota pola hraca pripravena na porovnanie, alebo None ak chyba."""
    if field in TEXT_FIELDS:
        return normalize(player[field]) if player[field] else None
    raw = player[NUMERIC_FIELDS[field]]
    if not raw:
        return None
    return age(raw) if field == "age" else int(raw)


def matches(player, filters):
    """True, ak hrac splna vsetky filtre (vztah AND)."""
    for field, op, expected in filters:
        value = field_value(player, field)
        if value is None:
            return False
        compare = TEXT_OPERATORS[op] if field in TEXT_FIELDS else NUMERIC_OPERATORS[op]
        if not compare(value, expected):
            return False
    return True
