"""The estimate docket's text sheets: Cover, Check Slip, Certificates, Quotations.

Stored under ``method_config["docket"]`` so a saved version keeps them. Check-slip
answers the app knows (amount, SSR year, lead statement, non-SOR items, sanctioning
level) are filled automatically unless the engineer typed an answer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.domain.money import amount_in_words, format_inr
from app.services import estimates as es
from app.services import icad
from app.services.context import AuthContext

SSR_YEAR = "2026-27"
LAKH = Decimal(100000)

# (no, question, auto key) - wording as in the department's check slip.
CHECK_SLIP: list[tuple[str, str, str | None]] = [
    ("1", "Name of the Project / Scheme / Work", "name_of_work"),
    ("2", "Estimate Amount Rs.", "amount"),
    ("3", "Category of Project / Scheme / Work", None),
    ("4", "Location / District / Mandal / Village", "location"),
    ("5", "Scope of work in brief", None),
    ("6", "Ayacut proposed - Wet / ID", None),
    ("7", "Cropping pattern", None),
    ("8", "Source / River basin / Sub-basin / Sub-Minor basin", None),
    ("9", "Availability of water at the site", None),
    ("10", "Allocation of water / utilization", None),
    (
        "11",
        "Reference in which Hydrological clearance was accorded by the competent authority",
        None,
    ),
    ("12", "Cost per Acre Rs.", None),
    ("13", "B.C. Ratio", None),
    (
        "14",
        "Whether the report accompanying the estimate, detailed estimate and abstract estimate are enclosed",
        None,
    ),
    ("15", "Whether salient features are enclosed", None),
    ("16", "Whether commanded area plan / index plan enclosed", None),
    (
        "17",
        "Whether the approved Designs / Drawings / Hydraulic particulars / Cross sections are enclosed",
        None,
    ),
    (
        "18",
        "Whether C.C. lining thickness, grade of concrete and CNS layer thickness proposed are with reference to the relevant IS codes",
        None,
    ),
    ("19", "Whether the data enclosed is based on the current SSR with year", "ssr"),
    ("20", "Whether latest cement / steel rates are adopted", None),
    ("21", "Whether the quotations for non SSR items are enclosed", "quotations"),
    ("22", "Whether the lead statement with certificates is enclosed", "lead"),
    ("23", "Whether borrow area / quarry maps are enclosed", None),
    ("24", "Whether the amount of labour component and certificate of L.A. & L.I. furnished", None),
    ("25", "Whether geological and foundation investigations carried out", None),
    ("26", "Whether the extent of L.A. / forest lands is furnished", None),
    (
        "27",
        "Are the rates of L.A. adopted based on the certificate issued by the Revenue Authorities",
        None,
    ),
    (
        "28",
        "Whether provision for compensatory afforestation and NPV is provided in consultation with Forest Dept.",
        None,
    ),
    (
        "29",
        "Whether the cost for CM & CD works is based on cost curves updated with current SSR",
        None,
    ),
    (
        "30",
        "Whether provision for distributaries and field channels is based on the estimate prepared for a model block covering 10% of the command",
        None,
    ),
    ("31", "Whether provisions made for dewatering and other LS provisions are reasonable", None),
    (
        "32",
        "Whether the provision for formation of road, NH crossing, railway crossing and other road crossings is based on their specification and standards",
        None,
    ),
    (
        "33",
        "Whether the site was inspected by the competent authority before submitting the estimate, and the estimate prepared keeping in view the observations",
        None,
    ),
    ("33 (i)", "Up to Rs.10.00 Lakhs - EE", "band_ee"),
    ("33 (ii)", "Rs.10.00 Lakhs to Rs.50.00 Lakhs - SE", "band_se"),
    ("33 (iii)", "Above Rs.50.00 Lakhs - ENC / CE", "band_ce"),
    ("34", "Are the detailed estimates / Data checked in SE's office", None),
    ("35", "Are the provisions examined / abstract estimate checked in CE's office", None),
    ("36", "Whether the check slip for administrative approval is enclosed", None),
    ("37", "Whether all officers up to CE signed", None),
    ("38", "Construction programme of the Project / Scheme / Work", None),
    ("39", "Q.C. check authority proposed for this work", None),
]

DEFAULT_CERTIFICATES = [
    "Certified that the site of the work has been inspected by me and the estimate has been prepared correctly as per the actual site conditions and requirements.",
    "Certified that the quantities in the detailed estimate are correct and as per the drawings / designs enclosed.",
    "Certified that the rates adopted in this estimate are strictly as per the Common Schedule of Rates (SSR 2026-27) and the Standard Data approved by the Board of Chief Engineers, and that the latest cement and steel rates are adopted.",
    "Certified that seigniorage charges are provided as per the G.O.s in force, and DMF, SMET and permit fee at the prescribed percentages.",
    "Certified that the sources adopted for lead are the nearest available sources, that sufficient quantity of approved materials is available at the quarries, and that the leads are taken along the shortest route from the quarry to the work spot.",
    "Certified that no departmental material is proposed to be issued.",
    "Certified that the work proposed in this estimate is not covered in any other sanctioned estimate or ongoing contract, and there is no duplication of provisions.",
]

COVER_FIELDS = (
    "name_of_work",
    "department",
    "circle",
    "division",
    "sub_division",
    "district",
    "mandal",
    "village",
    "project",
)
DEFAULT_DOCKET: dict[str, Any] = {
    "cover": {
        "department": "Irrigation & CAD Department",
        **{f: "" for f in COVER_FIELDS if f != "department"},
    },
    "signatories": [
        "Assistant Executive Engineer",
        "Deputy Executive Engineer",
        "Executive Engineer",
    ],
    "check_slip": {},
    "certificates": DEFAULT_CERTIFICATES,
    "quotations": {},
}


def docket_config(config: dict[str, Any]) -> dict[str, Any]:
    stored = config.get("docket") or {}
    return {
        "cover": {**DEFAULT_DOCKET["cover"], **stored.get("cover", {})},
        "signatories": stored.get("signatories") or DEFAULT_DOCKET["signatories"],
        "check_slip": dict(stored.get("check_slip", {})),
        "certificates": stored.get("certificates") or DEFAULT_DOCKET["certificates"],
        "quotations": dict(stored.get("quotations", {})),
    }


@dataclass(frozen=True)
class Docket:
    scope: es.VersionScope
    config: dict[str, Any]
    amount: Decimal
    check_slip: list[dict[str, Any]]
    quotations: list[dict[str, Any]]


def build(db: Session, scope: es.VersionScope) -> Docket:
    cfg = docket_config(icad.config_of(scope.version))
    ga = icad.general_abstract(db, scope)
    amount = ga.result.total.quantize(Decimal("0.01"))
    cover = cfg["cover"]
    lakhs = amount / LAKH
    non_sor = [(sl, item) for sl, item, _ in ga.items if item.rate_source_type != "rate_database"]
    location = ", ".join(x for x in (cover["village"], cover["mandal"], cover["district"]) if x)
    auto = {
        "name_of_work": cover["name_of_work"] or scope.estimate.title,
        "amount": format_inr(amount),
        "location": location,
        "ssr": SSR_YEAR,
        "quotations": "YES" if non_sor else "NA",
        "lead": "YES" if icad.lead_entries(db, scope.version.id) else "NA",
        "band_ee": "YES" if lakhs <= 10 else "--",
        "band_se": "YES" if 10 < lakhs <= 50 else "--",
        "band_ce": "YES" if lakhs > 50 else "--",
    }
    slip = []
    for no, question, key in CHECK_SLIP:
        typed = cfg["check_slip"].get(no)
        slip.append(
            {
                "no": no,
                "question": question,
                "answer": typed if typed not in (None, "") else (auto.get(key, "") if key else ""),
                "auto": typed in (None, "") and key is not None,
            }
        )
    quotations = []
    for sl, item in non_sor:
        q = cfg["quotations"].get(str(item.line_key), {})
        quotations.append(
            {
                "item_id": str(item.id),
                "line_key": str(item.line_key),
                "sl_no": sl,
                "description": item.description,
                "unit": item.unit_code,
                "quantity": item.quantity,
                "rate": item.rate,
                "supplier": q.get("supplier", ""),
                "reference": q.get("reference", ""),
                "note": q.get("note", ""),
            }
        )
    return Docket(scope, cfg, amount, slip, quotations)


def update(db: Session, ctx: AuthContext, version_id: uuid.UUID, data: dict[str, Any]) -> None:
    scope = es._scope_for(db, ctx, version_id)
    cfg = docket_config(icad.config_of(scope.version))
    if "cover" in data:
        unknown = set(data["cover"]) - set(COVER_FIELDS)
        if unknown:
            raise AppError(
                "VALIDATION_ERROR", f"Unknown cover field(s): {', '.join(sorted(unknown))}."
            )
        cfg["cover"] = {
            **cfg["cover"],
            **{k: str(v or "").strip()[:1000] for k, v in data["cover"].items()},
        }
    if "signatories" in data:
        cfg["signatories"] = [str(s).strip()[:120] for s in data["signatories"] if str(s).strip()][
            :6
        ]
    if "check_slip" in data:
        valid = {no for no, _, _ in CHECK_SLIP}
        for no, answer in data["check_slip"].items():
            if no not in valid:
                raise AppError("VALIDATION_ERROR", f"Check slip has no point '{no}'.")
            cfg["check_slip"][no] = str(answer or "").strip()[:1000]
    if "certificates" in data:
        certs = [str(c).strip()[:2000] for c in data["certificates"] if str(c).strip()]
        if not certs:
            raise AppError("VALIDATION_ERROR", "Keep at least one certificate.")
        cfg["certificates"] = certs[:30]
    if "quotations" in data:
        for key, q in data["quotations"].items():
            cfg["quotations"][str(key)] = {
                k: str(q.get(k) or "").strip()[:500] for k in ("supplier", "reference", "note")
            }
    icad.update_config(db, ctx, version_id, {"docket": cfg})


def words(amount: Decimal) -> str:
    return amount_in_words(amount) if amount >= 0 else ""
