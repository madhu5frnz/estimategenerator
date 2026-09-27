from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models import User


@dataclass(frozen=True)
class AuthContext:
    """Who is calling, and in which workspace. Built by the API layer from the token."""

    user: User
    organization_id: uuid.UUID
    org_role: str  # owner | admin | member

    @property
    def is_org_admin(self) -> bool:
        return self.org_role in ("owner", "admin")
