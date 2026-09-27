# 07 — MVP Screen List & Wireframes

Desktop-first (1280–1920 px), responsive down to 360 px. Plain and dense like a spreadsheet: no decorative animation, and keyboard navigation in grids. Every AI-derived value shows a provenance badge. The disclaimer is in the footer of every estimate screen and export.

## 7.1 Screen list

| # | Route | Screen | MVP scope |
|---|---|---|---|
| S1 | `/login`, `/register`, `/forgot-password` | Auth | email/password, Google, email verification |
| S2 | `/dashboard` | Dashboard | KPIs, recent projects/estimates, subscription card, quick actions |
| S3 | `/projects` | Project list | filter by type/status, search by name/ref |
| S4 | `/projects/new` | New Project wizard | 3 steps: basics → location/parties → review |
| S5 | `/projects/[id]` | Project overview | details, estimates list, "AI Estimate" / "New blank estimate" |
| S6 | `/ai-estimate` | AI Estimate: describe | text box, project picker, examples |
| S7 | `/ai-estimate/[xid]` | AI Estimate: review & fill missing | parameters table, missing-info form, assumptions, confirm |
| S8 | `/projects/[id]/estimates/[eid]` → **BOQ** tab | BOQ editor | inline grid, sections, add/delete/duplicate/reorder, rate picker |
| S9 | same → **Detailed** tab | Detailed estimate | measurement lines (L, B, D/H, No), View Calculation modal |
| S10 | same → **Parameters** tab | Project parameters | named inputs, provenance, accept-default |
| S11 | same → **Abstract** tab | Abstract estimate | section totals, charges editor, GST panel, grand total, words |
| S12 | same → **Validation** tab | Validation | GREEN/YELLOW/RED findings with jump-to-item |
| S13 | same → **Versions** tab | Versions | list, freeze with note, open read-only old version |
| S14 | same → **Export** dialog | Export | PDF/Excel, sections, signatories, progress, download |
| S15 | `/calculator` | Quantity calculator | template or custom formula, units, step breakdown |
| S16 | `/rates` | Rates (manual) | org rate source + manual items, search |
| S17 | `/settings/*` | Settings | profile, organisation (logo, GSTIN, state), GST & charge defaults, billing/plan |
| S18 | `/admin` (minimal) | Admin | plans & limits, units, templates, AI usage, users |

Phase 2 adds Documents, Rate imports, Compare versions, Audit view, Assistant panel and Word export. Phase 3 adds Drawing analysis, Site observations, Team, and the Irrigation/Road/Building modules.

## 7.2 App shell

```
┌────────────┬─────────────────────────────────────────────────────────────────────┐
│ EstimateAI │  🔍 Search projects, items, estimate no…            Org ▾   (M) ▾     │
├────────────┼─────────────────────────────────────────────────────────────────────┤
│ Dashboard  │                                                                     │
│ Projects   │                        <page content>                               │
│ AI Estimate│                                                                     │
│ BOQ        │                                                                     │
│ Rates      │                                                                     │
│ Documents° │                                                                     │
│ Calculator │                                                                     │
│ Reports°   │                                                                     │
│ Settings   │                                                                     │
│            ├─────────────────────────────────────────────────────────────────────┤
│ Plan: Free │ ⚠ AI-generated estimates are an assistive tool. Verify quantities,   │
│ 3/5 AI gens│   specifications, rates, standards, SOR provisions and statutory…   │
└────────────┴─────────────────────────────────────────────────────────────────────┘
 ° = Phase 2 (shown disabled with "coming soon" in MVP, or hidden by feature flag)
```

## 7.3 S2 Dashboard

