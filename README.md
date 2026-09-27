# EstimateAI

AI-assisted estimate, BOQ and quantity generation for Indian civil engineers and contractors.

> **AI interprets. The deterministic engine calculates. The rate database supplies rates. The user verifies.**
> Every important number traces back to a formula or a source.

**Status:** M0 (foundation) and M1 (units and quantity engine) are done. Next: M2 (accounts and projects). See [milestones](docs/design/08-development-milestones.md).

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
* **API**: `GET /api/v1/units`, `POST /api/v1/units/convert`, `GET /api/v1/calculation-templates`, `POST /api/v1/calculate`, `POST /api/v1/calculate/validate-expression`, `/healthz`, `/readyz`. Every error uses a structured format and carries a request id.
* **Database**: the initial Alembic migration creates the reviewed schema (37 tables), including the guard that makes frozen estimate versions read-only.
* **Web**: the app shell with navigation and the disclaimer footer, plus a working **Quantity Calculator** page (`/calculator`).

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
