from __future__ import annotations

import contextlib
import hmac
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .collectors import build_collectors, collect_all, source_definitions
from .config import get_settings
from .db import SessionLocal, assert_schema_ready, get_session
from .mcp_server import mcp
from .models import Opportunity, OpportunityStatus, ResearchRun, RunStatus, Signal, Source
from .repository import DomainError, add_feedback, published_run_query, seed_sources
from .schemas import FeedbackInput


PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

# Regenerated on every process start; the feedback form only needs to prove the
# request came from a page this instance rendered, never from a stored secret.
CSRF_TOKEN = secrets.token_hex(32)


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
    with SessionLocal() as session:
        seed_sources(session, source_definitions(settings))
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Edgefinder", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
app.mount("/mcp", BearerTokenMiddleware(mcp.streamable_http_app(), get_settings().agent_token))


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=409)


def template_context(request: Request, **items: Any) -> dict[str, Any]:
    return {"request": request, "app_name": get_settings().app_name, "csrf_token": CSRF_TOKEN, **items}


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
    opportunities = sorted(
        [item for item in latest.opportunities if item.status not in {OpportunityStatus.REJECT, OpportunityStatus.SUPERSEDED}],
        key=lambda item: (item.kind.value, -item.score),
    ) if latest else []
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        template_context(request, latest=latest, opportunities=opportunities, recent_runs=recent_runs, source_counts=source_counts),
    )


