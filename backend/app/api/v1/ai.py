from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DB, Auth
from app.api.envelope import Envelope, ok
from app.models import AiGeneration
from app.services import ai_extraction as service

router = APIRouter(prefix="/ai", tags=["ai"])

PROVIDER_LABELS = {
    "rules": "Rules-based parser (no AI key configured)",
    "mock": "Test provider",
    "anthropic": "AI (Claude)",
}
DISCLAIMER = (
    "Values below were read from your description and must be checked. Quantities are "
    "calculated by the engine only after you confirm. No rates are suggested."
)

Number = str | int | float | None


class SuggestedDefaultOut(BaseModel):
    value: str | None
    unit: str | None
    reason: str


class ExtractedParamOut(BaseModel):
    name: str
    label: str
    dimension: str
    required: bool
    value: str | None
    unit: str | None
    source_text: str | None
    status: str  # ok | needs_confirmation | missing | template_default
    note: str | None
    question: str | None
    suggested_default: SuggestedDefaultOut | None


class PreviewOut(BaseModel):
    value: str
    unit: str
    unit_display: str
    substituted: str


class ComponentOut(BaseModel):
    key: str
    component_name: str
    template_id: str
    template_name: str
    output_unit: str
    output_unit_display: str
    parameters: list[ExtractedParamOut]
    preview: PreviewOut | None


class CustomItemOut(BaseModel):
    key: str
    description: str
    source_text: str | None


class MissingOut(BaseModel):
    component_key: str | None
    component_name: str
    parameter: str
    label: str
    question: str | None


class ResultOut(BaseModel):
    estimate_id: uuid.UUID
    version_id: uuid.UUID
    items_created: int
    parameters_created: int


class ExtractionOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    provider: str
    provider_label: str
    model: str
    served_from_cache: bool
    input_text: str
    project_type: str | None
    components: list[ComponentOut]
    custom_items: list[CustomItemOut]
    missing_information: list[MissingOut]
    assumptions: list[str]
    warnings: list[str]
    result: ResultOut | None
    disclaimer: str
    created_at: datetime


class ExtractionIn(BaseModel):
    project_id: uuid.UUID
    text: str = Field(min_length=1, max_length=20000)


class ParamChoice(BaseModel):
    value: Number = None
    unit: str | None = Field(default=None, max_length=40)
    accept_default: bool = False


class ComponentChoice(BaseModel):
    key: str = Field(max_length=10)
    include: bool = True
    parameters: dict[str, ParamChoice] = Field(default_factory=dict, max_length=20)


class CustomChoice(BaseModel):
    key: str = Field(max_length=10)
    include: bool = True


class ConfirmIn(BaseModel):
    estimate_id: uuid.UUID | None = None
    new_estimate_title: str | None = Field(default=None, max_length=200)
    section_title: str | None = Field(default=None, max_length=200)
    components: list[ComponentChoice] = Field(default_factory=list, max_length=30)
    custom_items: list[CustomChoice] = Field(default_factory=list, max_length=30)


class ConfirmOut(BaseModel):
    project_id: uuid.UUID
    estimate_id: uuid.UUID
    version_id: uuid.UUID
    items_created: int
    parameters_created: int


def extraction_out(row: AiGeneration) -> ExtractionOut:
    data: dict[str, Any] = row.validated_output or {}
    provider = data.get("provider", "rules")
    assert row.project_id is not None
    return ExtractionOut(
        id=row.id,
        project_id=row.project_id,
        status=row.status,
        provider=provider,
        provider_label=PROVIDER_LABELS.get(provider, provider),
        model=row.model,
        served_from_cache=row.served_from_cache,
        input_text=row.input_text or "",
        project_type=data.get("project_type"),
        components=[ComponentOut.model_validate(c) for c in data.get("components", [])],
        custom_items=[CustomItemOut.model_validate(c) for c in data.get("custom_items", [])],
        missing_information=[
            MissingOut.model_validate(m) for m in data.get("missing_information", [])
        ],
        assumptions=data.get("assumptions", []),
        warnings=data.get("warnings", []),
        result=ResultOut.model_validate(data["result"]) if data.get("result") else None,
        disclaimer=DISCLAIMER,
        created_at=row.created_at,
    )


@router.post("/extractions", response_model=Envelope[ExtractionOut], status_code=201)
def create_extraction(body: ExtractionIn, auth: Auth, db: DB) -> Envelope[ExtractionOut]:
    row = service.create(db, auth, project_id=body.project_id, text=body.text)
    return ok(extraction_out(row))


@router.get("/extractions/{extraction_id}", response_model=Envelope[ExtractionOut])
def get_extraction(extraction_id: uuid.UUID, auth: Auth, db: DB) -> Envelope[ExtractionOut]:
    return ok(extraction_out(service.get(db, auth, extraction_id)))


@router.post("/extractions/{extraction_id}/confirm", response_model=Envelope[ConfirmOut])
def confirm_extraction(
    extraction_id: uuid.UUID, body: ConfirmIn, auth: Auth, db: DB
) -> Envelope[ConfirmOut]:
    payload = body.model_dump(mode="json")
    result = service.confirm(db, auth, extraction_id, payload)
    return ok(
        ConfirmOut(
            project_id=result.project_id,
            estimate_id=result.estimate_id,
            version_id=result.version_id,
            items_created=result.items_created,
            parameters_created=result.parameters_created,
        )
    )
