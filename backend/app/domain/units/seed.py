"""Built-in unit and conversion data.

This mirrors the seed rows in ``migrations/sql/0001_initial_schema.sql`` (a test keeps the
two in sync). At runtime the service layer builds the registry from the database tables so
administrators can extend units; this module is the default for tests and for a fresh DB.
Only conversions *to the canonical unit* are listed; everything else is derived.
"""

from __future__ import annotations

from app.domain.units.registry import Conversion, Dimension, Unit

UNITS: tuple[Unit, ...] = (
    Unit("mm", "mm", Dimension.LENGTH, False, 0, ("millimetre", "millimeter")),
    Unit("cm", "cm", Dimension.LENGTH, False, 1, ("centimetre", "centimeter")),
    Unit("m", "m", Dimension.LENGTH, True, 3, ("metre", "meter", "mtr", "mts")),
    Unit("km", "km", Dimension.LENGTH, False, 3, ("kilometre", "kilometer", "kms")),
    Unit("ft", "ft", Dimension.LENGTH, False, 2, ("feet", "foot")),
    Unit("rmt", "Rmt", Dimension.LENGTH, False, 2, ("running metre", "r.m", "rmt")),
    Unit("sqm", "Sq.m", Dimension.AREA, True, 2, ("sq.m", "m2", "square metre", "sqmt")),
    Unit("sqft", "Sq.ft", Dimension.AREA, False, 2, ("sq.ft", "ft2", "square feet", "sft")),
    Unit("acre", "Acre", Dimension.AREA, False, 4, ("acres",)),
    Unit("ha", "Hectare", Dimension.AREA, False, 4, ("hectare", "hectares")),
    Unit("cum", "Cum", Dimension.VOLUME, True, 3, ("cu.m", "m3", "cubic metre")),
    Unit("cuft", "Cft", Dimension.VOLUME, False, 2, ("cu.ft", "ft3", "cft", "cubic feet")),
    Unit("l", "Litre", Dimension.VOLUME, False, 2, ("litre", "liter", "ltr")),
    Unit("kg", "Kg", Dimension.MASS, True, 3, ("kilogram", "kgs")),
    Unit("qtl", "Quintal", Dimension.MASS, False, 3, ("quintal", "quintals")),
    Unit("mt", "MT", Dimension.MASS, False, 3, ("tonne", "ton", "tonnes", "metric tonne")),
    Unit("kgpm", "kg/m", Dimension.LINEAR_DENSITY, True, 3, ("kg/m", "kg/rm", "kg per metre")),
    Unit("nos", "Nos", Dimension.COUNT, True, 0, ("no", "number", "numbers", "each")),
    Unit("set", "Set", Dimension.COUNT, False, 0, ("sets",)),
    Unit("joint", "Joints", Dimension.COUNT, False, 0, ("joints",)),
    Unit("kwh", "kWh", Dimension.OTHER, False, 2, ("kwhr", "kilowatt hour")),
    Unit("ls", "LS", Dimension.LUMP_SUM, True, 0, ("lump sum", "lumpsum")),
)

CONVERSIONS: tuple[Conversion, ...] = (
    Conversion("mm", "m", "0.001", note="SI"),
    Conversion("cm", "m", "0.01", note="SI"),
    Conversion("km", "m", "1000", note="SI"),
    Conversion("ft", "m", "0.3048", note="International foot (exact)"),
    Conversion("rmt", "m", "1", note="Running metre"),
    Conversion("sqft", "sqm", "0.09290304", note="0.3048² (exact)"),
    Conversion("acre", "sqm", "4046.8564224", note="International acre (exact)"),
    Conversion("ha", "sqm", "10000", note="SI"),
    Conversion("cuft", "cum", "0.028316846592", note="0.3048³ (exact)"),
    Conversion("l", "cum", "0.001", note="SI"),
    Conversion("qtl", "kg", "100", note="Indian quintal"),
    Conversion("mt", "kg", "1000", note="Metric tonne"),
)