@app.get("/talent", response_class=HTMLResponse)
def talent(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Talent Radar — white-collar hiring intelligence from NAV job signals."""
    import re
    from collections import Counter

    CATEGORY_KEYWORDS: dict[str, set[str]] = {
        "software": {
            "developer", "utvikler", "software", "python", "java", "javascript", "frontend",
            "backend", "fullstack", "full stack", "devops", "cloud", "aws", "azure", "kubernetes",
            "react", "node", "typescript", "golang", "rust", "c++", "c#", ".net", "sql", "data engineer",
            "data scientist", "machine learning", " ai ", " ml ", "systemutvikler", "arkitekt",
            "tech lead", "teknisk", "it-konsulent", "sikkerhet", "security", "cyber", "scrum",
            "product owner", "product manager", "qa ", "test ", "terraform", "docker", "linux",
            "programmerer", "platform", "infrastruktur", "ios", "android", "flutter", "vue",
            "svelte", "nextjs", "graphql", "microservice", "saas", "api ", "cicd",
        },
        "finance": {
            "økonomi", "finans", "regnskap", "accounting", "controller", "audit", "revisor",
            "skatt", "tax", "investering", "investment", "bank", "forsikring", "insurance",
            "aktuar", "actuary", "risk", "compliance", "kreditt", "credit", "analytiker",
            "analyst", "portfolio", "fond", "fund", "trader", "treasury", "bokfør",
            "billing", "faktura", "vat", "mva", "afregning", "kapital", "equity", "valuta",
            "regnskapsfører", "regnskapsmedarbeider", "økonomimedarbeider", "finansanalytiker",
        },
        "economics": {
            "økonom", "analytiker", "analyst", "strateg", "rådgiver", "konsulent", "consultant",
            "research", "forskning", "marked", "market", "business", "forretningsutvikling",
            "kommer", "salg", "sales", "prosjektleder", "prosjekt", "change", "transformasjon",
            "operasjon", "kvalitet", "prosess", "ledelse", "management", "direktør",
            "forretnings", "business analyst", "strategy",
        },
    }

    SKILL_KEYWORDS = [
        "python", "java", "javascript", "typescript", "react", "vue", "angular", "node",
        "go ", "golang", "rust", "c++", "c#", ".net", "sql", "nosql", "postgresql",
        "aws", "azure", "gcp", "cloud", "kubernetes", "docker", "terraform", "ansible",
        "linux", "windows", "macos", "git", "ci/cd", "jenkins", "github actions",
        "devops", "sre", "platform", "microservice", "api", "graphql", "rest",
        "kafka", "rabbitmq", "redis", "elasticsearch", "snowflake", "dbt",
        "machine learning", " ai ", " ml ", "llm", "tensorflow", "pytorch", "pandas",
        "scrum", "agile", "kanban", "safe", "prince2", "pmp", "itil",
        "regnskap", "økonomi", "finans", "audit", "revisjon", "skatt", "tax",
        "ifs", "sap", "oracle", "power bi", "tableau", "excel", "visma", "tripletex",
        "excel", "vba", "macros", "powerpoint", "power query",
        "konsulent", "rådgiver", "prosjektledelse", "forretningsutvikling",
        "kommunikasjon", "forhandling", "presentasjon", "ledelse",
        "norsk", "english", "skandinavisk", "tysk", "fransk",
    ]

    job_sources = session.scalars(select(Source).where(Source.kind == "jobs", Source.enabled.is_(True))).all()
    if not job_sources:
        return templates.TemplateResponse(
            request, "talent.html",
            template_context(request, total_signals=0, total_employers=0, total_municipalities=0,
                              top_roles=[], top_employers=[],
                              top_municipalities=[], top_skills=[],
                              category="all", category_counts={},
                              skill_filter="", job_listings=[]),
        )

    cat_filter = request.query_params.get("cat", "all")
    skill_filter = request.query_params.get("skill", "").strip().lower()
    from datetime import datetime as _dt, timedelta
    cutoff = _dt.now() - timedelta(days=30)
    source_ids = [source.id for source in job_sources]
    signals = session.scalars(
        select(Signal).where(Signal.source_id.in_(source_ids)).order_by(desc(Signal.observed_at)).limit(3000)
    ).all()
    signals = [
        sig for sig in signals
        if (sig.metadata_json or {}).get("status", "ACTIVE") != "INACTIVE"
        and (sig.deadline_at is None or sig.deadline_at >= cutoff)
    ]

    # Categorize each signal
    categorized: list[tuple[Signal, list[str]]] = []
    for sig in signals:
        text = (sig.title + " " + sig.excerpt).lower()
        cats = [name for name, keywords in CATEGORY_KEYWORDS.items() if any(kw in text for kw in keywords)]
        categorized.append((sig, cats))

    # Count per category for the filter tabs
    category_counts = {name: 0 for name in CATEGORY_KEYWORDS}
    for _sig, cats in categorized:
        for c in cats:
            category_counts[c] += 1

    # Filter by selected category
    if cat_filter in CATEGORY_KEYWORDS:
        filtered = [(sig, cats) for sig, cats in categorized if cat_filter in cats]
    else:
        filtered = categorized
        cat_filter = "all"

    # Further filter by skill if selected
    job_listings: list[dict] = []
    if skill_filter:
        filtered = [(sig, cats) for sig, cats in filtered if skill_filter in (sig.title + " " + sig.excerpt).lower()]
        for sig, _cats in filtered:
            meta = sig.metadata_json or {}
            job_listings.append({
                "title": sig.title,
                "employer": meta.get("employer", ""),
                "municipality": meta.get("municipality", ""),
                "url": sig.canonical_url,
                "observed_at": sig.observed_at.strftime("%d %b %Y"),
            })

    employers: Counter[str] = Counter()
    municipalities: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    skills: Counter[str] = Counter()

    STOP_WORDS = {
        "til", "for", "med", "av", "som", "eller", "det", "ved", "kun", "kan", "skal",
        "har", "ikke", "weekend", "deltid", "heltid", "fast", "engasjement", "oppdrag",
        "søker", "søkes", "stilling", "stillinger", "ledig", "vår", "nye", "hos",
        "engasjert", "åpen", "100", "50", "75", "vi", "deg", "du", "er", "en", "ei",
        "til", "og", "i", "på", "å", "tilsvar", "bruke", "både", "gjennom", "slik",
        "sine", "sitt", "hvor", "hva", "når", "hvordan", "allerede", "både", "siden",
    }

    for sig, _cats in filtered:
        meta = sig.metadata_json or {}
        if meta.get("employer"):
            employers[meta["employer"]] += 1
        if meta.get("municipality"):
            municipalities[meta["municipality"]] += 1
        for token in re.findall(r"[a-zA-ZæøåÆØÅ]{3,}", sig.title.lower()):
            if token not in STOP_WORDS:
                roles[token] += 1
        text = (sig.title + " " + sig.excerpt).lower()
        for kw in SKILL_KEYWORDS:
            kw_clean = kw.strip()
            if kw_clean and kw_clean in text:
                skills[kw_clean] += 1

    return templates.TemplateResponse(
        request, "talent.html",
        template_context(
            request,
            total_signals=len(filtered),
            total_employers=len(employers),
            total_municipalities=len(municipalities),
            top_employers=employers.most_common(15),
            top_municipalities=municipalities.most_common(15),
            top_roles=roles.most_common(15),
            top_skills=skills.most_common(25),
            category=cat_filter,
            category_counts=category_counts,
            skill_filter=skill_filter,
            job_listings=job_listings,
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
