# 04 — Folder Structure

A monorepo with two deployable apps and shared fixtures. The backend is layered as described in [01 §1.3](./01-system-architecture.md#13-backend-internal-layering).

```
estimategenerator/
├── README.md
├── docker-compose.yml               # postgres, redis, minio, clamav, api, worker, web (local dev)
├── .env.example                     # every variable from doc 09, no real secrets
├── .github/
│   └── workflows/
│       ├── backend.yml              # ruff, mypy, pytest (+ postgres service), alembic check
│       ├── frontend.yml             # eslint, tsc, vitest, playwright (smoke)
│       └── deploy.yml
│
├── docs/
│   └── design/                      # this design package
│
├── fixtures/                        # shared by backend tests, frontend tests and AI evals
│   ├── golden/
│   │   ├── extraction/*.json        # description → expected parameters (EN + Telugu)
│   │   └── estimates/*.json         # inputs → expected quantities/totals
│   └── demo/
│       └── cc_road_demo.json        # §39 demo project, demo rates marked "Not Official SOR"
│
├── backend/
│   ├── pyproject.toml               # uv/poetry; fastapi, sqlalchemy 2, alembic, pydantic 2,
│   │                                # celery, redis, anthropic, openpyxl, reportlab, python-docx,
│   │                                # pypdf/pdfplumber, python-magic, argon2-cffi, authlib, structlog
│   ├── alembic.ini
│   ├── Dockerfile
│   ├── migrations/
│   │   └── versions/
│   ├── app/
│   │   ├── main.py                  # app factory, middleware, exception handlers
│   │   ├── config.py                # pydantic-settings, reads env
│   │   ├── core/
│   │   │   ├── errors.py            # AppError(error_code, message, http_status, details)
│   │   │   ├── security.py          # password hashing, JWT, CSRF
│   │   │   ├── rate_limit.py
│   │   │   ├── logging.py
│   │   │   └── ids.py               # uuid7
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   └── base.py
│   │   ├── models/                  # SQLAlchemy ORM, one module per aggregate
│   │   │   ├── identity.py          # User, Organization, members, oauth, refresh tokens
│   │   │   ├── project.py
│   │   │   ├── estimate.py          # Estimate, Version, Section, BoqItem, EstimateItem,
│   │   │   │                        # Calculation, QuantityInput, EstimateCharge
│   │   │   ├── rates.py
│   │   │   ├── documents.py
│   │   │   ├── ai.py
│   │   │   ├── billing.py
│   │   │   └── platform.py          # settings, prompts, flags, audit, jobs, notifications
│   │   ├── domain/                  # ★ PURE — no imports from app.* outside domain
│   │   │   ├── quantity/
│   │   │   │   ├── expression.py    # AST whitelist parser/evaluator on Decimal
│   │   │   │   ├── templates.py     # built-in template catalogue (seeded into DB)
│   │   │   │   ├── engine.py        # evaluate(template, params, units) → CalculationResult
│   │   │   │   └── modules/         # road.py, building.py, irrigation.py (Phase 3 helpers)
│   │   │   ├── units/
│   │   │   │   ├── registry.py      # UnitRegistry(built from DB rows), parse aliases
│   │   │   │   └── convert.py
│   │   │   ├── estimate/
│   │   │   │   ├── totals.py        # line amounts, sections, charges, GST, grand total
│   │   │   │   ├── rounding.py
│   │   │   │   └── diff.py          # version comparison by line_key
│   │   │   ├── validation/
│   │   │   │   ├── rules.py         # each rule: id, severity, check(estimate) → findings
│   │   │   │   └── runner.py
│   │   │   └── money/
│   │   │       ├── indian_format.py # ₹12,34,567.00
│   │   │       └── words.py         # "Rupees Thirty Lakh Twenty Five Thousand Only"
│   │   ├── ai/
│   │   │   ├── client.py            # Anthropic SDK wrapper: retries, timeouts, metering
│   │   │   ├── router.py            # purpose → model tier → model id (from env/DB)
│   │   │   ├── prompts/             # versioned prompt files (seeded into prompt_templates)
│   │   │   │   ├── extract_parameters.v1.md
│   │   │   │   ├── document_boq.v1.md
│   │   │   │   ├── explain_item.v1.md
│   │   │   │   └── assistant.v1.md
│   │   │   ├── schemas.py           # Pydantic models = JSON schemas for structured output
│   │   │   ├── postprocess.py       # whitelist check, source-span check, unit normalisation
│   │   │   ├── cache.py             # input-hash response cache
│   │   │   └── cost.py              # token → USD from model price table (config)
│   │   ├── repositories/            # tenant-scoped queries
│   │   ├── services/
│   │   │   ├── auth_service.py
│   │   │   ├── project_service.py
│   │   │   ├── estimate_service.py  # CRUD, recalc, freeze/clone, audit
│   │   │   ├── calculation_service.py
│   │   │   ├── ai_extraction_service.py
│   │   │   ├── rate_service.py      # search, select, import
│   │   │   ├── validation_service.py
│   │   │   ├── export_service.py
│   │   │   ├── document_service.py
│   │   │   ├── billing_service.py
│   │   │   ├── quota_service.py
│   │   │   ├── search_service.py
│   │   │   └── audit_service.py
│   │   ├── exports/
│   │   │   ├── pdf/                 # ReportLab: layout.py, tables.py, header_footer.py
│   │   │   ├── xlsx/                # openpyxl: workbook.py, sheets/*.py, styles.py
│   │   │   └── docx/                # python-docx
│   │   ├── integrations/
│   │   │   ├── storage.py           # S3 (boto3), signed URLs
│   │   │   ├── ocr/                 # base.py (Protocol), tesseract.py, textract.py, docai.py
│   │   │   ├── razorpay.py
│   │   │   ├── email.py
│   │   │   └── malware.py           # clamd
│   │   ├── api/
│   │   │   ├── deps.py              # current_user, require_project_role, pagination
│   │   │   ├── envelope.py          # success/error response models
│   │   │   └── v1/
│   │   │       ├── auth.py  projects.py  estimates.py  versions.py  boq.py
│   │   │       ├── measurements.py  parameters.py  calculations.py  charges.py
│   │   │       ├── ai.py  rates.py  units.py  validation.py  exports.py
│   │   │       ├── documents.py  jobs.py  search.py  audit.py  dashboard.py
│   │   │       ├── billing.py  webhooks.py
│   │   │       └── admin/ rates.py users.py plans.py prompts.py flags.py usage.py
│   │   └── workers/
│   │       ├── celery_app.py
│   │       ├── ai_tasks.py  document_tasks.py  export_tasks.py  billing_tasks.py
│   └── tests/
│       ├── unit/
│       │   ├── domain/              # quantity, units, totals, GST, words, validation, diff
│       │   └── ai/                  # postprocess with recorded LLM outputs (no network)
│       ├── integration/             # API + DB (testcontainers/postgres service)
│       │   ├── test_ai_to_boq_flow.py   # LLM mocked → calc → BOQ → abstract
│       │   ├── test_authorization.py    # cross-org / cross-project access denied
│       │   └── test_webhooks.py
│       ├── exports/                 # open generated xlsx/pdf/docx and assert content
│       └── evals/                   # opt-in, calls real LLM on golden set (not in CI by default)
│
└── frontend/
    ├── package.json                 # next, react, typescript, tailwind, @tanstack/react-query,
    │                                # @tanstack/react-table, react-hook-form, zod, shadcn/ui
    ├── next.config.ts               # rewrites /api/* → BACKEND_URL
    ├── Dockerfile
    ├── src/
    │   ├── app/                     # App Router
    │   │   ├── (auth)/login  register  forgot-password
    │   │   ├── (app)/
    │   │   │   ├── layout.tsx       # sidebar nav + top bar + disclaimer footer
    │   │   │   ├── dashboard/
    │   │   │   ├── projects/  projects/new/  projects/[id]/
    │   │   │   │   └── [id]/estimates/[eid]/  (tabs: boq · detailed · abstract · parameters ·
    │   │   │   │                               validation · versions · exports)
    │   │   │   ├── ai-estimate/
    │   │   │   ├── boq/             # → picks project/estimate, then BOQ editor
    │   │   │   ├── rates/
    │   │   │   ├── documents/
    │   │   │   ├── calculator/      # standalone quantity calculator
    │   │   │   ├── reports/
    │   │   │   ├── settings/        # profile, organisation, GST & charges defaults, billing
    │   │   │   └── admin/
    │   ├── components/
    │   │   ├── ui/                  # shadcn primitives
    │   │   ├── boq/                 # BoqGrid (inline edit), RatePicker, CalculationModal
    │   │   ├── estimate/            # AbstractTable, ChargesEditor, GstPanel, VersionBadge
    │   │   ├── ai/                  # ExtractionReview, MissingInfoForm, ProvenanceBadge
    │   │   └── validation/          # FindingsList (GREEN/YELLOW/RED)
    │   ├── lib/
    │   │   ├── api/                 # typed client generated from OpenAPI (openapi-typescript)
    │   │   ├── format/              # inr.ts (Indian grouping), units.ts — display only
    │   │   └── auth.ts
    │   └── i18n/                    # en.json (MVP); te.json, hi.json (Phase 4)
    └── tests/
        ├── unit/                    # vitest: formatters, components
        └── e2e/                     # playwright: MVP acceptance test (§49)
```

## Notes

* **One source of arithmetic.** `frontend/lib/format` only *formats*. It never computes quantities or totals. Inline edits send a PATCH request and render the server's recalculated values. Grid updates are optimistic, but the displayed amounts are always the server response.
* **API types are generated from FastAPI's OpenAPI schema**, so frontend and backend cannot drift.
* **`fixtures/golden`** is the shared contract: the same cases drive domain unit tests, integration tests and the LLM extraction eval.
