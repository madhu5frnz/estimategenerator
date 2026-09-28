# EstimateAI

AI-assisted estimate, BOQ and quantity generation for Indian civil engineers and contractors.

> **AI interprets. The deterministic engine calculates. The rate database supplies rates. The user verifies.**
> Every important number traces back to a formula or a source.

**Status:** M0 (foundation), M1 (units and quantity engine), M2 (accounts, projects, dashboard), M3 (estimates, BOQ, measurements, parameters, versions), M4 (AI estimate), M5 (rates, abstract, GST and charges, validation) and M5b (Telangana I&CAD method: Standard Data 2026-27, data sheets, lead statement, seigniorage, General Abstract) are done. Next: M6 (exports: PDF, Excel, Word). See [milestones](docs/design/08-development-milestones.md).

No AI API key is needed to develop or run the app. Without one, the rules-based extractor is used (see [doc 06 §6.3](docs/design/06-ai-prompt-architecture.md)).

## Getting started

**With Docker** (Postgres, Redis, API, web):

```bash
cp .env.example .env
docker compose up --build
# Web: http://localhost:3000   API docs: http://localhost:8000/api/docs
```

**Without Docker** (Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 22, a local Postgres 16 and Redis):

```bash
cd backend
uv sync
uv run alembic upgrade head          # uses DATABASE_URL
uv run uvicorn app.main:app --reload # http://localhost:8000

cd ../frontend
npm install
npm run dev                          # http://localhost:3000 (proxies /api to :8000)
```

**Checks** (the same ones CI runs):

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
# Migration tests need a disposable database:
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/estimateai_test uv run pytest

