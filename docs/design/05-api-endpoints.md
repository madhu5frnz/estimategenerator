# 05 — API Endpoint List

Base path: `/api/v1`. JSON only. Auth via `HttpOnly` cookies (access plus refresh). All mutating requests need the `X-CSRF-Token` header.

## 5.1 Conventions

**Success envelope**
```json
{ "success": true, "data": { ... }, "meta": { "request_id": "01J…", "page": 1, "page_size": 50, "total": 132 } }
```

**Error envelope** (never contains stack traces)
```json
{
  "success": false,
  "error_code": "MISSING_PARAMETER",
  "message": "CC thickness is required.",
  "details": { "parameter": "cc_thickness", "template_id": "road_layer" },
  "request_id": "01J…"
}
```

| HTTP | error_code examples |
|---|---|
| 400 | `VALIDATION_ERROR`, `FORMULA_INVALID`, `UNIT_MISMATCH`, `MISSING_PARAMETER` |
| 401 | `UNAUTHENTICATED`, `TOKEN_EXPIRED` |
| 403 | `FORBIDDEN`, `PLAN_FEATURE_UNAVAILABLE` |
| 404 | `NOT_FOUND` (also used for resources in another org, to avoid leaking their existence) |
| 409 | `VERSION_FROZEN`, `RATE_OVERWRITE_REQUIRES_CONFIRMATION`, `STALE_WRITE` (optimistic concurrency via `If-Match`/`row_version`) |
| 413 | `FILE_TOO_LARGE` |
| 415 | `UNSUPPORTED_FILE_TYPE` |
| 422 | `AI_OUTPUT_INVALID`, `DOCUMENT_UNREADABLE` |
| 429 | `RATE_LIMITED`, `QUOTA_EXCEEDED` |
| 502/503 | `AI_PROVIDER_UNAVAILABLE`, `OCR_PROVIDER_UNAVAILABLE` |

Money and quantities are sent as **strings** (`"412.500"`) so they don't lose precision in JavaScript. Every numeric object that has a unit carries it: `{ "value": "412.500", "unit": "cum" }`.

Legend: **MVP** = Phase 1, **P2/P3** = later phases.

## 5.2 Auth & account

| Method | Path | Purpose | Phase |
|---|---|---|---|
| POST | `/auth/register` | email, password, full_name → creates user + personal org + Free subscription | MVP |
| POST | `/auth/login` | email/password → sets cookies | MVP |
| POST | `/auth/logout` | revoke refresh family | MVP |
| POST | `/auth/refresh` | rotate refresh token | MVP |
| GET | `/auth/google/start` | OAuth redirect (state + PKCE) | MVP |
| GET | `/auth/google/callback` | link/create user | MVP |
| POST | `/auth/verify-email` · `/auth/resend-verification` | | MVP |
| POST | `/auth/forgot-password` · `/auth/reset-password` | | MVP |
| GET | `/me` | profile, orgs, current org, plan, usage | MVP |
| PATCH | `/me` | name, phone, locale | MVP |
| POST | `/me/switch-organization` | | P3 |

## 5.3 Organisations & members

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET/PATCH | `/organizations/{org_id}` | name, GSTIN, state, address, logo | MVP |
| POST | `/organizations/{org_id}/logo` | upload letterhead logo | MVP |
| GET/POST/PATCH/DELETE | `/organizations/{org_id}/members[/{user_id}]` | team management | P3 |
| GET/PUT | `/organizations/{org_id}/settings/{key}` | GST defaults, charge defaults, export letterhead | MVP |

## 5.4 Dashboard & search

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/dashboard/summary` | counts (total/draft/completed), total estimated value, recent projects/BOQs/documents, subscription status | MVP |
| GET | `/search?q=&types=project,boq_item,rate,document,estimate` | Postgres FTS + trigram, tenant-scoped | P2 (projects-only in MVP) |

## 5.5 Projects

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/projects?status=&type=&q=&page=` | list | MVP |
| POST | `/projects` | wizard submit | MVP |
| GET/PATCH/DELETE | `/projects/{project_id}` | soft delete | MVP |
| GET | `/project-types` · `/work-categories?project_type=` | configurable lists | MVP |
| GET/POST/PATCH/DELETE | `/projects/{project_id}/members[/{user_id}]` | project roles | P3 |

