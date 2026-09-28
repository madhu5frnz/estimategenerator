"""Telangana I&CAD estimate method on top of estimates: data sheets, leads, seigniorage,
General Abstract.

* Picking a book rate copies the book's data sheet into the item (``item_analyses``).
  The item's rate is then the engine's "or say" rate of that sheet, so edits (deleted
  components, cement correction, conveyance) reprice the item.
* Conveyance lines in a sheet point at a lead-statement entry; changing a lead distance
  reprices every item that uses it.
* Seigniorage lines can follow a BOQ item's quantity.
* All settings live in ``estimate_versions.method_config`` and are copied on freeze.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.ids import new_id
from app.domain.icad import general_abstract as ga
from app.domain.icad import seigniorage as sg
from app.domain.icad.lead import LeadError, mechanical_lead
from app.domain.icad.rate_analysis import DataResult, DataSheetError, compute
from app.domain.icad.serialize import AnalysisFormatError, to_sheet
from app.models import BoqItem, EstimateVersion, ItemAnalysis, LeadEntry, RateItem, SeigniorageLine
from app.services import estimates as es
from app.services.context import AuthContext

DATA = Path(__file__).resolve().parents[1] / "data" / "ts_icad_2026_27"
ZONES = ("I", "II", "III")
MATERIAL_CLASSES = ("earth_sand", "aggregate_stone", "cement_steel")
EDITABLE = ("verified", "rounded", "user")


@lru_cache(maxsize=1)
def basic_rates() -> dict[str, Any]:
    return json.loads((DATA / "basic_rates.json").read_text())  # type: ignore[no-any-return]


# =============================================================================
# Settings
# =============================================================================
def default_config() -> dict[str, Any]:
    seig = basic_rates()["seigniorage_defaults"]
    return {
        "zone": "III",
        "area_allowance": "none",
        "abstract": {
            "item_rounding": "none",
            "labour_cess_pct": "1",
            "nac_pct": "0.1",
            "cess_rounding": "paise",
            "nac_rounding": "paise",
            "gst_pct": "18",
            "gst_rounding": "paise",
            "final": "none",
            "unforeseen": "0",
            "lump_sums": [],  # [{"label", "amount", "stage": "before_gst"|"after_gst"}]
        },
        "seigniorage": {
            "rates": {k: v["rate"] for k, v in seig["rates"].items()},
            "dmf_pct": seig["dmf_pct"],
            "smet_pct": seig["smet_pct"],
            "permit_fee_pct": seig["permit_fee_pct"],
            "permit_fee_materials": [seig["permit_fee_on"]],
            "line_rounding": "roundup_paise",
            "levy_rounding": "rupee",
            "sand_split": "natural",  # or "50_50" (GO Ms 37: M-sand and river sand 50:50)
        },
    }


def config_of(version: EstimateVersion) -> dict[str, Any]:
    base = default_config()
    stored = version.method_config or {}
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


ROUNDING = ("none", "paise", "rupee")


def _check_config(cfg: dict[str, Any]) -> None:
    if cfg["zone"] not in ZONES:
        raise AppError("VALIDATION_ERROR", "Zone must be I, II or III.", details={"field": "zone"})
    ab = cfg["abstract"]
    for key in ("item_rounding", "cess_rounding", "nac_rounding", "gst_rounding"):
        if ab[key] not in ROUNDING:
            raise AppError("VALIDATION_ERROR", f"{key} must be one of {', '.join(ROUNDING)}.")
    if ab["final"] not in ("none", "round_up_1000_plus_unforeseen"):
        raise AppError("VALIDATION_ERROR", "Unknown final rounding.")
    for key in ("labour_cess_pct", "nac_pct", "gst_pct", "unforeseen"):
        _num(ab[key], key)
    for ls in ab["lump_sums"]:
        if not str(ls.get("label", "")).strip() or ls.get("stage") not in (
            "before_gst",
            "after_gst",
        ):
            raise AppError("VALIDATION_ERROR", "Each lump sum needs a label and a stage.")
        _num(ls.get("amount"), ls.get("label", "amount"))
    sgc = cfg["seigniorage"]
    for key, value in sgc["rates"].items():
        _num(value, f"seigniorage rate {key}")
    for key in ("dmf_pct", "smet_pct", "permit_fee_pct"):
        _num(sgc[key], key)
    if sgc["sand_split"] not in ("natural", "50_50"):
        raise AppError("VALIDATION_ERROR", "sand_split must be natural or 50_50.")


def update_config(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, changes: dict[str, Any]
) -> es.VersionScope:
    scope = es._scope_for(db, ctx, version_id)
    old = config_of(scope.version)
    new = config_of(scope.version)
    for key, value in changes.items():
        if key not in new:
            raise AppError("VALIDATION_ERROR", f"Unknown setting '{key}'.")
        new[key] = {**new[key], **value} if isinstance(new[key], dict) else value
    _check_config(new)
    if new != old:
        scope.version.method_config = new
        es._audit(
            db,
            ctx,
            scope,
            entity_type="estimate_version",
            entity_id=scope.version.id,
            action="update",
            field_name="method_config",
            old=old,
            new=new,
        )
        if new["zone"] != old["zone"]:
            _reprice_all(db, scope.version)
    db.commit()
    return scope


def _num(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", ""))
    except Exception as exc:
        raise AppError("VALIDATION_ERROR", f"{label}: '{value}' is not a number.") from exc
    if not number.is_finite() or number < 0:
        raise AppError("VALIDATION_ERROR", f"{label} must be zero or more.")
    return number


# =============================================================================
# Lead statement
# =============================================================================
@dataclass(frozen=True)
class LeadView:
    entry: LeadEntry
    amount: Decimal
    working: str
    problem: str | None


def lead_amount(entry: LeadEntry, zone: str) -> LeadView:
    if entry.manual_amount is not None:
        return LeadView(entry, entry.manual_amount, "entered", None)
    if entry.distance_km is None:
        return LeadView(entry, Decimal("0.00"), "", "Enter the distance.")
    try:
        charge = mechanical_lead(
            basic_rates()["lead"]["mechanical"][zone],
            entry.material_class,
            entry.distance_km,
            initial_km=entry.initial_km,
        )
    except LeadError as exc:
        return LeadView(entry, Decimal("0.00"), "", str(exc))
    return LeadView(entry, charge.amount, charge.working, None)


def lead_entries(db: Session, version_id: uuid.UUID) -> list[LeadEntry]:
    return list(
        db.scalars(
            select(LeadEntry)
            .where(LeadEntry.version_id == version_id)
            .order_by(LeadEntry.sequence, LeadEntry.id)
        )
    )


def lead_statement(db: Session, version: EstimateVersion) -> list[LeadView]:
    zone = config_of(version)["zone"]
    return [lead_amount(e, zone) for e in lead_entries(db, version.id)]


LEAD_FIELDS = (
    "material",
    "source",
    "unit",
    "material_class",
    "distance_km",
    "initial_km",
    "manual_amount",
    "note",
)


def _lead_values(data: dict[str, Any], current: LeadEntry | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in LEAD_FIELDS:
        if key not in data and current is not None:
            continue
        value = data.get(key)
        if key in ("distance_km", "manual_amount"):
            value = None if value in (None, "") else _num(value, key)
        elif key == "initial_km":
            value = int(value if value not in (None, "") else 1)
            if value not in (0, 1):
                raise AppError("VALIDATION_ERROR", "Initial lead must be 0 or 1 km.")
        elif key == "material_class":
            value = value or "earth_sand"
            if value not in MATERIAL_CLASSES:
                raise AppError(
                    "VALIDATION_ERROR",
                    "Unknown material class.",
                    details={"field": "material_class"},
                )
        elif isinstance(value, str) or value is None:
            value = (value or "").strip() or None
        out[key] = value
    if current is None and not out.get("material"):
        raise AppError("VALIDATION_ERROR", "Material is required.", details={"field": "material"})
    if "unit" in out and not out["unit"]:
        out["unit"] = "cum"
    return out


def add_lead(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, data: dict[str, Any]
) -> es.VersionScope:
    scope = es._scope_for(db, ctx, version_id)
    last = db.scalar(select(func.max(LeadEntry.sequence)).where(LeadEntry.version_id == version_id))
    entry = LeadEntry(
        id=new_id(),
        organization_id=ctx.organization_id,
        version_id=version_id,
        line_key=new_id(),
        sequence=int(last or 0) + 1,
        **_lead_values(data, None),
    )
    db.add(entry)
    es._audit(
        db,
        ctx,
        scope,
        entity_type="lead_entry",
        entity_id=entry.id,
        action="create",
        new={"material": entry.material, "distance_km": es._json(entry.distance_km)},
    )
    db.commit()
    return scope


def _lead(db: Session, ctx: AuthContext, entry_id: uuid.UUID) -> tuple[LeadEntry, es.VersionScope]:
    entry = db.scalar(
        select(LeadEntry).where(
            LeadEntry.id == entry_id, LeadEntry.organization_id == ctx.organization_id
        )
    )
    if entry is None:
        raise AppError("NOT_FOUND", "Lead entry not found.", 404)
    return entry, es._scope_for(db, ctx, entry.version_id)


def update_lead(
    db: Session, ctx: AuthContext, entry_id: uuid.UUID, data: dict[str, Any]
) -> es.VersionScope:
    entry, scope = _lead(db, ctx, entry_id)
    for key, value in _lead_values(data, entry).items():
        old = getattr(entry, key)
        if old != value:
            setattr(entry, key, value)
            es._audit(
                db,
                ctx,
                scope,
                entity_type="lead_entry",
                entity_id=entry.id,
                action="update",
                field_name=key,
                old=old,
                new=value,
            )
    db.flush()
    _reprice_all(db, scope.version)
    db.commit()
    return scope


def delete_lead(db: Session, ctx: AuthContext, entry_id: uuid.UUID) -> es.VersionScope:
    entry, scope = _lead(db, ctx, entry_id)
    key = str(entry.line_key)
    used = [
        a
        for a in _analyses(db, entry.version_id)
        if any(adj.get("lead_key") == key for adj in a.analysis.get("adjustments", []))
    ]
    if used:
        raise AppError(
            "LEAD_IN_USE",
            f"{len(used)} item(s) use this lead for conveyance. "
            "Remove it from their data sheets first.",
            409,
        )
    es._audit(
        db,
        ctx,
        scope,
        entity_type="lead_entry",
        entity_id=entry.id,
        action="delete",
        old={"material": entry.material},
    )
    db.delete(entry)
    db.commit()
    return scope


# =============================================================================
# Data sheets
# =============================================================================
def _analyses(db: Session, version_id: uuid.UUID) -> list[ItemAnalysis]:
    return list(db.scalars(select(ItemAnalysis).where(ItemAnalysis.version_id == version_id)))


def _lead_lookup(db: Session, version: EstimateVersion) -> dict[str, Decimal]:
    return {str(v.entry.line_key): v.amount for v in lead_statement(db, version)}


def evaluate(analysis: ItemAnalysis, description: str, leads: dict[str, Decimal]) -> DataResult:
    return compute(to_sheet(analysis.code, description, analysis.analysis, leads.get))


def _reprice(item: BoqItem, analysis: ItemAnalysis, leads: dict[str, Decimal]) -> None:
    item.rate = evaluate(analysis, item.description, leads).rate.quantize(Decimal("0.01"))
    es._reprice(item)


def _reprice_all(db: Session, version: EstimateVersion) -> None:
    leads = _lead_lookup(db, version)
    for analysis in _analyses(db, version.id):
        item = db.get(BoqItem, analysis.boq_item_id)
        if item is not None:
            _reprice(item, analysis, leads)


def attach_book_analysis(db: Session, item: BoqItem, rate_item: RateItem) -> None:
    """Called by set_rate: copy the book's data sheet when it can be recomputed."""
    existing = db.scalar(select(ItemAnalysis).where(ItemAnalysis.boq_item_id == item.id))
    if existing is not None:
        db.delete(existing)
        db.flush()
    if not rate_item.analysis or rate_item.analysis_status not in EDITABLE:
        return
    analysis = ItemAnalysis(
        id=new_id(),
        organization_id=item.organization_id,
        version_id=item.version_id,
        boq_item_id=item.id,
        source_rate_item_id=rate_item.id,
        code=rate_item.item_code,
        analysis={**rate_item.analysis, "adjustments": [], "deleted_rows": []},
        status=rate_item.analysis_status,
    )
    db.add(analysis)
    db.flush()
    version = db.get(EstimateVersion, item.version_id)
    assert version is not None
    _reprice(item, analysis, _lead_lookup(db, version))


