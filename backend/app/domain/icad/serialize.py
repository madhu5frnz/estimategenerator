"""JSON form of a rate analysis (stored on rate items and on estimate items).

    {
      "analysis_qty": "15.38", "unit": "cum", "ohp_pct": "13.615", "or_say_step": "0.1",
      "rows": [
        {"section": "A", "description": "Cement for mix", "unit": "kg",
         "quantity": "3998.8", "rate": "5.10"},
        {"section": "A", "description": "Scaffolding @ 10 % of shuttering", "unit": "%",
         "pct": "10", "pct_of_row": 7}
      ],
      "additions": [{"description": "Conveyor system", "pct": "3"}],
      "extras": [{"description": "Lead charges for 1 km for FA", "amount": "4048.80"}],
      "adjustments": [
        {"kind": "conveyance", "description": "Conveyance of sand", "quantity": "0.40",
         "lead_key": "<lead entry line key>"},
        {"kind": "correction", "description": "Cement rate difference", "quantity": "263",
         "rate": "0.20", "with_ohp": true}
      ],
      "deleted_rows": [6]
    }

`pct_of_row` indexes rows of the same section. Conveyance adjustments take their rate
from the estimate's lead statement at calculation time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from app.domain.icad.rate_analysis import (
    OHP_PCT,
    Addition,
    DataSheet,
    Extra,
    PerUnitAdjustment,
    Row,
)

LeadLookup = Callable[[str], Decimal | None]


class AnalysisFormatError(ValueError):
    pass


def _d(value: Any, name: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception as exc:
        raise AnalysisFormatError(f"{name}: '{value}' is not a number.") from exc


def to_sheet(
    code: str,
    description: str,
    data: Mapping[str, Any],
    lead_rate: LeadLookup | None = None,
) -> DataSheet:
    rows = []
    for n, r in enumerate(data.get("rows", [])):
        section = r.get("section")
        if section not in ("A", "B", "C"):
            raise AnalysisFormatError(f"Row {n + 1}: section must be A, B or C.")
        if r.get("pct") is not None:
            rows.append(
                Row(
                    section,
                    r.get("description", ""),
                    r.get("unit", "%"),
                    pct=_d(r["pct"], "pct"),
                    pct_of_row=int(r["pct_of_row"]),
                )
            )
        else:
            rows.append(
                Row(
                    section,
                    r.get("description", ""),
                    r.get("unit", ""),
                    _d(r.get("quantity"), "quantity"),
                    _d(r.get("rate"), "rate"),
                    is_labour=bool(r.get("is_labour", False)),
                )
            )
    adjustments = []
    for a in data.get("adjustments", []):
        if a.get("kind") == "conveyance":
            rate = lead_rate(a["lead_key"]) if lead_rate and a.get("lead_key") else None
            rate = rate if rate is not None else Decimal(0)
        else:
            rate = _d(a.get("rate", 0), "rate")
        adjustments.append(
            PerUnitAdjustment(
                a.get("description", ""),
                _d(a.get("quantity"), "quantity"),
                rate,
                with_ohp=bool(a.get("with_ohp", False)),
            )
        )
    return DataSheet(
        code=code,
        description=description,
        unit=data.get("unit", ""),
        analysis_qty=_d(data.get("analysis_qty"), "analysis quantity"),
        rows=rows,
        additions=[
            Addition(x.get("description", ""), _d(x["pct"], "pct"))
            for x in data.get("additions", [])
        ],
        extras=[
            Extra(x.get("description", ""), _d(x["amount"], "amount"))
            for x in data.get("extras", [])
        ],
        adjustments=adjustments,
        ohp_pct=_d(data.get("ohp_pct", OHP_PCT), "ohp_pct"),
        or_say_step=_d(data.get("or_say_step", "0.1"), "or_say_step"),
        deleted_rows=frozenset(int(i) for i in data.get("deleted_rows", [])),
    )
