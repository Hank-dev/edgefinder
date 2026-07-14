from __future__ import annotations

import httpx
import pytest
from helpers import make_job, make_job_source

from edgefinder.config import Settings
from edgefinder.jobs.digest import format_digest, select_digest_rows, send_telegram_message


def profile_settings(tmp_path) -> Settings:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "skills_have: [python, sql]\n"
        "target_roles: [data engineer]\n"
        "locations: {Trondheim: 1.0}\n"
        "seniority: {graduate: 1.0, senior: 0.3}\n"
    )
    return Settings(agent_token="test-agent-token", internal_token="test-internal-token", jobs_profile_path=profile_path, digest_min_relevance=60.0)


def test_digest_selects_recent_relevant_jobs_only(session, tmp_path) -> None:
    settings = profile_settings(tmp_path)
    nav = make_job_source(session, "nav-jobs", 0.9)
    relevant = make_job(session, nav, "n1", "Data Engineer", "Eksempel AS", days_old=0)
    make_job(session, nav, "n2", "Senior sykepleier", "Helse AS", days_old=0, skills_text="")  # low relevance
    make_job(session, nav, "n3", "Data Engineer", "Gammel AS", days_old=5)                     # outside window
    rows = select_digest_rows(session, settings, hours=24)
    assert [row.signal_id for row in rows] == [relevant.id]


def test_digest_windows_before_the_feed_cap(session, tmp_path, monkeypatch) -> None:
    from edgefinder.jobs import service

    settings = profile_settings(tmp_path)
    nav = make_job_source(session, "nav-jobs", 0.9)
    make_job(session, nav, "old", "Data Engineer", "Gammel AS", days_old=5)   # high relevance, outside window
    fresh = make_job(session, nav, "new", "Data Engineer", "Fersk AS", days_old=0)
    monkeypatch.setattr(service, "FEED_ROW_CAP", 1, raising=False)
    rows = select_digest_rows(session, settings, hours=24)
    assert [row.signal_id for row in rows] == [fresh.id]


def test_digest_formats_scores_links_and_deadlines(session, tmp_path) -> None:
    settings = profile_settings(tmp_path)
    nav = make_job_source(session, "nav-jobs", 0.9)
    make_job(session, nav, "n1", "Data Engineer", "Eksempel AS", days_old=0, deadline_days=9)
    rows = select_digest_rows(session, settings, hours=24)
    text = format_digest(rows)
    assert "Data Engineer" in text
    assert "Eksempel AS" in text
    assert "https://nav-jobs.example/n1" in text
    assert "9d" in text


@pytest.mark.asyncio
async def test_send_telegram_message_posts_to_bot_api() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await send_telegram_message(client, "bot-token", "chat-1", "hello")
    assert captured["url"] == "https://api.telegram.org/botbot-token/sendMessage"
    assert captured["body"]["chat_id"] == "chat-1"
    assert captured["body"]["text"] == "hello"
    assert captured["body"]["disable_web_page_preview"] is True


@pytest.mark.asyncio
async def test_send_telegram_message_failure_never_leaks_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError) as failure:
            await send_telegram_message(client, "secret-bot-token", "chat-1", "hello")
    assert "secret-bot-token" not in str(failure.value)
    assert "401" in str(failure.value)