def detach_analysis(db: Session, item: BoqItem) -> None:
    """A typed rate replaces the data sheet."""
    existing = db.scalar(select(ItemAnalysis).where(ItemAnalysis.boq_item_id == item.id))
    if existing is not None:
        db.delete(existing)


def get_analysis(
    db: Session, ctx: AuthContext, item_id: uuid.UUID
) -> tuple[BoqItem, ItemAnalysis | None, es.VersionScope]:
    item = db.scalar(
        select(BoqItem).where(BoqItem.id == item_id, BoqItem.organization_id == ctx.organization_id)
    )
    if item is None:
        raise AppError("NOT_FOUND", "BOQ item not found.", 404)
    scope = es.get_version(db, ctx, item.version_id)
    analysis = db.scalar(select(ItemAnalysis).where(ItemAnalysis.boq_item_id == item.id))
    return item, analysis, scope


def update_analysis(
    db: Session, ctx: AuthContext, item_id: uuid.UUID, data: dict[str, Any]
) -> es.VersionScope:
    item, analysis, _ = get_analysis(db, ctx, item_id)
    scope = es._scope_for(db, ctx, item.version_id)
    if analysis is None:
        raise AppError(
            "NO_ANALYSIS", "This item has no data sheet. Pick a Standard Data rate first.", 409
        )
    new = {**analysis.analysis, **data}
    leads = _lead_lookup(db, scope.version)
    known = set(leads)
    for adj in new.get("adjustments", []):
        if adj.get("kind") == "conveyance" and adj.get("lead_key") not in known:
            raise AppError(
                "VALIDATION_ERROR", "A conveyance line must use an entry of the lead statement."
            )
    try:
        result = compute(to_sheet(analysis.code, item.description, new, leads.get))
    except (DataSheetError, AnalysisFormatError) as exc:
        raise AppError("VALIDATION_ERROR", str(exc)) from exc
    old_rate = item.rate
    analysis.analysis = new
    if analysis.status != "user":
        analysis.status = "user" if _changed_rows(new) else analysis.status
    item.rate = result.rate.quantize(Decimal("0.01"))
    es._reprice(item)
    es._audit(
        db,
        ctx,
        scope,
        entity_type="item_analysis",
        entity_id=analysis.id,
        action="update",
        old={"rate": es._json(old_rate)},
        new={"rate": es._json(item.rate), "changed": sorted(data)},
    )
    db.commit()
    return scope


