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

from tools.ts_sor.extract_text import extract
from tools.ts_sor.parse_datasheets import check
from tools.ts_sor.parse_datasheets import parse as parse_sheets
from tools.ts_sor.parse_items import parse as parse_items

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


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1]), indent=1))
