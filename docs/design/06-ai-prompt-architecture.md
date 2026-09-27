# 06 — AI Prompt Architecture

## 6.1 What the AI is allowed to do

| AI **may** | AI **must not** |
|---|---|
| Identify project type and work components | Perform final arithmetic (quantities, amounts, totals, GST) |
| Map components to **catalogue templates** | Invent formulas outside the catalogue (it may only propose a `custom_item` without a quantity) |
| Extract dimensions, counts and units from text or documents, quoting the source span | Supply rates, SOR codes or references |
| List missing information and assumptions | Fill in missing dimensions silently |
| Draft item descriptions (marked `ai_suggested`) | Claim that an estimate or quantity is "correct" or "approved" |
| Answer questions about **this project's data** with citations | Use knowledge outside the project, documents and selected SOR as fact |

These rules are written in the prompts **and** enforced in `ai/postprocess.py`. Prompts are advisory. Post-processing is the guarantee.

## 6.2 Pipeline

```
input text / document chunks
   │
   ├─ normalise: Unicode NFC, Telugu/Devanagari digits → ASCII, strip control chars,
   │             length cap (plan-dependent), PII-free logging
   │
   ├─ cache lookup: sha256(prompt_id, prompt_version, model, normalised input)
   │                hit → reuse validated output (no quota charged)
   │
   ├─ LLM call  (model chosen by router; structured outputs = JSON schema)
   │
   ├─ schema validation (Pydantic, strict) ──fail──► 1 retry with error feedback ──fail──► AI_OUTPUT_INVALID
   │
   ├─ post-processing / guardrails
   │     • template_id ∈ active catalogue, else → custom_item (no quantity)
   │     • parameter names ∈ template.parameters, else dropped + warning
   │     • unit parses via UnitRegistry and dimension matches, else → needs_confirmation
   │     • source_text must appear in the input (fuzzy ≥ 0.9), else → needs_confirmation
   │     • any quantity/rate/amount keys the model emitted are removed
   │     • required parameter with null value → missing_information (deduplicated)
   │
   ├─ persist ai_generations (tokens, cost, latency, raw + validated output)
   │
   └─ return to UI for review ── user corrects/confirms ── deterministic engine calculates
```

## 6.3 Extraction providers (the app works without an AI key)

*Implemented in M4:* `backend/app/ai/` (`rules.py`, `providers.py`, `postprocess.py`), with the golden set in `fixtures/golden/extraction/cases.json`.

All extraction goes through one interface, `ExtractionProvider.extract(text, catalogue) -> ExtractionResult`. The rest of the pipeline in §6.2 (schema validation, guardrails, review UI, confirm → engine) does not know which provider produced the result. The provider is chosen by `AI_PROVIDER`:

| Provider | When | Behaviour |
|---|---|---|
| `rules` | **Default when no `ANTHROPIC_API_KEY` is set.** Also the fallback when the AI provider is down or the org's AI quota is used up | Deterministic parser: finds `number + unit` pairs next to dimension keywords (long/length, wide/width, thick/thickness/depth, …) and component keywords (CC, PCC, GSB, WMM, WBM, BT, brickwork, plaster, excavation, …); normalises Telugu/Devanagari digits and unit words (మీటర్లు, मीटर). It only extracts values that are literally in the text, so `source_text` is always exact. Anything it cannot place becomes missing information for the user. No cost, no quota consumed |
| `mock` | Automated tests, CI, offline demos | Returns recorded `ExtractionResult` fixtures keyed by input hash |
| `anthropic` | When `ANTHROPIC_API_KEY` is set | LLM extraction as described below |

The UI labels which provider produced a result ("Parsed by rules" or "AI-extracted"). Provenance is `ai_extracted` only for the LLM. The rules parser uses a separate provenance value, `rule_extracted` (already in the `provenance` enum). The golden set (§6.10) is run against **both** `rules` and `anthropic`, so the value of the paid provider can be measured.

## 6.4 Model routing

Model IDs are **configuration** (`AI_MODEL_FAST`, `AI_MODEL_STANDARD`, `AI_MODEL_DEEP`), so they can be changed without a deploy. Suggested initial mapping (Anthropic Claude API, current model IDs):

| Tier | Default model | Used for | Why |
|---|---|---|---|
| `fast` | `claude-haiku-4-5` | short single-component descriptions, item-description drafting, classifying uploads | lowest cost; extraction from one sentence is a narrow task |
| `standard` | `claude-sonnet-5` | multi-component extraction (the default for `/ai-estimate`), Telugu/Hindi input, project assistant | better at messy, multilingual, multi-item text |
| `deep` | `claude-opus-5` | document BOQ extraction from long/scanned PDFs, drawing analysis, reconciling conflicting sources | complex reasoning over long inputs |

