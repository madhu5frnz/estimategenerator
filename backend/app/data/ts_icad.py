"""Load the TS I&CAD Standard Data 2026-27 (built by tools/ts_sor) as rate-list records.

Each book item becomes a rate item with its printed rate and labour component. Its data
sheet is converted to the analysis JSON (app.domain.icad.serialize) and recomputed with
the engine; `analysis_status` is

* ``verified``   - recomputes to the printed rate (within Rs 0.06), editable in estimates
* ``rounded``    - recomputes within the book's own rounding (<= Rs 1 or 0.2 %)
* ``unverified`` - the printed breakdown could not be reconstructed; the printed rate is
                   used and the sheet is shown for reference only
* ``none``       - the book has no data sheet for the item
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.domain.icad.rate_analysis import DataSheetError, compute
from app.domain.icad.serialize import AnalysisFormatError, to_sheet

DATA = Path(__file__).resolve().parent / "ts_icad_2026_27"
UNIT_MAP = {
    "cum": "cum",
    "cum.": "cum",
    "*cum": "cum",
    "sqm": "sqm",
    "rm": "rmt",
    "*rm": "rmt",
    "each": "nos",
    "one": "nos",
    "stage": "nos",
    "shifting": "nos",
    "tonne": "mt",
    "kg": "kg",
    "joint": "joint",
    "joints": "joint",
    "kwhr": "kwh",
}
TWO = Decimal("0.01")
NUM = re.compile(r"\d[\d,]*\.?\d*")


def unit_code(unit: str | None) -> str | None:
    return UNIT_MAP.get((unit or "").strip().lower())


def _num(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))


def _quantity(printed: str, rate: Decimal, amount: Decimal) -> str:
    """The book prints quantities to 2 decimals but computed amounts from the full value
    (6.921 cum x 1107 = 7661.55, printed as 6.92). Rebuild the quantity when that is what
    reproduces the printed amount."""
    q = _num(printed)
    if rate and (q * rate).quantize(TWO, ROUND_HALF_UP) != amount:
        exact = (amount / rate).quantize(Decimal("0.0001"), ROUND_HALF_UP).normalize()
        if (exact * rate).quantize(TWO, ROUND_HALF_UP) == amount:
            return format(exact, "f")
    return printed.replace(",", "")


def convert(sheet: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for section in ("A", "B", "C"):
        kept: list[dict[str, Any]] = []
        for r in sheet["sections"][section]:
            amount = _num(r["amount"])
            if r.get("pct") is not None and kept:
                pct = _num(r["pct"])
                prev = len(kept) - 1
                prev_amount = _num(kept[prev]["_amount"])
                if (prev_amount * pct / 100).quantize(TWO, ROUND_HALF_UP) == amount:
                    kept.append(
                        {
                            "section": section,
                            "description": r["name"],
                            "unit": "%",
                            "pct": r["pct"],
                            "pct_of_row": prev,
                            "_amount": r["amount"],
                        }
                    )
                    continue
            name, unit = r["name"], r["unit"]
            if " " in unit.strip():  # "Coarse aggregate 40-20" + "mm cum": size belongs to the name
                *head, unit = unit.split()
                name = f"{name} {' '.join(head)}"
            if r.get("rate") and r.get("qty") and _num(r["rate"]) != 0:
                rate = _num(r["rate"])
                kept.append(
                    {
                        "section": section,
                        "description": name,
                        "unit": unit,
                        "quantity": _quantity(r["qty"], rate, amount),
                        "rate": r["rate"].replace(",", ""),
                        "_amount": r["amount"],
                    }
                )
            elif amount != 0:  # factor rows ("Reconditioning charges @ 0.10") kept as fixed sums
                kept.append(
                    {
                        "section": section,
                        "description": r["name"],
                        "unit": "LS",
                        "quantity": "1",
                        "rate": format(amount, "f"),
                        "_amount": r["amount"],
                    }
                )
        for row in kept:
            row.pop("_amount")
        rows.extend(kept)
    extras = []
    for line in sheet.get("extras", []):
        numbers = NUM.findall(line)
        if numbers:
            extras.append(
                {
                    "description": NUM.sub("", line).strip(" @:.") or line,
                    "amount": numbers[-1].replace(",", ""),
                }
            )
    return {
        "analysis_qty": (sheet.get("analysis_qty") or "1").replace(",", ""),
        "unit": sheet.get("analysis_unit", ""),
        "ohp_pct": "13.615",
        "or_say_step": "0.1",
        "rows": rows,
        "additions": [
            {"description": a["name"], "pct": a["pct"]} for a in sheet.get("additions", [])
        ],
        "extras": extras,
    }


def _status(
    code: str, description: str, analysis: dict[str, Any], printed: Decimal
) -> tuple[str, str | None]:
    try:
        result = compute(to_sheet(code, description, analysis))
    except (DataSheetError, AnalysisFormatError, ArithmeticError) as exc:
        return "unverified", str(exc)
    diff = abs(result.rate_before_adjustments - printed)
    if diff <= Decimal("0.06"):
        return "verified", None
    if diff <= 1 or diff / printed <= Decimal("0.002"):
        return "rounded", f"recomputes to {result.rate_before_adjustments:.2f}"
    return (
        "unverified",
        f"recomputes to {result.rate_before_adjustments:.2f}, book prints {printed}",
    )


@lru_cache(maxsize=1)
def book_items() -> list[dict[str, Any]]:
    items = json.loads((DATA / "items.json").read_text())["items"]
    sheets = {
        s["code"]: s for s in json.loads((DATA / "datasheets.json").read_text())["datasheets"]
    }
    out = []
    for item in items:
        if not item.get("rate") or not unit_code(item.get("unit")):
            continue
        rate = _num(item["rate"])
        record: dict[str, Any] = {
            "code": item["code"],
            "sl": item["sl"],
            "description": item["description"],
            "group": (item.get("group") or {}).get("title"),
            "unit_code": unit_code(item["unit"]),
            "rate": format(rate, "f"),
            "labour_component": item.get("labour_component"),
            "analysis": None,
            "analysis_status": "none",
            "analysis_note": None,
        }
        sheet = sheets.get(item["code"])
        if sheet and sheet.get("analysis_qty"):
            analysis = convert(sheet)
            status, note = _status(item["code"], item["description"], analysis, rate)
            record.update(analysis=analysis, analysis_status=status, analysis_note=note)
        elif sheet:
            record.update(
                analysis_status="unverified",
                analysis_note="analysis unit not found in the book text",
            )
        out.append(record)
    return out
