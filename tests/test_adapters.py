from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from edgefinder.collectors.adapters import (
    BrregCollector,
    FeedCollector,
    GitHubIssuesCollector,
    HackerNewsCollector,
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
            return httpx.Response(200, json={"items": [{"id": 20, "html_url": "https://github.com/acme/repo/issues/20", "title": "Feature request: reconcile imports", "body": "Our team manually compares every imported row.", "created_at": "2026-07-08T08:00:00Z", "repository_url": "https://api.github.com/repos/acme/repo", "comments": 7}]})
        if host == "data.brreg.no":
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
            return httpx.Response(200, json={"notices": [{"publication-number": "123456-2026", "notice-title": "Digital saksflyt", "buyer-name": "Norsk kommune", "publication-date": "2026-07-08"}]})
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


@pytest.mark.asyncio
async def test_nav_adapter_fails_closed_without_public_feed_token() -> None:
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token", nav_api_token=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
        with pytest.raises(RuntimeError, match="NAV_API_TOKEN"):
            await NavJobsCollector(settings).collect(client)


@pytest.mark.asyncio
async def test_feed_collector_keeps_entries_without_a_description() -> None:
    settings = Settings(agent_token="test-agent-token", internal_token="test-internal-token")
    rss = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>OJ L</title><item><guid>oj-1</guid><title>Commission Implementing Regulation (EU) 2026/999</title><link>https://eur-lex.example/reg/2026/999</link><description/><pubDate>Wed, 08 Jul 2026 08:00:00 GMT</pubDate></item></channel></rss>'''
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=rss))) as client:
        results = await FeedCollector(settings, key="eurlex", url="https://eur-lex.example/feed", region="europe", language="en").collect(client)
    assert len(results) == 1
    assert results[0].excerpt == "Commission Implementing Regulation (EU) 2026/999"