def _changed_rows(data: dict[str, Any]) -> bool:
    return bool(data.get("deleted_rows"))


def auto_conveyance(db: Session, ctx: AuthContext, item_id: uuid.UUID) -> es.VersionScope:
    """Add a conveyance line per lead entry whose material the data sheet uses (A section),
    with the quantity of that material per unit of the item."""
    item, analysis, _ = get_analysis(db, ctx, item_id)
    if analysis is None:
        raise AppError("NO_ANALYSIS", "This item has no data sheet.", 409)
    scope = es._scope_for(db, ctx, item.version_id)
    data = analysis.analysis
    qty = Decimal(str(data["analysis_qty"]))
    deleted = set(data.get("deleted_rows", []))
    kept = [a for a in data.get("adjustments", []) if a.get("kind") != "conveyance"]
    lines = []
    for view in lead_statement(db, scope.version):
        entry = view.entry
        names = [w.strip() for w in re.split(r"[/,]", entry.material) if len(w.strip()) > 2]
        if not names:
            continue
        words = re.compile("|".join(re.escape(n) for n in names), re.I)
        total = Decimal(0)
        for n, row in enumerate(data.get("rows", [])):
            if row.get("section") != "A" or n in deleted or row.get("quantity") is None:
                continue
            text = row.get("description", "")
            if not words.search(text):
                continue
            q = Decimal(str(row["quantity"]))
            unit = row.get("unit", "").lower()
            if entry.unit.lower() in ("mt", "tonne") and unit == "kg":
                q = q / 1000
            elif (
                unit.rstrip(".") not in (entry.unit.lower(), "cum") and entry.unit.lower() == "cum"
            ):
                continue
            total += q
        if total:
            lines.append(
                {
                    "kind": "conveyance",
                    "description": f"Conveyance of {entry.material}",
                    "quantity": format((total / qty).quantize(Decimal("0.0001")).normalize(), "f"),
                    "lead_key": str(entry.line_key),
                }
            )
    return _save_adjustments(db, ctx, item, analysis, scope, [*kept, *lines])


