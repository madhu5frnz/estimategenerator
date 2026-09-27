"""Print the OpenAPI schema: uv run python -m app.openapi_dump > ../frontend/openapi.json

The frontend generates its API types from this file (npm run gen:api); CI fails if the
committed copy is out of date.
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("APP_ENV", "development")  # docs are disabled only in production

from app.main import create_app


def main() -> None:
    json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
