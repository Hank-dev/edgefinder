from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from edgefinder.config import Settings
from edgefinder.models import OpportunityKind, OpportunityStatus, RunStatus, Source
from edgefinder.repository import DomainError, add_feedback, get_signal_batch, operator_context, publish_run, save_candidate, save_review, start_weekly_run
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


def test_stale_active_run_is_auto_failed_so_the_weekly_cadence_survives_a_crash(session) -> None:
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token", max_run_age_hours=48)
    stale = start_weekly_run(session, settings)
    stale.started_at = datetime.now(timezone.utc) - timedelta(hours=49)
    session.commit()
    fresh = start_weekly_run(session, settings)
    session.refresh(stale)
    assert fresh.id != stale.id
    assert stale.status == RunStatus.FAILED
    assert "expired" in (stale.error or "")


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


def test_signal_batches_mix_sources_so_a_high_volume_feed_cannot_starve_the_others(session) -> None:
    flood = Source(key="flood-registry", name="Flood registry", kind="registry", region="norway", base_url="https://flood.test", quality=0.95)
    sparse = Source(key="sparse-jobs", name="Sparse jobs", kind="jobs", region="norway", base_url="https://sparse.test", quality=0.9)
    session.add_all([flood, sparse])
    session.commit()
    for index in range(30):
        add_signal(session, flood, f"flood-{index}")
    for index in range(2):
        add_signal(session, sparse, f"sparse-{index}")
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    run = start_weekly_run(session, settings)
    batch = get_signal_batch(session, run.id, settings, limit=10)
    assert len(batch) == 10
    by_source = {item["source_name"] for item in batch}
    assert by_source == {"Flood registry", "Sparse jobs"}
    assert sum(1 for item in batch if item["source_name"] == "Sparse jobs") == 2


def test_labor_lane_catches_pain_phrasings_beyond_workflow_and_manual(session, source) -> None:
    from edgefinder.models import Signal
    from edgefinder.normalization import content_hash

    title = "Tedious weekly reporting eats our Fridays"
    excerpt = "Every Friday the team rebuilds the same spreadsheet from three systems."
    item = Signal(
        source_id=source.id,
        external_id="tedious-1",
        canonical_url="https://example.com/signals/tedious-1",
        title=title,
        excerpt=excerpt,
        language="en",
        region="global",
        observed_at=datetime.now(timezone.utc),
        content_hash=content_hash(title, excerpt),
    )
    session.add(item)
    session.commit()
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    run = start_weekly_run(session, settings)
    batch = get_signal_batch(session, run.id, settings, lane="labor")
    assert [entry["title"] for entry in batch] == [title]


def test_seed_sources_disables_sources_that_leave_the_configuration(session) -> None:
    from edgefinder.repository import seed_sources

    first = {"key": "keeper", "name": "Keeper", "kind": "community", "region": "global", "base_url": "https://keep.test", "quality": 0.6}
    second = {"key": "leaver", "name": "Leaver", "kind": "community", "region": "global", "base_url": "https://leave.test", "quality": 0.6}
    seed_sources(session, [first, second])
    seed_sources(session, [first])
    keeper = session.scalar(select(Source).where(Source.key == "keeper"))
    leaver = session.scalar(select(Source).where(Source.key == "leaver"))
    assert keeper.enabled is True
    assert leaver.enabled is False


def test_funding_lane_returns_grants_and_tenders_together(session, source) -> None:
    funding = Source(key="grants", name="Grants", kind="funding", region="europe", base_url="https://grants.test", quality=0.9)
    tenders = Source(key="tenders", name="Tenders", kind="procurement", region="norway", base_url="https://tenders.test", quality=0.9)
    session.add_all([funding, tenders])
    session.commit()
    add_signal(session, funding, "grant-1")
    add_signal(session, tenders, "tender-1")
    add_signal(session, source, "community-1")
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    run = start_weekly_run(session, settings)
    batch = get_signal_batch(session, run.id, settings, lane="funding")
    assert {item["source_name"] for item in batch} == {"Grants", "Tenders"}


def test_deadlines_flow_from_signal_batches_to_saved_candidates(session, source) -> None:
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    deadline = datetime.now(timezone.utc) + timedelta(days=21)
    signal = add_signal(session, source, "tender")
    signal.deadline_at = deadline
    session.commit()
    run = start_weekly_run(session, settings)
    batch = get_signal_batch(session, run.id, settings)
    assert batch[0]["deadline_at"] == deadline.isoformat()
    from zoneinfo import ZoneInfo

    payload = candidate(signal, None).model_copy(update={"deadline_at": deadline.astimezone(ZoneInfo("Europe/Oslo"))})
    opportunity = save_candidate(session, settings, run.id, payload)
    session.expire_all()
    stored = opportunity.deadline_at if opportunity.deadline_at.tzinfo else opportunity.deadline_at.replace(tzinfo=timezone.utc)
    assert stored == deadline


def test_judge_score_delta_adjusts_the_stored_opportunity_score(session, source) -> None:
    signal = add_signal(session, source, "delta")
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    run = start_weekly_run(session, settings)
    opportunity = save_candidate(session, settings, run.id, candidate(signal, None))
    original = opportunity.score
    save_review(session, settings, run.id, opportunity.id, ReviewInput(role="judge", verdict="revise", reasoning="Adoption friction is higher than the synthesizer assumed, so the attractiveness must come down.", score_delta=-10))
    session.refresh(opportunity)
    assert opportunity.score == pytest.approx(original - 10)
    save_review(session, settings, run.id, opportunity.id, ReviewInput(role="skeptic", verdict="advance", reasoning="Skeptic deltas must not move the score because only the judge owns calibration.", score_delta=-10))
    session.refresh(opportunity)
    assert opportunity.score == pytest.approx(original - 10)


def test_operator_context_reports_profile_and_per_source_feedback_track_record(session, source) -> None:
    signal = add_signal(session, source, "ctx")
    settings = Settings(
        database_url="sqlite:////tmp/edgefinder-tests.db",
        agent_token="test-agent-token",
        internal_token="test-internal-token",
        operator_profile="Solo full-stack developer in Oslo, 10 hours per week, no starting capital.",
    )
    run = start_weekly_run(session, settings)
    opportunity = save_candidate(session, settings, run.id, candidate(signal, None))
    add_feedback(session, opportunity.id, FeedbackInput(action=OpportunityStatus.VALIDATE, reason="Executable solo"))
    context = operator_context(session, settings)
    assert context["operator_profile"].startswith("Solo full-stack developer")
    assert context["source_track_record"] == [{"source_name": "Fixture Source", "validated": 1, "rejected": 0, "other": 0}]
    assert context["recent_feedback"][0]["action"] == "validate"


def test_candidate_referencing_unknown_prior_opportunity_is_a_domain_error(session, source) -> None:
    signal = add_signal(session, source, "update-ref")
    settings = Settings(database_url="sqlite:////tmp/edgefinder-tests.db", agent_token="test-agent-token", internal_token="test-internal-token")
    run = start_weekly_run(session, settings)
    payload = candidate(signal, None).model_copy(update={"update_of_id": "does-not-exist"})
    with pytest.raises(DomainError, match="update_of_id"):
        save_candidate(session, settings, run.id, payload)