def _save_adjustments(
    db: Session,
    ctx: AuthContext,
    item: BoqItem,
    analysis: ItemAnalysis,
    scope: es.VersionScope,
    adjustments: list[dict[str, Any]],
) -> es.VersionScope:
    analysis.analysis = {**analysis.analysis, "adjustments": adjustments}
    old = item.rate
    _reprice(item, analysis, _lead_lookup(db, scope.version))
    es._audit(
        db,
        ctx,
        scope,
        entity_type="item_analysis",
        entity_id=analysis.id,
        action="conveyance",
        old={"rate": es._json(old)},
        new={"rate": es._json(item.rate)},
    )
    db.commit()
    return scope


# =============================================================================
# Seigniorage
# =============================================================================
MIX = re.compile(
    r"\bCA\s*:?\s*(?P<ca>\d+(?:\.\d+)?)\s*cum.*?\bFA\s*:?\s*(?P<fa>\d+(?:\.\d+)?)\s*cum",
    re.I | re.S,
)


def seigniorage_lines(db: Session, version_id: uuid.UUID) -> list[SeigniorageLine]:
    return list(
        db.scalars(
            select(SeigniorageLine)
            .where(SeigniorageLine.version_id == version_id)
            .order_by(SeigniorageLine.sequence, SeigniorageLine.id)
        )
    )


