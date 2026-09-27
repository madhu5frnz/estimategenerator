# 02 — Database ER Diagram

The full DDL is in [`03-database-schema.sql`](./03-database-schema.sql). This page shows the relationships.

## 2.1 Terminology used by the schema

Indian estimates have two levels, and the table names follow them:

| Table | What it represents | Example |
|---|---|---|
| `boq_items` | A **priced item** of the BOQ / abstract: description, unit, quantity, rate, amount | "PCC M15 for CC road — 825.000 Cum @ ₹6,450 = ₹53,21,250.00" |
| `estimate_items` | A **measurement line** of the detailed estimate under a BOQ item: L, B, D/H, No., quantity, deduction flag | "Chainage 0–500: 1 × 500 × 5.5 × 0.15 = 412.500" |
| `calculations` | The immutable **calculation record** behind a measurement line: template, expression, inputs, result, engine version | `road_layer`, `500 × 5.5 × 0.15`, 412.500 cu.m |
| `quantity_inputs` | **Named parameters** at version level that formulas can reference | `road_length = 1 km`, `cc_thickness = 150 mm` |

A BOQ item's quantity is the sum of its measurement lines (deductions subtract). If a BOQ item has no measurement lines, it is a manual quantity with `quantity_source = manual`.

## 2.2 Core estimating model

```mermaid
erDiagram
  organizations ||--o{ projects : owns
  projects ||--o{ project_members : has
  users ||--o{ project_members : "is member"
  projects ||--o{ estimates : contains
  estimates ||--o{ estimate_versions : "versioned as"
  estimate_versions ||--o{ estimate_sections : groups
  estimate_sections ||--o{ boq_items : contains
  boq_items ||--o{ estimate_items : "measured by"
  estimate_items ||--o| calculations : "computed by"
  calculation_templates ||--o{ calculations : "template for"
  estimate_versions ||--o{ quantity_inputs : "parameters"
  estimate_versions ||--o{ estimate_charges : "charges & GST"
  rate_items ||--o{ boq_items : "rate selected from"
  units ||--o{ boq_items : "unit"
  ai_generations ||--o{ boq_items : "created by (optional)"

  organizations {
    uuid id PK
    text name
    text gstin
    text state_code
  }
  projects {
    uuid id PK
    uuid organization_id FK
    text name
    text project_type
    text work_category
    text district
    text state
    numeric estimated_value
  }
  estimates {
    uuid id PK
    uuid project_id FK
    text estimate_number
    text title
  }
  estimate_versions {
    uuid id PK
    uuid estimate_id FK
    int version_no
    text status "draft|frozen"
    text change_note
    jsonb gst_config
    jsonb totals_snapshot
  }
  estimate_sections {
    uuid id PK
    uuid version_id FK
    text title "Earthwork, GSB, CC..."
    int sequence
  }
  boq_items {
    uuid id PK
    uuid line_key "stable across versions"
    uuid section_id FK
    text item_no
    text description
    text unit_code FK
    numeric quantity
    text quantity_source
    numeric rate
    text rate_source_type
    uuid rate_item_id FK
    numeric amount
    text provenance
  }
  estimate_items {
    uuid id PK
    uuid line_key
    uuid boq_item_id FK
    text description
    numeric nos
    numeric length
    numeric breadth
    numeric depth_height
    numeric quantity
    bool is_deduction
  }
  calculations {
    uuid id PK
    uuid estimate_item_id FK
    text template_id FK
    text expression
    jsonb input_parameters
    numeric result_raw
    text result_unit
    jsonb steps
    text engine_version
  }
  quantity_inputs {
    uuid id PK
    uuid version_id FK
    text name
    numeric value
    text unit_code
    text provenance
    text source_text
  }
  estimate_charges {
    uuid id PK
    uuid version_id FK
    text name
    text kind
    numeric percentage
    numeric fixed_amount
    text applies_to
    bool enabled
    int sequence
  }
```

## 2.3 Rates, documents, AI

```mermaid
erDiagram
  rate_sources ||--o{ rate_items : contains
  rate_import_batches ||--o{ rate_items : imported
  organizations ||--o{ rate_sources : "private SORs (optional)"
  projects ||--o{ documents : has
  documents ||--o{ document_chunks : "split into"
  users ||--o{ ai_generations : "requested"
  projects ||--o{ ai_generations : "about"
  prompt_templates ||--o{ ai_generations : "prompt version"

  rate_sources {
    uuid id PK
    uuid organization_id "NULL = global"
    text state
    text department
    text sor_name
    text year "2026-27"
    date effective_from
    date effective_to
    text verification_status "demo|user_entered|verified_official"
    text source_reference
  }
  rate_items {
    uuid id PK
    uuid rate_source_id FK
    text item_code
    text description
    text unit_code
    numeric basic_rate
    numeric gst_pct
    numeric total_rate
    tsvector search_vector
  }
  documents {
    uuid id PK
    uuid project_id FK
    text original_filename
    text mime_type
    bigint size_bytes
    text storage_key
    text scan_status
    bool has_text_layer
    text processing_status
  }
  document_chunks {
    uuid id PK
    uuid document_id FK
    int page_no
    text text_content
    text extraction_method "text_layer|ocr"
    numeric ocr_confidence
  }
  ai_generations {
    uuid id PK
    uuid user_id FK
    uuid project_id FK
    text purpose
    text model
    text prompt_version
    int input_tokens
    int output_tokens
    int cache_read_tokens
    numeric cost_usd
    jsonb validated_output
    text status
  }
  prompt_templates {
    text id PK
    int version
    text purpose
    text system_prompt
    jsonb output_schema
    bool active
  }
```

