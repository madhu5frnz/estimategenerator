"""Parse TS I&CAD Standard Data 2026-27 data sheets from pdfplumber text."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
CODE = re.compile(r"^(IRR[-_ ][A-Z]+[-_ ]\d+[-_ ]\d+(?:\([a-z]\))?)(?:\s+[A-Z(].*)?\s*$")
NUM = r"-?\d[\d,]*\.?\d*"
ROW = re.compile(
    rf"^(?:(?P<sl>\d{{1,2}})\s+)?(?P<name>.*?)\s+(?P<unit>[A-Za-z][A-Za-z./ ]*?|%|Each|LS)\s+"
    rf"(?P<qty>{NUM})\s+(?P<rate>{NUM})\s+(?P<amt>{NUM})\s*$"
)
PCT = re.compile(rf"^(?P<name>.*?)\s+(?P<pct>{NUM})\s*%\s+(?P<amt>{NUM})\s*$")
UNIT = re.compile(rf"UNIT\s*:?\s*(?:A\.\s*MATERIALS:?\s*)?(?P<q>{NUM})\s*(?P<u>[A-Za-z.]+)")
TOTAL = re.compile(
    rf"^Total (?:cost of Materials|hire charges of Machinery|cost of Machinery|cost of Labour)\s*(?:Rs[.:]?)?\s*(?P<amt>{NUM})\s*$"
)
FACTOR = re.compile(rf"^(?:\d{{1,2}}\s+)?(?P<name>.*?)\s*@\s*(?P<f>{NUM})\s+(?P<amt>{NUM})\s*$")
ABS_START = re.compile(r"^(A\.\s*MATERIAL\b|A\.\s*Cost of Materials|ABSTRACT)", re.I)
RATE = re.compile(rf"^Rate per\s+(?P<u>\S+).*?(?P<rate>{NUM})\s*$", re.I)
TOTAL_FOR = re.compile(rf"^Total cost for\s+(?P<q>{NUM})\s*(?P<u>\S+)", re.I)
OHP = re.compile(
    rf"^(?:D\.\s*)?Add (?:for contractor.*?)?(?P<pct>13\.615)\s*%\s*Rs[.:]?\s*(?P<amt>{NUM})"
)


def num(s: str) -> D:
    return D(s.replace(",", ""))


def parse(text: str) -> list[dict]:
    lines = [ln.strip() for ln in text.splitlines()]
    starts = [i for i, ln in enumerate(lines) if CODE.match(ln)]
    items = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        seg = [
            ln
            for ln in lines[start + 1 : end]
            if ln
            and not ln.startswith("=====PAGE")
            and not re.match(r"^Page \d+ of \d+$", ln)
            and not re.search(r"- ?2026-27$", ln)
        ]
        code = re.sub(r"[_ ]", "-", CODE.match(lines[start]).group(1))
        body = "\n".join(seg)
        if "MATERIALS" not in body.upper() or not any(RATE.match(s) for s in seg):
            continue  # chapter heading, not a data sheet
        item: dict = {
            "code": code,
            "description": [],
            "sections": {"A": [], "B": [], "C": []},
            "totals": {},
            "extras": [],
            "notes": [],
        }
        section = None
        stage = "desc"
        for ln in seg:
            up = ln.upper()
            m = UNIT.search(ln)
            if m and "analysis_qty" not in item and ("UNIT" in up):
                item["analysis_qty"], item["analysis_unit"] = m.group("q"), m.group("u").rstrip(".")
            if "RATE ANALYSIS" in up or up.startswith("A. MATERIALS") or up.startswith("DATA"):
                stage = "data"
            if stage == "desc":
                item["description"].append(ln)
                continue
            if (
                up.startswith("A. MATERIALS")
                or up.startswith("A.MATERIALS")
                or "A. MATERIALS" in up
            ):
                section = "A"
                if "ABSTRACT" not in up:
                    continue
            if up.startswith("B. MACHINERY") or up.startswith("B.MACHINERY"):
                section = "B"
                continue
            if up.startswith("C. LABOUR") or up.startswith("C.LABOUR"):
                section = "C"
                continue
            if section in ("A", "B", "C") and ABS_START.match(ln) and section == "C":
                section = "ABS"
                if up.startswith("ABSTRACT"):
                    continue
            if up.startswith("ABSTRACT"):
                section = "ABS"
                continue
            t = TOTAL.match(ln)
            if t:
                key = {
                    "Total cost of Materials": "A",
                    "Total hire charges of Machinery": "B",
                    "Total cost of Machinery": "B",
                    "Total cost of Labour": "C",
                }
                for k, v in key.items():
                    if ln.startswith(k):
                        if section in ("A", "B", "C") and v == section:
                            item["totals"][v] = t.group("amt")
                        elif section == "ABS":
                            item["totals"].setdefault("abs_" + v, t.group("amt"))
                continue
            if up.startswith(("SL NO", "IN RS", "RATE AMOUNT", "RATE ")) and "RATE PER" not in up:
                continue
            bare = re.fullmatch(rf"Rs[.:]?\s*(?P<amt>{NUM})", ln)
            if bare and section in ("A", "B", "C") and section not in item["totals"]:
                item["totals"][section] = bare.group("amt")
                continue
            if section == "ABS":
                o = OHP.match(ln)
                if o:
                    item["ohp_pct"], item["totals"]["D"] = o.group("pct"), o.group("amt")
                    stage = "after_d"
                    continue
                tf = TOTAL_FOR.match(ln)
                if tf:
                    item["totals"]["total_for"] = ln
                    stage = "total"
                    continue
                r = RATE.match(ln)
                if r:
                    item["rate"] = r.group("rate")
                    item["rate_line"] = ln
                    stage = "done"
                    continue
                if (
                    (stage == "after_d" or re.search(r"LEAD|CONVEYANCE|LIFT CHARGES", up))
                    and re.search(NUM + r"\s*$", ln)
                    and not re.fullmatch(NUM, ln)
                    and not up.startswith(("TOTAL", "D.", "D ", "PERCENTAGES"))
                ):
                    item["extras"].append(ln)
                elif stage != "after_d" and ln.upper().startswith("ADD") and "%" in ln:
                    m2 = re.search(rf"(?P<pct>{NUM})\s*%\s*(?:Rs[.:]?)?\s*(?P<amt>{NUM})\s*$", ln)
                    if m2:
                        item.setdefault("additions", []).append(
                            {
                                "name": ln[: m2.start()].strip(" @"),
                                "pct": m2.group("pct"),
                                "amount": m2.group("amt"),
                            }
                        )
                continue
            if section in ("A", "B", "C"):
                if up.startswith("LABOUR COMPONENT"):
                    found = re.findall(NUM, ln)
                    key = "labour_component_incl" if "INCLUDING" in up else "labour_component"
                    if found:
                        item[key] = found[-1]
                    else:
                        item["pending_label"] = key
                    continue
                if item.get("pending_label") and re.fullmatch(NUM, ln):
                    item[item.pop("pending_label")] = ln
                    continue
                if up.startswith("ADD CONTRACTOR"):
                    continue
                heading = re.fullmatch(r"(?:\d{1,2}\s+)?([A-Za-z][A-Za-z .()/-]{2,40})", ln)
                if heading and not ROW.match(ln):
                    item["group_label"] = heading.group(
                        1
                    ).strip()  # e.g. "7 mazdoor" over "for laying"
                    continue
                r = ROW.match(ln)
                if r and r.group("sl"):
                    item.pop("group_label", None)
                if r:
                    name, unit = r.group("name").strip(), r.group("unit").strip()
                    if " " in unit:  # "work" + "inspector Day": words before the unit are the name
                        *head, unit = unit.split()
                        name = f"{name} {' '.join(head)}".strip()
                    if item.get("group_label") and name.lower().startswith("for "):
                        name = f"{item['group_label']} {name}"
                    item["sections"][section].append(
                        {
                            "sl": r.group("sl"),
                            "name": name,
                            "unit": unit,
                            "qty": r.group("qty"),
                            "rate": r.group("rate"),
                            "amount": r.group("amt"),
                        }
                    )
                    continue
                f = FACTOR.match(ln)
                if f and not PCT.match(ln):
                    item["sections"][section].append(
                        {
                            "sl": None,
                            "name": f.group("name").strip(),
                            "unit": "factor",
                            "factor": f.group("f"),
                            "amount": f.group("amt"),
                        }
                    )
                    continue
                p = PCT.match(ln)
                if p:
                    item["sections"][section].append(
                        {
                            "sl": None,
                            "name": p.group("name").strip(),
                            "unit": "%",
                            "pct": p.group("pct"),
                            "amount": p.group("amt"),
                        }
                    )
                    continue
                item["notes"].append(f"{section}: {ln}")
        item["description"] = " ".join(item["description"])
        items.append(item)
    return items


def check(item: dict) -> list[str]:
    problems = []
    for s in ("A", "B", "C"):
        rows = item["sections"][s]
        total = sum((num(r["amount"]) for r in rows), D(0))
        printed = item["totals"].get(s)
        if printed is None:
            problems.append(f"{s}: no printed total")
        elif abs(total - num(printed)) > D("0.05"):
            problems.append(f"{s}: rows {total} != printed {printed}")
    try:
        abc = sum(num(item["totals"][s]) for s in ("A", "B", "C"))
        d = (abc * D("0.13615")).quantize(D("0.01"), ROUND_HALF_UP)
        q = num(item["analysis_qty"])
        adds = sum((num(a["amount"]) for a in item.get("additions", [])), D(0))
        d = ((abc + adds) * D("0.13615")).quantize(D("0.01"), ROUND_HALF_UP)
        extras = sum(
            (num(re.findall(NUM, e)[-1]) for e in item["extras"] if re.findall(NUM, e)), D(0)
        )
        rate = (abc + adds + d + extras) / q
        printed = num(item["rate"])
        item["recomputed_rate"] = str(rate.quantize(D("0.01"), ROUND_HALF_UP))
        diff = abs(rate - printed)
        if diff > D("0.06"):
            kind = "rate_rounding" if diff <= D(1) or diff / printed <= D("0.002") else "rate"
            problems.append(f"{kind}: recomputed {rate:.2f} != printed {printed}")
    except (KeyError, ArithmeticError) as exc:
        problems.append(f"rate: cannot recompute ({exc!r})")
    return problems