def seigniorage(
    db: Session, version: EstimateVersion
) -> tuple[list[tuple[SeigniorageLine, Decimal]], sg.SeigniorageResult]:
    cfg = config_of(version)["seigniorage"]
    items = {
        i.line_key: i for i in db.scalars(select(BoqItem).where(BoqItem.version_id == version.id))
    }
    rows = []
    for line in seigniorage_lines(db, version.id):
        item = items.get(line.boq_item_line_key) if line.boq_item_line_key else None
        qty = (
            (item.quantity or Decimal(0))
            if item is not None
            else (line.item_quantity or Decimal(0))
        )
        rows.append((line, qty))
    result = sg.compute(
        [
            sg.SeigniorageLine(line.label, line.material, qty, line.factor, line.rate)
            for line, qty in rows
        ],
        sg.SeigniorageSettings(
            dmf_pct=Decimal(cfg["dmf_pct"]),
            smet_pct=Decimal(cfg["smet_pct"]),
            permit_fee_pct=Decimal(cfg["permit_fee_pct"]),
            permit_fee_materials=frozenset(cfg["permit_fee_materials"]),
            line_rounding=cfg["line_rounding"],
            levy_rounding=cfg["levy_rounding"],
        ),
    )
    return rows, result


SEIG_FIELDS = ("label", "material", "boq_item_line_key", "item_quantity", "factor", "rate")


def _seig_values(
    db: Session, version: EstimateVersion, data: dict[str, Any], current: SeigniorageLine | None
) -> dict[str, Any]:
    rates = config_of(version)["seigniorage"]["rates"]
    out: dict[str, Any] = {}
    for key in SEIG_FIELDS:
        if key not in data and current is not None:
            continue
        value = data.get(key)
        if key in ("factor", "rate", "item_quantity"):
            value = None if value in (None, "") else _num(value, key)
        elif key == "boq_item_line_key":
            if value:
                value = uuid.UUID(str(value))
                if not db.scalar(
                    select(BoqItem.id).where(
                        BoqItem.version_id == version.id, BoqItem.line_key == value
                    )
                ):
                    raise AppError("VALIDATION_ERROR", "Choose an item of this estimate.")
            else:
                value = None
        elif key == "material":
            if value not in rates:
                raise AppError("VALIDATION_ERROR", f"Material must be one of {', '.join(rates)}.")
        else:
            value = (value or "").strip()
        out[key] = value
    if current is None:
        if not out.get("label"):
            raise AppError("VALIDATION_ERROR", "Label is required.")
        out.setdefault("factor", Decimal(1))
        if out.get("factor") is None:
            out["factor"] = Decimal(1)
        if out.get("rate") is None:
            out["rate"] = Decimal(rates[out["material"]])
    return out


