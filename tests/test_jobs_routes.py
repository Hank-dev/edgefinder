from __future__ import annotations

import pytest
from fastapi import HTTPException

from helpers import make_job, make_job_source

from edgefinder.jobs.routes import talent, update_job_status
from edgefinder.main import app
from edgefinder.models import JobStatus, JobStatusValue
from edgefinder.webutil import CSRF_TOKEN


def _request(query: str = ""):
    from starlette.requests import Request

    return Request({"type": "http", "method": "GET", "path": "/talent", "root_path": "", "scheme": "http", "query_string": query.encode(), "headers": [], "server": ("test", 80), "app": app})


def test_talent_page_renders_ranked_feed_with_dedupe_chip(session) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    hub = make_job_source(session, "thehub", 0.85)
    make_job(session, nav, "n1", "Data Engineer", "Eksempel AS", board="NAV")
    make_job(session, hub, "h1", "Data Engineer", "Eksempel AS", board="The Hub")
    response = talent(_request(), session)
    assert response.status_code == 200
    body = response.body.decode()
    assert "Data Engineer" in body
    assert "The Hub" in body        # dedupe chip
    assert "relevance" in body.lower() or "score" in body.lower()


def test_tracker_post_upserts_and_redirects(session) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    job = make_job(session, nav, "n1", "Data Engineer", "Eksempel AS")
    response = update_job_status(job.fingerprint, status="applied", csrf_token=CSRF_TOKEN, back="/talent?tab=all", session=session)
    assert response.status_code == 303
    assert response.headers["location"] == "/talent?tab=all"
    assert session.query(JobStatus).one().status is JobStatusValue.APPLIED


def test_tracker_post_rejects_bad_csrf_and_unknown_fingerprint(session) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    job = make_job(session, nav, "n1", "Data Engineer", "Eksempel AS")
    with pytest.raises(HTTPException) as forbidden:
        update_job_status(job.fingerprint, status="applied", csrf_token="wrong", back="/talent", session=session)
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as missing:
        update_job_status("0000000000000000", status="applied", csrf_token=CSRF_TOKEN, back="/talent", session=session)
    assert missing.value.status_code == 404


def test_tracker_post_sanitizes_redirect_target(session) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    job = make_job(session, nav, "n1", "Data Engineer", "Eksempel AS")
    response = update_job_status(job.fingerprint, status="dismissed", csrf_token=CSRF_TOKEN, back="https://evil.example/", session=session)
    assert response.headers["location"] == "/talent"


def test_dismissed_job_disappears_from_next_render(session) -> None:
    nav = make_job_source(session, "nav-jobs", 0.9)
    job = make_job(session, nav, "n1", "Data Engineer", "Eksempel AS")
    update_job_status(job.fingerprint, status="dismissed", csrf_token=CSRF_TOKEN, back="/talent", session=session)
    body = talent(_request(), session).body.decode()
    assert "Data Engineer" not in body
