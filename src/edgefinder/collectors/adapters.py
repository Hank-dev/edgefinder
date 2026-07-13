from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import feedparser
import httpx

from edgefinder.normalization import clean_text

from .base import BaseCollector, RawSignal


def earliest_deadline(values: Any) -> datetime | None:
    """TED lot deadlines arrive as date strings like '2026-08-17Z'; keep the earliest."""
    if not isinstance(values, list):
        values = [values] if values else []
    parsed: list[datetime] = []
    for value in values:
        text = str(value or "").strip().rstrip("Z")
        if not text:
            continue
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            continue
        parsed.append(result if result.tzinfo else result.replace(tzinfo=timezone.utc))
    return min(parsed, default=None)


def localized_text(value: Any) -> str:
    """Pick a useful scalar from TED's multilingual field shapes."""
    if isinstance(value, dict):
        for language in ("nor", "nob", "nno", "eng"):
            if language in value:
                return localized_text(value[language])
        return localized_text(next(iter(value.values()), ""))
    if isinstance(value, list):
        return localized_text(value[0]) if value else ""
    return str(value or "")


class FeedCollector(BaseCollector):
    def __init__(self, settings, *, key: str, url: str, region: str, language: str = "und") -> None:
        super().__init__(settings)
        self.key = key
        self.url = url
        self.region = region
        self.language = language

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        response = await client.get(self.url)
        if response.status_code == 429:
            # Unauthenticated feed hosts (notably Reddit) allow roughly one request per few seconds per IP.
            retry_after = min(float(response.headers.get("Retry-After", 10) or 10), 15.0)
            await asyncio.sleep(retry_after)
            response = await client.get(self.url)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise ValueError(f"Invalid feed: {getattr(parsed, 'bozo_exception', 'unknown error')}")
        results: list[RawSignal] = []
        for entry in parsed.entries[:100]:
            url = entry.get("link", "")
            title = clean_text(entry.get("title", "Untitled"), limit=500)
            excerpt = clean_text(entry.get("summary", entry.get("description", ""))) or title
            identifier = str(entry.get("id") or url or hashlib.sha256(title.encode()).hexdigest())
            published = entry.get("published") or entry.get("updated")
            try:
                observed = parsedate_to_datetime(published) if published else datetime.now(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                observed = datetime.now(timezone.utc)
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            if url and excerpt:
                results.append(RawSignal(identifier, url, title, excerpt, observed, self.language, self.region))
        return results


class HackerNewsCollector(BaseCollector):
    key = "hacker-news"

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        since = int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp())
        response = await client.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"tags": "story", "numericFilters": f"created_at_i>{since}", "hitsPerPage": 100},
        )
        response.raise_for_status()
        results = []
        for item in response.json().get("hits", []):
            object_id = str(item.get("objectID", ""))
            title = clean_text(item.get("title") or "Untitled", limit=500)
            story_url = item.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
            excerpt = clean_text(item.get("story_text") or f"Hacker News discussion: {title}")
            results.append(
                RawSignal(object_id, story_url, title, excerpt, self.timestamp(item.get("created_at")), "en", "global", {"points": item.get("points"), "comments": item.get("num_comments")})
            )
        return results