def add_seigniorage_line(
    db: Session, ctx: AuthContext, version_id: uuid.UUID, data: dict[str, Any]
) -> es.VersionScope:
    scope = es._scope_for(db, ctx, version_id)
    last = db.scalar(
        select(func.max(SeigniorageLine.sequence)).where(SeigniorageLine.version_id == version_id)
    )
    line = SeigniorageLine(
        id=new_id(),
        organization_id=ctx.organization_id,
        version_id=version_id,
        line_key=new_id(),
        sequence=int(last or 0) + 1,
        **_seig_values(db, scope.version, data, None),
    )
    db.add(line)
    es._audit(
        db,
        ctx,
        scope,
        entity_type="seigniorage_line",
        entity_id=line.id,
        action="create",
        new={"label": line.label, "material": line.material},
    )
    db.commit()
    return scope


def _seig(
    db: Session, ctx: AuthContext, line_id: uuid.UUID
) -> tuple[SeigniorageLine, es.VersionScope]:
    line = db.scalar(
        select(SeigniorageLine).where(
            SeigniorageLine.id == line_id, SeigniorageLine.organization_id == ctx.organization_id
        )
    )
    if line is None:
        raise AppError("NOT_FOUND", "Seigniorage line not found.", 404)
    return line, es._scope_for(db, ctx, line.version_id)


def update_seigniorage_line(
    db: Session, ctx: AuthContext, line_id: uuid.UUID, data: dict[str, Any]
) -> es.VersionScope:
    line, scope = _seig(db, ctx, line_id)
    for key, value in _seig_values(db, scope.version, data, line).items():
        if getattr(line, key) != value:
            es._audit(
                db,
                ctx,
                scope,
                entity_type="seigniorage_line",
                entity_id=line.id,
                action="update",
                field_name=key,
                old=getattr(line, key),
                new=value,
            )
            setattr(line, key, value)
    db.commit()
    return scope


def delete_seigniorage_line(db: Session, ctx: AuthContext, line_id: uuid.UUID) -> es.VersionScope:
    line, scope = _seig(db, ctx, line_id)
    es._audit(
        db,
        ctx,
        scope,
        entity_type="seigniorage_line",
        entity_id=line.id,
        action="delete",
        old={"label": line.label},
    )
    db.delete(line)
    db.commit()
    return scope


def suggest_seigniorage(db: Session, ctx: AuthContext, version_id: uuid.UUID) -> es.VersionScope:
    """Create lines for concrete items (metal and sand from the CA / FA of the mix in the
    item description) and embankment items (earth), linked to the item quantity. Items
    that already have lines are skipped."""
    scope = es._scope_for(db, ctx, version_id)
    cfg = config_of(scope.version)["seigniorage"]
    rates = cfg["rates"]
    linked = {line.boq_item_line_key for line in seigniorage_lines(db, version_id)}
    view = es.load_version(db, scope)
    added = 0
    for section in view.sections:
        for iv in section.items:
            item = iv.item
            if item.line_key in linked:
                continue
            label = f"{iv.sl_no} {(item.item_no or '').strip()}".strip()
            book = (item.rate_snapshot or {}).get("description") or ""
            text = f"{item.description or ''} {book}"
            mix = MIX.search(text)
            proposals: list[tuple[str, Decimal]] = []
            if mix:
                proposals.append(("metal", Decimal(mix.group("ca"))))
                fa = Decimal(mix.group("fa"))
                if cfg["sand_split"] == "50_50":
                    proposals += [("sand", fa / 2), ("m_sand", fa / 2)]
                else:
                    proposals.append(("sand", fa))
            elif (
                re.search(r"\b(embankment|casing|hearting|gravel|murrum|filling)\b", text, re.I)
                and item.unit_code == "cum"
            ):
                proposals.append(("earth", Decimal(1)))
            for material, factor in proposals:
                add = {
                    "label": label,
                    "material": material,
                    "boq_item_line_key": str(item.line_key),
                    "factor": format(factor, "f"),
                    "rate": rates[material],
                }
                last = db.scalar(
                    select(func.max(SeigniorageLine.sequence)).where(
                        SeigniorageLine.version_id == version_id
                    )
                )
                db.add(
                    SeigniorageLine(
                        id=new_id(),
                        organization_id=ctx.organization_id,
                        version_id=version_id,
                        line_key=new_id(),
                        sequence=int(last or 0) + 1,
                        **_seig_values(db, scope.version, add, None),
                    )
                )
                db.flush()
                added += 1
    es._audit(
        db,
        ctx,
        scope,
        entity_type="seigniorage_line",
        entity_id=None,
        action="suggest",
        new={"added": added},
    )
    db.commit()
    return scope


