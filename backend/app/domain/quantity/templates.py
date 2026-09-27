"""Built-in formula templates.

Templates are versioned: a published (id, version) never changes, so a stored calculation
can always be reproduced. To change a formula, add a new version.

Template defaults are limited to *neutral* values (one instance, no deduction). They never
stand in for an engineering dimension; a missing dimension blocks the calculation.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.units.registry import Dimension

L, A, C = Dimension.LENGTH, Dimension.AREA, Dimension.COUNT


@dataclass(frozen=True)
class TemplateParameter:
    name: str
    label: str
    dimension: Dimension
    default: str | None = None  # neutral default only; None = required
    description: str = ""

    @property
    def required(self) -> bool:
        return self.default is None


@dataclass(frozen=True)
class CalculationTemplate:
    id: str
    version: int
    name: str
    category: str
    expression: str
    parameters: tuple[TemplateParameter, ...]
    output_unit: str
    description: str = ""

    def parameter(self, name: str) -> TemplateParameter | None:
        return next((p for p in self.parameters if p.name == name), None)


def _count(name: str = "N", label: str = "Number of identical items") -> TemplateParameter:
    return TemplateParameter(name, label, C, default="1")


BUILTIN_TEMPLATES: tuple[CalculationTemplate, ...] = (
    CalculationTemplate(
        "volume_lbh",
        1,
        "Volume (L × B × H)",
        "generic",
        "L * B * H * N",
        (
            TemplateParameter("L", "Length", L),
            TemplateParameter("B", "Breadth", L),
            TemplateParameter("H", "Depth / height", L),
            _count(),
        ),
        "cum",
        "General volume, e.g. concrete, masonry, earthwork.",
    ),
    CalculationTemplate(
        "area_lb",
        1,
        "Area (L × B)",
        "generic",
        "L * B * N",
        (TemplateParameter("L", "Length", L), TemplateParameter("B", "Breadth", L), _count()),
        "sqm",
        "General area, e.g. flooring, formwork, surface dressing.",
    ),
    CalculationTemplate(
        "road_layer",
        1,
        "Road layer",
        "road",
        "length * width * thickness",
        (
            TemplateParameter("length", "Road length", L),
            TemplateParameter("width", "Layer width", L),
            TemplateParameter("thickness", "Layer thickness", L),
        ),
        "cum",
        "Any pavement layer: CC, GSB, WMM, WBM, BT.",
    ),
    CalculationTemplate(
        "road_shoulder",
        1,
        "Road shoulders (left + right)",
        "road",
        "length * (width_left + width_right) * thickness",
        (
            TemplateParameter("length", "Road length", L),
            TemplateParameter("width_left", "Left shoulder width", L),
            TemplateParameter("width_right", "Right shoulder width", L),
            TemplateParameter("thickness", "Shoulder layer thickness", L),
        ),
        "cum",
        "Enter 0 for a side without a shoulder.",
    ),
    CalculationTemplate(
        "wall_masonry",
        1,
        "Wall masonry (less openings)",
        "building",
        "(L * H * N - openings_area) * T",
        (
            TemplateParameter("L", "Wall length", L),
            TemplateParameter("H", "Wall height", L),
            TemplateParameter("T", "Wall thickness", L),
            _count("N", "Number of identical walls"),
            TemplateParameter(
                "openings_area", "Total area of doors, windows and openings", A, default="0"
            ),
        ),
        "cum",
        "Brickwork or blockwork volume after deducting openings.",
    ),
    CalculationTemplate(
        "plaster_area",
        1,
        "Plastering (less openings)",
        "building",
        "L * H * faces - openings_area",
        (
            TemplateParameter("L", "Wall length", L),
            TemplateParameter("H", "Wall height", L),
            TemplateParameter("faces", "Number of faces plastered", C),
            TemplateParameter("openings_area", "Total area of openings deducted", A, default="0"),
        ),
        "sqm",
        "",
    ),
    CalculationTemplate(
        "excavation_trench",
        1,
        "Trench excavation",
        "generic",
        "L * B * D * N",
        (
            TemplateParameter("L", "Trench length", L),
            TemplateParameter("B", "Trench width", L),
            TemplateParameter("D", "Trench depth", L),
            _count(),
        ),
        "cum",
        "",
    ),
    CalculationTemplate(
        "steel_weight",
        1,
        "Steel weight",
        "generic",
        "length * unit_weight * N",
        (
            TemplateParameter("length", "Length of one bar / section", L),
            TemplateParameter("unit_weight", "Unit weight", Dimension.LINEAR_DENSITY),
            _count("N", "Number of bars / sections"),
        ),
        "kg",
        "Unit weight is entered by the user (e.g. from the section table used).",
    ),
    CalculationTemplate(
        "pipe_volume",
        1,
        "Circular section volume",
        "generic",
        "pi * D^2 / 4 * L",
        (TemplateParameter("D", "Internal diameter", L), TemplateParameter("L", "Length", L)),
        "cum",
        "Volume of a circular section, e.g. pipe bore or circular pit.",
    ),
    CalculationTemplate(
        "kerb_length",
        1,
        "Kerb length",
        "road",
        "length * sides",
        (
            TemplateParameter("length", "Road length", L),
            TemplateParameter("sides", "Number of sides with kerb", C),
        ),
        "rmt",
        "",
    ),
)
