"""The structured result every extraction provider must return.

The same Pydantic models are used as the JSON schema for the LLM's structured output, so a
provider cannot return anything else. Unknown keys (for example a quantity or a rate the
model decided to add) are ignored.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProjectType = Literal[
    "building", "road", "drain", "culvert", "bridge", "irrigation", "canal", "tank",
    "lift_irrigation", "water_supply", "sewerage", "electrical", "other",
]  # fmt: skip


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SuggestedDefault(_Model):
    value: float
    unit: str | None = None
    reason: str = Field(max_length=300)


class ExtractedParameter(_Model):
    name: str = Field(max_length=64)
    value: float | None = None
    unit: str | None = Field(default=None, max_length=40)
    source_text: str | None = Field(default=None, max_length=300)
    suggested_default: SuggestedDefault | None = None


class ExtractedComponent(_Model):
    component_name: str = Field(max_length=200)
    template_id: str = Field(max_length=64)
    parameters: list[ExtractedParameter] = Field(default_factory=list, max_length=20)


class CustomItem(_Model):
    description: str = Field(max_length=300)
    source_text: str | None = Field(default=None, max_length=300)


class MissingInformation(_Model):
    component_name: str = Field(max_length=200)
    parameter: str = Field(max_length=64)
    question: str = Field(max_length=300)


class ExtractionResult(_Model):
    project_type: ProjectType | None = None
    components: list[ExtractedComponent] = Field(default_factory=list, max_length=30)
    custom_items: list[CustomItem] = Field(default_factory=list, max_length=30)
    missing_information: list[MissingInformation] = Field(default_factory=list, max_length=60)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
