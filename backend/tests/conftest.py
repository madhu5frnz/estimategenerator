from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"


@pytest.fixture(scope="session")
def golden_quantities() -> list[dict[str, Any]]:
    data = json.loads((FIXTURES / "golden" / "quantities.json").read_text(encoding="utf-8"))
    return data["cases"]  # type: ignore[no-any-return]
