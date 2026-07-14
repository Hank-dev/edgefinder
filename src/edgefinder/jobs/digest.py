from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from edgefinder.config import Settings, get_settings
from edgefinder.db import SessionLocal

from .relevance import load_profile
from .service import JobRow, build_talent_view

DIGEST_CAP = 15


def select_digest_rows(session, settings: Settings, hours: int) -> list[JobRow]:
    window_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    view = build_talent_view(session, settings)
    return [
        row
        for row in view.rows
        if row.observed_at >= window_start and row.relevance >= settings.digest_min_relevance
    ][:DIGEST_CAP]


def format_digest(rows: list[JobRow]) -> str:
    lines = [f"Edgefinder jobs digest — {len(rows)} match{'es' if len(rows) != 1 else ''}"]
    for row in rows:
        deadline = f" · {row.days_left}d left" if row.days_left is not None else ""
        location = f" ({row.municipality})" if row.municipality else ""
        lines.append(f"\n{row.relevance:.0f} · {row.title} — {row.employer}{location}{deadline}\n{row.url}")
    return "\n".join(lines)


async def send_telegram_message(client: httpx.AsyncClient, bot_token: str, chat_id: str, text: str) -> None:
    response = await client.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
    )
    response.raise_for_status()


async def send_digest(hours: int = 24) -> dict[str, Any]:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return {"sent": 0, "reason": "telegram not configured"}
    if load_profile(settings.jobs_profile_path) is None:
        print("warning: no profile.yaml configured; every job scores 50 and the digest threshold filters everything", file=sys.stderr)
    with SessionLocal() as session:
        rows = select_digest_rows(session, settings, hours)
    if not rows:
        return {"sent": 0, "reason": "no matching jobs in window"}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        await send_telegram_message(client, settings.telegram_bot_token, settings.telegram_chat_id, format_digest(rows))
    return {"sent": len(rows)}