## 5.6 Estimates & versions

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET/POST | `/projects/{project_id}/estimates` | create creates V1 draft | MVP |
| GET/PATCH/DELETE | `/estimates/{estimate_id}` | title, number, signatories | MVP |
| GET | `/estimates/{estimate_id}/versions` | list with totals | MVP |
| GET | `/versions/{version_id}` | full version: sections, items, measurements, parameters, charges, GST, live totals | MVP |
| POST | `/versions/{version_id}/freeze` | `{change_note}` → freezes and returns the new draft | MVP |
| GET | `/versions/{a}/compare/{b}` | added/deleted/changed qty/rate/amount by `line_key` | P2 |
| POST | `/versions/{version_id}/restore` | clone an old frozen version into a new draft | P2 |

## 5.7 BOQ, measurements, parameters (all require a draft version)

| Method | Path | Purpose | Phase |
|---|---|---|---|
| POST | `/versions/{vid}/sections` · PATCH/DELETE `/sections/{id}` · POST `/versions/{vid}/sections/reorder` | abstract grouping | MVP |
| POST | `/versions/{vid}/boq-items` | add item (manual) | MVP |
| PATCH | `/boq-items/{id}` | inline edit any field. The response includes recalculated item, section, and version totals plus changed validation findings | MVP |
| DELETE | `/boq-items/{id}` | | MVP |
| POST | `/boq-items/{id}/duplicate` | | MVP |
| POST | `/versions/{vid}/boq-items/reorder` | `{section_id, ordered_ids[]}` | MVP |
| POST | `/boq-items/{id}/set-rate` | `{rate_item_id}` or `{rate, source:"manual"}`. If a manual rate exists and `confirm_overwrite` ≠ true, returns 409 `RATE_OVERWRITE_REQUIRES_CONFIRMATION` | MVP |
| GET/POST | `/boq-items/{id}/measurements` | detailed-estimate lines (L, B, D/H, No, deduction) | MVP |
| PATCH/DELETE | `/measurements/{id}` | triggers recalculation | MVP |
| GET | `/measurements/{id}/calculation` | "View Calculation": expression, substituted values, steps, units, provenance, engine version | MVP |
| GET/POST | `/versions/{vid}/parameters` | named quantity inputs | MVP |
| PATCH | `/parameters/{id}` | `{value, unit}` → recalculates all dependents and returns the affected items | MVP |
| POST | `/parameters/{id}/accept-default` | explicit acceptance, audited | MVP |
| POST | `/boq-items/{id}/ai/explain` | AI explanation that uses only the item's own data | P2 |
| POST | `/versions/{vid}/ai/suggest-items` | missing-item suggestions (no quantities, no rates) | P2 |

## 5.8 Calculations & units (stateless)

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/calculation-templates?category=` | catalogue with parameter definitions | MVP |
| POST | `/calculate` | `{template_id | expression, parameters{name:{value,unit}}, output_unit}` → result + steps (standalone calculator) | MVP |
| POST | `/calculate/validate-expression` | syntax + dimension check for custom formulas | MVP |
| GET | `/units` | units with aliases and dimensions | MVP |
| POST | `/units/convert` | `{value, from, to}` | MVP |

## 5.9 AI estimate

| Method | Path | Purpose | Phase |
|---|---|---|---|
| POST | `/ai/extractions` | `{project_id?, text, language_hint?}` → 202 `{job_id, extraction_id}`. Consumes quota | MVP |
| GET | `/ai/extractions/{id}` | status, detected project type, components → templates, parameters (value, unit, provenance, source_text, confidence), `missing_information[]`, `assumptions[]`, `warnings[]` | MVP |
| PATCH | `/ai/extractions/{id}/parameters` | user corrections / entries | MVP |
| POST | `/ai/extractions/{id}/confirm` | `{estimate_id | create_estimate:{…}, accepted_defaults:[param names]}` → rejects with `MISSING_PARAMETER` if anything is still missing → creates sections, BOQ items, measurements, calculations and parameters in the draft version | MVP |
| POST | `/ai/extractions/{id}/rate-suggestions` | ranked candidate rates per item from the selected SOR (search only) | MVP |
| POST | `/projects/{pid}/assistant/messages` | project-scoped Q&A with citations (SSE stream) | P2 |

## 5.10 Rates

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/rate-sources?state=&department=&year=` | selectable SORs with verification badge | MVP (manual/org sources) |
| POST/PATCH/DELETE | `/rate-sources[/{id}]` | org-private SOR (Pro+) | P2 |
| GET | `/rate-sources/{id}/items?q=&unit=` | search by FTS + trigram. Returns code, description, unit, rate, SOR, year, state, source, effective period | MVP |
| POST | `/rate-sources/{id}/items` | manual entry | MVP |
| POST | `/rate-sources/{id}/imports` | CSV/XLSX upload → 202 job → preview with row errors | P2 |
| POST | `/rate-imports/{batch_id}/commit` · `/rollback` | | P2 |
| GET | `/rate-imports/template.csv` · `.xlsx` | import template | P2 |