# =============================================================================
# General Abstract
# =============================================================================
@dataclass(frozen=True)
class GeneralAbstract:
    view: es.VersionView
    items: list[tuple[str, BoqItem, Decimal]]  # sl no, item, amount
    seigniorage: sg.SeigniorageResult
    result: ga.AbstractResult
    config: dict[str, Any]


def general_abstract(db: Session, scope: es.VersionScope) -> GeneralAbstract:
    cfg = config_of(scope.version)
    ab = cfg["abstract"]
    view = es.load_version(db, scope)
    boq = [(iv.sl_no, iv.item) for s in view.sections for iv in s.items]
    items = [
        ga.AbstractItem(
            sl,
            i.item_no or sl,
            i.description,
            i.quantity or Decimal(0),
            i.unit_code or "",
            i.rate or Decimal(0),
        )
        for sl, i in boq
    ]
    _, seig = seigniorage(db, scope.version)
    settings = ga.AbstractSettings(
        item_rounding=ab["item_rounding"],
        labour_cess_pct=Decimal(ab["labour_cess_pct"]),
        nac_pct=Decimal(ab["nac_pct"]),
        cess_rounding=ab["cess_rounding"],
        nac_rounding=ab["nac_rounding"],
        gst_pct=Decimal(ab["gst_pct"]),
        gst_rounding=ab["gst_rounding"],
        final=ab["final"],
        unforeseen=Decimal(ab["unforeseen"]),
    )
    lump = ab["lump_sums"]
    result = ga.compute(
        items,
        seigniorage=seig.total,
        dmf=seig.dmf,
        smet=seig.smet,
        permit_fee=seig.permit_fee,
        before_gst=[
            ga.LumpSum(x["label"], Decimal(str(x["amount"])))
            for x in lump
            if x["stage"] == "before_gst"
        ],
        after_gst=[
            ga.LumpSum(x["label"], Decimal(str(x["amount"])))
            for x in lump
            if x["stage"] == "after_gst"
        ],
        settings=settings,
    )
    return GeneralAbstract(
        view,
        [(sl, i, a) for (sl, i), a in zip(boq, result.item_amounts, strict=True)],
        seig,
        result,
        cfg,
    )


# =============================================================================
# Freeze
# =============================================================================
def copy_to_draft(db: Session, source: EstimateVersion, draft: EstimateVersion) -> None:
    draft.method_config = dict(source.method_config or {})
    new_items = {
        i.line_key: i.id for i in db.scalars(select(BoqItem).where(BoqItem.version_id == draft.id))
    }
    old_items = {
        i.id: i.line_key for i in db.scalars(select(BoqItem).where(BoqItem.version_id == source.id))
    }
    for a in _analyses(db, source.id):
        target = new_items.get(old_items.get(a.boq_item_id))  # type: ignore[arg-type]
        if target:
            db.add(
                ItemAnalysis(
                    id=new_id(),
                    organization_id=a.organization_id,
                    version_id=draft.id,
                    boq_item_id=target,
                    source_rate_item_id=a.source_rate_item_id,
                    code=a.code,
                    analysis=dict(a.analysis),
                    status=a.status,
                )
            )
    for e in lead_entries(db, source.id):
        db.add(
            LeadEntry(
                id=new_id(),
                organization_id=e.organization_id,
                version_id=draft.id,
                **{k: getattr(e, k) for k in ("line_key", "sequence", *LEAD_FIELDS)},
            )
        )
    for s in seigniorage_lines(db, source.id):
        db.add(
            SeigniorageLine(
                id=new_id(),
                organization_id=s.organization_id,
                version_id=draft.id,
                **{k: getattr(s, k) for k in ("line_key", "sequence", *SEIG_FIELDS)},
            )
        )
