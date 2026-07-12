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
async def test_mcp_contract_exposes_only_the_eight_planned_tools() -> None:
    tools = await mcp.list_tools()
    assert {tool.name for tool in tools} == {
        "start_weekly_run",
        "get_signal_batch",
        "search_signal_archive",
        "find_similar_opportunities",
        "save_candidate",
        "save_review",
        "publish_run",
        "fail_run",
    }
