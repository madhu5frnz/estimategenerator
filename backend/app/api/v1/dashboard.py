from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import DB, Auth
from app.api.envelope import Envelope, ok
from app.api.v1.estimates import EstimateOut, estimate_out
from app.api.v1.me import SubscriptionOut, UsageOut, build_me
from app.api.v1.projects import ProjectOut, project_out
from app.domain.money import format_inr
from app.services import estimates as estimate_service
from app.services import projects as project_service

router = APIRouter(tags=["dashboard"])


class DashboardOut(BaseModel):
    total_projects: int
    draft_projects: int
    in_progress_projects: int
    completed_projects: int
    total_estimated_value: str
    total_estimated_value_display: str
    recent_projects: list[ProjectOut]
    recent_estimates: list[EstimateOut]
    recent_documents: list[dict[str, object]]  # filled from Phase 2
    subscription: SubscriptionOut
    usage: UsageOut


@router.get("/dashboard/summary", response_model=Envelope[DashboardOut])
def dashboard(auth: Auth, db: DB) -> Envelope[DashboardOut]:
    summary = project_service.summary(db, auth)
    recent = summary["recent"]
    roles = project_service.roles_for(db, auth, [p.id for p in recent])
    me = build_me(db, auth.user, auth.organization_id)
    value = summary["total_estimated_value"]
    return ok(
        DashboardOut(
            total_projects=summary["total"],
            draft_projects=summary["by_status"]["draft"],
            in_progress_projects=summary["by_status"]["in_progress"],
            completed_projects=summary["by_status"]["completed"],
            total_estimated_value=format(value, "f"),
            total_estimated_value_display=format_inr(value),
            recent_projects=[project_out(p, roles.get(p.id, "viewer")) for p in recent],
            recent_estimates=[estimate_out(s) for s in estimate_service.list_recent(db, auth, 5)],
            recent_documents=[],
            subscription=me.subscription,
            usage=me.usage,
        )
    )
