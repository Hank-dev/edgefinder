from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from edgefinder.collectors.adapters import (
    AbakusCollector,
    BrregCollector,
    DoffinCollector,
    EuFundingCollector,
    FeedCollector,
    GitHubIssuesCollector,
    HackerNewsCollector,
    Kode24Collector,
    NavJobsCollector,
    StackExchangeCollector,
    TedNorwayCollector,
)
from edgefinder.config import Settings


@pytest.mark.asyncio
async def test_each_public_source_adapter_normalizes_recorded_fixtures() -> None:
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token", github_token="github-public-token", nav_api_token="nav-public-token")

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "feeds.example.test":
            return httpx.Response(200, content=b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Updates</title><item><guid>reg-1</guid><title>New reporting rule</title><link>https://reg.example/rule</link><description>Small firms must change reporting workflows.</description><pubDate>Wed, 08 Jul 2026 08:00:00 GMT</pubDate></item></channel></rss>''')
        if host == "hn.algolia.com":
            return httpx.Response(200, json={"hits": [{"objectID": "hn-1", "title": "Ask HN: manual billing pain", "url": "https://example.com/hn", "story_text": "Operators reconcile billing by hand.", "created_at": "2026-07-08T08:00:00Z", "points": 42, "num_comments": 18}]})
        if host == "api.stackexchange.com":
            return httpx.Response(200, json={"items": [{"question_id": 10, "link": "https://stackoverflow.com/q/10", "title": "Automating a repeated export", "body": "<p>This export is rebuilt manually every day.</p>", "creation_date": 1783497600, "tags": ["automation"], "score": 3, "answer_count": 1}]})
        if host == "api.github.com":
            assert request.headers["Authorization"] == "Bearer github-public-token"
            assert request.url.params["advanced_search"] == "true"
            assert request.url.params["q"].count(" OR ") >= 4
            return httpx.Response(200, json={"items": [{"id": 20, "html_url": "https://github.com/acme/repo/issues/20", "title": "Feature request: reconcile imports", "body": "Our team manually compares every imported row.", "created_at": "2026-07-08T08:00:00Z", "repository_url": "https://api.github.com/repos/acme/repo", "comments": 7}]})
        if host == "data.brreg.no":
            assert request.url.params["organisasjonsform"] == "AS,ENK,ANS,DA"
            return httpx.Response(200, json={"_embedded": {"enheter": [{"organisasjonsnummer": "999999999", "navn": "Norsk Drift AS", "registreringsdatoEnhetsregisteret": "2026-07-08", "naeringskode1": {"beskrivelse": "Tekniske tjenester"}, "forretningsadresse": {"kommune": "OSLO"}}]}})
        if host == "pam-stilling-feed.nav.no":
            assert request.headers["Authorization"] == "Bearer nav-public-token"
            assert request.url.params["last"] == "true"
            fresh = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            return httpx.Response(200, json={"items": [
                {"id": "nav-1", "url": "https://pam-stilling-feed.nav.no/api/v1/feedentry/nav-1", "title": "Stilling: Koordinator", "content_text": "En stilling har blitt publisert.", "date_modified": fresh, "_feed_entry": {"uuid": "nav-1", "status": "ACTIVE", "title": "Koordinator", "businessName": "Eksempel AS", "municipal": "OSLO", "sistEndret": fresh}},
                {"id": "nav-2", "url": "https://pam-stilling-feed.nav.no/api/v1/feedentry/nav-2", "title": "Stilling: Avpublisert", "content_text": "En stilling har blitt avpublisert.", "date_modified": fresh, "_feed_entry": {"uuid": "nav-2", "status": "INACTIVE", "title": "Avpublisert", "businessName": "Borte AS", "municipal": "BERGEN", "sistEndret": fresh}},
                {"id": "nav-3", "url": "https://pam-stilling-feed.nav.no/api/v1/feedentry/nav-3", "title": "Stilling: Gammel", "content_text": "En stilling har blitt publisert.", "date_modified": stale, "_feed_entry": {"uuid": "nav-3", "status": "ACTIVE", "title": "Gammel", "businessName": "Treg AS", "municipal": "TROMSØ", "sistEndret": stale}},
            ], "next_url": None, "next_id": None})
        if host == "api.ted.europa.eu":
            body = json.loads(request.content)
            assert body["paginationMode"] == "PAGE_NUMBER"
            return httpx.Response(200, json={"notices": [{"publication-number": "123456-2026", "notice-title": "Digital saksflyt", "buyer-name": "Norsk kommune", "publication-date": "2026-07-08", "deadline-receipt-tender-date-lot": ["2026-08-17Z"]}]})
        raise AssertionError(f"Unhandled fixture URL {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = [
            await FeedCollector(settings, key="regulations", url="https://feeds.example.test/rss", region="norway", language="no").collect(client),
            await HackerNewsCollector(settings).collect(client),
            await StackExchangeCollector(settings).collect(client),
            await GitHubIssuesCollector(settings).collect(client),
            await BrregCollector(settings).collect(client),
            await NavJobsCollector(settings).collect(client),
            await TedNorwayCollector(settings).collect(client),
        ]
    assert all(len(items) == 1 for items in results)
    assert results[0][0].region == "norway"
    assert results[4][0].language == "no"
    assert results[5][0].external_id == "nav-1"
    assert results[5][0].url == "https://arbeidsplassen.nav.no/stillinger/stilling/nav-1"
    assert results[5][0].region == "norway"
    assert "Eksempel AS" in results[5][0].excerpt
    assert results[6][0].metadata["buyer"] == "Norsk kommune"
    assert results[6][0].deadline_at == datetime(2026, 8, 17, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_doffin_adapter_keeps_only_national_notices_ted_never_carries() -> None:
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.doffin.no"
        body = json.loads(request.content)
        assert body["sortBy"] == "PUBLICATION_DATE_DESC"
        assert body["facets"]["status"]["checkedItems"] == ["ACTIVE"]
        assert body["facets"]["type"]["checkedItems"] == ["COMPETITION"]
        assert body["facets"]["publicationDate"]["from"]
        return httpx.Response(200, json={"numHitsTotal": 2, "hits": [
            {"id": "2026-900001", "heading": "Rammeavtale vintervedlikehold", "description": "Kommunen trenger brøyting av kommunale veier.", "buyer": [{"name": "Eksempel kommune", "organizationId": "999888777"}], "status": "ACTIVE", "type": "ANNOUNCEMENT_OF_COMPETITION", "sentToTed": False, "issueDate": "2026-07-10T09:00:00Z", "publicationDate": "2026-07-10", "deadline": "2026-08-19T10:00:00Z", "estimatedValue": None, "placeOfPerformance": ["Innlandet"]},
            {"id": "2026-900002", "heading": "Stor EU-kontrakt", "description": "Denne finnes også på TED.", "buyer": [{"name": "Stor etat"}], "status": "ACTIVE", "type": "ANNOUNCEMENT_OF_COMPETITION", "sentToTed": True, "issueDate": "2026-07-10T09:00:00Z", "publicationDate": "2026-07-10", "deadline": "2026-08-19T10:00:00Z"},
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await DoffinCollector(settings).collect(client)
    assert len(results) == 1
    signal = results[0]
    assert signal.external_id == "2026-900001"
    assert signal.url == "https://www.doffin.no/notices/2026-900001"
    assert signal.region == "norway"
    assert signal.language == "no"
    assert signal.deadline_at == datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
    assert signal.metadata["buyer"] == "Eksempel kommune"


@pytest.mark.asyncio
async def test_eu_funding_adapter_keeps_open_calls_with_future_deadlines() -> None:
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token")
    future = "2026-10-01T15:00:00.000+0000"
    past = "2026-06-01T15:00:00.000+0000"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.tech.ec.europa.eu"
        assert request.url.params["apiKey"] == "SEDIA"
        return httpx.Response(200, json={"results": [
            {"reference": "ref-1", "summary": "Pilot support for SMB automation", "metadata": {"identifier": ["HORIZON-CL4-2026-DATA-01"], "title": ["Support for trustworthy automation"], "deadlineDate": [future], "startDate": ["2026-07-08T12:00:00.000+0000"], "frameworkProgramme": ["43108390"], "callIdentifier": ["HORIZON-CL4-2026"], "status": ["31094502"]}},
            {"reference": "ref-2", "summary": "Closed call", "metadata": {"identifier": ["HORIZON-OLD-2026"], "title": ["Expired call"], "deadlineDate": [past], "startDate": ["2026-01-08T12:00:00.000+0000"], "frameworkProgramme": ["43108390"], "status": ["31094502"]}},
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await EuFundingCollector(settings).collect(client)
    assert len(results) == 1
    signal = results[0]
    assert signal.external_id == "HORIZON-CL4-2026-DATA-01"
    assert "topic-details/horizon-cl4-2026-data-01" in signal.url
    assert signal.deadline_at == datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
    assert signal.region == "europe"
    assert signal.metadata["call"] == "HORIZON-CL4-2026"


@pytest.mark.asyncio
async def test_nav_naive_timestamps_are_read_as_oslo_wall_time_not_utc() -> None:
    from zoneinfo import ZoneInfo

    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token", nav_api_token="nav-public-token")
    oslo = ZoneInfo("Europe/Oslo")
    naive = (datetime.now(oslo) - timedelta(hours=3)).replace(tzinfo=None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [
            {"id": "nav-9", "title": "Stilling", "_feed_entry": {"uuid": "nav-9", "status": "ACTIVE", "title": "Utvikler", "businessName": "Fersk AS", "municipal": "OSLO", "sistEndret": naive.isoformat()}},
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await NavJobsCollector(settings).collect(client)
    assert len(results) == 1
    assert results[0].observed_at == naive.replace(tzinfo=oslo)
    assert results[0].observed_at <= datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_nav_adapter_fails_closed_without_public_feed_token() -> None:
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token", nav_api_token=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        with pytest.raises(RuntimeError, match="NAV_API_TOKEN"):
            await NavJobsCollector(settings).collect(client)


@pytest.mark.asyncio
async def test_collection_stores_aware_timestamps_as_utc_wall_time(session, source) -> None:
    from zoneinfo import ZoneInfo

    from edgefinder.collectors.base import BaseCollector, RawSignal
    from edgefinder.collectors.service import collect_all
    from edgefinder.models import Signal
    from sqlalchemy import select

    class StubCollector(BaseCollector):
        key = "fixture-source"

        async def collect(self, client):
            aware = datetime(2026, 7, 13, 13, 34, tzinfo=ZoneInfo("Europe/Oslo"))
            return [RawSignal("stub-1", "https://example.com/stub", "Stub title", "Stub excerpt for storage.", aware, deadline_at=aware)]

    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token")
    await collect_all(session, settings, [StubCollector(settings)])
    session.expire_all()
    stored = session.scalar(select(Signal).where(Signal.external_id == "stub-1"))
    assert stored.observed_at.replace(tzinfo=None) == datetime(2026, 7, 13, 11, 34)
    assert stored.deadline_at.replace(tzinfo=None) == datetime(2026, 7, 13, 11, 34)


@pytest.mark.asyncio
async def test_feed_collector_retries_once_when_rate_limited() -> None:
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token")
    rss = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Sub</title><item><guid>p-1</guid><title>Anyone else drowning in invoices?</title><link>https://reddit.example/p1</link><description>Manual invoicing again.</description><pubDate>Sun, 12 Jul 2026 08:00:00 GMT</pubDate></item></channel></rss>'''
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=rss)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await FeedCollector(settings, key="reddit", url="https://reddit.example/new/.rss", region="global", language="en").collect(client)
    assert attempts == 2
    assert len(results) == 1


@pytest.mark.asyncio
async def test_feed_collector_keeps_entries_without_a_description() -> None:
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token")
    rss = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>OJ L</title><item><guid>oj-1</guid><title>Commission Implementing Regulation (EU) 2026/999</title><link>https://eur-lex.example/reg/2026/999</link><description/><pubDate>Wed, 08 Jul 2026 08:00:00 GMT</pubDate></item></channel></rss>'''
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=rss))) as client:
        results = await FeedCollector(settings, key="eurlex", url="https://eur-lex.example/feed", region="europe", language="en").collect(client)
    assert len(results) == 1
    assert results[0].excerpt == "Commission Implementing Regulation (EU) 2026/999"


@pytest.mark.asyncio
async def test_abakus_adapter_normalizes_job_listings_and_drops_expired_deadlines() -> None:
    # Fixture mirrors the live https://lego.abakus.no/api/v1/joblistings/ response observed
    # 2026-07-14: cursor-paginated {next, previous, results[]}; each result has company.name,
    # workplaces[].town, deadline (ISO8601 with trailing Z), and jobType (e.g. "full_time").
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token")
    future = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "lego.abakus.no"
        return httpx.Response(200, json={"next": None, "previous": None, "results": [
            {"id": 21, "title": "Graduate Developer", "slug": "21-graduate-developer", "company": {"id": 1, "name": "Data AS"}, "deadline": future, "jobType": "full_time", "workplaces": [{"id": 1, "town": "Oslo"}]},
            {"id": 22, "title": "Utgått stilling", "slug": "22-utgatt-stilling", "company": {"id": 2, "name": "Gammel AS"}, "deadline": past, "jobType": "part_time", "workplaces": [{"id": 2, "town": "Bergen"}]},
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await AbakusCollector(settings).collect(client)
    assert [item.external_id for item in results] == ["21"]  # expired deadline dropped
    signal = results[0]
    assert signal.url == "https://abakus.no/joblistings/21"
    assert signal.metadata["employer"] == "Data AS"
    assert signal.metadata["municipality"] == "Oslo"
    assert signal.metadata["source_board"] == "Abakus"
    assert signal.metadata["status"] == "ACTIVE"
    assert signal.metadata["job_type"] == "full_time"
    assert signal.deadline_at is not None
    assert signal.region == "norway"
    assert signal.language == "no"


@pytest.mark.asyncio
async def test_kode24_adapter_parses_job_cards() -> None:
    # Fixture mirrors the live board observed 2026-07-14: https://www.kode24.no/jobb
    # 302-redirects to https://www.kodejobb.no, which 308-redirects to https://kodejobb.no/
    # (a Next.js app). The homepage only samples 4 jobs; the full board lives at
    # https://kodejobb.no/stillinger (21 postings observed, server-rendered, no JSON
    # endpoint found). Each card is <li class="job-list-item">...<a href="/stillinger/
    # {employer-slug}/{uuid}">, with .job-title-from-customer (real job title),
    # .job-company-name (employer), and .job-location holding two duplicate spans
    # (light/dark mode) each following an inline <svg> icon before the plain-text city.
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token")
    html = (
        '<li class="job-list-item bg-gray-50 dark:bg-gray-800 rounded-lg relative">'
        '<a class="flex flex-col justify-between h-full" '
        'href="/stillinger/eksempel-as/11111111-1111-1111-1111-111111111111">'
        '<div class="job-title-from-customer text-2xl dark:text-gray-50 font-semibold">Senior utvikler</div>'
        '<div class="job-company-name font dark:text-gray-400 mb-4">Eksempel AS</div>'
        '<div class="job-location comma-separated-list flex flex-wrap gap-2">'
        '<span class="p-2 dark:hidden"><span class="text-pink-500">'
        '<svg viewBox="0 0 24 24"><path d="M1"></path></svg></span>Oslo</span>'
        '<span class="p-2 hidden dark:flex"><span class="text-pink-500">'
        '<svg viewBox="0 0 24 24"><path d="M1"></path></svg></span>Oslo</span>'
        "</div></a></li>"
        '<li class="job-list-item bg-gray-50 dark:bg-gray-800 rounded-lg relative">'
        '<a class="flex flex-col justify-between h-full" '
        'href="/stillinger/data-as/22222222-2222-2222-2222-222222222222">'
        '<div class="job-title-from-customer text-2xl dark:text-gray-50 font-semibold">Data engineer</div>'
        '<div class="job-company-name font dark:text-gray-400 mb-4">Data AS</div>'
        '<div class="job-location comma-separated-list flex flex-wrap gap-2">'
        '<span class="p-2 dark:hidden"><span class="text-pink-500">'
        '<svg viewBox="0 0 24 24"><path d="M1"></path></svg></span>Trondheim</span>'
        '<span class="p-2 hidden dark:flex"><span class="text-pink-500">'
        '<svg viewBox="0 0 24 24"><path d="M1"></path></svg></span>Trondheim</span>'
        "</div></a></li>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "kodejobb.no"
        return httpx.Response(200, text=html)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await Kode24Collector(settings).collect(client)
    assert [item.external_id for item in results] == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    assert results[0].url == "https://kodejobb.no/stillinger/eksempel-as/11111111-1111-1111-1111-111111111111"
    assert results[1].url == "https://kodejobb.no/stillinger/data-as/22222222-2222-2222-2222-222222222222"
    assert results[0].metadata["employer"] == "Eksempel AS"
    assert results[1].metadata["municipality"] == "Trondheim"
    assert all(item.metadata["source_board"] == "kode24" for item in results)
    assert all(item.language == "no" and item.region == "norway" for item in results)
