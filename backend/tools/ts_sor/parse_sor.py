"""Parse basic input rates from the Telangana SoR 2026-27 (Part-I I&CAD and Part-II labour)."""

from __future__ import annotations

import re

NUM = r"\d[\d,]*\.\d{2}"
UNIT = r"(?:cum|Cum|sqm|Sqm|Rm|RM|Rmt|Each|each|No\.?|Nos\.?|tonne|Tonne|MT|kg|Kg|Ltr|ltr|litre|Set|set|Hour|Day|Pair|pair|Job|Coil|Bag|bag|Roll|roll|Km|km|Kl|KL|Lit|Litre)"
MAT_ROW = re.compile(
    rf"^(?P<sl>\d{{1,3}}\s*(?:\([a-z]\))?)\s+(?P<name>.+?)\s+(?P<unit>{UNIT})\s+(?P<rate>{NUM})\s*$"
)
MAT_TAIL = re.compile(rf"^(?P<name>.*?)\s*(?P<unit>{UNIT})\s+(?P<rate>{NUM})\s*$")
MAT_SLRATE = re.compile(
    rf"^(?P<sl>\d{{1,3}}\s*(?:\([a-z]\))?)\s+(?P<name>.*?)\s*(?P<rate>{NUM})\s*$"
)
LABOUR_ROW = re.compile(
    r"^(?P<sl>\d{1,3})\s+(?P<name>.+?)\s+Per\s+(?P<unit>Day|Hour|Month)\s+(?P<z1>\d+)\s+(?P<z2>\d+)\s+(?P<z3>\d+)\s*$"
)
LABOUR_SPLIT = re.compile(
    r"^(?P<sl>\d{1,3})\s+Per\s+(?P<unit>Day|Hour|Month)\s+(?P<z1>\d+)\s+(?P<z2>\d+)\s+(?P<z3>\d+)\s*$"
)
HIRE_ROW = re.compile(
    rf"^(?P<sl>\d{{1,3}})\s+(?P<name>.*?)\s*(?P<unit>Hour|Day|Month|Each)\s+(?P<hire>{NUM})\s+(?P<fuel>{NUM})\s+(?P<crew>{NUM})\s+(?P<total>{NUM})\s*$"
)


def pages(text: str, first: int, last: int) -> str:
    start = text.index(f"=====PAGE {first}/")
    end = text.index(f"=====PAGE {last + 1}/")
    return text[start:end]


def _clean(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("=====PAGE") or re.match(r"^Page \d+ of \d+$", ln):
            continue
        if "SoR 2026-27" in ln or ln.startswith(("Sl.", "Sl ", "No.", "Description", "Scheduled")):
            continue
        out.append(ln)
    return out


def parse_materials(text: str) -> list[dict]:
    """Material rows are 'Sl Description Unit Rate', often wrapped over two or three lines."""
    rows: list[dict] = []
    pending: list[str] = []
    for ln in _clean(text.splitlines()):
        m = MAT_ROW.match(ln)
        if m:
            name = " ".join([*pending, m.group("name")])
            rows.append(
                {
                    "sl": m.group("sl").replace(" ", ""),
                    "name": name,
                    "unit": m.group("unit"),
                    "rate": m.group("rate"),
                }
            )
            pending = []
            continue
        m = MAT_SLRATE.match(ln)
        if m:  # "27 (a) cum 777.00" style: unit may follow on the next line
            rows.append(
                {
                    "sl": m.group("sl").replace(" ", ""),
                    "name": " ".join([*pending, m.group("name")]).strip(),
                    "unit": None,
                    "rate": m.group("rate"),
                }
            )
            pending = []
            continue
        t = MAT_TAIL.match(ln)
        if t and rows and rows[-1]["unit"] is None:
            rows[-1]["unit"] = t.group("unit")
            rows[-1]["name"] = f"{rows[-1]['name']} {t.group('name')}".strip()
            continue
        if (
            rows
            and rows[-1]["unit"] is None
            and re.fullmatch(UNIT, ln.split()[-1] if ln.split() else "")
        ):
            rows[-1]["unit"] = ln.split()[-1]
            rows[-1]["name"] = f"{rows[-1]['name']} {' '.join(ln.split()[:-1])}".strip()
            continue
        if (
            len(ln) < 90
            and not re.match(r"^\d+\.\s", ln)
            and not ln.endswith(".")
            and not ln.startswith(("The ", "Note", "*(Note", "(Note", "However"))
        ):
            pending.append(ln)
            pending = pending[-2:]
        else:
            pending = []
    for r in rows:
        r["name"] = re.sub(r"\s+", " ", r["name"]).strip()
    return rows


def parse_labour(text: str) -> list[dict]:
    rows: list[dict] = []
    pending: list[str] = []
    category = None
    for ln in _clean(text.splitlines()):
        if re.fullmatch(r"[A-Z &-]+CATEGORY:?", ln):
            category = ln.rstrip(":").title()
            pending = []
            continue
        m = LABOUR_ROW.match(ln)
        if m:
            name = " ".join([*pending, m.group("name")])
        else:
            m = LABOUR_SPLIT.match(ln)
            name = " ".join(pending)
        if m:
            rows.append(
                {
                    "sl": m.group("sl"),
                    "category": category,
                    "name": re.sub(r"\s+", " ", name).strip(),
                    "unit": m.group("unit"),
                    "zone_1": m.group("z1"),
                    "zone_2": m.group("z2"),
                    "zone_3": m.group("z3"),
                }
            )
            pending = []
            continue
        if len(ln) < 60:
            if rows and (ln.startswith("/") or ln[:1].islower()) and not pending:
                rows[-1]["name"] = f"{rows[-1]['name']} {ln}"  # wrapped tail of the row above
                continue
            pending.append(ln)
            pending = pending[-2:]
    return rows


def parse_hire(text: str) -> list[dict]:
    rows: list[dict] = []
    pending: list[str] = []
    for ln in _clean(text.splitlines()):
        m = HIRE_ROW.match(ln)
        if m:
            name = m.group("name") or ""
            name = " ".join([*pending, name]).strip()
            name = re.sub(r"^.*?\b1 2 3 4 5 6 7\s*", "", name)
            name = re.sub(r"^\d+\s+\*?\s*", "", name)
            rows.append(
                {
                    "sl": m.group("sl"),
                    "name": re.sub(r"\s+", " ", name),
                    "unit": m.group("unit"),
                    "hire": m.group("hire"),
                    "fuel": m.group("fuel"),
                    "crew": m.group("crew"),
                    "total": m.group("total"),
                }
            )
            pending = []
            continue
        if rows and not pending and len(ln) < 40 and not re.search(NUM, ln) and ln[0].islower():
            rows[-1]["name"] = f"{rows[-1]['name']} {ln}"  # wrapped tail, e.g. "electric)"
            continue
        if len(ln) < 60 and not re.search(NUM, ln):
            pending.append(ln)
            pending = pending[-2:]
    return rows
