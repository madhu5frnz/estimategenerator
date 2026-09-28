"""Lead, lift, loading and unloading charges, SoR 2026-27 Part-I (COM-LDLFT-1 to 6).

Transcribed by hand from the book (pages 66-74 of the merged PDF, SoR pages 31-39)
because the printed tables do not extract in column order. All charges include the
13.615 % contractor's profit and overheads (note 12), so they are added to a rate
after overheads, never inside them (note 13).
"""

from __future__ import annotations

# COM-LDLFT-2: conveyance by trucks and tippers, cumulative up to 5 km, then per km.
# Columns 3-8 of the printed table.
MECHANICAL_CLASSES = {
    "earth_sand": "Earth / Sand / Gravel / Murrum / Lime / Surki (per cum)",
    "aggregate_stone": "Rubble / Size stones / Cut stones / Coarse aggregate (per cum)",
    "col5": "Column 5 of COM-LDLFT-2 (per cum) - label to be confirmed",
    "cement_steel": "Cement / Steel / RCC poles / AC & GI sheets / packed materials (per tonne)",
    "col7": "Column 7 of COM-LDLFT-2 - label to be confirmed",
    "col8": "Column 8 of COM-LDLFT-2 - label to be confirmed",
}
_ORDER = list(MECHANICAL_CLASSES)


def _row(*values: str) -> dict[str, str]:
    return dict(zip(_ORDER, values, strict=True))


MECHANICAL = {
    "I": {
        "1": _row("49.30", "47.50", "29.70", "69.90", "29.00", "79.20"),
        "2": _row("69.00", "66.50", "41.60", "97.90", "40.60", "110.90"),
        "3": _row("92.00", "92.00", "57.50", "135.30", "54.10", "147.90"),
        "4": _row("111.70", "111.70", "69.80", "164.20", "65.70", "179.60"),
        "5": _row("131.40", "131.40", "82.10", "193.20", "77.30", "211.20"),
        "per_km_5_30": _row("19.70", "19.70", "12.30", "29.00", "11.60", "31.70"),
        "per_km_beyond_30": _row("16.40", "16.40", "10.30", "24.20", "9.70", "26.40"),
    },
    "II": {
        "1": _row("48.70", "47.00", "29.40", "69.10", "28.60", "78.30"),
        "2": _row("68.20", "65.80", "41.10", "96.80", "40.10", "109.70"),
        "3": _row("91.00", "91.00", "56.90", "133.80", "53.50", "146.20"),
        "4": _row("110.50", "110.50", "69.00", "162.50", "64.90", "177.60"),
        "5": _row("130.00", "130.00", "81.20", "191.10", "76.40", "208.90"),
        "per_km_5_30": _row("19.50", "19.50", "12.20", "28.70", "11.50", "31.30"),
        "per_km_beyond_30": _row("16.30", "16.30", "10.20", "23.90", "9.50", "26.10"),
    },
    "III": {
        "1": _row("48.20", "46.50", "29.00", "68.30", "28.30", "77.40"),
        "2": _row("67.50", "65.10", "40.70", "95.70", "39.60", "108.40"),
        "3": _row("90.00", "90.00", "56.20", "132.30", "52.80", "144.60"),
        "4": _row("109.30", "109.30", "68.30", "160.70", "64.20", "175.50"),
        "5": _row("128.60", "128.60", "80.30", "189.10", "75.50", "206.50"),
        "per_km_5_30": _row("19.30", "19.30", "12.10", "28.40", "11.30", "31.00"),
        "per_km_beyond_30": _row("16.10", "16.10", "10.00", "23.60", "9.40", "25.80"),
    },
}

# COM-LDLFT-1: head load, total lead including the 50 m initial lead (covered by the rate).
HEAD_LOAD = {
    "classes": {
        "earth_sand": "Earth / Sand / Gravel / Murrum / Lime / Surki / Size stone / Rubble / Coarse aggregate (per cum)",
        "cement_steel": "Cement / Reinforcement steel / Structural steel (per tonne)",
        "slabs": "PCC slab / Shahbad slab / CC block / BS slab / Laterite / Wood (per cum)",
    },
    "I": {
        "100": {"earth_sand": "116.10", "cement_steel": "67.70", "slabs": "147.70"},
        "150": {"earth_sand": "232.10", "cement_steel": "135.40", "slabs": "295.40"},
    },
    "II": {
        "100": {"earth_sand": "109.60", "cement_steel": "63.90", "slabs": "139.40"},
        "150": {"earth_sand": "219.10", "cement_steel": "127.80", "slabs": "278.90"},
    },
    "III": {
        "100": {"earth_sand": "103.10", "cement_steel": "60.10", "slabs": "131.20"},
        "150": {"earth_sand": "206.10", "cement_steel": "120.20", "slabs": "262.30"},
    },
}

# COM-LDLFT-3/4/5: loading and unloading.
LOADING = {
    "classes": {
        "earth_sand": "Earth / Sand / Gravel / Murrum / Surki (per cum)",
        "stone_aggregate": "Rubble / Size stone / Cut stone / Coarse aggregate / Lime (per cum)",
        "cement": "Cement (per tonne)",
        "steel": "Steel (per tonne)",
        "bricks": "Bricks (per 1000 Nos)",
    },
    "manual": {  # COM-LDLFT-3, idle hire charges of trucks not added
        "I": {
            "loading": ["38.50", "77.00", "127.10", "152.30", "105.90"],
            "unloading": ["19.25", "38.50", "127.10", "152.30", "105.90"],
        },
        "II": {
            "loading": ["36.40", "72.70", "120.00", "143.80", "100.00"],
            "unloading": ["18.20", "36.35", "120.00", "143.80", "100.00"],
        },
        "III": {
            "loading": ["34.20", "68.40", "112.90", "135.30", "94.10"],
            "unloading": ["17.10", "34.20", "112.90", "135.30", "94.10"],
        },
    },
    "manual_with_idle_hire": {  # COM-LDLFT-4
        "I": {
            "loading": ["182.50", "221.00", "285.50", "310.70", "367.30"],
            "unloading": ["67.10", "110.50", "285.50", "310.70", "367.30"],
        },
        "II": {
            "loading": ["178.80", "215.10", "276.60", "300.50", "358.50"],
            "unloading": ["65.50", "107.55", "276.60", "300.50", "358.50"],
        },
        "III": {
            "loading": ["175.00", "209.20", "267.80", "290.20", "349.60"],
            "unloading": ["63.90", "104.60", "267.80", "290.20", "349.60"],
        },
    },
    "mechanical": {  # COM-LDLFT-5: earth/sand class and stone/aggregate class only
        "I": {"loading": ["80.60", "151.60"], "unloading": ["24.80", "24.80"]},
        "II": {"loading": ["80.00", "150.50"], "unloading": ["24.50", "24.50"]},
        "III": {"loading": ["79.40", "149.40"], "unloading": ["24.30", "24.30"]},
    },
}

# COM-LDLFT-6: lift by head load, per 1 m beyond the 3 m initial lift.
LIFT = {
    "classes": HEAD_LOAD["classes"],
    "I": {"earth_sand": "13.50", "cement_steel": "9.80", "slabs": "18.10"},
    "II": {"earth_sand": "12.80", "cement_steel": "9.20", "slabs": "17.00"},
    "III": {"earth_sand": "12.00", "cement_steel": "8.70", "slabs": "16.00"},
}
