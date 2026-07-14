from __future__ import annotations

import pytest
from conftest import add_signal

from edgefinder.models import JobPick, ResearchRun, RunStatus, utcnow
from edgefinder.repository import DomainError, save_job_picks
from edgefinder.schemas import JobPickInput


@pytest.fixture
def run(session) -> ResearchRun:
    item = ResearchRun(cutoff_at=utcnow(), status=RunStatus.RUNNING)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def test_save_job_picks_replaces_previous_picks(session, source, run) -> None:
    first = add_signal(session, source, "job-1")
    second = add_signal(session, source, "job-2")
    save_job_picks(session, run.id, [JobPickInput(signal_id=first.id, reasoning="Good Indøk data fit.")])
    save_job_picks(session, run.id, [JobPickInput(signal_id=second.id, reasoning="Better fit, earlier deadline.")])
    picks = session.query(JobPick).all()
    assert [pick.signal_id for pick in picks] == [second.id]


def test_save_job_picks_validates_run_count_and_signals(session, source, run) -> None:
    signal = add_signal(session, source, "job-1")
    with pytest.raises(DomainError):
        save_job_picks(session, "missing-run", [JobPickInput(signal_id=signal.id, reasoning="x" * 10)])
    with pytest.raises(DomainError):
        save_job_picks(session, run.id, [JobPickInput(signal_id="missing-signal", reasoning="x" * 10)])
    too_many = [JobPickInput(signal_id=signal.id, reasoning=f"pick {index}") for index in range(6)]
    with pytest.raises(DomainError):
        save_job_picks(session, run.id, too_many)