The router picks `fast` only when the input is short (< 300 chars), English, and the fast model's output passes validation. Otherwise it escalates once to `standard`. Escalations are logged, so the thresholds can be tuned with real data. **The golden eval set (§6.10) decides whether a cheaper tier is good enough.** Cost alone does not.

Structured JSON is obtained with the API's structured-outputs feature (`output_config.format` with a JSON schema, via `client.messages.parse()` in the Python SDK). The system prompt is stable and placed first, so prompt caching applies to the system prompt and template catalogue.

## 6.5 Prompt registry

Each prompt is a versioned record (`prompt_templates`: `id`, `version`, `model_tier`, `system_prompt`, `output_schema`, `is_active`, `eval_score`). Source files live in `backend/app/ai/prompts/*.vN.md` and are seeded on deploy. Admins can author a new version in the admin panel, but **activation requires the golden eval to pass** at or above the current version's score. Every `ai_generations` row records the `prompt_id` and `version` that produced it.

| prompt id | Tier | Phase | Output schema |
|---|---|---|---|
| `extract_parameters` | fast → standard | MVP | `ExtractionResult` |
| `describe_item` | fast | MVP | `{description, specification}` |
| `document_boq` | deep | P2 | `DocumentBoqResult` (rows with page refs) |
| `document_project_info` | standard | P2 | `ProjectInfoResult` |
| `explain_item` | standard | P2 | `{explanation, citations[]}` |
| `suggest_missing_items` | standard | P2 | `{suggestions[{description, reason, template_id?}]}` (never quantities) |
| `assistant` | standard | P2 | tool-using agent loop with read-only tools |
| `drawing_measurements` | deep | P3 | `DrawingResult` (every value flagged `drawing_derived`) |
| `site_observation` | standard | P3 | `SiteObservationResult` (hedged language enforced) |

## 6.6 `extract_parameters` — system prompt (v1)

```text
You are an assistant to Indian civil engineers. You read a description of proposed
construction work and turn it into structured parameters for a calculation engine.

Your job is interpretation only. A separate deterministic engine performs every
calculation, and a human engineer reviews everything you return.

Rules:
1. Map each distinct work component to exactly one template_id from TEMPLATE_CATALOGUE.
   If no template fits, return it under custom_items with a description only.
2. For each template, extract only the parameters that template defines. For every value,
   give the number, the unit exactly as the user wrote it, and source_text: the exact words
   from the input the value came from.
3. Never invent, estimate, or assume a dimension, thickness, count, grade, or specification
   that is not stated. If a required parameter is not stated, set its value to null and add
   an entry to missing_information with a short, specific question for the user.
4. You may add a suggested_default for a missing parameter only if you name why it is a
   common choice. It is a suggestion; it will not be used unless the user accepts it.
5. Do not calculate quantities, amounts, or totals. Do not provide rates, SOR item codes,
   or references to any government schedule.
6. Keep units as written ("150 mm", "2 km", "5.5 mtrs"). Do not convert them.
7. If the same dimension applies to several components (for example the road width
   applies to the CC layer and the GSB layer), repeat it for each template and quote the
   same source_text. If a component needs a width that differs from the carriageway and
   the text does not say, treat it as missing.
8. Descriptions may be in English, Telugu, Hindi, or mixed. Read numbers and units in any
   of these languages. Write descriptions and questions in English. (The UI translates
   in a later phase.)
9. List interpretations you made (for example "'CC road' interpreted as cement concrete
   pavement") under assumptions.

TEMPLATE_CATALOGUE:
{{template_catalogue_json}}        ← id, name, category, parameters[name, dimension, required, description]
```

User message: the raw description, inside `<description>` tags, and nothing else. Project metadata such as the project type (if known) is passed in a separate, clearly labelled block.

