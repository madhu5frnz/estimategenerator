"""Deterministic, rules-based extractor (the default when no AI key is configured).

It recognises common Indian civil-works phrasing in English, Telugu and Hindi, for example
"500 m long CC road, 5.5 m wide and 150 mm thick with 100 mm GSB" or
"500 మీటర్ల పొడవు, 5.5 మీటర్ల వెడల్పుతో 150 mm మందం CC రోడ్డు".

Guarantees (the same ones the LLM is held to):
* A value is only ever taken from a number written in the text; ``source_text`` is the
  exact words it came from.
* Anything it cannot place becomes missing information (a question for the user), or a
  suggested default the user must explicitly accept. Nothing is filled in silently.
* It never produces quantities or rates.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.ai.schemas import (
    CustomItem,
    ExtractedComponent,
    ExtractedParameter,
    ExtractionResult,
    MissingInformation,
    SuggestedDefault,
)
from app.ai.text import normalise

RULES_VERSION = "rules-v1"

# ----------------------------------------------------------------- lexicons
UNIT_WORDS: dict[str, tuple[str, ...]] = {
    "km": ("kilometres", "kilometers", "kilometre", "kilometer", "kms", "km",
           "కిలోమీటర్లు", "కిలోమీటర్ల", "కిలోమీటర్", "కి.మీ", "किलोमीटर", "कि.मी", "किमी"),
    "mm": ("millimetres", "millimeters", "millimetre", "millimeter", "mm",
           "మిల్లీమీటర్లు", "మిల్లీమీటర్ల", "మి.మీ", "मिलीमीटर", "मि.मी", "मिमी"),
    "cm": ("centimetres", "centimeters", "centimetre", "centimeter", "cm",
           "సెంటీమీటర్లు", "సెం.మీ", "सेंटीमीटर", "सेमी"),
    "m": ("metres", "meters", "metre", "meter", "mtrs", "mtr", "mts", "m",
          "మీటర్లు", "మీటర్ల", "మీటరు", "మీటర్", "మీ", "मीटर", "मी"),
    "ft": ("feet", "foot", "ft"),
}  # fmt: skip

DIMENSION_STEMS: dict[str, tuple[str, ...]] = {
    "length": ("long", "length", "పొడవు", "लंब", "लम्ब"),
    "width": ("wide", "width", "breadth", "వెడల్పు", "चौड़", "चौड"),
    "thickness": ("thick", "మందం", "मोट"),
    "height": ("high", "height", "tall", "ఎత్తు", "ऊंच", "ऊँच"),
    "depth": ("deep", "depth", "లోతు", "गहर"),
}
FILLER = {"of", "is", "=", ":", "about", "approx", "approximately", "with", "a", "total"}


@dataclass(frozen=True)
class ComponentKind:
    key: str
    name: str
    pattern: re.Pattern[str]
    template: str | None  # None = custom item (no quantity)
    road_layer: bool = False
    question: str | None = None  # for custom items


def _p(expr: str) -> re.Pattern[str]:
    return re.compile(expr, re.IGNORECASE)


COMPONENTS: tuple[ComponentKind, ...] = (
    ComponentKind("cc", "CC pavement", _p(r"(?<!\w)(?:p\.?)?c\.?c(?!\w)|cement concrete|rigid pavement|concrete road|సీసీ|सीसी"), "road_layer", True),
    ComponentKind("gsb", "Granular sub-base (GSB)", _p(r"(?<!\w)g\.?s\.?b(?!\w)|granular sub[- ]?base"), "road_layer", True),
    ComponentKind("wmm", "Wet mix macadam (WMM)", _p(r"(?<!\w)w\.?m\.?m(?!\w)|wet mix macadam"), "road_layer", True),
    ComponentKind("wbm", "Water bound macadam (WBM)", _p(r"(?<!\w)w\.?b\.?m(?!\w)|water bound macadam"), "road_layer", True),
    ComponentKind("dbm", "Dense bituminous macadam (DBM)", _p(r"(?<!\w)d\.?b\.?m(?!\w)|dense bituminous"), "road_layer", True),
    ComponentKind("bt", "Bituminous surface (BT)", _p(r"(?<!\w)b\.?t(?!\w)|bituminous (?:surface|road|carpet|layer)|bitumen"), "road_layer", True),
    ComponentKind("kerb", "Kerb", _p(r"(?<!\w)(?:kerb|curb)(?:s|ing| stones?)?(?!\w)"), "kerb_length"),
    ComponentKind("wall", "Masonry wall", _p(r"compound wall|retaining wall|brick ?work|block ?work|brick wall|masonry|(?<!\w)wall(?!\w)"), "wall_masonry"),
    ComponentKind("plaster", "Plastering", _p(r"plaster(?:ing)?"), "plaster_area"),
    ComponentKind("earthwork", "Earthwork / excavation", _p(r"earth ?work|excavation"), None,
                  question="Dimensions for earthwork were not given; add the quantity or measurement lines."),
    ComponentKind("shoulder", "Shoulders", _p(r"shoulders?"), None,
                  question="Enter left and right shoulder widths and thickness to measure shoulders."),
    ComponentKind("drain", "Drain", _p(r"(?<!\w)drains?(?!\w)|side drain"), None,
                  question="Drain size and type were not given; add the drain items manually."),
)  # fmt: skip

ROAD_WORDS = _p(r"(?<!\w)road(?:s)?(?!\w)|pavement|carriageway|రోడ్డు|రహదారి|सड़क")
BOTH_SIDES = _p(r"both sides|on either side|two sides|రెండు వైపులా|दोनों तरफ")
ONE_SIDE = _p(r"one side|single side|ఒక వైపు|एक तरफ")

_ALL_UNITS = sorted(
    ((word, code) for code, words in UNIT_WORDS.items() for word in words),
    key=lambda pair: -len(pair[0]),
)
_UNIT_LOOKUP = {word.lower(): code for word, code in _ALL_UNITS}
MEASURE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*("
    + "|".join(re.escape(w) for w, _ in _ALL_UNITS)
    + r")(?![\wఀ-౿ऀ-ॿ])",
    re.IGNORECASE,
)
TOKEN = re.compile(r"[^\s,;.()]+")


@dataclass
class Measure:
    start: int
    end: int
    value: float
    unit: str
    dimension: str | None = None
    span: tuple[int, int] = (0, 0)  # quoted source span, includes the keyword
    used: bool = False
    chain: tuple[int, int, int] | None = None  # (position, chain length, chain id)


@dataclass
class Found:
    kind: ComponentKind
    start: int
    end: int
    params: dict[str, ExtractedParameter] = field(default_factory=dict)


# Compared against NFC-normalised input, so normalise the stems the same way
# (e.g. Devanagari ड़ has two encodings).
_STEMS = {
    dimension: tuple(unicodedata.normalize("NFC", s).lower() for s in stems)
    for dimension, stems in DIMENSION_STEMS.items()
}


def _stem_dimension(token: str) -> str | None:
    word = token.lower()
    for dimension, stems in _STEMS.items():
        if any(word.startswith(stem) for stem in stems):
            return dimension
    return None


def _measures(text: str) -> list[Measure]:
    found: list[Measure] = []
    for m in MEASURE.finditer(text):
        value = float(m.group(1).replace(",", ""))
        unit = _UNIT_LOOKUP[m.group(2).lower()]
        measure = Measure(m.start(), m.end(), value, unit, span=(m.start(), m.end()))
        # Keyword after: "500 m long", "150 mm మందం", "5.5 मीटर चौड़ी"
        after = TOKEN.search(text, m.end())
        if after and not text[m.end() : after.start()].strip() and after.start() - m.end() <= 2:
            dimension = _stem_dimension(after.group())
            if dimension:
                measure.dimension, measure.span = dimension, (m.start(), after.end())
        # Keyword before: "length of 500 m", "thickness: 150mm"
        if measure.dimension is None:
            # Never reach back past the previous measurement's own words.
            floor = max([0, m.start() - 40, *(f.span[1] for f in found)])
            before = [t for t in TOKEN.finditer(text, floor, m.start())]
            for token in reversed(before[-4:]):
                if token.group().lower() in FILLER:
                    continue
                dimension = _stem_dimension(token.group())
                if dimension:
                    measure.dimension, measure.span = dimension, (token.start(), m.end())
                break
        found.append(measure)
    return found


TIMES = re.compile(r"^\s*[x×*X]\s*$")


def _mark_chains(text: str, measures: list[Measure]) -> list[list[Measure]]:
    """Find "300 m x 3.75 m x 0.15 m" style chains of unlabelled measurements."""
    chains: list[list[Measure]] = []
    current: list[Measure] = []
    for m in measures:
        if current and TIMES.match(text[current[-1].end : m.start]):
            current.append(m)
        else:
            if len(current) >= 2:
                chains.append(current)
            current = [m]
    if len(current) >= 2:
        chains.append(current)
    chains = [c for c in chains if len(c) <= 3 and all(m.dimension is None for m in c)]
    for chain_id, chain in enumerate(chains):
        for position, m in enumerate(chain):
            m.chain = (position, len(chain), chain_id)
            m.span = (chain[0].start, chain[-1].end)
    return chains


def _components(text: str) -> list[Found]:
    found: list[Found] = []
    for kind in COMPONENTS:
        match = kind.pattern.search(text)
        if match is None:
            continue
        # "masonry wall" / "compound wall" is one wall, not wall + masonry.
        if any(
            f.start <= match.start() < f.end or match.start() <= f.start < match.end()
            for f in found
        ):
            continue
        found.append(Found(kind, match.start(), match.end()))
    return sorted(found, key=lambda f: f.start)


def _param(name: str, m: Measure | None, text: str) -> ExtractedParameter:
    if m is None:
        return ExtractedParameter(name=name)
    m.used = True
    return ExtractedParameter(
        name=name, value=m.value, unit=m.unit, source_text=text[m.span[0] : m.span[1]]
    )


def _gap(a_end: int, b_start: int, text: str) -> int:
    """Characters between two spans, ignoring spaces."""
    return len(text[a_end:b_start].strip()) if b_start >= a_end else 10_000


def _distance(m: Measure, f: Found) -> int:
    return min(abs(m.start - f.end), abs(f.start - m.end))


def extract(raw: str) -> ExtractionResult:
    text = normalise(raw)
    measures = _measures(text)
    comps = _components(text)
    layers = [c for c in comps if c.kind.road_layer]
    missing: list[MissingInformation] = []
    assumptions: list[str] = []
    custom: list[CustomItem] = []

    # "L x B x D" chains: road layers read length × width × thickness; walls read
    # length × thickness × height (the L, B, D/H order of a detailed estimate).
    has_wall = any(c.kind.key == "wall" for c in comps)
    for chain in _mark_chains(text, measures):
        order = (
            ("length", "width", "thickness") if layers
            else ("length", "thickness", "height") if has_wall
            else None
        )  # fmt: skip
        if order is None:
            continue
        for m in chain:
            assert m.chain is not None
            m.dimension = order[m.chain[0]]
        named = " × ".join(order[: len(chain)])
        assumptions.append(f"'{text[chain[0].start : chain[-1].end]}' read as {named}.")

    # ---------------------------------------------------------------- road
    road_length = next((m for m in measures if m.dimension == "length"), None)
    if road_length is None:
        # "500 m CC road", "1 km road": an unlabelled length right before the road words.
        targets = [(c.start, c.end) for c in layers] + [
            (r.start(), r.end()) for r in ROAD_WORDS.finditer(text)
        ]
        for m in measures:
            if (
                m.dimension is None
                and m.unit in ("m", "km", "ft")
                and any(_gap(m.end, start, text) <= 3 for start, _ in targets)
            ):
                m.dimension = "length"
                road_length = m
                break

    if layers:
        if any(c.kind.key == "cc" for c in layers):
            assumptions.append("'CC' interpreted as cement concrete pavement.")
        width = next((m for m in measures if m.dimension == "width"), None)
        primary = min(layers, key=lambda c: _distance(width, c)) if width else None

        # Thickness: first the layers written right next to a thickness ("100 mm GSB",
        # "GSB 100 mm thick"), then the nearest remaining layer.
        thick_of: dict[int, Measure] = {}
        candidates = [
            m for m in measures
            if m.dimension == "thickness" or (m.dimension is None and m.unit in ("mm", "cm"))
        ]  # fmt: skip
        for m in candidates:
            for i, layer in enumerate(layers):
                if i in thick_of:
                    continue
                if _gap(m.span[1], layer.start, text) <= 2:  # "100 mm GSB"
                    if m.dimension is None:
                        m.span = (m.start, layer.end)
                elif _gap(layer.end, m.start, text) <= 2:  # "GSB 100 mm"
                    if m.dimension is None:
                        m.span = (layer.start, m.end)
                else:
                    continue
                thick_of[i] = m
                m.dimension = "thickness"
                break
        for m in candidates:
            if m in thick_of.values() or m.dimension != "thickness":
                continue
            free = [(i, layer) for i, layer in enumerate(layers) if i not in thick_of]
            if free:
                i, _ = min(free, key=lambda pair: _distance(m, pair[1]))
                thick_of[i] = m

        for i, layer in enumerate(layers):
            name = layer.kind.name
            layer.params["length"] = _param("length", road_length, text)
            if road_length is None:
                missing.append(MissingInformation(component_name=name, parameter="length",
                                                  question="Please enter the road length."))  # fmt: skip
            if layer is primary:
                layer.params["width"] = _param("width", width, text)
            else:
                layer.params["width"] = ExtractedParameter(
                    name="width",
                    suggested_default=(
                        SuggestedDefault(
                            value=width.value,
                            unit=width.unit,
                            reason="Same as the carriageway width given; confirm it "
                            "does not extend under the shoulders.",
                        )
                        if width
                        else None
                    ),
                )
                missing.append(MissingInformation(component_name=name, parameter="width",
                                                  question=f"Please enter the {name} width."))  # fmt: skip
            layer.params["thickness"] = _param("thickness", thick_of.get(i), text)
            if i not in thick_of:
                missing.append(MissingInformation(component_name=name, parameter="thickness",
                                                  question=f"Please enter the {name} thickness."))  # fmt: skip
        if road_length and len(layers) > 1:
            assumptions.append("The road length applies to every pavement layer.")
    elif ROAD_WORDS.search(text) and not any(c.kind.template == "wall_masonry" for c in comps):
        missing.append(MissingInformation(
            component_name="Road", parameter="pavement",
            question="Which pavement layers are needed (e.g. CC, GSB, WMM, BT) and how thick?",
        ))  # fmt: skip

    # ------------------------------------------------------ other templates
    sides_match = BOTH_SIDES.search(text) or ONE_SIDE.search(text)
    sides = None
    if sides_match:
        sides = ExtractedParameter(
            name="sides", value=2 if BOTH_SIDES.search(sides_match.group()) else 1,
            source_text=sides_match.group(),
        )  # fmt: skip

    for comp in comps:
        kind = comp.kind
        if kind.key == "kerb":
            comp.params["length"] = ExtractedParameter(
                name="length",
                suggested_default=(
                    SuggestedDefault(
                        value=road_length.value,
                        unit=road_length.unit,
                        reason="Kerb along the full road length.",
                    )
                    if road_length
                    else None
                ),
            )
            missing.append(MissingInformation(component_name=kind.name, parameter="length",
                                              question="Please enter the kerb length."))  # fmt: skip
            comp.params["sides"] = sides or ExtractedParameter(name="sides")
            if sides is None:
                missing.append(MissingInformation(component_name=kind.name, parameter="sides",
                                                  question="Kerb on one side or both sides?"))  # fmt: skip
        elif kind.key == "wall":
            for name, dimension in (("L", "length"), ("H", "height"), ("T", "thickness")):
                wall_m: Measure | None
                wall_m = next(
                    (x for x in measures if x.dimension == dimension and not x.used), None
                )
                if wall_m is None and dimension == "thickness":
                    wall_m = next(
                        (
                            x
                            for x in measures
                            if x.dimension is None and x.unit in ("mm", "cm") and not x.used
                        ),
                        None,
                    )
                comp.params[name] = _param(name, wall_m, text)
                if wall_m is None:
                    label = {"L": "length", "H": "height", "T": "thickness"}[name]
                    missing.append(MissingInformation(component_name=kind.name, parameter=name,
                                                      question=f"Please enter the wall {label}."))  # fmt: skip
        elif kind.key == "plaster":
            wall = next((c for c in comps if c.kind.key == "wall"), None)
            for name in ("L", "H"):
                source = wall.params.get(name) if wall else None
                if source is not None and source.value is not None:
                    comp.params[name] = source.model_copy()
                else:
                    comp.params[name] = ExtractedParameter(name=name)
                    missing.append(MissingInformation(component_name=kind.name, parameter=name,
                                                      question=f"Please enter the plastered {'length' if name == 'L' else 'height'}."))  # fmt: skip
            if sides is not None:
                comp.params["faces"] = ExtractedParameter(
                    name="faces", value=sides.value, source_text=sides.source_text
                )
            else:
                comp.params["faces"] = ExtractedParameter(name="faces")
                missing.append(MissingInformation(component_name=kind.name, parameter="faces",
                                                  question="Plaster on one face or both faces?"))  # fmt: skip
        elif kind.template is None:
            custom.append(
                CustomItem(description=kind.name, source_text=text[comp.start : comp.end])
            )
            if kind.question:
                missing.append(MissingInformation(component_name=kind.name, parameter="details",
                                                  question=kind.question))  # fmt: skip

    components = [
        ExtractedComponent(
            component_name=c.kind.name,
            template_id=c.kind.template or "",
            parameters=list(c.params.values()),
        )
        for c in comps
        if c.kind.template
    ]
    project_type = "road" if layers or ROAD_WORDS.search(text) else (
        "building" if any(c.kind.key in ("wall", "plaster") for c in comps) else None
    )  # fmt: skip
    if not components and not custom:
        missing.append(MissingInformation(
            component_name="Work", parameter="components",
            question="No work items were recognised. Describe the items (e.g. 'CC road 500 m long, "
                     "5.5 m wide, 150 mm thick') or add them on the BOQ page.",
        ))  # fmt: skip
    for m in measures:
        if not m.used:
            assumptions.append(
                f"'{text[m.span[0] : m.span[1]]}' was not assigned to any item; add it manually if needed."
            )
    return ExtractionResult(
        project_type=project_type, components=components, custom_items=custom,
        missing_information=missing, assumptions=assumptions,
    )  # fmt: skip
