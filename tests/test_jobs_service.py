from __future__ import annotations

import pytest
from helpers import make_job, make_job_source

from edgefinder.config import Settings
from edgefinder.jobs.service import CLUSTER_SLUGS, build_talent_view, set_job_status
from edgefinder.models import JobStatusValue
from edgefinder.repository import DomainError


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(agent_token="test-agent-token", internal_token="test-internal-token", jobs_profile_path=tmp_path / "no-profile.yaml")


def test_same_job_on_two_boards_collapses_to_highest_quality_primary(session, settings) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    hub = make_job_source(session, "thehub", 0.85)
    make_job(session, nav, "n1", "Data Engineer", "Eksempel AS", board="NAV")
    make_job(session, hub, "h1", "Data Engineer", "Eksempel AS", board="The Hub")
    view = build_talent_view(session, settings)
    assert view.total_jobs == 1
    row = view.rows[0]
    assert row.source_board == "NAV"
    assert row.also_on == ["The Hub"]


def test_dismissed_fingerprint_vanishes_from_feed_and_counts(session, settings) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    keep = make_job(session, nav, "n1", "Data Engineer", "Eksempel AS")
    drop = make_job(session, nav, "n2", "Regnskapsfører", "Tall AS")
    set_job_status(session, drop.fingerprint, JobStatusValue.DISMISSED)
    view = build_talent_view(session, settings)
    assert [row.signal_id for row in view.rows] == [keep.id]
    assert view.total_jobs == 1


def test_expired_deadline_and_inactive_rows_are_excluded(session, settings) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    make_job(session, nav, "n1", "Analyst", "Eksempel AS", deadline_days=-1)
    make_job(session, nav, "n2", "Utvikler", "Eksempel AS", status="INACTIVE")
    live = make_job(session, nav, "n3", "Data Engineer", "Eksempel AS", deadline_days=10)
    view = build_talent_view(session, settings)
    assert [row.signal_id for row in view.rows] == [live.id]
    assert view.rows[0].days_left == 10


def test_deadlines_tab_sorts_soonest_first(session, settings) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    late = make_job(session, nav, "n1", "Analyst", "A AS", deadline_days=20)
    soon = make_job(session, nav, "n2", "Konsulent", "B AS", deadline_days=3)
    make_job(session, nav, "n3", "Utvikler", "C AS")  # no deadline
    view = build_talent_view(session, settings, tab="deadlines")
    assert [row.signal_id for row in view.rows] == [soon.id, late.id]


def test_applied_tab_lists_tracked_jobs_and_tab_count(session, settings) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    job = make_job(session, nav, "n1", "Data Engineer", "Eksempel AS")
    make_job(session, nav, "n2", "Analyst", "Annet AS")
    set_job_status(session, job.fingerprint, JobStatusValue.APPLIED, note="sent 12 July")
    view = build_talent_view(session, settings, tab="applied")
    assert [row.signal_id for row in view.rows] == [job.id]
    assert view.rows[0].status == "applied"
    assert view.tab_counts["applied"] == 1


def test_cluster_tab_and_skill_filter(session, settings) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    make_job(session, nav, "n1", "Regnskapsfører", "Tall AS", skills_text="")  # Finance & Econ via 'regnskapsfører'
    tech = make_job(session, nav, "n2", "Data Engineer", "Eksempel AS")  # Python/SQL in excerpt
    slug = CLUSTER_SLUGS["Data & ML"]
    view = build_talent_view(session, settings, tab=slug)
    assert tech.id in [row.signal_id for row in view.rows]
    filtered = build_talent_view(session, settings, skill_filter="sql")
    assert [row.signal_id for row in filtered.rows] == [tech.id]


def test_profile_missing_flag_and_uniform_scores(session, settings) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    make_job(session, nav, "n1", "Data Engineer", "Eksempel AS")
    view = build_talent_view(session, settings)
    assert view.profile_missing is True
    assert view.rows[0].relevance == 50.0


def test_set_job_status_upserts_and_rejects_unknown_fingerprint(session, settings) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    job = make_job(session, nav, "n1", "Data Engineer", "Eksempel AS")
    first = set_job_status(session, job.fingerprint, JobStatusValue.INTERESTED)
    second = set_job_status(session, job.fingerprint, JobStatusValue.APPLIED)
    assert first.id == second.id
    assert second.status is JobStatusValue.APPLIED
    with pytest.raises(DomainError):
        set_job_status(session, "0000000000000000", JobStatusValue.APPLIED)
