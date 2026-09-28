"""Build the Telangana I&CAD Standard Data 2026-27 dataset from the published PDF.

    uv run --with pdfplumber python -m tools.ts_sor.build \
        "../reference/ts-2026-27/Standard Data 2026-27 merged.pdf"

Writes app/data/ts_icad_2026_27/{items,datasheets}.json and prints a verification
summary. Every data sheet is recomputed ((A+B+C) + additions, 13.615 % overheads and
profit, lead charges, divided by the analysis quantity) and compared with the rate the
book prints. Sheets that do not recompute are kept with their printed rate and a
`problems` list, so nothing is silently trusted.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from tools.ts_sor import lead_tables
from tools.ts_sor.extract_text import extract
from tools.ts_sor.parse_datasheets import check
from tools.ts_sor.parse_datasheets import parse as parse_sheets
from tools.ts_sor.parse_items import parse as parse_items
from tools.ts_sor.parse_sor import pages, parse_hire, parse_labour, parse_materials

OUT = Path(__file__).resolve().parents[2] / "app" / "data" / "ts_icad_2026_27"
SOURCE = {
    "title": "Telangana Revised Standard Data (with Schedule of Rates 2026-27), Part-I I&CAD",
    "reference": "Proc.No.ENC(Admn)/Dy.ENC/EE(Tech)/DEE1/AEE1/Data-2026-27/Vol.-I Dt: 29.06.2026",
    "effective_from": "2026-06-01",
    "zone": "III (Rural and other areas)",
    "overheads_and_profit_pct": "13.615",
    "note": "Rates exclude leads beyond the initial lead, area allowance, seigniorage and GST.",
}


def build(pdf_path: str) -> dict[str, object]:
    text = extract(pdf_path)
    a, b = text.index("=====PAGE 17/"), text.index("=====PAGE 66/")
    items = parse_items(text[a:b])
    sheets = parse_sheets(text[b:])
    for sheet in sheets:
        sheet["problems"] = check(sheet)
    by_code = {s["code"]: s for s in sheets}
    for item in items:
        item["has_datasheet"] = item["code"] in by_code
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "items.json").write_text(
        json.dumps({"source": SOURCE, "items": items}, indent=1, ensure_ascii=False)
    )
    (OUT / "datasheets.json").write_text(
        json.dumps({"source": SOURCE, "datasheets": sheets}, indent=1, ensure_ascii=False)
    )
    problems = Counter(p.split(":")[0] for s in sheets for p in s["problems"])
    return {
        "items": len(items),
        "datasheets": len(sheets),
        "datasheets_verified": sum(not s["problems"] for s in sheets),
        "items_with_datasheet": sum(i["has_datasheet"] for i in items),
        "problem_kinds": dict(problems),
    }


SOR_SOURCE = {
    "title": "Telangana Standard Schedule of Rates 2026-27 (Part-I I&CAD, Part-II labour)",
    "reference": "Proc.No.ENC/Admn/Dy.EnC/EE(Tech)/DEE-1/AEE-3/SoR 2026-27/Vol.I Dt:29.06.2026",
    "effective_from": "2026-06-01",
}
AREA_ALLOWANCES = [  # SoR common preamble 1: extra % on the labour component only
    {"key": "none", "label": "Rural and other areas", "pct": "0"},
    {
        "key": "corporation",
        "label": "Municipal Corporations (except Greater Hyderabad)",
        "pct": "25",
    },
    {"key": "ghmc", "label": "Greater Hyderabad (up to 12 km belt)", "pct": "40"},
    {"key": "municipality", "label": "District headquarters and other municipalities", "pct": "20"},
    {"key": "industrial", "label": "Notified industrial areas (10 km belt)", "pct": "20"},
    {"key": "jail", "label": "Jail compounds (on labour rates)", "pct": "20"},
    {
        "key": "agency_16",
        "label": "Agency / Tribal, within 16 km of an all-weather route",
        "pct": "25",
    },
    {"key": "agency_beyond_16", "label": "Agency / Tribal, beyond 16 km", "pct": "40"},
]
# Not in the SoR: the rates the department's own estimates use. Editable in the app and
# labelled "confirm against the current G.O." wherever they appear.
SEIGNIORAGE_DEFAULTS = {
    "status": "from sample estimates; confirm against the current G.O.",
    "rates": {
        "metal": {"label": "Metal / coarse aggregate", "unit": "cum", "rate": "117"},
        "sand": {"label": "Natural sand", "unit": "cum", "rate": "40"},
        "m_sand": {"label": "Manufactured sand", "unit": "cum", "rate": "117"},
        "earth": {"label": "Earth / gravel", "unit": "cum", "rate": "39"},
        "stone": {"label": "Dressed stone (km / hectometre stones)", "unit": "MT", "rate": "156"},
    },
    "dmf_pct": "30",
    "smet_pct": "2",
    "permit_fee_pct": "80",
    "permit_fee_on": "metal",
}


def build_sor(pdf_path: str) -> dict[str, object]:
    text = extract(pdf_path)
    zones = {"I": (58, 59), "II": (60, 61), "III": (62, 63)}
    data = {
        "source": SOR_SOURCE,
        "materials": parse_materials(pages(text, 33, 36)),
        "labour": parse_labour(pages(text, 77, 82)),
        "hire_charges": {z: parse_hire(pages(text, a, b)) for z, (a, b) in zones.items()},
        "lead": {
            "mechanical_classes": lead_tables.MECHANICAL_CLASSES,
            "mechanical": lead_tables.MECHANICAL,
            "head_load": lead_tables.HEAD_LOAD,
            "loading": lead_tables.LOADING,
            "lift": lead_tables.LIFT,
        },
        "area_allowances": AREA_ALLOWANCES,
        "seigniorage_defaults": SEIGNIORAGE_DEFAULTS,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "basic_rates.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return {
        "materials": len(data["materials"]),
        "labour": len(data["labour"]),
        "hire_charges": {z: len(v) for z, v in data["hire_charges"].items()},  # type: ignore[attr-defined]
    }


if __name__ == "__main__":
    # python -m tools.ts_sor.build <Standard Data pdf> [<SoR pdf>]
    print(json.dumps(build(sys.argv[1]), indent=1))
    if len(sys.argv) > 2:
        print(json.dumps(build_sor(sys.argv[2]), indent=1))
