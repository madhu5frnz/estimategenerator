"""Projects: tenant scoping, project roles, plan limits and audit.

Access rules
* Every query is filtered by the caller's organisation. A project in another organisation
  is reported as "not found", never "forbidden", so ids cannot be probed.
* Organisation owners/admins act as project admin on every project in the organisation.
* Other members see only projects they belong to (project_members).
* Project roles, lowest to highest: viewer < contractor < professional < admin.
  View: viewer. Edit details: professional. Delete: admin.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.ids import new_id
from app.core.security import now_utc
from app.models import Project, ProjectMember, WorkCategory
from app.services import audit
from app.services.context import AuthContext
from app.services.plans import current_plan, projects_used

ROLE_RANK = {"viewer": 0, "contractor": 1, "professional": 2, "admin": 3}
AUDITED_FIELDS = (
    "name", "project_type", "work_category_id", "client_department", "location", "district",
    "state", "estimated_value", "description", "engineer_name", "contractor_name",
    "reference_number", "project_date", "status",
)  # fmt: skip


@dataclass(frozen=True)
class ProjectAccess:
    project: Project
    role: str


def _visible(ctx: AuthContext) -> Select[Project]:
    query = select(Project).where(
        Project.organization_id == ctx.organization_id, Project.deleted_at.is_(None)
    )
    if not ctx.is_org_admin:
        query = query.where(
            Project.id.in_(
                select(ProjectMember.project_id).where(ProjectMember.user_id == ctx.user.id)
            )
        )
    return query


def get_access(
    db: Session, ctx: AuthContext, project_id: uuid.UUID, minimum: str = "viewer"
) -> ProjectAccess:
    project = db.scalar(_visible(ctx).where(Project.id == project_id))
    if project is None:
        raise AppError("NOT_FOUND", "Project not found.", 404)
    if ctx.is_org_admin:
        role = "admin"
    else:
        role = (
            db.scalar(
                select(ProjectMember.role).where(
                    ProjectMember.project_id == project.id, ProjectMember.user_id == ctx.user.id
                )
            )
            or "viewer"
        )
    if ROLE_RANK[role] < ROLE_RANK[minimum]:
        raise AppError(
            "FORBIDDEN", f"Your role on this project ({role}) does not allow this action.", 403
        )
    return ProjectAccess(project=project, role=role)


def _check_category(
    db: Session, ctx: AuthContext, category_id: uuid.UUID | None, project_type: str
) -> None:
    if category_id is None:
        return
    category = db.get(WorkCategory, category_id)
    if (
        category is None
        or not category.is_active
        or category.organization_id not in (None, ctx.organization_id)
        or category.project_type != project_type
    ):
        raise AppError(
            "VALIDATION_ERROR",
            "The selected work category does not belong to this project type.",
            details={"field": "work_category_id"},
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal | date | uuid.UUID):
        return str(value)
    return value


def create(db: Session, ctx: AuthContext, data: dict[str, Any]) -> ProjectAccess:
    state = current_plan(db, ctx.organization_id)
    limit = state.limit("projects")
    if limit is not None and projects_used(db, ctx.organization_id) >= limit:
        raise AppError(
            "PLAN_LIMIT_REACHED",
            f"Your {state.plan.name} plan allows {limit} projects. Delete a project or "
            "upgrade your plan to add more.",
            403,
            {"limit": limit, "plan": state.plan.code},
        )
    _check_category(db, ctx, data.get("work_category_id"), data["project_type"])
    project = Project(
        id=new_id(), organization_id=ctx.organization_id, created_by=ctx.user.id, **data
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id, user_id=ctx.user.id, role="admin", added_by=ctx.user.id
        )
    )
    audit.record(
        db, actor=ctx.user, organization_id=ctx.organization_id, entity_type="project",
        entity_id=project.id, project_id=project.id, action="create",
        new_value={k: _jsonable(v) for k, v in data.items()},
    )  # fmt: skip
    db.commit()
    return ProjectAccess(project=project, role="admin")


def update(
    db: Session, ctx: AuthContext, project_id: uuid.UUID, changes: dict[str, Any]
) -> ProjectAccess:
    access = get_access(db, ctx, project_id, "professional")
    project = access.project
    project_type = changes.get("project_type", project.project_type)
    category_id = changes.get("work_category_id", project.work_category_id)
    if "project_type" in changes or "work_category_id" in changes:
        _check_category(db, ctx, category_id, project_type)
    for field, new in changes.items():
        old = getattr(project, field)
        if old == new:
            continue
        setattr(project, field, new)
        if field in AUDITED_FIELDS:
            audit.record(
                db, actor=ctx.user, organization_id=ctx.organization_id,
                entity_type="project", entity_id=project.id, project_id=project.id,
                action="update", field=field, old_value=_jsonable(old),
                new_value=_jsonable(new),
            )  # fmt: skip
    db.commit()
    db.refresh(project)
    return access


def delete(db: Session, ctx: AuthContext, project_id: uuid.UUID) -> None:
    access = get_access(db, ctx, project_id, "admin")
    access.project.deleted_at = now_utc()
    audit.record(
        db, actor=ctx.user, organization_id=ctx.organization_id, entity_type="project",
        entity_id=project_id, project_id=project_id, action="delete",
    )  # fmt: skip
    db.commit()


def search(
    db: Session,
    ctx: AuthContext,
    *,
    q: str | None,
    status: str | None,
    project_type: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Project], int]:
    query = _visible(ctx)
    if status:
        query = query.where(Project.status == status)
    if project_type:
        query = query.where(Project.project_type == project_type)
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{escaped}%"
        query = query.where(
            or_(
                Project.name.ilike(pattern, escape="\\"),
                Project.reference_number.ilike(pattern, escape="\\"),
                Project.location.ilike(pattern, escape="\\"),
                Project.district.ilike(pattern, escape="\\"),
            )
        )
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.scalars(
        query.order_by(Project.updated_at.desc(), Project.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


def roles_for(db: Session, ctx: AuthContext, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if ctx.is_org_admin:
        return dict.fromkeys(project_ids, "admin")
    rows = db.execute(
        select(ProjectMember.project_id, ProjectMember.role).where(
            ProjectMember.user_id == ctx.user.id, ProjectMember.project_id.in_(project_ids)
        )
    ).all()
    return {pid: role for pid, role in rows}


def summary(db: Session, ctx: AuthContext) -> dict[str, Any]:
    visible = _visible(ctx).subquery()
    counts: dict[str, int] = dict(
        db.execute(select(visible.c.status, func.count()).group_by(visible.c.status)).all()
    )
    total_value = db.scalar(select(func.coalesce(func.sum(visible.c.estimated_value), 0)))
    recent = db.scalars(
        _visible(ctx).order_by(Project.updated_at.desc(), Project.id.desc()).limit(5)
    ).all()
    return {
        "total": sum(counts.values()),
        "by_status": {
            s: int(counts.get(s, 0)) for s in ("draft", "in_progress", "completed", "archived")
        },
        "total_estimated_value": Decimal(total_value or 0),
        "recent": list(recent),
    }