## 5.11 Abstract, charges, GST, validation

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/versions/{vid}/abstract` | section totals, works subtotal, each charge (base, %, amount), CGST/SGST/IGST, grand total, amount in words | MVP |
| GET/POST | `/versions/{vid}/charges` · PATCH/DELETE `/charges/{id}` · POST `/versions/{vid}/charges/reorder` | | MVP |
| GET/PUT | `/versions/{vid}/gst` | applicable, inclusive/exclusive, intra (CGST+SGST) / inter (IGST), percentages, base | MVP |
| POST | `/versions/{vid}/validate` | run all rules → findings `{rule_id, severity: green/yellow/red, message, entity_ref}` | MVP |
| GET | `/validation-rules` | rule catalogue with thresholds (admin-tunable) | P2 |

## 5.12 Exports & jobs

| Method | Path | Purpose | Phase |
|---|---|---|---|
| POST | `/versions/{vid}/exports` | `{format: pdf|xlsx|docx, sections:[cover,details,detailed,boq,abstract,calculations,assumptions], signatories}` → 202 `{job_id}` | MVP (pdf, xlsx); P2 docx |
| GET | `/exports/{id}` | metadata + short-lived signed download URL | MVP |
| GET | `/jobs/{job_id}` | status, progress, stage, result, error | MVP |
| GET | `/jobs/{job_id}/events` | SSE progress stream | P2 |

## 5.13 Documents

| Method | Path | Purpose | Phase |
|---|---|---|---|
| POST | `/projects/{pid}/documents` | multipart upload → scan → classify (job) | P2 |
| GET | `/projects/{pid}/documents` · GET/DELETE `/documents/{id}` | | P2 |
| GET | `/documents/{id}/download` | signed URL | P2 |
| POST | `/documents/{id}/extract` | `{target: boq|project_info|dimensions}` → job. The result reports extraction method per page and flags unreadable pages | P2 |
| POST | `/documents/{id}/extractions/{xid}/import` | reviewed rows → BOQ items (`provenance=document_extracted`) | P2 |
| POST | `/documents/{id}/drawing-analysis` | AI-derived measurements labelled "verify before use" | P3 |
| POST | `/projects/{pid}/site-observations` | photo → possible observations (no structural safety conclusions) | P3 |

## 5.14 Audit & notifications

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/projects/{pid}/audit?entity_type=&from=&to=` | who/when/what/old → new | P2 (captured from MVP) |
| GET | `/notifications` · POST `/notifications/{id}/read` | | P2 |

## 5.15 Billing

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/plans` | public plan list (prices from DB) | MVP |
| GET | `/billing/subscription` | current plan, status, period, usage vs limits | MVP |
| POST | `/billing/checkout` | `{plan_code, interval}` → creates Razorpay subscription and returns `{subscription_id, key_id}` for Checkout. **Does not change the plan** | MVP (structure) |
| POST | `/billing/cancel` | cancel at period end | MVP (structure) |
| GET | `/billing/invoices` | | P2 |
| POST | `/webhooks/razorpay` | signature-verified, idempotent. **Only** this path activates, renews, halts or cancels a subscription | MVP (structure) |

## 5.16 Admin (platform_role = admin)

| Method | Path | Purpose |
|---|---|---|
| CRUD | `/admin/rate-sources`, `/admin/rate-sources/{id}/items`, imports | global SORs, verification status |
| CRUD | `/admin/units`, `/admin/unit-conversions` | |
| CRUD | `/admin/calculation-templates` | new template versions (never mutate existing) |
| GET/PUT | `/admin/settings/{key}` | platform GST/charge defaults |
| GET/PATCH | `/admin/users`, `/admin/organizations` | activate/deactivate, change plan manually (audited) |
| CRUD | `/admin/plans` | prices and limits |
| GET | `/admin/ai-usage?from=&to=&group_by=user|org|model|purpose` | tokens, cost, cache hit rate |
| CRUD | `/admin/prompts` + POST `/admin/prompts/{id}/{version}/activate` | activation requires a passing eval score |
| CRUD | `/admin/feature-flags` | |
| GET | `/admin/logs`, `/admin/jobs` | system logs and failed jobs |

## 5.17 Health

`GET /healthz`, `GET /readyz` (unauthenticated, no data).
