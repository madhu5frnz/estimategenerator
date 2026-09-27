"""AI Estimate: description → reviewed parameters → (user confirms) → BOQ.

Flow
1. ``create``: normalise the text, pick the provider, reuse a cached result for the same
   input, check the plan quota (metered providers only), call the provider, run the
   guardrails, and store everything in ``ai_generations`` (the cost ledger and the record of
   what was proposed).
2. The user reviews the proposed parameters, fills in missing ones, and may accept
   suggested defaults. Nothing is calculated into an estimate yet.
3. ``confirm``: every value is validated again on the server. Values the user left as
   extracted keep the provider's provenance; changed values become ``user_entered``;
   accepted defaults become ``default_accepted`` (and are audited). Parameters, BOQ items
   and formula lines are then created in one transaction, and the engine calculates the
   quantities.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai import postprocess
from app.ai.providers import PROMPT_ID, PROMPT_VERSION, ProviderResult, cost_usd, get_provider
from app.ai.schemas import ExtractionResult
from app.ai.text import normalise
from app.config import get_settings
from app.core.errors import AppError
from app.core.ids import new_id
from app.core.security import now_utc
from app.domain.numeric import InvalidNumberError, plain, to_decimal
from app.domain.quantity import BUILTIN_TEMPLATES
from app.domain.units import Dimension, UnitError, default_registry
from app.models import AiGeneration, EstimateSection, EstimateVersion, QuantityInput, UsageCounter
from app.services import audit
from app.services import estimates as estimate_service
from app.services import projects as project_service
from app.services.context import AuthContext
from app.services.plans import current_plan

PURPOSE = "extract_parameters"
METRIC = "ai_generations"
TEMPLATES = {t.id: t for t in BUILTIN_TEMPLATES}


# ============================================================ quota & usage
def _period_start(db: Session, organization_id: uuid.UUID) -> date:
    return current_plan(db, organization_id).subscription.current_period_start.date()


def ai_used(db: Session, organization_id: uuid.UUID) -> int:
    used = db.scalar(
        select(UsageCounter.used).where(
            UsageCounter.organization_id == organization_id,
            UsageCounter.metric == METRIC,
            UsageCounter.period_start == _period_start(db, organization_id),
        )
    )
    return int(used or 0)


def _check_quota(db: Session, organization_id: uuid.UUID) -> None:
    state = current_plan(db, organization_id)
    limit = state.limit("ai_generations_per_period")
    if limit is not None and ai_used(db, organization_id) >= limit:
        raise AppError(
            "QUOTA_EXCEEDED",
            f"Your {state.plan.name} plan includes {limit} AI generations per month, and they "
            "have been used. The rules-based parser and manual entry remain available.",
            429,
            {"limit": limit, "plan": state.plan.code},
        )


def _count_usage(db: Session, organization_id: uuid.UUID) -> None:
    stmt = insert(UsageCounter).values(
        organization_id=organization_id,
        metric=METRIC,
        period_start=_period_start(db, organization_id),
        used=1,
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["organization_id", "metric", "period_start"],
            set_={"used": UsageCounter.used + 1},
        )
    )


# ================================================================== create
def create(db: Session, ctx: AuthContext, *, project_id: uuid.UUID, text: str) -> AiGeneration:
    project_service.get_access(db, ctx, project_id, estimate_service.EDIT_ROLE)
    settings = get_settings()
    cleaned = normalise(text)
    if not cleaned:
        raise AppError("VALIDATION_ERROR", "Describe the work first.", details={"field": "text"})
    if len(cleaned) > settings.ai_max_input_chars:
        raise AppError(
            "INPUT_TOO_LONG",
            f"Please keep the description under {settings.ai_max_input_chars} characters.",
            details={"field": "text"},
        )
    provider = get_provider()
    model = provider.model_id()
    input_hash = hashlib.sha256(
        f"{PROMPT_ID}|{PROMPT_VERSION}|{provider.name}|{model}|{cleaned}".encode()
    ).hexdigest()
    row = AiGeneration(
        id=new_id(),
        organization_id=ctx.organization_id,
        user_id=ctx.user.id,
        project_id=project_id,
        purpose=PURPOSE,
        prompt_id=PROMPT_ID if provider.name != "rules" else "rules_extractor",
        prompt_version=PROMPT_VERSION,
        model=model,
        input_hash=input_hash,
        input_text=cleaned,
        status="running",
    )

    cached = db.scalar(
        select(AiGeneration)
        .where(
            AiGeneration.organization_id == ctx.organization_id,
            AiGeneration.input_hash == input_hash,
            AiGeneration.raw_output.is_not(None),
            AiGeneration.created_at
            >= now_utc() - timedelta(hours=settings.ai_response_cache_ttl_hours),
        )
        .order_by(AiGeneration.created_at.desc())
        .limit(1)
    )
    if cached is not None and cached.raw_output is not None:
        result = ExtractionResult.model_validate(cached.raw_output)
        row.raw_output = cached.raw_output
        row.served_from_cache = True
    else:
        if provider.metered:
            _check_quota(db, ctx.organization_id)
        try:
            outcome: ProviderResult = provider.extract(cleaned)
        except AppError as exc:
            row.status = "failed"
            row.validation_errors = {"error_code": exc.error_code, "message": exc.message}
            db.add(row)
            db.commit()
            raise
        result = outcome.result
        row.model = outcome.model
        row.raw_output = outcome.raw
        row.input_tokens, row.output_tokens = outcome.input_tokens, outcome.output_tokens
        row.cache_read_tokens = outcome.cache_read_tokens
        row.cache_write_tokens = outcome.cache_write_tokens
        row.latency_ms = outcome.latency_ms
        row.cost_usd = cost_usd(outcome)
        if provider.metered:
            _count_usage(db, ctx.organization_id)

    reviewed = postprocess.review(result, cleaned, provider=provider.name)
    reviewed["provenance"] = provider.provenance
    row.validated_output = reviewed
    row.status = "needs_input"
    db.add(row)
    db.commit()
    return row


def get(db: Session, ctx: AuthContext, extraction_id: uuid.UUID) -> AiGeneration:
    row = db.scalar(
        select(AiGeneration).where(
            AiGeneration.id == extraction_id,
            AiGeneration.organization_id == ctx.organization_id,
            AiGeneration.purpose == PURPOSE,
        )
    )
    if row is None or row.project_id is None:
        raise AppError("NOT_FOUND", "Extraction not found.", 404)
    project_service.get_access(db, ctx, row.project_id, "viewer")
    return row


# ================================================================= confirm
@dataclass(frozen=True)
class FinalValue:
    value: Decimal
    unit: str | None
    provenance: str
    source_text: str | None
    accepted_default: bool


def _same(a: Any, b: Any) -> bool:
    try:
        return a is not None and b is not None and to_decimal(a) == to_decimal(b)
    except InvalidNumberError:
        return False


def _final_values(
    component: dict[str, Any], given: dict[str, dict[str, Any]], provider_provenance: str
) -> tuple[dict[str, FinalValue], list[dict[str, str]]]:
    registry = default_registry()
    values: dict[str, FinalValue] = {}
    problems: list[dict[str, str]] = []
    for p in component["parameters"]:
        name = p["name"]
        entry = given.get(name, {})
        problem = {
            "component_key": component["key"],
            "component_name": component["component_name"],
            "parameter": name,
            "label": p["label"],
        }
        if entry.get("accept_default"):
            suggestion = p.get("suggested_default")
            if not suggestion:
                problems.append({**problem, "reason": "There is no suggested value to accept."})
                continue
            values[name] = FinalValue(
                to_decimal(suggestion["value"]),
                suggestion.get("unit"),
                "default_accepted",
                None,
                True,
            )
            continue
        trusted = p["status"] in ("ok", "template_default")
        raw_value = entry["value"] if "value" in entry else (p["value"] if trusted else None)
        raw_unit = entry.get("unit", p["unit"])
        if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
            reason = (
                "Please confirm this value."
                if p["status"] == "needs_confirmation"
                else "Value is required."
            )
            problems.append({**problem, "reason": reason})
            continue
        try:
            value = to_decimal(raw_value)
        except InvalidNumberError:
            problems.append({**problem, "reason": "Not a number."})
            continue
        if value < 0:
            problems.append({**problem, "reason": "Cannot be negative."})
            continue
        dimension = Dimension(p["dimension"])
        unit: str | None = None
        if dimension is not Dimension.COUNT:
            try:
                parsed = registry.parse(raw_unit or "")
            except UnitError:
                problems.append({**problem, "reason": "Choose a unit."})
                continue
            if parsed.dimension is not dimension:
                problems.append({**problem, "reason": f"Needs a {dimension.value} unit."})
                continue
            unit = parsed.code
        if p["status"] == "template_default" and _same(value, p["value"]):
            continue  # neutral template default: the formula line uses it automatically
        unchanged = p["status"] == "ok" and _same(value, p["value"]) and unit == p["unit"]
        values[name] = FinalValue(
            value,
            unit,
            provider_provenance if unchanged else "user_entered",
            p["source_text"] if unchanged else None,
            False,
        )
    return values, problems


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _short(component_name: str) -> str:
    """'Granular sub-base (GSB)' → 'gsb'; 'CC pavement' → 'cc'."""
    abbreviation = re.search(r"\(([^)]+)\)", component_name)
    return _slug(abbreviation.group(1) if abbreviation else component_name.split()[0])


@dataclass(frozen=True)
class ConfirmResult:
    estimate_id: uuid.UUID
    version_id: uuid.UUID
    project_id: uuid.UUID
    items_created: int
    parameters_created: int


def confirm(
    db: Session, ctx: AuthContext, extraction_id: uuid.UUID, payload: dict[str, Any]
) -> ConfirmResult:
    row = get(db, ctx, extraction_id)
    assert row.project_id is not None
    if row.status == "succeeded":
        raise AppError(
            "ALREADY_CONFIRMED",
            "This description has already been turned into a BOQ.",
            409,
            {"result": (row.validated_output or {}).get("result")},
        )
    if row.status != "needs_input" or not row.validated_output:
        raise AppError("NOT_READY", "This extraction cannot be confirmed.", 409)
    reviewed = row.validated_output
    provenance = reviewed.get("provenance", "ai_extracted")
    choices = {c["key"]: c for c in payload.get("components", [])}
    custom_choices = {c["key"]: c for c in payload.get("custom_items", [])}

    # Check the target before anything else, so the clearest error comes first.
    estimate_id = payload.get("estimate_id")
    if estimate_id:
        target, _ = estimate_service.get_estimate(db, ctx, estimate_id, estimate_service.EDIT_ROLE)
        if target.project_id != row.project_id:
            raise AppError("VALIDATION_ERROR", "That estimate belongs to a different project.")

    plans: list[tuple[dict[str, Any], dict[str, FinalValue]]] = []
    problems: list[dict[str, str]] = []
    for component in reviewed["components"]:
        choice = choices.get(component["key"], {})
        if not choice.get("include", True):
            continue
        values, found = _final_values(component, choice.get("parameters") or {}, provenance)
        problems.extend(found)
        plans.append((component, values))
    customs = [
        c for c in reviewed["custom_items"] if custom_choices.get(c["key"], {}).get("include", True)
    ]
    if problems:
        listed = "; ".join(
            f"{p['component_name']} – {p['label']}: {p['reason']}" for p in problems[:5]
        )
        raise AppError(
            "MISSING_PARAMETER",
            f"Some values still need attention: {listed}",
            400,
            {"problems": problems},
        )
    if not plans and not customs:
        raise AppError("VALIDATION_ERROR", "Select at least one item to add.")

    # ------------------------------------------------------------ target
    if estimate_id:
        estimate = target
    else:
        title = (payload.get("new_estimate_title") or "").strip() or "Estimate from description"
        estimate = estimate_service.create_estimate(
            db, ctx, row.project_id, {"title": title[:200]}, commit=False
        )
    version_id = db.scalar(
        select(EstimateVersion.id).where(
            EstimateVersion.estimate_id == estimate.id, EstimateVersion.status == "draft"
        )
    )
    assert version_id is not None
    estimate_service.get_version(db, ctx, version_id, estimate_service.EDIT_ROLE, writable=True)

    section_title = (payload.get("section_title") or "").strip() or "Works from description"
    estimate_service.add_section(db, ctx, version_id, section_title[:200], commit=False)
    section_id = db.scalar(
        select(EstimateSection.id)
        .where(EstimateSection.version_id == version_id)
        .order_by(EstimateSection.sequence.desc())
        .limit(1)
    )

    # ----------------------------------------------------------- parameters
    existing = {
        p.name: p
        for p in db.scalars(select(QuantityInput).where(QuantityInput.version_id == version_id))
    }
    created_params = 0

    def parameter_for(component: dict[str, Any], label: str, v: FinalValue) -> str:
        nonlocal created_params
        base = _slug(label)[:50] or "value"
        for candidate in (base, f"{base}_{_short(component['component_name'])}"[:60]):
            current = existing.get(candidate)
            if current is None:
                name = candidate
                break
            if (
                current.value == v.value
                and current.unit_code == v.unit
                and current.provenance == v.provenance
                and not v.accepted_default
            ):
                return candidate  # the same value is shared (e.g. road length for CC and GSB)
        else:
            n = 2
            while f"{base}_{n}" in existing:
                n += 1
            name = f"{base}_{n}"
        estimate_service.add_parameter(
            db,
            ctx,
            version_id,
            {
                "name": name,
                "label": label if name == base else f"{label} ({component['component_name']})",
                "value": v.value,
                "unit": v.unit,
                "provenance": v.provenance,
                "source_text": v.source_text,
            },
            commit=False,
        )
        param = db.scalar(
            select(QuantityInput).where(
                QuantityInput.version_id == version_id, QuantityInput.name == name
            )
        )
        assert param is not None
        existing[name] = param
        created_params += 1
        if v.accepted_default:
            audit.record(
                db,
                actor=ctx.user,
                organization_id=ctx.organization_id,
                entity_type="parameter",
                entity_id=param.id,
                project_id=row.project_id,
                version_id=version_id,
                action="accept_default",
                new_value={"name": name, "value": plain(v.value), "unit": v.unit},
            )
        return name

    # ---------------------------------------------------------------- items
    items = 0
    for component, values in plans:
        template = TEMPLATES[component["template_id"]]
        labels = {tp.name: tp.label for tp in template.parameters}
        refs = {name: parameter_for(component, labels[name], v) for name, v in values.items()}
        _, item = estimate_service.add_item(
            db,
            ctx,
            version_id,
            {
                "section_id": section_id,
                "description": component["component_name"],
                "unit": template.output_unit,
                "provenance": provenance,
            },
            commit=False,
        )
        item.ai_generation_id = row.id
        estimate_service.add_line(
            db,
            ctx,
            item.id,
            {
                "mode": "formula",
                "template_id": template.id,
                "description": component["component_name"],
                "inputs": {name: {"ref": ref} for name, ref in refs.items()},
                "provenance": provenance,
            },
            commit=False,
        )
        items += 1
    for custom in customs:
        _, item = estimate_service.add_item(
            db,
            ctx,
            version_id,
            {
                "section_id": section_id,
                "description": custom["description"],
                "provenance": "ai_suggested",
                "remarks": "Quantity not given in the description",
            },
            commit=False,
        )
        item.ai_generation_id = row.id
        items += 1

    result = {
        "estimate_id": str(estimate.id),
        "version_id": str(version_id),
        "items_created": items,
        "parameters_created": created_params,
    }
    row.validated_output = {**reviewed, "result": result, "confirmed_payload": payload}
    row.status = "succeeded"
    audit.record(
        db,
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type="ai_generation",
        entity_id=row.id,
        project_id=row.project_id,
        version_id=version_id,
        action="confirm",
        new_value=result,
    )
    db.commit()
    return ConfirmResult(estimate.id, version_id, row.project_id, items, created_params)