### Output schema `ExtractionResult` (abridged)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["project_type", "components", "custom_items", "missing_information", "assumptions"],
  "properties": {
    "project_type": { "enum": ["building","road","drain","culvert","bridge","irrigation","canal","tank",
                               "lift_irrigation","water_supply","sewerage","electrical","other"] },
    "components": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["component_name", "template_id", "parameters"],
        "properties": {
          "component_name": { "type": "string" },
          "template_id": { "type": "string" },
          "parameters": {
            "type": "array",
            "items": {
              "type": "object", "additionalProperties": false,
              "required": ["name", "value", "unit", "source_text"],
              "properties": {
                "name":        { "type": "string" },
                "value":       { "type": ["number", "null"] },
                "unit":        { "type": ["string", "null"] },
                "source_text": { "type": ["string", "null"] },
                "suggested_default": {
                  "type": ["object", "null"],
                  "properties": { "value": {"type":"number"}, "unit": {"type":"string"}, "reason": {"type":"string"} }
                }
              }
            }
          }
        }
      }
    },
    "custom_items": { "type": "array", "items": { "type": "object",
        "properties": { "description": {"type":"string"}, "source_text": {"type":"string"} } } },
    "missing_information": { "type": "array", "items": { "type": "object",
        "properties": { "component_name": {"type":"string"}, "parameter": {"type":"string"}, "question": {"type":"string"} } } },
    "assumptions": { "type": "array", "items": { "type": "string" } }
  }
}
```

### Worked example

Input: *"Construction of 500 m long CC road, 5.5 m wide and 150 mm thick with 100 mm GSB."*

LLM output (abridged):
```json
{
  "project_type": "road",
  "components": [
    { "component_name": "CC pavement", "template_id": "road_layer",
      "parameters": [
        {"name":"length","value":500,"unit":"m","source_text":"500 m long"},
        {"name":"width","value":5.5,"unit":"m","source_text":"5.5 m wide"},
        {"name":"thickness","value":150,"unit":"mm","source_text":"150 mm thick"} ] },
    { "component_name": "Granular sub-base", "template_id": "road_layer",
      "parameters": [
        {"name":"length","value":500,"unit":"m","source_text":"500 m long"},
        {"name":"width","value":null,"unit":null,"source_text":null,
         "suggested_default":{"value":5.5,"unit":"m","reason":"GSB is often laid to the carriageway width; confirm whether it extends under shoulders"}},
        {"name":"thickness","value":100,"unit":"mm","source_text":"100 mm GSB"} ] }
  ],
  "custom_items": [],
  "missing_information": [
    {"component_name":"Granular sub-base","parameter":"width","question":"Please enter the GSB width (is it 5.5 m like the carriageway, or wider?)."}
  ],
  "assumptions": ["'CC road' interpreted as cement concrete pavement."]
}
```

Backend (after the user confirms GSB width = 5.5 m):
```
CC  : road_layer  500 m × 5.5 m × 0.150 m = 412.500 Cum   (150 mm → 0.150 m by unit service)
GSB : road_layer  500 m × 5.5 m × 0.100 m = 275.000 Cum   (width provenance: default_accepted, user X, time T)
```

Telugu input *"500 మీటర్ల పొడవు, 5.5 మీటర్ల వెడల్పుతో 150 mm మందం CC రోడ్డు నిర్మించాలి."* must produce the same CC component. This pair is in the golden set.

## 6.7 `document_boq` (Phase 2)

* Input: document chunks (text layer or OCR), **one page range per call**, with page numbers.
* The model returns rows `{item_no, description, unit_as_written, quantity_as_written, rate_as_written, page_no, source_text}`. Values are copied, not computed.
* Backend: parses numbers (Indian grouping aware), maps units, recomputes `quantity × rate`, and **flags rows where the document's own amount disagrees** with the recomputation.
* Pages with OCR confidence below a threshold, or with no extractable text, are reported as `unreadable_pages[]`. The UI shows them. We never claim they were analysed.

## 6.8 Project assistant (Phase 2)

* A tool-use loop with **read-only** tools: `get_version_summary`, `get_boq_items(filter)`, `get_calculation(measurement_id)`, `run_validation`, `search_documents(query)` (Postgres FTS over `document_chunks`), `search_rates(query, source_id)`.
* The system prompt restricts answers to tool results. Every factual statement must cite a tool result (`[item 3.2]`, `[doc: BOQ.pdf p.4]`, `[calc: measurement 12]`). The UI renders citations as links.
* The assistant can **draft** text (technical justification, completion report) that the user edits. It cannot mutate the estimate. Any change it suggests is presented as a proposal that the user applies through normal endpoints.
* Context control: only summaries plus the tool results the model asks for are sent. The whole project database is never sent.

## 6.9 Prompt-injection & data-safety measures

* User and document text is always passed as *data* inside delimited blocks, never concatenated into instructions.
* The assistant's tools are read-only and tenant-scoped by the server. The model cannot name an org or project id.
* Outputs are schema-validated. Free text from the model is rendered as plain text (no HTML).
* No secrets, other users' data, or other projects' data are included in any prompt.

## 6.10 Evaluation

* `fixtures/golden/extraction/*.json`: at least 60 cases at launch (roads, buildings, drains, canals; English, Telugu, Hindi, mixed; deliberately incomplete descriptions; distractor numbers such as chainages and years).
* Metrics: parameter exact-match (after unit normalisation), **false-fill rate** (a value supplied that was not in the text — target 0), missing-info recall, template accuracy.
* The eval runs on every prompt-version change and model change, and weekly on schedule. Prompt activation is gated on the score.

## 6.11 Cost controls

* Per-org quota (`usage_counters`) checked **before** enqueueing. Cache hits don't count.
* Response cache keyed by the normalised input hash. The prompt cache holds the stable system prompt plus catalogue.
* Hard caps: max input characters per plan, `max_tokens` per purpose, max pages per document job.
* The Batch API (about 50 % cheaper) is used for non-interactive bulk work such as re-extracting a large rate-book import.
* `ai_generations.cost_usd` is computed from a price table in config and shown in the admin AI-usage report.
