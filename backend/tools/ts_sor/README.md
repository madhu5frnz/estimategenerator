# Telangana SoR / Standard Data 2026-27 import

Source documents are kept in `reference/ts-2026-27/`.

Rebuild the dataset (pdfplumber is needed only for this step):

```bash
cd backend
uv run --with pdfplumber python -m tools.ts_sor.build "../reference/ts-2026-27/Standard Data 2026-27 merged.pdf"
```

Output: `app/data/ts_icad_2026_27/items.json` (the 364 work items with unit, rate and
labour component, Zone III) and `datasheets.json` (the rate analyses: A materials,
B machinery, C labour, additions, 13.615 % overheads and profit, lead charges).

Every data sheet is recomputed and compared with the printed rate. Sheets that do not
recompute (mostly multi-part gate and hoist analyses) keep their printed rate and list
the reason under `problems`; the app must show them as "breakdown not verified".
