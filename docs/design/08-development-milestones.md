# 08 — Development Milestones

Each milestone ends with a **gate**: tests green in CI, lint/type-check clean, the demo scenario for that milestone run by hand, and no known breakage. We don't start the next milestone while the current one is broken (brief §50).

Sizes are rough, for one full-stack developer working with AI assistance.

## Phase 1 — MVP

| M | Milestone | Deliverables | Gate (must pass) | Size |
|---|---|---|---|---|
| **M0** | Foundation | Monorepo, docker-compose (pg, redis, minio), FastAPI skeleton with error envelope, request ids, structured logging, `/healthz`; Next.js shell with nav; Alembic initial migration from `03-database-schema.sql`; CI for both apps | `docker compose up` → web + api healthy; CI green; error envelope test | 3–4 d |
| **M1** | Units + quantity engine (pure domain) | Unit registry & conversion, safe expression evaluator on Decimal, template catalogue (generic + road + building basics), step breakdown, Indian number format, amount-in-words | ≥ 95 % coverage of `domain/`; golden cases incl. `500×5.5×0.15 = 412.5`, `1000×5.5×0.15 = 825`; rejects `__import__`, attribute access, and unknown names; ft/sq.ft/cu.ft conversion tests; words for 0, 1 paise, 99,99,99,999.99 | 4–5 d |
| **M2** | Auth, orgs, projects, dashboard | Register/login/refresh/logout, Google OAuth, email verification, personal org + Free plan on signup, authorisation dependency, project CRUD + wizard, dashboard summary | Security tests: no cross-org read/write (404), no access without auth, refresh-token reuse revokes the family; registration → project creation e2e | 5–6 d |
| **M3** | Estimate core: BOQ, detailed, parameters, versions | Estimates, versions (freeze/clone, frozen immutability), sections, BOQ CRUD with inline edit/duplicate/reorder, measurements, parameters with dependency recalculation, View Calculation, basic audit capture | Editing qty/rate recalculates item → section → totals server-side; a frozen version rejects writes (API 409 + DB trigger); old version reopens identically; audit rows written for each change | 7–8 d |
| **M4** | AI extraction | Anthropic client wrapper with metering, prompt registry, `extract_parameters` v1, structured output + Pydantic validation, post-processing guardrails, job queue + progress, review/missing-info UI, confirm → BOQ | Integration test with **recorded** LLM responses: text → params → confirm → BOQ quantities correct; false-fill guard test (model returns an unquoted value → downgraded); a missing param blocks confirm; quota enforced; golden eval ≥ agreed threshold on the real model (run manually) | 6–7 d |
| **M5** | Rates (manual), abstract, charges, GST, validation | Org rate source + manual items + search; rate picker with overwrite confirmation and unit check; demo rate source flagged "Demo Rate — Not Official SOR"; charges editor; GST panel (CGST/SGST/IGST, incl/excl); abstract; validation engine with the MVP rule set | Totals match hand-computed fixtures to the paisa; GST scenarios (intra/inter/exempt/inclusive); each validation rule has a positive and a negative test; `TOTAL_MISMATCH` detects a tampered DB row | 6–7 d |
| **M6** | Exports: PDF + Excel | Async export jobs; ReportLab PDF (logo, header block, signatories, page x of y, Indian formatting, amount in words, disclaimer); openpyxl workbook with Cover, Project Details, Detailed Estimate, BOQ, Abstract, Calculations, Assumptions (the Rate Analysis sheet is a placeholder in MVP), **live Excel formulas** for amounts and totals | Tests open the generated files: xlsx formulas recompute to the same totals (LibreOffice headless recalc in CI); PDF text contains expected totals and words; a 500-item BOQ exports in < 30 s | 6–7 d |
| **M7** | Subscription structure | Plans table + admin editing, quota service, feature gating (plan features), Razorpay subscription checkout (test mode), verified idempotent webhook handler, billing page | Webhook: bad signature rejected; replayed event is a no-op; plan changes **only** via webhook; quota exhaustion → 429 `QUOTA_EXCEEDED` | 4–5 d |
| **M8** | Hardening & release | Rate limiting, upload limits, security headers, Sentry, backups, seed demo project (§39), staging + production deploy, Playwright run of the **MVP acceptance test (§49)** end to end | All 17 acceptance steps pass on staging; OWASP ZAP baseline scan clean of high findings; dashboard p95 < 2 s with 50 projects | 4–5 d |

**Total Phase 1: ≈ 9–11 weeks.**

### MVP acceptance test mapping (§49)

| # | Step | Milestone |
|---|---|---|
| 1 | Register | M2 |
| 2 | Create project | M2 |
| 3–5 | Describe work → AI extracts → user corrects | M4 |
| 6 | Engine calculates quantities | M1, M4 |
| 7 | Enter/select rates | M5 |
| 8–9 | BOQ and abstract generated | M3, M5 |
| 10 | Validation performed | M5 |
| 11–12 | Edit item → totals recalculate | M3 |
| 13–14 | PDF and Excel generated | M6 |
| 15–16 | Project saved and reopened | M3 |
| 17 | Previous version remains available | M3 |

## Phase 2 (≈ 8–10 weeks)

1. **Rate database & SOR management:** CSV/XLSX import with preview, row-level errors, commit/rollback; global SORs by admin; verification status; effective-date filtering.
2. **Documents:** upload pipeline (MIME sniff, ClamAV, size limits), PDF text extraction (`pdfplumber`), text-layer detection → OCR adapter (Tesseract self-hosted first, a cloud OCR adapter behind the same interface), XLSX/CSV/DOCX parsing.
3. **AI document analysis:** `document_boq`, review grid, import into BOQ with page citations and an amount-disagreement flag.
4. **Word export** (python-docx).
5. **Version comparison UI**, restore version.
6. **Audit trail UI** (data has been captured since M3).
7. **Project assistant** (read-only tools, citations), AI explain item, AI suggest missing items.
8. **Global search** across items, rates, documents.

## Phase 3 (≈ 10–12 weeks)

Road module (shoulders L/R, WBM/WMM/BT layers, kerbs, drains), Building module (openings deduction tables, plaster faces, painting, masonry), Irrigation module (canal trapezoid lining with user-selected side slopes, bed/side area, joints, bunds, check dams), drawing analysis (AI-derived measurements with a mandatory verify step; scale calibration by a user-drawn known dimension), site photo observations, advanced validation (per-module outlier bounds), team accounts / Business plan, Postgres RLS.

## Phase 4

Mobile app (React Native or PWA first), WhatsApp integration (describe work → draft estimate link), voice input (speech-to-text → the same extraction pipeline), UI localisation in Telugu, Hindi, Tamil, Kannada, Marathi (AI extraction already accepts Telugu/Hindi from MVP via the golden set).

## Working agreement per module

1. Write or extend golden fixtures first.
2. Domain logic with unit tests.
3. Service + API with integration tests.
4. UI.
5. Run the full test suite, fix, then demo.
6. Update the docs in `docs/design` if the design changed.