```
 Dashboard                                   [+ New Project] [✦ AI Estimate] [Calculator]
 ┌──────────────┬──────────────┬──────────────┬──────────────┬──────────────────────────┐
 │ Projects  12 │ Drafts     7 │ Completed  5 │ Est. value   │ Plan: Starter · renews   │
 │              │              │              │ ₹4,32,18,500 │ 12-10-2026 · 23/50 AI    │
 └──────────────┴──────────────┴──────────────┴──────────────┴──────────────────────────┘
 Recent projects                                   Recent estimates
 ┌───────────────────────────┬───────┬──────────┐  ┌───────────────┬────┬────────────────┐
 │ CC Road Miryalaguda       │ Road  │ Draft    │  │ EST-2026-014  │ V3 │ ₹30,97,500.00  │
 │ Minor canal lining D-12   │ Canal │ Complete │  │ EST-2026-013  │ V1 │ ₹8,12,300.00   │
 └───────────────────────────┴───────┴──────────┘  └───────────────┴────┴────────────────┘
```

## 7.4 S6/S7 AI Estimate

```
 AI Estimate                                      Project: [CC Road Miryalaguda ▾] (or new)
 ┌──────────────────────────────────────────────────────────────────────────────────────┐
 │ Describe your proposed work…                                                          │
 │ Construction of 500 m long CC road, 5.5 m wide and 150 mm thick with 100 mm GSB.     │
 └──────────────────────────────────────────────────────────────────────────────────────┘
 Examples: CC road · Brick compound wall · Canal lining · RCC culvert       [Generate ▶]

 ── after generation (progress: "Reading description… Extracting parameters… Checking") ──

 Detected: Road · 2 components                        Model output validated ✓ (not a check
                                                       of engineering correctness)
 ┌ ⚠ Additional information required ─────────────────────────────────────────────────┐
 │ Granular sub-base › width   Please enter the GSB width.                             │
 │   [ ______ ] [m ▾]    or  ◻ Use suggested 5.5 m (same as carriageway) — I accept    │
 └──────────────────────────────────────────────────────────────────────────────────────┘
 Component: CC pavement  (template: Road layer = length × width × thickness)
 ┌───────────┬────────┬──────┬──────────────────────┬────────────────┐
 │ Parameter │ Value  │ Unit │ From your text       │ Source         │
 ├───────────┼────────┼──────┼──────────────────────┼────────────────┤
 │ Length    │ [500 ] │ m ▾  │ "500 m long"         │ ✦ AI-extracted │
 │ Width     │ [5.5 ] │ m ▾  │ "5.5 m wide"         │ ✦ AI-extracted │
 │ Thickness │ [150 ] │ mm ▾ │ "150 mm thick"       │ ✦ AI-extracted │
 └───────────┴────────┴──────┴──────────────────────┴────────────────┘
 Preview (calculated by engine): 500 × 5.5 × 0.15 = 412.500 Cum
 Assumptions: 'CC road' interpreted as cement concrete pavement.       [+ Add component]

                                         [Discard]   [Create BOQ ▶] (disabled until complete)
```

## 7.5 S8 BOQ editor (core screen)

```
 CC Road Miryalaguda › EST-2026-014 › V3 (Draft)       [Validate: 1 ● 2 ●] [Freeze version] [Export]
 Tabs:  BOQ | Detailed | Parameters | Abstract | Validation | Versions
 Rate source: [Telangana R&B SOR 2026-27 ▾]  ⓘ imported, unverified · effective 01-04-2026 → —
 ┌───┬─────┬──────────────────────────────┬──────┬───────────┬───────────┬──────────────┬───┐
 │Sl │Item │ Description                   │ Unit │ Quantity  │ Rate ₹    │ Amount ₹     │   │
 ├───┴─────┴──────────────────────────────┴──────┴───────────┴───────────┴──────────────┴───┤
 │ ▾ 1. Earthwork                                                        2,50,000.00        │
 │ 1 │ 1.1 │ Earthwork excavation…        │ Cum  │  200.000ƒ │  1,250.00 │   2,50,000.00│ ⋮ │
 │ ▾ 2. GSB                                                                                  │
 │ 2 │ 2.1 │ Providing and laying GSB…    │ Cum  │  825.000ƒ │ [      ]⚠ │          —   │ ⋮ │
 │ ▾ 3. CC pavement                                                                          │
 │ 3 │ 3.1 │ PCC M30 for pavement…  ✦    │ Cum  │  825.000ƒ │  6,450.00Ⓓ│  53,21,250.00│ ⋮ │
 │   [+ Add item]  [+ Add section]                                                           │
 ├──────────────────────────────────────────────────────────────────────┬────────────────────┤
 │                                                  Works subtotal      │   55,71,250.00     │
 └──────────────────────────────────────────────────────────────────────┴────────────────────┘
  ƒ = quantity from formula (click → View Calculation)   ✦ = AI-suggested text
  Ⓓ = Demo Rate — Not Official SOR    ⚠ = missing rate
  ⋮ menu: Edit · Duplicate · Move up/down · Delete · Pick rate · (P2) AI explain
```

