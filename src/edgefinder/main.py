from __future__ import annotations

import contextlib
import hmac
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .collectors import build_collectors, collect_all, source_definitions
from .config import get_settings
from .db import SessionLocal, assert_schema_ready, get_session
from .jobs.routes import router as jobs_router
from .mcp_server import mcp
from .models import Opportunity, OpportunityStatus, ResearchRun, RunStatus, Signal, Source
from .repository import DomainError, add_feedback, published_run_query, seed_sources
from .schemas import FeedbackInput
from .webutil import CSRF_TOKEN, template_context, templates


PACKAGE_DIR = Path(__file__).resolve().parent


class BearerTokenMiddleware:
    """Minimal ASGI bearer guard for the localhost-only MCP application."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"authorization", b"")
        expected = b"Bearer " + self.token
        if not hmac.compare_digest(supplied, expected):
            if scope["type"] == "http":
                await JSONResponse({"detail": "Invalid or missing agent token"}, status_code=401)(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.assert_safe_production_config()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    assert_schema_ready()
    from .jobs.relevance import load_profile

    load_profile(settings.jobs_profile_path)  # raises ValueError on a malformed profile
    with SessionLocal() as session:
        seed_sources(session, source_definitions(settings))
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Edgefinder", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
app.mount("/mcp", BearerTokenMiddleware(mcp.streamable_http_app(), get_settings().agent_token))
app.include_router(jobs_router)


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, Any]:
    session.scalar(select(func.count(Source.id)))
    latest = session.scalar(select(ResearchRun).order_by(desc(ResearchRun.started_at)).limit(1))
    return {"status": "ok", "latest_run": latest.status.value if latest else None}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    latest = session.scalar(published_run_query().limit(1))
    recent_runs = session.scalars(select(ResearchRun).order_by(desc(ResearchRun.started_at)).limit(8)).all()
    source_counts = session.execute(
        select(Source, func.count(Signal.id)).outerjoin(Signal).where(Source.enabled).group_by(Source.id).order_by(Source.name)
    ).all()
    total_signals = sum(count for _source, count in source_counts)
    healthy_sources = sum(
        1 for source, _count in source_counts
        if source.last_success_at is not None and not source.consecutive_failures
    )
    failing_sources = sum(1 for source, _count in source_counts if source.consecutive_failures)
    opportunities = sorted(
        [item for item in latest.opportunities if item.status not in {OpportunityStatus.REJECT, OpportunityStatus.SUPERSEDED}],
        key=lambda item: (item.kind.value, -item.score),
    ) if latest else []
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        template_context(
            request,
            latest=latest,
            latest_run=recent_runs[0] if recent_runs else None,
            opportunities=opportunities,
            recent_runs=recent_runs,
            source_counts=source_counts,
            total_signals=total_signals,
            healthy_sources=healthy_sources,
            failing_sources=failing_sources,
        ),
    )


@app.get("/rankings", response_class=HTMLResponse)
def rankings(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """All opportunities ranked by score — regardless of run status.

    Surfaces findings from failed runs too, so the best ideas are never
    hidden behind a crashed research pipeline.
    """
    opportunities = session.scalars(
        select(Opportunity)
        .where(Opportunity.status.not_in({OpportunityStatus.REJECT, OpportunityStatus.SUPERSEDED}))
        .order_by(desc(Opportunity.score))
        .limit(50)
    ).all()
    return templates.TemplateResponse(
        request,
        "rankings.html",
        template_context(request, opportunities=opportunities),
    )


@app.get("/archive", response_class=HTMLResponse)
def archive(request: Request, q: str = Query(default="", max_length=200), session: Session = Depends(get_session)) -> HTMLResponse:
    statement = select(Opportunity).options(selectinload(Opportunity.run)).order_by(desc(Opportunity.created_at))
    if q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(or_(Opportunity.title.ilike(term), Opportunity.observed_pain.ilike(term), Opportunity.proposed_wedge.ilike(term)))
    opportunities = session.scalars(statement.limit(100)).all()
    return templates.TemplateResponse(request, "archive.html", template_context(request, opportunities=opportunities, query=q))


@app.get("/opportunities/{opportunity_id}", response_class=HTMLResponse)
def opportunity_detail(request: Request, opportunity_id: str, session: Session = Depends(get_session)) -> HTMLResponse:
    opportunity = session.scalar(
        select(Opportunity)
        .where(Opportunity.id == opportunity_id)
        .options(selectinload(Opportunity.evidence), selectinload(Opportunity.reviews), selectinload(Opportunity.feedback))
    )
    if not opportunity:
        raise HTTPException(404, "Opportunity not found")
    return templates.TemplateResponse(request, "opportunity.html", template_context(request, opportunity=opportunity))


@app.post("/opportunities/{opportunity_id}/feedback")
def opportunity_feedback(
    opportunity_id: str,
    action: OpportunityStatus = Form(),
    reason: str | None = Form(default=None),
    note: str | None = Form(default=None),
    csrf_token: str = Form(),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if not hmac.compare_digest(csrf_token, CSRF_TOKEN):
        raise HTTPException(403, "Invalid form token")
    add_feedback(session, opportunity_id, FeedbackInput(action=action, reason=reason or None, note=note or None))
    return RedirectResponse(f"/opportunities/{opportunity_id}", status_code=303)


def require_internal_token(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {get_settings().internal_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "Invalid or missing internal token")


@app.post("/internal/collect", dependencies=[Depends(require_internal_token)])
async def trigger_collection(session: Session = Depends(get_session)) -> dict[str, Any]:
    settings = get_settings()
    summary = await collect_all(session, settings, build_collectors(settings))
    return {"inserted": summary.inserted, "updated": summary.updated, "skipped": summary.skipped, "failures": summary.failures}
