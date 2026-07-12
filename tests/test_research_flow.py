from __future__ import annotations

from datetime import datetime, timezone

import pytest

from edgefinder.config import Settings
from edgefinder.models import OpportunityKind, OpportunityStatus, RunStatus, Source
from edgefinder.repository import DomainError, add_feedback, get_signal_batch, publish_run, save_candidate, save_review, start_weekly_run
from edgefinder.schemas import CandidateInput, EvidenceInput, FeedbackInput, ReviewInput, UsageInput

from conftest import add_signal


BREAKDOWN = {
    "asymmetry": 8,
    "timing": 8,
    "pain": 9,
    "novelty": 7,
    "distribution": 7,
    "norway_to_global": 8,
    "capital_efficiency": 9,
}


def candidate(signal_a, signal_b, *, kind: OpportunityKind = OpportunityKind.RANKED) -> CandidateInput:
    evidence = [
        EvidenceInput(signal_id=signal_a.id, claim="The first organization reports repeated manual reconciliation work.", source_url=signal_a.canonical_url, source_name="Fixture A", directness=0.9, quality=0.8),
    ]
    if signal_b:
        evidence.append(EvidenceInput(signal_id=signal_b.id, claim="An independent organization describes the same costly workflow.", source_url=signal_b.canonical_url, source_name="Fixture B", directness=0.8, quality=0.8))
    return CandidateInput(
        canonical_key="automated-compliance-reconciliation",
        kind=kind,
        title="Automated compliance reconciliation for small exporters",
        buyer="Operations managers at small Norwegian exporters handling recurring compliance records.",
        observed_pain="Teams manually reconcile incompatible shipment and compliance records for several hours every week.",
        proposed_wedge="A narrow ingestion and exception-reporting service that starts with Norwegian export documents.",
        why_now="New reporting requirements and better document extraction make a small, focused implementation practical.",
        norway_advantage="Norwegian terminology and direct access to a concentrated initial customer segment.",
        global_path="Expand the same workflow to Nordic and European exporters with equivalent reporting obligations.",
        business_model="Monthly subscription priced per legal entity and document volume.",
        risks=["Incumbent accounting suites may add the feature", "Document variance could increase support costs"],
        validation_effort="One day to interview five operators and manually process sample documents.",
        next_experiment="Recruit five consenting operations managers and measure time saved on one historical reconciliation without retaining sensitive documents.",
        score_breakdown=BREAKDOWN,
        evidence=evidence,
    )


def test_end_to_end_research_publication_and_feedback(session, source) -> None:
    second_source = Source(key="fixture-second", name="Fixture B", kind="procurement", base_url="https://second.test", quality=0.9)
    session.add(second_source)
    session.commit()
    signal_a = add_signal(session, source, "a")
    signal_b = add_signal(session, second_source, "b")
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    run = start_weekly_run(session, settings, datetime.now(timezone.utc))
    opportunity = save_candidate(session, settings, run.id, candidate(signal_a, signal_b))
    save_review(session, settings, run.id, opportunity.id, ReviewInput(role="skeptic", verdict="advance", reasoning="Existing tools remain broad and do not cover the narrow document handoff in the cited segment."))
    save_review(session, settings, run.id, opportunity.id, ReviewInput(role="judge", verdict="advance", reasoning="The opportunity has direct pain evidence, a reachable buyer, and a cheap falsifiable first experiment."))
    published = publish_run(session, settings, run.id, UsageInput(input_tokens=10000, output_tokens=2000, estimated_cost_eur=2.4, model_name="fixture-model"))
    assert published.status == RunStatus.PUBLISHED
    assert published.published_at is not None
    updated = add_feedback(session, opportunity.id, FeedbackInput(action=OpportunityStatus.VALIDATE, reason="Reachable buyers"))
    assert updated.status == OpportunityStatus.VALIDATE


def test_publication_gates_independent_evidence_reviews_and_budget(session, source) -> None:
    signal = add_signal(session, source, "only")
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token", weekly_budget_eur=7)
    run = start_weekly_run(session, settings)
    opportunity = save_candidate(session, settings, run.id, candidate(signal, None))
    with pytest.raises(DomainError, match="independent"):
        publish_run(session, settings, run.id, UsageInput())
    save_review(session, settings, run.id, opportunity.id, ReviewInput(role="skeptic", verdict="watch", reasoning="There is only one source and competitor evidence remains incomplete for this candidate."))
    save_review(session, settings, run.id, opportunity.id, ReviewInput(role="judge", verdict="watch", reasoning="Keep this candidate unpublished until direct evidence from another organization appears."))
    with pytest.raises(DomainError, match="budget"):
        publish_run(session, settings, run.id, UsageInput(estimated_cost_eur=8))


def test_only_one_run_can_be_active(session) -> None:
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    start_weekly_run(session, settings)
    with pytest.raises(DomainError, match="already active"):
        start_weekly_run(session, settings)


def test_signal_and_deep_review_limits_are_enforced_in_storage(session, source) -> None:
    signals = [add_signal(session, source, f"limit-{index}") for index in range(12)]
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token", max_signals_per_run=10, max_deep_reviews=1)
    run = start_weekly_run(session, settings)
    first_batch = get_signal_batch(session, run.id, settings, limit=6)
    second_batch = get_signal_batch(session, run.id, settings, limit=6)
    assert len(first_batch) == 6
    assert len(second_batch) == 4
    assert not get_signal_batch(session, run.id, settings, limit=6)
    assert len({item["id"] for item in first_batch + second_batch}) == 10

    first = save_candidate(session, settings, run.id, candidate(signals[0], signals[1]))
    second_payload = candidate(signals[2], signals[3]).model_copy(update={"canonical_key": "second-compliance-reconciliation", "title": "Second compliance reconciliation wedge"})
    second = save_candidate(session, settings, run.id, second_payload)
    save_review(session, settings, run.id, first.id, ReviewInput(role="skeptic", verdict="advance", reasoning="The first candidate receives the one permitted deep-review slot for this constrained run."))
    with pytest.raises(DomainError, match="Deep-review"):
        save_review(session, settings, run.id, second.id, ReviewInput(role="skeptic", verdict="advance", reasoning="The second candidate must be prevented from exceeding the configured deep-review limit."))
