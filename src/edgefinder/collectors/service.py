from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from edgefinder.config import Settings
from edgefinder.models import Signal, Source
from edgefinder.normalization import canonicalize_url, clean_text, contains_suspicious_instructions, content_hash, job_fingerprint

from .base import BaseCollector, RawSignal


@dataclass(slots=True)
class CollectionSummary:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failures: dict[str, str] = field(default_factory=dict)


def _utc(value: datetime | None) -> datetime | None:
    """SQLite persists wall time and drops the offset, so anything aware must become UTC before storage."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value


def _store_signal(session: Session, source: Source, raw: RawSignal) -> str:
    title = clean_text(raw.title, limit=500)
    excerpt = clean_text(raw.excerpt, limit=2000)
    url = canonicalize_url(raw.url)
    digest = content_hash(title, excerpt)
    fingerprint = job_fingerprint(str(raw.metadata.get("employer") or "") or None, title) if source.kind == "jobs" else None
    existing = session.scalar(
        select(Signal).where(Signal.source_id == source.id, Signal.external_id == raw.external_id)
    )
    if existing:
        if existing.content_hash == digest:
            existing.fetched_at = datetime.now(timezone.utc)
            if fingerprint and not existing.fingerprint:
                existing.fingerprint = fingerprint
            return "skipped"
        existing.title = title
        existing.excerpt = excerpt
        existing.canonical_url = url
        existing.observed_at = _utc(raw.observed_at)
        existing.fetched_at = datetime.now(timezone.utc)
        existing.content_hash = digest
        existing.language = raw.language
        existing.region = raw.region
        existing.deadline_at = _utc(raw.deadline_at)
        existing.metadata_json = raw.metadata
        existing.fingerprint = fingerprint
        existing.suspicious_instructions = contains_suspicious_instructions(f"{title} {excerpt}")
        return "updated"
    duplicate_hash = session.scalar(select(Signal.id).where(Signal.content_hash == digest).limit(1))
    if duplicate_hash:
        return "skipped"
    session.add(
        Signal(
            source_id=source.id,
            external_id=raw.external_id[:500],
            canonical_url=url,
            title=title,
            excerpt=excerpt,
            language=raw.language[:12],
            region=raw.region[:40],
            observed_at=_utc(raw.observed_at),
            deadline_at=_utc(raw.deadline_at),
            content_hash=digest,
            suspicious_instructions=contains_suspicious_instructions(f"{title} {excerpt}"),
            metadata_json=raw.metadata,
            fingerprint=fingerprint,
        )
    )
    return "inserted"


async def collect_all(session: Session, settings: Settings, collectors: list[BaseCollector]) -> CollectionSummary:
    summary = CollectionSummary()
    headers = {"User-Agent": settings.collection_user_agent, "Accept": "application/json, application/atom+xml, application/rss+xml, text/xml;q=0.9, */*;q=0.5"}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, headers=headers, follow_redirects=True) as client:
        for collector in collectors:
            source = session.scalar(select(Source).where(Source.key == collector.key))
            if not source or not source.enabled:
                continue
            try:
                signals = await collector.collect(client)
                if len(signals) > settings.max_signals_per_run:
                    signals = signals[: settings.max_signals_per_run]
                for raw in signals:
                    outcome = _store_signal(session, source, raw)
                    setattr(summary, outcome, getattr(summary, outcome) + 1)
                source.last_success_at = datetime.now(timezone.utc)
                source.last_error = None
                source.consecutive_failures = 0
                session.commit()
            except Exception as exc:  # source isolation is intentional
                session.rollback()
                source = session.scalar(select(Source).where(Source.key == collector.key))
                if source:
                    source.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                    source.consecutive_failures += 1
                    session.commit()
                summary.failures[collector.key] = f"{type(exc).__name__}: {exc}"
    return summary