Rate picker (opened from the Rate cell):
```
 Search rates: [cement concrete            ]   Source: Demo Rates 2026-27 (Demo — Not Official SOR)
 ┌────────┬────────────────────────────────────┬──────┬──────────┬─────────┬──────┬───────────┐
 │ Code   │ Description                          │ Unit │ Rate ₹   │ SOR     │ Year │ Source    │
 │ CC-001 │ Providing and laying cement concrete │ Cum  │ 7,500.00 │ Demo    │26-27 │ Demo rate │
 └────────┴────────────────────────────────────┴──────┴──────────┴─────────┴──────┴───────────┘
 ⚠ This item has a manually entered rate (₹6,450.00). Replace it?   [Keep manual] [Replace]
 ⚠ Unit mismatch: item is Cum, rate is Sq.m — cannot apply.
```

## 7.6 S9 Detailed estimate and View Calculation

```
 3.1 PCC M30 for pavement                                                  Unit: Cum
 ┌───┬──────────────────────────┬─────┬─────────┬───────┬────────┬───────────┬─────────┐
 │Sl │ Description              │ No  │ L (m)   │ B (m) │ D/H (m)│ Quantity  │         │
 │ a │ Ch 0–500                 │ 1   │ 500.000 │ 5.500 │ 0.150  │ 412.500   │ [calc]  │
 │ b │ Ch 500–1000              │ 1   │ 500.000 │ 5.500 │ 0.150  │ 412.500   │ [calc]  │
 │ c │ Less: culvert gap  (−)   │ 1   │   0.000 │ …     │ …      │  (0.000)  │ [calc]  │
 │                                                    Total   │ 825.000 Cum │         │
 └──────────────────────────────────────────────────────────────────────────────────────┘

 ┌ View Calculation — 3.1 (a) ───────────────────────────────────────────────┐
 │ Template: Road layer v1   Formula: length × width × thickness            │
 │ length    = 500 m        ← parameter road_length (AI-extracted, "500 m")  │
 │ width     = 5.5 m        ← parameter cc_width    (User-entered)           │
 │ thickness = 150 mm = 0.150 m  (unit conversion 1 mm = 0.001 m)            │
 │ Quantity  = 500 × 5.5 × 0.15 = 412.500 Cum                                │
 │ Engine v1.0.0 · calculated 27-09-2026 17:30 · Calculation check passed    │
 └───────────────────────────────────────────────────────────────────────────┘
```

## 7.7 S11 Abstract estimate