cd frontend && npm run lint && npm run typecheck && npm run build
```

## What works now

* **Quantity engine** (`backend/app/domain`). This is pure Python using exact decimal arithmetic. It includes a safe formula evaluator that never calls `eval`, unit-dimension checks (a length cannot be added to an area), 10 versioned formula templates, custom formulas, and a step-by-step calculation trace. It also has Indian number formatting (₹12,34,567.00) and amount in words (lakh/crore).
* **Units**: one central registry with aliases (`Cu.m`, `sft`, `mtrs` …) and exact conversions. No conversion factors appear anywhere else in the code.
* **API** (calculations): `GET /api/v1/units`, `POST /api/v1/units/convert`, `GET /api/v1/calculation-templates`, `POST /api/v1/calculate`, `POST /api/v1/calculate/validate-expression`, `/healthz`, `/readyz`. Every error uses a structured format and carries a request id.
* **Database**: the initial Alembic migration creates the reviewed schema (37 tables), including the guard that makes frozen estimate versions read-only.
* **Accounts (M2)**: register, sign in and out, Google sign-in (when configured), email confirmation, and password reset. Passwords are hashed with Argon2id. Sessions use a 15-minute access token and a rotating refresh token in HttpOnly cookies. Reusing a stolen refresh token ends every session in its family. All cookie-authenticated writes are CSRF-protected. Each new user gets a personal workspace on the Free plan.
* **Projects (M2)**: a three-step creation wizard, list with search, filters and pagination, overview, edit, status changes and delete. Plan limits apply (Free: 3 projects). Project roles (viewer, contractor, professional, admin) are enforced by the server. Another workspace's projects are never visible (404). Every change is written to the audit log with old and new values.
* **Dashboard and settings (M2)**: project counts, total estimated value in ₹ with Indian grouping, recent projects, plan usage, profile, and workspace details (name, GSTIN, state, address).
* **Estimates and BOQ (M3)**:
  * Each project holds numbered estimates (EST-YYYY-NNNN), and each estimate has versions.
  * **BOQ:** an inline-editable grid with sections, units, quantities, rates, amounts and remarks. Items can be added, duplicated, moved, reordered and deleted. Amount = quantity × rate, recalculated by the server on every change. Section subtotals, the works subtotal and the amount in words (lakh/crore) update with it.
  * **Detailed estimate:** measurement lines per item. A line is either No × L × B × D/H, using the dimensions the item's unit needs, or a formula line built from a standard template or a custom formula. Deduction lines subtract. Each line has a **View calculation** step breakdown.
  * **Parameters:** named values such as road length or carriageway width. Formula lines can use them, and changing one recalculates every line that depends on it.
  * **Versions:** saving a version freezes it exactly as it is (read-only through the API and a database trigger), and work continues in the next draft. Old versions reopen unchanged.
  * **Audit log:** every change is recorded with its old and new value.
* **AI Estimate (M4)**:
  * **Describing the work:** you describe it in English, Telugu or Hindi, for example "500 m long CC road, 5.5 m wide and 150 mm thick with 100 mm GSB".
  * **Reading it:** without an API key, a rules-based parser does this. It understands common phrasing and "L x B x D" notation. With `ANTHROPIC_API_KEY` set, Claude does it instead, using structured outputs.
  * **Review:** each value is shown with the words it came from. Missing values become questions. Suggested defaults (e.g. GSB width = carriageway width) are only used if you tick "I accept". A value that can't be found in the text must be confirmed. The engine previews each quantity.
  * **Create BOQ:** creates the parameters, BOQ items and formula lines. Each value keeps its origin: parsed, AI-extracted, entered by you, or default accepted.
  * **Usage:** AI calls are logged with tokens and cost, and repeated descriptions reuse the earlier result. They count against the plan quota; the rules parser is free.
* **Rates, abstract and validation (M5)**:
  * **Rate Database:** a searchable rate list (description, item code, unit). The app ships a demo source labelled **"Demo Rates — Not Official SOR"**; it is read-only and every use of it is flagged. Workspace owners and admins add their own sources and rates (marked "entered by you"). A rate used by an estimate cannot be deleted.
  * **Picking a rate:** "pick rate" on a BOQ row opens the rate list filtered to the item's unit. A rate in a different unit is refused. Replacing a rate you typed asks first. The item keeps a copy of the rate (source, year, code, unit), so later changes to the rate list never change an estimate.
  * **Abstract:** section totals, then charges in order (contingencies, work-charged establishment, labour cess, seigniorage, royalty or your own), each as a percentage of the works subtotal, the running total or chosen sections, or a fixed amount. Then GST: CGST + SGST or IGST, added on top or shown as included, at the rate you enter (there is no default rate). Then optional rounding and the grand total in words. Everything is to the paisa.
  * **Validation:** recalculates every measurement line and checks units, missing or zero quantities, missing rates, unit/rate mismatches, demo and expired rates, amounts that don't equal quantity × rate (including rows changed outside the app), duplicate items, unconfirmed AI or default values, and GST settings. A clean run says "Calculation checks passed", never that the engineering is confirmed.
  * **Estimate defaults:** a workspace can set the GST, charges and rounding new estimates start with (Settings).
  * Saving a version keeps its charges, GST and grand total; the next draft starts from them.
* **Telangana I&CAD estimates (M5b)**, built from the department's own estimates in `reference/ts-2026-27/`:
  * **Standard Data 2026-27** (Zone III) is in the rate list: 363 items with rate and labour component, imported from the published book and marked "imported – verify". 283 items carry their data sheet; each was recomputed and matches the printed rate (266 exactly, 17 within the book's rounding). The rest use the printed rate only and say so.
  * **Data tab:** the rate analysis of each item as in the book (A materials, B machinery, C labour, 13.615 % overheads and profit, per analysis unit). Components the work does not need can be omitted; cement/steel rate corrections and conveyance from the lead statement are added; the BOQ uses the "Or say" rate.
  * **Lead statement:** material, source and distance; charges from the SoR lead table of the zone (e.g. sand 16 km in Zone III: 128.60 − 48.20 + 11 × 19.30 = Rs 292.70). Changing a distance reprices every item that uses it.
  * **Seigniorage:** lines follow the item quantities; metal and sand factors come from the concrete mix in the item; DMF, SMET and permit fee per the settings (defaults from the department's estimates, to be confirmed against the current G.O.).
  * **General Abstract:** E.C.V., labour cess 1 %, NAC 0.1 %, seigniorage, DMF, SMET, permit fee, GST 18 % on Part A + B, lump-sum provisions, rounding and unforeseen, total in lakhs. Rounding conventions are settings, because estimates differ.
  * Built through the app, the UT at Km 8.388 estimate reproduces the department's figures (IRR-CCDW-2-3 at Rs 6,649.30, total Rs 9,78,221.00; the original prints .03 because it keeps a pipe rate to four decimals).
* **Web**: the app shell with navigation and the disclaimer footer, plus a working **Quantity Calculator** page (`/calculator`).
* **Typed API**: the frontend's API types are generated from the backend's OpenAPI schema (`npm run gen:api`), and CI fails if they drift.

In development, emails (confirmation and reset links) are printed to the API log instead of being sent.

## Design package

| # | Document | Contents |
|---|---|---|
| 1 | [System architecture](docs/design/01-system-architecture.md) | Components, backend layering, AI → calculation pipeline, quantity engine, totals, versioning, jobs, security, deployment |
| 2 | [Database ER diagram](docs/design/02-database-er-diagram.md) | Mermaid ER diagrams and terminology (BOQ item vs measurement line vs calculation) |
| 3 | [Database schema (SQL)](docs/design/03-database-schema.sql) | PostgreSQL 16 DDL: 37 tables, frozen-version triggers, unit and conversion seed data. Loaded and trigger-tested on Postgres 16 |
| 4 | [Folder structure](docs/design/04-folder-structure.md) | Monorepo layout for `backend/` (FastAPI) and `frontend/` (Next.js) |
| 5 | [API endpoint list](docs/design/05-api-endpoints.md) | REST endpoints by module and phase, error envelope, error codes |
| 6 | [AI prompt architecture](docs/design/06-ai-prompt-architecture.md) | Guardrails, model routing, prompt registry, extraction prompt and JSON schema, evals, cost controls |
| 7 | [MVP screens](docs/design/07-mvp-screens.md) | Screen list, wireframes, validation rule catalogue |
| 8 | [Development milestones](docs/design/08-development-milestones.md) | M0–M8 MVP milestones with test gates; Phases 2–4 |
| 9 | [Environment variables](docs/design/09-environment-variables.md) | Backend, frontend and CI configuration |
| 10 | [Third-party costs](docs/design/10-third-party-costs.md) | LLM cost per operation, per-plan margins, OCR, payments, infrastructure |

## Stack

Next.js · React · TypeScript · Tailwind | Python · FastAPI · SQLAlchemy 2 · Alembic · Celery | PostgreSQL 16 · Redis · S3-compatible storage | Claude API (structured outputs) | ReportLab · openpyxl · python-docx | Razorpay

## Decisions to confirm before implementation

1. **Versioning in the MVP.** The brief places version control in Phase 2, but MVP acceptance test #17 ("previous version remains available") needs it. Proposal: the MVP ships freeze-and-clone versions with read-only viewing of old versions. The comparison UI waits for Phase 2. Audit data is captured from the MVP onward, and the audit UI comes in Phase 2.
2. **Plan limits.** Full-quota LLM cost exceeds revenue for "unlimited" Pro/Business once document analysis is included (see doc 10). Proposal: explicit caps plus a separate `doc_pages` quota and top-up packs.
3. **LLM provider and models.** No AI key is needed to develop or run the app: a rules-based extractor is the default (doc 06 §6.3). When a key is added, the proposal is: Claude, with configurable tiers (`claude-haiku-4-5` / `claude-sonnet-5` / `claude-opus-5`). Tiers are chosen by eval results, not cost alone.
4. **Hosting region.** Proposed: Indian region (Mumbai) for DB and storage, for DPDP Act compliance.
5. **OCR.** Proposed: start with self-hosted Tesseract, and compare it against Claude vision on the eval set before paying for cloud OCR.
6. **Brief errata.** The abstract example in §12 sums to ₹25,75,000, not ₹26,25,000 (2,50,000 + 4,50,000 + 15,50,000 + 3,25,000). The golden fixtures will use the corrected figure.

## Disclaimer (shown in the app and in every export)

> AI-generated estimates are provided as an assistive tool. Verify quantities, specifications, rates, applicable standards, SOR provisions and statutory requirements before using the estimate for tendering, approval, billing or construction.
