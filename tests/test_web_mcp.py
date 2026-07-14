from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from edgefinder.main import BearerTokenMiddleware, app, dashboard, health, require_internal_token
from edgefinder.mcp_server import mcp


def test_health_and_empty_dashboard_render(session) -> None:
    assert health(session)["status"] == "ok"
    request = Request({"type": "http", "method": "GET", "path": "/", "root_path": "", "scheme": "http", "query_string": b"", "headers": [], "server": ("test", 80), "app": app})
    response = dashboard(request, session)
    assert response.status_code == 200
    assert b"Building the baseline" in response.body


@pytest.mark.asyncio
async def test_mcp_bearer_middleware_rejects_missing_token() -> None:
    reached = False

    async def protected_app(scope, receive, send):
        nonlocal reached
        reached = True

    middleware = BearerTokenMiddleware(protected_app, "correct-token")
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware({"type": "http", "method": "POST", "path": "/", "headers": []}, receive, send)
    assert not reached
    assert messages[0]["status"] == 401


def test_internal_collection_requires_a_different_token() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_internal_token(None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_mcp_contract_exposes_only_the_ten_planned_tools() -> None:
    tools = await mcp.list_tools()
    assert {tool.name for tool in tools} == {
        "start_weekly_run",
        "get_signal_batch",
        "get_signal_trends",
        "search_signal_archive",
        "find_similar_opportunities",
        "save_candidate",
        "save_review",
        "save_job_picks",
        "publish_run",
        "fail_run",
    }


def test_csrf_token_is_random_rather_than_derived_from_the_internal_token(session) -> None:
    import hashlib

    from edgefinder.config import get_settings
    from edgefinder.main import CSRF_TOKEN, opportunity_feedback
    from edgefinder.models import Opportunity, OpportunityKind, OpportunityStatus, ResearchRun
    legacy = hashlib.sha256(get_settings().internal_token.encode()).hexdigest()
    assert CSRF_TOKEN != legacy

    from datetime import datetime, timezone

    run = ResearchRun(cutoff_at=datetime.now(timezone.utc))
    session.add(run)
    session.flush()
    opportunity = Opportunity(
        run_id=run.id, canonical_key="csrf-check", kind=OpportunityKind.WATCH, title="CSRF check candidate",
        buyer="b", observed_pain="p", proposed_wedge="w", why_now="n", norway_advantage="a", global_path="g",
        business_model="m", risks=[], validation_effort="v", next_experiment="e", score=10.0, confidence=10.0,
        score_breakdown={},
    )
    session.add(opportunity)
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        opportunity_feedback(opportunity.id, action=OpportunityStatus.WATCH, reason=None, note=None, csrf_token=legacy, session=session)
    assert exc_info.value.status_code == 403

    response = opportunity_feedback(opportunity.id, action=OpportunityStatus.WATCH, reason=None, note=None, csrf_token=CSRF_TOKEN, session=session)
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_mcp_bearer_middleware_rejects_unauthenticated_websocket_scopes() -> None:
    reached = False

    async def protected_app(scope, receive, send):
        nonlocal reached
        reached = True

    middleware = BearerTokenMiddleware(protected_app, "correct-token")
    messages: list[dict] = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        messages.append(message)

    await middleware({"type": "websocket", "path": "/", "headers": []}, receive, send)
    assert not reached
