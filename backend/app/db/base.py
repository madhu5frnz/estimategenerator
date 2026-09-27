from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base. The schema itself is owned by Alembic migrations, which are the
    reviewed source of truth; models map onto it and never create tables."""

    type_annotation_map: dict[Any, Any] = {datetime: DateTime(timezone=True)}  # noqa: RUF012
