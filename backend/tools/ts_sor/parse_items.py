"""Parse the 'Work item rates' list (Standard Data 2026-27, Abstract Items, pages 1-49)."""

from __future__ import annotations

import re

NUM = r"\d[\d,]*\.\d{2}"
UNITS = r"(?:\*?cum\.?|Cum|sqm|Sqm|Rm|RM|Rmt|Each|each|No\.?|Nos\.?|Joints?|tonne|Tonne|MT|kg|Kg|km|Km|LS|L\.S|ltr|litre|Set|set|Hour|Day|Month|Point|ha|Ha|m|\*Rm|Kwhr|one|shifting|stage|plug)"
START = re.compile(
    r"^(?P<sl>\d{1,4})\s+(?P<code>IRR[-_][A-Z]+[-_]\d+[-_]\d+(?:\([a-z]\))?)\s*(?P<rest>.*)$"
)
TAIL = re.compile(rf"^(?P<text>.*?)\s*(?P<unit>{UNITS})\s+(?P<rate>{NUM})\s*$")
LABOUR = re.compile(rf"^Labour Component.*?(?P<unit>{UNITS})\s+(?P<rate>{NUM})\s*$")
CHAPTER = re.compile(r"^(IRR[-_][A-Z]+[-_]\d+)\s+(.+?):?\s*$")


def parse(text: str) -> list[dict]:
    lines = [ln.strip() for ln in text.splitlines()]
    items: list[dict] = []
    cur: dict | None = None
    group = None
    for ln in lines:
        if not ln or ln.startswith("=====PAGE") or re.match(r"^Page \d+ of \d+$", ln):
            continue
        g = CHAPTER.match(ln)
        if g and not START.match(ln):
            group = {"code": g.group(1).replace("_", "-"), "title": g.group(2).strip()}
            continue
        m = START.match(ln)
        if (
            not m
            and cur is not None
            and (cur["labour_component"] is not None or cur["code"].startswith("SL-"))
        ):
            m2 = re.match(r"^(?P<sl>3[5-9]\d)\s+(?P<rest>[A-Z].*)$", ln)
            if m2 and int(m2.group("sl")) == cur["sl"] + 1:
                ln = f"{m2.group('sl')} SL-{m2.group('sl')} {m2.group('rest')}"
                m = re.match(r"^(?P<sl>\d+)\s+(?P<code>SL-\d+)\s*(?P<rest>.*)$", ln)
        if m:
            cur = {
                "sl": int(m.group("sl")),
                "code": m.group("code").replace("_", "-"),
                "group": group,
                "text": [],
                "unit": None,
                "rate": None,
                "labour_unit": None,
                "labour_component": None,
                "sub_rates": [],
            }
            items.append(cur)
            rest = m.group("rest")
            t = TAIL.match(rest)
            if t:
                cur["unit"], cur["rate"] = t.group("unit"), t.group("rate")
                if t.group("text"):
                    cur["text"].append(t.group("text"))
            elif rest:
                cur["text"].append(rest)
            continue
        if cur is None:
            continue
        lab = LABOUR.match(ln)
        if lab:
            cur["labour_unit"], cur["labour_component"] = lab.group("unit"), lab.group("rate")
            continue
        t = TAIL.match(ln)
        if t and cur["rate"] is None:
            cur["unit"], cur["rate"] = t.group("unit"), t.group("rate")
            if t.group("text"):
                cur["text"].append(t.group("text"))
            continue
        if t and cur["rate"] is not None and cur["labour_component"] is None:
            cur["sub_rates"].append(
                {"label": t.group("text"), "unit": t.group("unit"), "rate": t.group("rate")}
            )
            continue
        if cur["labour_component"] is None:
            cur["text"].append(ln)
    for it in items:
        it["description"] = re.sub(r"\s+", " ", " ".join(it.pop("text"))).strip()
    return items
