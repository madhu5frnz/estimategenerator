from __future__ import annotations

from sqlalchemy.dialects.postgresql import ENUM

# Enum types are created by the migration; models only reference them.
OrgRoleType = ENUM("owner", "admin", "member", name="org_role", create_type=False)
ProjectRoleType = ENUM(
    "admin", "professional", "contractor", "viewer", name="project_role", create_type=False
)
