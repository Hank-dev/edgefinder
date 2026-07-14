"""Tests for the /rankings page — surfaces all opportunities by score."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from edgefinder.main import app, rankings
from edgefinder.models import (
    Opportunity,
    OpportunityKind,
    OpportunityStatus,
    ResearchRun,
    RunStatus,
)


def _make_opportunity(session, run, *, title, score, kind=OpportunityKind.RANKED, confidence=80.0):
    opp = Opportunity(
        run_id=run.id,
        canonical_key=f"key-{title}",
        kind=kind,
        title=title,
        buyer="Test buyer",
        observed_pain="Pain",
        proposed_wedge="Wedge",
        why_now="Now",
        norway_advantage="Advantage",
        global_path="Path",
        business_model="Model",
        risks=[],
        validation_effort="Low",
        next_experiment="Test",
        score=score,
        confidence=confidence,
        score_breakdown={"asymmetry": 8.0, "timing": 7.0},
        status=OpportunityStatus.NEW,
    )
    session.add(opp)
    session.commit()
    return opp


def test_rankings_page_renders_empty(session) -> None:
    """Rankings page renders even with no opportunities."""
    request = Request({
        "type": "http", "method": "GET", "path": "/rankings",
        "root_path": "", "scheme": "http", "query_string": b"",
        "headers": [], "server": ("test", 80), "app": app,
    })
    response = rankings(request, session)
    assert response.status_code == 200
    assert b"No opportunities" in response.body


def test_rankings_page_shows_opportunities_sorted_by_score(session) -> None:
    """Rankings are sorted highest score first regardless of run status."""
    run = ResearchRun(cutoff_at=datetime.now(timezone.utc), status=RunStatus.FAILED)
    session.add(run)
    session.commit()

    _make_opportunity(session, run, title="Low score", score=19.5)
    _make_opportunity(session, run, title="High score", score=85.0)
    _make_opportunity(session, run, title="Mid score", score=50.0)

    request = Request({
        "type": "http", "method": "GET", "path": "/rankings",
        "root_root": "", "scheme": "http", "query_string": b"",
        "headers": [], "server": ("test", 80), "app": app,
    })
    response = rankings(request, session)
    assert response.status_code == 200
    body = response.body.decode()
    # High score should appear before mid, which appears before low
    pos_high = body.find("High score")
    pos_mid = body.find("Mid score")
    pos_low = body.find("Low score")
    assert 0 < pos_high < pos_mid < pos_low


def test_rankings_page_shows_opportunities_from_failed_runs(session) -> None:
    """Opportunities from failed runs are included — the whole point."""
    run = ResearchRun(cutoff_at=datetime.now(timezone.utc), status=RunStatus.FAILED)
    session.add(run)
    session.commit()

    _make_opportunity(session, run, title="From failed run", score=78.0)

    request = Request({
        "type": "http", "method": "GET", "path": "/rankings",
        "root_path": "", "scheme": "http", "query_string": b"",
        "headers": [], "server": ("test", 80), "app": app,
    })
    response = rankings(request, session)
    assert b"From failed run" in response.body


def test_rankings_page_excludes_rejected(session) -> None:
    """Rejected opportunities don't clutter the rankings."""
    run = ResearchRun(cutoff_at=datetime.now(timezone.utc), status=RunStatus.RUNNING)
    session.add(run)
    session.commit()

    _make_opportunity(session, run, title="Visible", score=60.0)
    rejected = _make_opportunity(session, run, title="Rejected", score=10.0)
    rejected.status = OpportunityStatus.REJECT
    session.commit()

    request = Request({
        "type": "http", "method": "GET", "path": "/rankings",
        "root_path": "", "scheme": "http", "query_string": b"",
        "headers": [], "server": ("test", 80), "app": app,
    })
    response = rankings(request, session)
    assert b"Visible" in response.body
    assert b"Rejected" not in response.body


def test_rankings_page_shows_score_and_kind(session) -> None:
    """Each ranking entry shows the score and kind (ranked/watch)."""
    run = ResearchRun(cutoff_at=datetime.now(timezone.utc), status=RunStatus.PUBLISHED)
    session.add(run)
    session.commit()

    _make_opportunity(session, run, title="Ranked opp", score=85.0, kind=OpportunityKind.RANKED)
    _make_opportunity(session, run, title="Watch opp", score=30.0, kind=OpportunityKind.WATCH)

    request = Request({
        "type": "http", "method": "GET", "path": "/rankings",
        "root_path": "", "scheme": "http", "query_string": b"",
        "headers": [], "server": ("test", 80), "app": app,
    })
    response = rankings(request, session)
    body = response.body.decode()
    assert "85" in body
    assert "30" in body
    assert "ranked" in body.lower()
    assert "watch" in body.lower()
