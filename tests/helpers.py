from __future__ import annotations

from datetime import datetime, timedelta, timezone

from edgefinder.models import Signal, Source
from edgefinder.normalization import content_hash, job_fingerprint


def naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_job_source(session, key: str, quality: float) -> Source:
    source = Source(key=key, name=key.title(), kind="jobs", region="norway", base_url=f"https://{key}.example", quality=quality)
    session.add(source)
    session.commit()
    return source


def make_job(
    session,
    source: Source,
    external_id: str,
    title: str,
    employer: str,
    *,
    municipality: str = "Trondheim",
    board: str | None = None,
    days_old: int = 1,
    deadline_days: int | None = None,
    status: str = "ACTIVE",
    skills_text: str = "Python og SQL.",
) -> Signal:
    excerpt = f"{title} hos {employer} i {municipality}. {skills_text}".strip()
    signal = Signal(
        source_id=source.id,
        external_id=external_id,
        canonical_url=f"https://{source.key}.example/{external_id}",
        title=title,
        excerpt=excerpt,
        language="no",
        region="norway",
        observed_at=naive_now() - timedelta(days=days_old),
        deadline_at=naive_now() + timedelta(days=deadline_days) if deadline_days is not None else None,
        content_hash=content_hash(f"{title}-{source.key}", excerpt),
        metadata_json={"employer": employer, "municipality": municipality, "source_board": board or source.key, "status": status},
        fingerprint=job_fingerprint(employer, title),
    )
    session.add(signal)
    session.commit()
    return signal
