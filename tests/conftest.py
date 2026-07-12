from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/edgefinder-tests.db")
os.environ.setdefault("AGENT_TOKEN", "test-agent-token")
os.environ.setdefault("INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("DATA_DIR", "/tmp/edgefinder-test-data")
os.environ.setdefault("BACKUP_DIR", "/tmp/edgefinder-test-backups")

from edgefinder.db import Base, SessionLocal, engine  # noqa: E402
from edgefinder.models import Signal, Source  # noqa: E402
from edgefinder.normalization import content_hash  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def session() -> Session:
    with SessionLocal() as db_session:
        yield db_session


@pytest.fixture
def source(session: Session) -> Source:
    item = Source(key="fixture-source", name="Fixture Source", kind="community", region="global", base_url="https://example.com", quality=0.8)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def add_signal(session: Session, source: Source, suffix: str, *, title: str | None = None) -> Signal:
    item_title = title or f"Pain signal {suffix}"
    excerpt = f"Teams repeatedly spend several hours manually reconciling records for case {suffix}."
    item = Signal(
        source_id=source.id,
        external_id=suffix,
        canonical_url=f"https://example.com/signals/{suffix}",
        title=item_title,
        excerpt=excerpt,
        language="en",
        region="global",
        observed_at=datetime.now(timezone.utc),
        content_hash=content_hash(item_title, excerpt),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item