class StackExchangeCollector(BaseCollector):
    key = "stack-overflow"

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        since = int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp())
        response = await client.get(
            "https://api.stackexchange.com/2.3/questions",
            params={"site": "stackoverflow", "order": "desc", "sort": "activity", "fromdate": since, "pagesize": 60, "filter": "withbody"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error_message"):
            raise ValueError(payload["error_message"])
        return [
            RawSignal(
                str(item["question_id"]),
                item["link"],
                clean_text(item["title"], limit=500),
                clean_text(item.get("body", "")),
                self.timestamp(item.get("creation_date")),
                "en",
                "global",
                {"tags": item.get("tags", []), "score": item.get("score", 0), "answers": item.get("answer_count", 0)},
            )
            for item in payload.get("items", [])
        ]


class GitHubIssuesCollector(BaseCollector):
    key = "github-issues"

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        since = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        response = await client.get(
            "https://api.github.com/search/issues",
            params={"q": f'is:issue created:>={since} ("manual workflow" OR "manual process" OR "pain point" OR "feature request" OR "tedious")', "advanced_search": "true", "sort": "comments", "order": "desc", "per_page": 50},
            headers=headers,
        )
        response.raise_for_status()
        return [
            RawSignal(
                str(item["id"]),
                item["html_url"],
                clean_text(item["title"], limit=500),
                clean_text(item.get("body") or "No description supplied"),
                self.timestamp(item.get("created_at")),
                "en",
                "global",
                {"repository_url": item.get("repository_url"), "comments": item.get("comments", 0)},
            )
            for item in response.json().get("items", [])
        ]


class ArxivCollector(FeedCollector):
    def __init__(self, settings) -> None:
        query = quote_plus("cat:cs.AI OR cat:cs.CY OR cat:econ.GN")
        super().__init__(
            settings,
            key="arxiv",
            url=f"https://export.arxiv.org/api/query?search_query={query}&start=0&max_results=40&sortBy=submittedDate&sortOrder=descending",
            region="global",
            language="en",
        )


class BrregCollector(BaseCollector):
    key = "brreg"

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        response = await client.get(
            "https://data.brreg.no/enhetsregisteret/api/enheter",
            # Company forms only; keeps housing co-ops, condo boards, and associations out of the lane.
            params={"size": 50, "sort": "registreringsdatoEnhetsregisteret,desc", "organisasjonsform": "AS,ENK,ANS,DA"},
        )
        response.raise_for_status()
        entities = response.json().get("_embedded", {}).get("enheter", [])
        results = []
        for item in entities:
            orgnr = str(item.get("organisasjonsnummer", ""))
            name = item.get("navn", "Ukjent virksomhet")
            industry = (item.get("naeringskode1") or {}).get("beskrivelse", "ukjent næring")
            municipality = (item.get("forretningsadresse") or {}).get("kommune", "Norge")
            results.append(
                RawSignal(
                    orgnr,
                    f"https://virksomhet.brreg.no/nb/oppslag/enheter/{orgnr}",
                    f"Nyregistrert virksomhet: {name}",
                    f"{name} er registrert innen {industry} i {municipality}.",
                    self.timestamp(item.get("registreringsdatoEnhetsregisteret")),
                    "no",
                    "norway",
                    {"industry": industry, "municipality": municipality},
                )
            )
        return results


class NavJobsCollector(BaseCollector):
    """Reads the newest page of NAV's pam-stilling-feed (the public-feed API was retired May 2025)."""

    key = "nav-jobs"

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        if not self.settings.nav_api_token:
            raise RuntimeError(
                "NAV_API_TOKEN is not configured; fetch the experimental token from "
                "https://pam-stilling-feed.nav.no/api/publicToken or request a private one from NAV"
            )
        response = await client.get(
            "https://pam-stilling-feed.nav.no/api/v1/feed",
            params={"last": "true"},
            headers={"Authorization": f"Bearer {self.settings.nav_api_token}"},
        )
        response.raise_for_status()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        results = []
        for item in response.json().get("items", []):
            entry = item.get("_feed_entry") or {}
            if entry.get("status") != "ACTIVE":
                continue
            # sistEndret is Oslo wall time serialized without an offset; reading it as UTC pushes fresh ads into the future.
            observed = self.timestamp(entry.get("sistEndret") or item.get("date_modified"), naive_tz=ZoneInfo("Europe/Oslo"))
            if observed < cutoff:
                continue
            identifier = str(entry.get("uuid") or item.get("id"))
            title = clean_text(entry.get("title") or item.get("title") or "Ukjent stilling", limit=500)
            employer = entry.get("businessName") or "ukjent arbeidsgiver"
            municipality = entry.get("municipal") or "Norge"
            excerpt = clean_text(f"{title} hos {employer} i {municipality}.")
            results.append(
                RawSignal(
                    identifier,
                    f"https://arbeidsplassen.nav.no/stillinger/stilling/{identifier}",
                    title,
                    excerpt,
                    observed,
                    "no",
                    "norway",
                    {"employer": employer, "municipality": municipality},
                )
            )
        return results


class DoffinCollector(BaseCollector):
    """Reads Doffin's public search backend for the national notices TED never carries (below EEA thresholds)."""

    key = "doffin"

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        response = await client.post(
            "https://api.doffin.no/webclient/api/v2/search-api/search",
            json={
                "numHitsPerPage": 100,
                "page": 1,
                "searchString": "",
                "sortBy": "PUBLICATION_DATE_DESC",
                "facets": {
                    "publicationDate": {"from": since, "to": None},
                    "status": {"checkedItems": ["ACTIVE"]},
                    "type": {"checkedItems": ["COMPETITION"]},
                },
            },
        )
        response.raise_for_status()
        results = []
        for item in response.json().get("hits", []):
            if item.get("sentToTed"):
                continue
            notice_id = str(item.get("id"))
            buyers = item.get("buyer") or []
            buyer = (buyers[0].get("name") if buyers and isinstance(buyers[0], dict) else None) or "Ukjent oppdragsgiver"
            title = clean_text(item.get("heading") or "Kunngjøring", limit=500)
            excerpt = clean_text(item.get("description") or "") or f"Kunngjøring fra {buyer}."
            results.append(
                RawSignal(
                    notice_id,
                    f"https://www.doffin.no/notices/{notice_id}",
                    title,
                    excerpt,
                    self.timestamp(item.get("issueDate") or item.get("publicationDate")),
                    "no",
                    "norway",
                    {"buyer": buyer, "estimated_value": item.get("estimatedValue"), "place": item.get("placeOfPerformance")},
                    deadline_at=earliest_deadline(item.get("deadline")),
                )
            )
        return results


class EuFundingCollector(BaseCollector):
    """Reads open Horizon Europe and Digital Europe calls (programmes Norway participates in) from the EU Funding & Tenders portal."""

    key = "eu-funding"
    PROGRAMMES = ["43108390", "43152860"]  # HORIZON, DIGITAL

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        query = {
            "bool": {
                "must": [
                    {"terms": {"type": ["1", "2"]}},
                    {"terms": {"status": ["31094502"]}},  # open for submission
                    {"terms": {"frameworkProgramme": self.PROGRAMMES}},
                ]
            }
        }
        response = await client.post(
            "https://api.tech.ec.europa.eu/search-api/prod/rest/search",
            params={"apiKey": "SEDIA", "text": "***", "pageSize": "50", "pageNumber": "1"},
            files={
                "query": (None, json.dumps(query), "application/json"),
                "sort": (None, json.dumps({"field": "startDate", "order": "DESC"}), "application/json"),
            },
        )
        response.raise_for_status()
        now = datetime.now(timezone.utc)
        results = []
        for item in response.json().get("results", []):
            metadata = item.get("metadata") or {}

            def first(key: str) -> str:
                value = metadata.get(key)
                if isinstance(value, list):
                    return str(value[0]) if value else ""
                return str(value or "")

            identifier = first("identifier") or str(item.get("reference"))
            deadline = earliest_deadline(metadata.get("deadlineDate"))
            if deadline and deadline < now:
                continue
            title = clean_text(first("title") or "EU funding call", limit=500)
            excerpt = clean_text(str(item.get("summary") or "")) or title
            results.append(
                RawSignal(
                    identifier,
                    f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{identifier.lower()}",
                    title,
                    excerpt,
                    self.timestamp(first("startDate")),
                    "en",
                    "europe",
                    {"programme": first("frameworkProgramme"), "call": first("callIdentifier")},
                    deadline_at=deadline,
                )
            )
        return results


class TedNorwayCollector(BaseCollector):
    key = "ted-norway"

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y%m%d")
        response = await client.post(
            "https://api.ted.europa.eu/v3/notices/search",
            json={
                "query": f"place-of-performance = NOR AND publication-date >= {since}",
                "fields": ["publication-number", "notice-title", "buyer-name", "publication-date", "deadline-receipt-tender-date-lot", "links"],
                "page": 1,
                "limit": 100,
                "paginationMode": "PAGE_NUMBER",
            },
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("notices", payload.get("results", []))
        results = []
        for item in items:
            number = str(item.get("publication-number") or item.get("publicationNumber") or item.get("id"))
            title = localized_text(item.get("notice-title") or item.get("noticeTitle") or item.get("title")) or "Norwegian procurement notice"
            buyer = localized_text(item.get("buyer-name") or item.get("buyerName")) or "Unknown public buyer"
            url = f"https://ted.europa.eu/en/notice/-/detail/{number}"
            results.append(
                RawSignal(
                    number,
                    url,
                    clean_text(str(title), limit=500),
                    clean_text(f"Public buyer: {buyer}. Procurement notice {number}."),
                    self.timestamp(item.get("publication-date") or item.get("publicationDate")),
                    "en",
                    "norway",
                    {"buyer": buyer},
                    deadline_at=earliest_deadline(item.get("deadline-receipt-tender-date-lot")),
                )
            )
        return results
