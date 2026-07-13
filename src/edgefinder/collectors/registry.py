from __future__ import annotations

import hashlib

from edgefinder.config import Settings

from .adapters import (
    ArxivCollector,
    BrregCollector,
    DoffinCollector,
    EuFundingCollector,
    FeedCollector,
    GitHubIssuesCollector,
    HackerNewsCollector,
    NavJobsCollector,
    StackExchangeCollector,
    TedNorwayCollector,
)
from .base import BaseCollector


CORE_SOURCES = [
    {"key": "ted-norway", "name": "TED Norway (over EØS-terskel)", "kind": "procurement", "region": "norway", "base_url": "https://api.ted.europa.eu", "quality": 0.95},
    {"key": "doffin", "name": "Doffin nasjonale kunngjøringer", "kind": "procurement", "region": "norway", "base_url": "https://api.doffin.no", "quality": 0.95},
    {"key": "brreg", "name": "Brønnøysundregistrene", "kind": "registry", "region": "norway", "base_url": "https://data.brreg.no", "quality": 0.95},
    {"key": "nav-jobs", "name": "NAV Arbeidsplassen", "kind": "jobs", "region": "norway", "base_url": "https://pam-stilling-feed.nav.no", "quality": 0.9},
    {"key": "regjeringen", "name": "Regjeringen.no updates", "kind": "regulation", "region": "norway", "base_url": "https://www.regjeringen.no/no/rss/Rss/2581966/", "quality": 0.95},
    {"key": "eurlex", "name": "EUR-Lex Official Journal L", "kind": "regulation", "region": "europe", "base_url": "https://eur-lex.europa.eu/EN/display-feed.rss?rssId=222", "quality": 0.95},
    {"key": "eu-funding", "name": "EU Funding & Tenders (Horizon/Digital)", "kind": "funding", "region": "europe", "base_url": "https://api.tech.ec.europa.eu", "quality": 0.9},
    {"key": "hacker-news", "name": "Hacker News", "kind": "community", "region": "global", "base_url": "https://hn.algolia.com", "quality": 0.65},
    {"key": "github-issues", "name": "GitHub Issues", "kind": "developer", "region": "global", "base_url": "https://api.github.com", "quality": 0.7},
    {"key": "stack-overflow", "name": "Stack Overflow", "kind": "developer", "region": "global", "base_url": "https://api.stackexchange.com", "quality": 0.75},
    {"key": "arxiv", "name": "arXiv", "kind": "research", "region": "global", "base_url": "https://export.arxiv.org", "quality": 0.85},
]


def source_definitions(settings: Settings) -> list[dict[str, object]]:
    definitions: list[dict[str, object]] = list(CORE_SOURCES)
    for url in settings.feeds:
        digest = hashlib.sha256(url.encode()).hexdigest()[:12]
        definitions.append({"key": f"feed-{digest}", "name": f"Configured feed {digest}", "kind": "feed", "region": "global", "base_url": url, "quality": 0.7})
    return definitions


def build_collectors(settings: Settings) -> list[BaseCollector]:
    collectors: list[BaseCollector] = [
        TedNorwayCollector(settings),
        DoffinCollector(settings),
        BrregCollector(settings),
        NavJobsCollector(settings),
        FeedCollector(settings, key="regjeringen", url="https://www.regjeringen.no/no/rss/Rss/2581966/", region="norway", language="no"),
        FeedCollector(settings, key="eurlex", url="https://eur-lex.europa.eu/EN/display-feed.rss?rssId=222", region="europe", language="en"),
        EuFundingCollector(settings),
        HackerNewsCollector(settings),
        GitHubIssuesCollector(settings),
        StackExchangeCollector(settings),
        ArxivCollector(settings),
    ]
    definitions = source_definitions(settings)
    for definition in definitions[len(CORE_SOURCES):]:
        collectors.append(FeedCollector(settings, key=str(definition["key"]), url=str(definition["base_url"]), region=str(definition["region"])))
    return collectors
