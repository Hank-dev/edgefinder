from __future__ import annotations

import hashlib
import ipaddress
import socket
from urllib.parse import urlparse

from edgefinder.config import Settings

from .adapters import (
    AbakusCollector,
    ArxivCollector,
    BindeleddetCollector,
    BrregCollector,
    DoffinCollector,
    EuFundingCollector,
    FeedCollector,
    GitHubIssuesCollector,
    HackerNewsCollector,
    EnglishJobsCollector,
    JobbnorgeCollector,
    JobbsafariCollector,
    Kode24Collector,
    NavJobsCollector,
    StartupLabCollector,
    TheHubCollector,
    StackExchangeCollector,
    TedNorwayCollector,
)
from .base import BaseCollector


CORE_SOURCES = [
    {"key": "ted-norway", "name": "TED Norway (over EØS-terskel)", "kind": "procurement", "region": "norway", "base_url": "https://api.ted.europa.eu", "quality": 0.95},
    {"key": "doffin", "name": "Doffin nasjonale kunngjøringer", "kind": "procurement", "region": "norway", "base_url": "https://api.doffin.no", "quality": 0.95},
    {"key": "brreg", "name": "Brønnøysundregistrene", "kind": "registry", "region": "norway", "base_url": "https://data.brreg.no", "quality": 0.95},
    {"key": "nav-jobs", "name": "NAV Arbeidsplassen", "kind": "jobs", "region": "norway", "base_url": "https://pam-stilling-feed.nav.no", "quality": 0.9},
    {"key": "jobbnorge", "name": "Jobbnorge", "kind": "jobs", "region": "norway", "base_url": "https://publicapi.jobbnorge.no", "quality": 0.9},
    {"key": "bindeleddet", "name": "Bindeleddet NTNU", "kind": "jobs", "region": "norway", "base_url": "https://apiv2.bindeleddet.no", "quality": 0.85},
    {"key": "abakus", "name": "Abakus NTNU", "kind": "jobs", "region": "norway", "base_url": "https://lego.abakus.no", "quality": 0.85},
    {"key": "startuplab", "name": "STARTUPLAB Job Board", "kind": "jobs", "region": "norway", "base_url": "https://jobs.startuplab.no", "quality": 0.85},
    {"key": "englishjobs", "name": "EnglishJobs.no", "kind": "jobs", "region": "norway", "base_url": "https://englishjobs.no", "quality": 0.8},
    {"key": "thehub", "name": "The Hub Norway", "kind": "jobs", "region": "norway", "base_url": "https://thehub.io", "quality": 0.85},
    {"key": "kode24", "name": "kode24 jobb", "kind": "jobs", "region": "norway", "base_url": "https://kodejobb.no", "quality": 0.75},
    {"key": "jobbsafari", "name": "Jobbsafari (Oslo/Trondheim)", "kind": "jobs", "region": "norway", "base_url": "https://jobbsafari.no", "quality": 0.7},
    {"key": "regjeringen", "name": "Regjeringen.no updates", "kind": "regulation", "region": "norway", "base_url": "https://www.regjeringen.no/no/rss/Rss/2581966/", "quality": 0.95},
    {"key": "eurlex", "name": "EUR-Lex Official Journal L", "kind": "regulation", "region": "europe", "base_url": "https://eur-lex.europa.eu/EN/display-feed.rss?rssId=222", "quality": 0.95},
    {"key": "eu-funding", "name": "EU Funding & Tenders (Horizon/Digital)", "kind": "funding", "region": "europe", "base_url": "https://api.tech.ec.europa.eu", "quality": 0.9},
    {"key": "hacker-news", "name": "Hacker News", "kind": "community", "region": "global", "base_url": "https://hn.algolia.com", "quality": 0.65},
    {"key": "github-issues", "name": "GitHub Issues", "kind": "developer", "region": "global", "base_url": "https://api.github.com", "quality": 0.7},
    {"key": "stack-overflow", "name": "Stack Overflow", "kind": "developer", "region": "global", "base_url": "https://api.stackexchange.com", "quality": 0.75},
    {"key": "arxiv", "name": "arXiv", "kind": "research", "region": "global", "base_url": "https://export.arxiv.org", "quality": 0.85},
]


def _validate_feed_url(url: str) -> str:
    """Validate a feed URL to mitigate SSRF risk.

    Rejects non-http(s) schemes and hostnames that resolve to loopback,
    link-local, private RFC1918, or cloud-metadata addresses.
    Returns the URL unchanged if valid; raises ValueError otherwise.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            f"Feed URL rejected: unsupported scheme {parsed.scheme!r} "
            f"(only http/https allowed): {url}"
        )
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Feed URL rejected: no hostname present: {url}")

    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(
            f"Feed URL rejected: could not resolve hostname {hostname!r}: {exc}"
        ) from exc

    for _family, _type, _proto, _canon, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_loopback:
            raise ValueError(
                f"Feed URL rejected: hostname {hostname!r} resolves to loopback "
                f"address {ip}: {url}"
            )
        if ip.is_link_local:
            raise ValueError(
                f"Feed URL rejected: hostname {hostname!r} resolves to link-local "
                f"address {ip}: {url}"
            )
        if ip.is_private:
            raise ValueError(
                f"Feed URL rejected: hostname {hostname!r} resolves to private "
                f"address {ip}: {url}"
            )

    return url


def source_definitions(settings: Settings) -> list[dict[str, object]]:
    definitions: list[dict[str, object]] = list(CORE_SOURCES)
    for url in settings.feeds:
        try:
            _validate_feed_url(url)
        except ValueError as exc:
            print(f"warning: skipping invalid feed URL: {exc}")
            continue
        digest = hashlib.sha256(url.encode()).hexdigest()[:12]
        definitions.append({"key": f"feed-{digest}", "name": f"Configured feed {digest}", "kind": "feed", "region": "global", "base_url": url, "quality": 0.7})
    return definitions


def build_collectors(settings: Settings) -> list[BaseCollector]:
    collectors: list[BaseCollector] = [
        TedNorwayCollector(settings),
        DoffinCollector(settings),
        BrregCollector(settings),
        NavJobsCollector(settings),
        JobbnorgeCollector(settings),
        BindeleddetCollector(settings),
        AbakusCollector(settings),
        StartupLabCollector(settings),
        EnglishJobsCollector(settings),
        TheHubCollector(settings),
        Kode24Collector(settings),
        JobbsafariCollector(settings),
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