## 2.4 Identity, billing, platform

```mermaid
erDiagram
  users ||--o{ organization_members : ""
  organizations ||--o{ organization_members : ""
  users ||--o{ oauth_accounts : ""
  users ||--o{ refresh_tokens : ""
  organizations ||--o| subscriptions : "current"
  plans ||--o{ subscriptions : ""
  subscriptions ||--o{ payments : ""
  organizations ||--o{ usage_counters : ""
  users ||--o{ audit_logs : "actor"
  users ||--o{ notifications : ""
  estimate_versions ||--o{ exports : ""
  units ||--o{ unit_conversions : "from"

  users {
    uuid id PK
    citext email UK
    text password_hash "nullable (Google-only)"
    text full_name
    text platform_role "user|admin"
  }
  organizations {
    uuid id PK
    text name
  }
  organization_members {
    uuid organization_id FK
    uuid user_id FK
    text role "owner|admin|member"
  }
  plans {
    text code PK "free|starter|pro|business"
    numeric price_inr_monthly
    jsonb limits
    jsonb features
  }
  subscriptions {
    uuid id PK
    uuid organization_id FK
    text plan_code FK
    text status
    text razorpay_subscription_id
    timestamptz current_period_end
  }
  payments {
    uuid id PK
    uuid subscription_id FK
    text razorpay_payment_id UK
    numeric amount_inr
    text status
  }
  usage_counters {
    uuid organization_id FK
    text metric "ai_generations|doc_pages"
    date period_start
    int used
  }
  audit_logs {
    bigint id PK
    uuid actor_user_id
    text entity_type
    uuid entity_id
    text action
    jsonb old_value
    jsonb new_value
    timestamptz created_at
  }
  exports {
    uuid id PK
    uuid version_id FK
    text format "pdf|xlsx|docx"
    text storage_key
    text status
  }
  units {
    text code PK "m, sqm, cum, kg..."
    text dimension
    text display_name
  }
  unit_conversions {
    text from_unit FK
    text to_unit FK
    numeric factor
    numeric offset
  }
```

## 2.5 Tables beyond the brief's list

The brief listed 22 tables. The design adds these, each for a concrete reason:

| Added table | Why |
|---|---|
| `organization_members` | Users can belong to several orgs (Business plan, consultants working for multiple firms). |
| `oauth_accounts`, `refresh_tokens` | Google login, secure refresh-token rotation. |
| `estimates` | A project can hold several estimates (e.g. preliminary vs detailed, or Road vs Drain packages). Versions hang off an estimate, not a project. |
| `estimate_sections` | Abstract grouping (Earthwork, GSB, CC …). |
| `estimate_charges` | Contingencies, WCE, labour cess, seigniorage, and so on, as configurable rows. |
| `calculation_templates` | Versioned formula catalogue shared by the engine and the AI prompt. |
| `rate_import_batches` | Traceability and rollback of a CSV/Excel import. |
| `plans`, `usage_counters` | Configurable pricing and quota enforcement. |
| `prompt_templates`, `feature_flags` | Admin-managed prompts and flags. |
| `jobs` | Background job status and progress. |
| `webhook_events` | Idempotent payment webhook processing. |

## 2.6 Cross-cutting column conventions

* Primary keys: `uuid` (v7, time-ordered, generated in app) except append-only logs (`bigint identity`).
* Every tenant-owned row carries `organization_id` directly (denormalised), so every query can filter on it without joins. It is indexed.
* Money: `numeric(16,2)` INR. Rates: `numeric(14,2)`. Quantities: `numeric(18,3)` stored plus `numeric(28,10)` raw. Percentages: `numeric(7,4)`.
* `provenance` enum on quantities, parameters and rates: `user_entered | ai_extracted | ai_suggested | default_accepted | document_extracted | drawing_derived | rate_database | calculated`.
* `created_at`, `updated_at`, `created_by`, `updated_by` on all mutable tables. Soft delete (`deleted_at`) on projects, estimates, documents.
