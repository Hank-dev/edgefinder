"""Tests for auto-retiring old opportunities when update_of_id is used."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from edgefinder.config import Settings
from edgefinder.models import Opportunity, OpportunityKind, OpportunityStatus, RunStatus
from edgefinder.repository import DomainError, publish_run, save_candidate, save_review, start_weekly_run
from edgefinder.schemas import CandidateInput, EvidenceInput, ReviewInput, UsageInput

from conftest import add_signal

BREAKDOWN = {
    "asymmetry": 8, "timing": 8, "pain": 9, "novelty": 7,
    "distribution": 7, "norway_to_global": 8, "capital_efficiency": 9,
}


def _candidate(signal_a, signal_b=None, *, canonical_key="auto-retire-test", update_of_id=None):
    evidence = [EvidenceInput(
        signal_id=signal_a.id, claim="Source reports repeated manual reconciliation work.",
        source_url=signal_a.canonical_url, source_name="Fixture A", directness=0.9, quality=0.8,
    )]
    if signal_b:
        evidence.append(EvidenceInput(
            signal_id=signal_b.id, claim="Independent source confirms the same workflow pain.",
            source_url=signal_b.canonical_url, source_name="Fixture B", directness=0.8, quality=0.8,
        ))
    return CandidateInput(
        canonical_key=canonical_key, kind=OpportunityKind.RANKED,
        title="Automated compliance reconciliation for exporters",
        buyer="Operations managers at small Norwegian exporters handling recurring compliance records.",
        observed_pain="Teams manually reconcile incompatible shipment and compliance records for several hours every week.",
        proposed_wedge="A narrow ingestion and exception-reporting service that starts with Norwegian export documents.",
        why_now="New reporting requirements and better document extraction make a small, focused implementation practical.",
        norway_advantage="Norwegian terminology and direct access to a concentrated initial customer segment.",
        global_path="Expand the same workflow to Nordic and European exporters with equivalent reporting obligations.",
        business_model="Monthly subscription priced per legal entity and document volume.",
        risks=["Incumbent accounting suites may add the feature"],
        validation_effort="One day to interview five operators and manually process sample documents.",
        next_experiment="Recruit five consenting operations managers and measure time saved on one historical reconciliation.",
        score_breakdown=BREAKDOWN, evidence=evidence, update_of_id=update_of_id,
    )


def test_update_of_id_retires_the_original(session, source) -> None:
    """When update_of_id is used, the original opportunity is auto-retired (SUPERSEDED)."""
    second_source = type(source)(key="second", name="Fixture B", kind="procurement", base_url="https://second.test", quality=0.9)
    session.add(second_source)
    session.commit()
    signal_a = add_signal(session, source, "retire-a")
    signal_b = add_signal(session, second_source, "retire-b")
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    run = start_weekly_run(session, settings, datetime.now(timezone.utc))

    original = save_candidate(session, settings, run.id, _candidate(signal_a, signal_b))

    # Agent files an updated version referencing the original
    updated_payload = _candidate(signal_a, signal_b, canonical_key="auto-retire-test-v2", update_of_id=original.id)
    updated = save_candidate(session, settings, run.id, updated_payload)

    session.refresh(original)
    assert original.status == OpportunityStatus.SUPERSEDED
    assert updated.status == OpportunityStatus.NEW
    assert updated.update_of_id == original.id


def test_superseded_opportunities_do_not_count_against_publish_gate(session, source) -> None:
    """Superseded entries are excluded from the publish count limit so updates don't block publication."""
    second_source = type(source)(key="second", name="Fixture B", kind="procurement", base_url="https://second.test", quality=0.9)
    session.add(second_source)
    session.commit()
    signal_a = add_signal(session, source, "pub-a")
    signal_b = add_signal(session, second_source, "pub-b")
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token", max_candidates_per_run=20)
    run = start_weekly_run(session, settings, datetime.now(timezone.utc))

    # Create 5 ranked candidates (the max)
    opps = []
    for i in range(5):
        sig_a = add_signal(session, source, f"pub-ra-{i}")
        sig_b = add_signal(session, second_source, f"pub-rb-{i}")
        opp = save_candidate(session, settings, run.id, _candidate(sig_a, sig_b, canonical_key=f"pub-ranked-{i}"))
        opps.append(opp)

    # Now update one of them — without auto-retire this would create a 6th entry and block publish
    updated_payload = _candidate(signal_a, signal_b, canonical_key="pub-ranked-0-v2", update_of_id=opps[0].id)
    save_candidate(session, settings, run.id, updated_payload)

    # Add reviews for all non-superseded opportunities
    non_retired = session.scalars(
        select(Opportunity).where(Opportunity.run_id == run.id, Opportunity.status != OpportunityStatus.SUPERSEDED)
    ).all()
    for opp in non_retired:
        save_review(session, settings, run.id, opp.id, ReviewInput(role="skeptic", verdict="advance", reasoning="Evidence supports advancement with independent sourcing."))
        save_review(session, settings, run.id, opp.id, ReviewInput(role="judge", verdict="advance", reasoning="Strong candidate with clear pain and executable path forward."))

    # Publish should succeed — superseded entry doesn't count
    published = publish_run(session, settings, run.id, UsageInput(input_tokens=10000, output_tokens=2000, estimated_cost_eur=2.0, model_name="test"))
    assert published.status == RunStatus.PUBLISHED


def test_superseded_opportunities_are_excluded_from_rankings(session, source) -> None:
    """The rankings page should not show superseded opportunities."""
    from starlette.requests import Request
    from edgefinder.main import app, rankings

    signal_a = add_signal(session, source, "rank-a")
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    run = start_weekly_run(session, settings, datetime.now(timezone.utc))

    original = save_candidate(session, settings, run.id, _candidate(signal_a, canonical_key="rank-visible"))
    save_candidate(session, settings, run.id, _candidate(signal_a, canonical_key="rank-v2", update_of_id=original.id))

    request = Request({"type": "http", "method": "GET", "path": "/rankings", "root_path": "", "scheme": "http", "query_string": b"", "headers": [], "server": ("test", 80), "app": app})
    response = rankings(request, session)
    body = response.body.decode()
    assert "rank-v2" not in body.lower() or "Automated compliance reconciliation" in body
    # The superseded original should not appear as a separate entry
    # Count ranking rows — should be 1 (the update), not 2
    assert body.count("ranking-row") == 1
