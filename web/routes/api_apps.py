"""
Job Application Tracker & Kanban Sync Endpoints (`routes/api_apps.py`):
- POST `/api/applications/save` (used by web Dashboard + browser extension auto-save on Apply)
- GET  `/api/applications/list` (supports search/status filter + Kanban stats)
- POST `/api/applications/update` (drag-drop status, interview date, private notes sync)
- POST `/api/applications/delete` (and DELETE `/api/applications/{app_id}`)
- GET  `/api/applications/export.csv` (Pro CSV export)
"""

import csv
from datetime import datetime, timedelta, timezone
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lib.limits import check_dashboard_app_limit
from lib.security import require_authenticated_user
from lib.supabase_client import (
    create_user_application,
    delete_user_application,
    list_user_applications,
    update_user_application,
)

router = APIRouter(prefix="/api/applications", tags=["Job Applications Tracker"])


class SaveApplicationRequest(BaseModel):
    job_title: str = Field(..., min_length=1, max_length=200)
    company: str = Field(default="Unknown Client", max_length=160)
    platform: str = Field(default="Manual", max_length=60)
    job_url: str = Field(default="", max_length=1000)
    salary: str = Field(default="", max_length=120)
    status: str = Field(default="Applied", max_length=30)
    match_score: Optional[int] = Field(default=None, ge=0, le=100)
    scam_risk: Optional[str] = Field(default=None, max_length=20)
    private_notes: str = Field(default="", max_length=2000)
    interview_at: Optional[str] = Field(default=None, max_length=64)


class UpdateApplicationRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    job_title: Optional[str] = Field(default=None, max_length=200)
    company: Optional[str] = Field(default=None, max_length=160)
    status: Optional[str] = Field(default=None, max_length=30)
    salary: Optional[str] = Field(default=None, max_length=120)
    private_notes: Optional[str] = Field(default=None, max_length=2000)
    interview_at: Optional[str] = Field(default=None, max_length=64)
    followup_done: Optional[bool] = None


class DeleteApplicationRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)


def compute_dashboard_stats(apps: List[Dict[str, Any]], weekly_goal: int = 10) -> Dict[str, Any]:
    total = len(apps)
    counts = {"Saved": 0, "Applied": 0, "Interview": 0, "Offer": 0, "Rejected": 0}
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    seven_days_ago = now - timedelta(days=7)

    this_week = 0
    followups_due: List[Dict[str, Any]] = []

    for app in apps:
        st = app.get("status", "Applied")
        if st in counts:
            counts[st] += 1
        applied_raw = app.get("applied_at") or app.get("created_at")
        if applied_raw:
            try:
                dt = datetime.fromisoformat(str(applied_raw).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= week_ago:
                    this_week += 1
                if st == "Applied" and not app.get("followup_done") and dt <= seven_days_ago:
                    followups_due.append(app)
            except ValueError:
                pass

    interview_plus_offer = counts["Interview"] + counts["Offer"]
    interview_rate = round((interview_plus_offer / total) * 100, 1) if total > 0 else 0.0
    goal_pct = min(100, round((this_week / max(1, weekly_goal)) * 100))

    return {
        "total": total,
        "by_status": counts,
        "interview_rate_pct": interview_rate,
        "applied_this_week": this_week,
        "weekly_goal": weekly_goal,
        "weekly_goal_pct": goal_pct,
        "followups_due_count": len(followups_due),
        "followups_due": followups_due[:8],
    }


@router.post("/save")
async def api_save_application(
    payload: SaveApplicationRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
) -> Dict[str, Any]:
    check_dashboard_app_limit(user)
    created = create_user_application(user["id"], payload.model_dump())
    return {"ok": True, "application": created}


@router.get("/list")
async def api_list_applications(
    q: str = Query(default="", max_length=120),
    status_filter: str = Query(default="", max_length=30),
    user: Dict[str, Any] = Depends(require_authenticated_user),
) -> Dict[str, Any]:
    apps = list_user_applications(user["id"])
    stats = compute_dashboard_stats(apps, weekly_goal=int(user.get("weekly_goal", 10)))

    if q.strip():
        needle = q.strip().lower()
        apps = [
            a
            for a in apps
            if needle in a.get("job_title", "").lower()
            or needle in a.get("company", "").lower()
            or needle in a.get("platform", "").lower()
            or needle in a.get("private_notes", "").lower()
        ]
    if status_filter.strip():
        apps = [a for a in apps if a.get("status") == status_filter.strip()]

    return {
        "ok": True,
        "applications": apps,
        "stats": stats,
        "is_pro": bool(user.get("is_pro")),
        "free_limit": 20,
    }


@router.post("/update")
async def api_update_application(
    payload: UpdateApplicationRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
) -> Dict[str, Any]:
    updates = {k: v for k, v in payload.model_dump().items() if k != "id" and v is not None}
    updated = update_user_application(user["id"], payload.id, updates)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return {"ok": True, "application": updated}


@router.post("/delete")
async def api_delete_application(
    payload: DeleteApplicationRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
) -> Dict[str, Any]:
    deleted = delete_user_application(user["id"], payload.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    return {"ok": True, "deleted_id": payload.id}


@router.get("/export.csv")
async def api_export_applications_csv(
    user: Dict[str, Any] = Depends(require_authenticated_user),
) -> StreamingResponse:
    if not user.get("is_pro"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "UPGRADE_REQUIRED",
                "message": "CSV Export is an ApplyKit Pro feature. Upgrade via M-Pesa (750 KES) or Lemon Squeezy ($6/mo).",
            },
        )
    apps = list_user_applications(user["id"])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["Job Title", "Company", "Platform", "Status", "Salary", "Match Score", "Scam Risk", "Applied At", "Interview At", "URL", "Private Notes"]
    )
    for a in apps:
        writer.writerow(
            [
                a.get("job_title", ""),
                a.get("company", ""),
                a.get("platform", ""),
                a.get("status", ""),
                a.get("salary", ""),
                a.get("match_score", ""),
                a.get("scam_risk", ""),
                a.get("applied_at", ""),
                a.get("interview_at", ""),
                a.get("job_url", ""),
                a.get("private_notes", ""),
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="applykit_applications.csv"'},
    )
