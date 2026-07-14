from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from edgefinder.config import get_settings
from edgefinder.db import get_session
from edgefinder.models import JobStatusValue
from edgefinder.repository import DomainError
from edgefinder.webutil import CSRF_TOKEN, template_context, templates

from .service import CLUSTER_SLUGS, build_talent_view, set_job_status

router = APIRouter()


@router.get("/talent", response_class=HTMLResponse)
def talent(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    view = build_talent_view(
        session,
        get_settings(),
        tab=request.query_params.get("tab", "all"),
        skill_filter=request.query_params.get("skill", ""),
    )
    return templates.TemplateResponse(request, "talent.html", template_context(request, view=view, cluster_slugs=CLUSTER_SLUGS))


@router.post("/talent/status/{fingerprint}")
def update_job_status(
    fingerprint: str,
    status: str = Form(),
    csrf_token: str = Form(),
    back: str = Form(default="/talent"),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if not hmac.compare_digest(csrf_token, CSRF_TOKEN):
        raise HTTPException(403, "Invalid form token")
    try:
        value = JobStatusValue(status)
    except ValueError as exc:
        raise HTTPException(422, "Unknown status") from exc
    try:
        set_job_status(session, fingerprint, value)
    except DomainError as exc:
        raise HTTPException(404, str(exc)) from exc
    target = back if back.startswith("/talent") else "/talent"
    return RedirectResponse(target, status_code=303)
