from __future__ import annotations

from datetime import datetime, timedelta, timezone

from edgefinder.models import Signal, Source
from edgefinder.normalization import content_hash
from edgefinder.repository import get_signal_trends


def make_signal(session, source, suffix, title, *, metadata=None, deadline_at=None):
    excerpt = f"Recorded observation {suffix}."
    item = Signal(
        source_id=source.id,
        external_id=suffix,
        canonical_url=f"https://{source.key}.test/{suffix}",
        title=title,
        excerpt=excerpt,
        language="und",
        region="norway",
        observed_at=datetime.now(timezone.utc) - timedelta(days=1),
        deadline_at=deadline_at,
        content_hash=content_hash(title, excerpt),
        metadata_json=metadata or {},
    )
    session.add(item)
    return item


def test_signal_trends_surface_aggregate_demand_patterns_across_single_signals(session) -> None:
    jobs = Source(key="jobs-src", name="Jobs", kind="jobs", base_url="https://jobs.test", quality=0.9)
    registry = Source(key="registry-src", name="Registry", kind="registry", base_url="https://registry.test", quality=0.9)
    community = Source(key="community-src", name="Community", kind="community", base_url="https://community.test", quality=0.6)
    procurement = Source(key="tender-src", name="Tenders", kind="procurement", base_url="https://tender.test", quality=0.9)
    session.add_all([jobs, registry, community, procurement])
    session.commit()

    make_signal(session, jobs, "j1", "Regnskapsmedarbeider", metadata={"employer": "Hyre AS", "municipality": "OSLO"})
    make_signal(session, jobs, "j2", "Regnskapskonsulent", metadata={"employer": "Hyre AS", "municipality": "OSLO"})
    make_signal(session, jobs, "j3", "Sykepleier", metadata={"employer": "Oslo kommune", "municipality": "OSLO"})
    make_signal(session, registry, "r1", "Nyregistrert: Tall og Bilag AS", metadata={"industry": "Regnskap og bokføring"})
    make_signal(session, registry, "r2", "Nyregistrert: Bilagsfix AS", metadata={"industry": "Regnskap og bokføring"})
    make_signal(session, registry, "r3", "Nyregistrert: Mysteriet ENK", metadata={"industry": "ukjent næring"})
    make_signal(session, registry, "r4", "Nyregistrert: Tomt AS", metadata={"industry": "Uoppgitt"})
    make_signal(session, community, "c1", "Invoice reconciliation is painful")
    make_signal(session, community, "c2", "Why is invoice matching still manual?")
    make_signal(session, community, "c3", "Show HN: invoice OCR pipeline")
    deadline = datetime.now(timezone.utc) + timedelta(days=12)
    make_signal(session, procurement, "t1", "Rammeavtale regnskapstjenester", deadline_at=deadline)
    session.commit()

    trends = get_signal_trends(session)

    assert trends["top_employers"][0] == {"employer": "Hyre AS", "count": 2}
    assert trends["top_industries"][0] == {"industry": "Regnskap og bokføring", "count": 2}
    assert all(entry["industry"] not in {"ukjent næring", "Uoppgitt"} for entry in trends["top_industries"])
    assert {"term": "invoice", "count": 3} in trends["recurring_terms"]
    soonest = trends["upcoming_deadlines"][0]
    assert soonest["title"] == "Rammeavtale regnskapstjenester"
    assert soonest["deadline_at"] == deadline.isoformat()
    kinds = {row["kind"] for row in trends["sources"]}
    assert {"jobs", "registry", "community", "procurement"} <= kinds
