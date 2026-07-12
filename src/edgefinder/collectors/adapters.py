from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import feedparser
import httpx

from edgefinder.normalization import clean_text

from .base import BaseCollector, RawSignal


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
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise ValueError(f"Invalid feed: {getattr(parsed, 'bozo_exception', 'unknown error')}")
        results: list[RawSignal] = []
        for entry in parsed.entries[:100]:
            url = entry.get("link", "")
            title = clean_text(entry.get("title", "Untitled"), limit=500)
            excerpt = clean_text(entry.get("summary", entry.get("description", "")))
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
            params={"q": f'is:issue created:>={since} ("manual workflow" OR "pain point" OR "feature request")', "sort": "comments", "order": "desc", "per_page": 50},
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
            params={"size": 50, "sort": "registreringsdatoEnhetsregisteret,desc"},
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
    key = "nav-jobs"

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        if not self.settings.nav_api_token:
            raise RuntimeError("NAV_API_TOKEN is not configured; obtain public-feed access from NAV")
        response = await client.get(
            "https://arbeidsplassen.nav.no/public-feed/api/v1/ads",
            params={"size": 100},
            headers={"Authorization": f"Bearer {self.settings.nav_api_token}"},
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("content", payload if isinstance(payload, list) else [])
        results = []
        for item in items:
            identifier = str(item.get("uuid") or item.get("id"))
            title = item.get("title", "Ukjent stilling")
            description = item.get("description") or item.get("jobtitle") or ""
            url = item.get("link") or f"https://arbeidsplassen.nav.no/stillinger/stilling/{identifier}"
            results.append(RawSignal(identifier, url, clean_text(title, limit=500), clean_text(description), self.timestamp(item.get("published")), "no", "norway", {"employer": item.get("employer"), "category": item.get("categoryList", [])}))
        return results


class TedNorwayCollector(BaseCollector):
    key = "ted-norway"

    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y%m%d")
        response = await client.post(
            "https://api.ted.europa.eu/v3/notices/search",
            json={
                "query": f"place-of-performance = NOR AND publication-date >= {since}",
                "fields": ["publication-number", "notice-title", "buyer-name", "publication-date", "links"],
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
            results.append(RawSignal(number, url, clean_text(str(title), limit=500), clean_text(f"Public buyer: {buyer}. Procurement notice {number}."), self.timestamp(item.get("publication-date") or item.get("publicationDate")), "en", "norway", {"buyer": buyer}))
        return results