```
 ┌────┬──────────────────────────────────────────┬──────────────────┐
 │ Sl │ Description                              │ Amount ₹         │
 │ 1  │ Earthwork                                │     2,50,000.00  │
 │ 2  │ GSB                                      │     4,50,000.00  │
 │ 3  │ CC Road                                  │    15,50,000.00  │
 │ 4  │ Drainage                                 │     3,25,000.00  │
 │    │ Works subtotal                           │    25,75,000.00  │
 │    │ Contingencies @ 2.50 % on works subtotal │       64,375.00  │  [edit charges]
 │    │ Subtotal                                 │    26,39,375.00  │
 │    │ CGST @ 9 % on ₹26,39,375.00              │     2,37,543.75  │  [GST settings]
 │    │ SGST @ 9 % on ₹26,39,375.00              │     2,37,543.75  │
 │    │ Grand total                              │    31,14,462.50  │
 └────┴──────────────────────────────────────────┴──────────────────┘
 Rupees Thirty One Lakh Fourteen Thousand Four Hundred Sixty Two and Fifty Paise Only
 (All percentages shown come from this estimate's configuration; none are fixed by the system.)
```

## 7.8 S12 Validation

Findings are grouped by severity. Each links to the offending cell. The header reads "Calculation checks", never "Estimate verified".

| Rule id | Severity | Check |
|---|---|---|
| `RATE_MISSING` | RED | BOQ item with quantity but no rate |
| `UNIT_MISSING` | RED | item without unit |
| `QTY_ZERO` | YELLOW | quantity = 0 |
| `QTY_NEGATIVE` | RED | net quantity < 0 (deductions exceed additions) |
| `DUPLICATE_ITEM` | YELLOW | same normalised description + unit (or same rate code) twice in a version |
| `QTY_OUTLIER_HIGH/LOW` | YELLOW | quantity outside configurable bounds relative to project parameters (e.g. CC volume ÷ road area implies thickness outside 0.075–0.45 m) |
| `PARAM_MISSING` | RED | parameter required by a formula is empty |
| `DEFAULT_ACCEPTED` | YELLOW | value came from an accepted default (reminder to verify) |
| `FORMULA_ERROR` | RED | expression fails to parse or has a dimension mismatch |
| `UNIT_RATE_MISMATCH` | RED | rate unit ≠ item unit |
| `GST_INCONSISTENT` | RED | CGST ≠ SGST, both intra- and inter-state set, or GST applied on GST-inclusive rates |
| `TOTAL_MISMATCH` | RED | stored totals ≠ independent recomputation |
| `ABSTRACT_MISMATCH` | RED | Σ section totals ≠ Σ BOQ amounts |
| `DEMO_RATE_USED` | YELLOW | at least one demo rate used |
| `AI_UNREVIEWED` | YELLOW | AI-suggested descriptions not yet edited or confirmed |
| All pass | GREEN | "Calculation checks passed". This is not a confirmation of engineering correctness |

## 7.9 S13 Versions / S14 Export

```
 Versions
 ┌────┬──────────────────────────────────┬────────────┬─────────┬────────────────┐
 │ V3 │ Draft                            │ —          │ Mahesh  │ ₹31,14,462.50  │
 │ V2 │ Width changed from 5 m to 5.5 m  │ 26-09-2026 │ Mahesh  │ ₹29,80,110.00  │ [Open] [Compare°]
 │ V1 │ Initial estimate                 │ 20-09-2026 │ Mahesh  │ ₹27,12,000.00  │ [Open] [Compare°]
 └────┴──────────────────────────────────┴────────────┴─────────┴────────────────┘
 [Freeze V3 as…  "note: ______"]

 Export  ○ PDF  ○ Excel  ○ Word°
 Include: ☑ Cover ☑ Project details ☑ Detailed estimate ☑ BOQ ☑ Abstract ☑ Calculations ☑ Assumptions
 Prepared by [____] Checked by [____] Approved by [____]    Logo: org default
 [Generate]  ▓▓▓▓▓▓░░░ 62 % Building BOQ sheet…   → [Download]
```

## 7.10 Mobile behaviour

* Sidebar collapses to a bottom tab bar (Dashboard, Projects, AI, More).
* The BOQ grid switches to a card list per item. Tapping a card opens the edit sheet, and totals stay in a sticky footer.
* AI Estimate and View Calculation work fully on mobile. Export works, and download opens the file.
