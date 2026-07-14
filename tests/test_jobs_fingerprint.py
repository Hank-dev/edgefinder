from __future__ import annotations

from edgefinder.models import JobPick, JobStatus, JobStatusValue, Signal
from edgefinder.normalization import job_fingerprint


def test_fingerprint_normalizes_employer_and_title_variants() -> None:
    base = job_fingerprint("Eksempel AS", "Data Engineer")
    assert base is not None and len(base) == 16
    assert job_fingerprint("eksempel", "data engineer") == base
    assert job_fingerprint("Eksempel AS.", "Data Engineer (Oslo)") == base
    assert job_fingerprint("Eksempel ASA", "Data Engineer 100 %") == base


def test_fingerprint_requires_employer_and_title() -> None:
    assert job_fingerprint(None, "Data Engineer") is None
    assert job_fingerprint("Eksempel AS", None) is None
    assert job_fingerprint("AS", "100 %") is None  # nothing left after normalization


def test_fingerprint_distinguishes_different_jobs() -> None:
    left = job_fingerprint("Eksempel AS", "Data Engineer")
    assert left != job_fingerprint("Eksempel AS", "Frontend Developer")
    assert left != job_fingerprint("Annet Firma AS", "Data Engineer")


def test_new_models_roundtrip(session, source) -> None:
    from conftest import add_signal  # repo convention, see tests/test_research_flow.py

    signal = add_signal(session, source, "job-1")
    signal.fingerprint = "abcdef0123456789"
    session.add(JobStatus(fingerprint="abcdef0123456789", status=JobStatusValue.APPLIED, note="sent CV"))
    session.commit()
    row = session.query(JobStatus).one()
    assert row.status is JobStatusValue.APPLIED
    assert session.query(Signal).filter(Signal.fingerprint == "abcdef0123456789").count() == 1
