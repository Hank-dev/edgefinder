from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from edgefinder.config import Settings
from edgefinder.models import JobPick, JobStatus, JobStatusValue, ResearchRun, RunStatus, Signal, Source
from edgefinder.repository import DomainError

from .relevance import load_profile, score_job
from .taxonomy import CLUSTERS, extract_skills

CLUSTER_SLUGS: dict[str, str] = {name: re.sub(r"[^a-z]+", "-", name.lower()).strip("-") for name in CLUSTERS}
_SLUG_TO_CLUSTER = {slug: name for name, slug in CLUSTER_SLUGS.items()}
MAX_SIGNALS = 3000
WINDOW_DAYS = 30


@dataclass(slots=True)
class JobRow:
    fingerprint: str | None
    signal_id: str
    title: str
    employer: str
    municipality: str
    url: str
    source_board: str
    also_on: list[str]
    observed_at: datetime
    deadline_at: datetime | None
    days_left: int | None
    relevance: float
    breakdown: dict[str, float]
    status: str | None
    skill_pairs: set[tuple[str, str]] = field(default_factory=set)
    clusters: set[str] = field(default_factory=set)
    skills: set[str] = field(default_factory=set)


@dataclass(slots=True)
class AgentPick:
    title: str
    employer: str
    url: str
    reasoning: str


@dataclass(slots=True)
class TalentView:
    rows: list[JobRow]
    tab: str
    skill_filter: str
    tab_counts: dict[str, int]
    cluster_skills: dict[str, list[tuple[str, int]]]
    top_employers: list[tuple[str, int]]
    top_municipalities: list[tuple[str, int]]
    total_jobs: int
    total_employers: int
    total_municipalities: int
    profile_missing: bool
    agent_picks: list[AgentPick]


def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def set_job_status(session: Session, fingerprint: str, status: JobStatusValue, note: str | None = None) -> JobStatus:
    known = session.scalar(select(Signal.id).where(Signal.fingerprint == fingerprint).limit(1))
    if not known:
        raise DomainError("Unknown job fingerprint")
    row = session.scalar(select(JobStatus).where(JobStatus.fingerprint == fingerprint))
    if row:
        row.status = status
        if note:
            row.note = note
    else:
        row = JobStatus(fingerprint=fingerprint, status=status, note=note)
        session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _latest_agent_picks(session: Session) -> list[AgentPick]:
    run = session.scalar(
        select(ResearchRun).where(ResearchRun.status == RunStatus.PUBLISHED).order_by(desc(ResearchRun.published_at)).limit(1)
    )
    if not run:
        return []
    rows = session.execute(
        select(JobPick, Signal).join(Signal, JobPick.signal_id == Signal.id).where(JobPick.run_id == run.id)
    ).all()
    return [
        AgentPick(
            title=signal.title,
            employer=str((signal.metadata_json or {}).get("employer", "")),
            url=signal.canonical_url,
            reasoning=pick.reasoning,
        )
        for pick, signal in rows
    ]


def build_talent_view(session: Session, settings: Settings, *, tab: str = "all", skill_filter: str = "") -> TalentView:
    now = _naive_now()
    profile = load_profile(settings.jobs_profile_path)
    skill_filter = skill_filter.strip().casefold()

    statuses = dict(session.execute(select(JobStatus.fingerprint, JobStatus.status)).all())
    signals = session.execute(
        select(Signal, Source)
        .join(Source)
        .where(Source.kind == "jobs", Source.enabled.is_(True), Signal.observed_at >= now - timedelta(days=WINDOW_DAYS))
        .order_by(desc(Signal.observed_at))
        .limit(MAX_SIGNALS)
    ).all()

    groups: dict[str, list[tuple[Signal, Source]]] = {}
    for signal, source in signals:
        meta = signal.metadata_json or {}
        if str(meta.get("status", "ACTIVE")).upper() == "INACTIVE":
            continue
        if signal.deadline_at is not None and signal.deadline_at < now:
            continue
        if statuses.get(signal.fingerprint) is JobStatusValue.DISMISSED:
            continue
        key = signal.fingerprint or f"solo-{signal.id}"
        groups.setdefault(key, []).append((signal, source))

    rows: list[JobRow] = []
    for members in groups.values():
        members.sort(key=lambda pair: pair[1].quality, reverse=True)
        primary, _primary_source = members[0]
        meta = primary.metadata_json or {}
        boards: list[str] = []
        for signal, source in members:
            board = str((signal.metadata_json or {}).get("source_board") or source.name)
            if board not in boards:
                boards.append(board)
        found = extract_skills(f"{primary.title} {primary.excerpt}")
        relevance, breakdown = score_job(primary.title, primary.excerpt, str(meta.get("municipality", "")), profile)
        status = statuses.get(primary.fingerprint)
        rows.append(
            JobRow(
                fingerprint=primary.fingerprint,
                signal_id=primary.id,
                title=primary.title,
                employer=str(meta.get("employer", "")),
                municipality=str(meta.get("municipality", "")),
                url=primary.canonical_url,
                source_board=boards[0],
                also_on=boards[1:],
                observed_at=primary.observed_at,
                deadline_at=primary.deadline_at,
                days_left=(primary.deadline_at.date() - now.date()).days if primary.deadline_at else None,
                relevance=relevance,
                breakdown=breakdown,
                status=status.value if status else None,
                skill_pairs=found,
                clusters={cluster for cluster, _skill in found},
                skills={skill.casefold() for _cluster, skill in found},
            )
        )

    tab_counts: dict[str, int] = {slug: 0 for slug in CLUSTER_SLUGS.values()}
    tab_counts["deadlines"] = 0
    tab_counts["applied"] = 0
    for row in rows:
        for cluster in row.clusters:
            tab_counts[CLUSTER_SLUGS[cluster]] += 1
        if row.deadline_at is not None:
            tab_counts["deadlines"] += 1
        if row.status in {"interested", "applied"}:
            tab_counts["applied"] += 1

    if tab in _SLUG_TO_CLUSTER:
        selected = [row for row in rows if _SLUG_TO_CLUSTER[tab] in row.clusters]
    elif tab == "deadlines":
        selected = [row for row in rows if row.deadline_at is not None]
    elif tab == "applied":
        selected = [row for row in rows if row.status in {"interested", "applied"}]
    else:
        tab = "all"
        selected = list(rows)
    if skill_filter:
        selected = [row for row in selected if skill_filter in row.skills]

    if tab == "deadlines":
        selected.sort(key=lambda row: (row.deadline_at, -row.relevance))
    else:
        selected.sort(key=lambda row: (-row.relevance, -row.observed_at.timestamp()))

    employers = Counter(row.employer for row in selected if row.employer)
    municipalities = Counter(row.municipality for row in selected if row.municipality)
    pair_counts: Counter[tuple[str, str]] = Counter()
    for row in selected:
        for pair in row.skill_pairs:
            pair_counts[pair] += 1
    cluster_skills = {
        cluster: [(skill, count) for (candidate, skill), count in pair_counts.most_common() if candidate == cluster][:8]
        for cluster in CLUSTERS
    }
    return TalentView(
        rows=selected[:200],
        tab=tab,
        skill_filter=skill_filter,
        tab_counts=tab_counts,
        cluster_skills=cluster_skills,
        top_employers=employers.most_common(15),
        top_municipalities=municipalities.most_common(15),
        total_jobs=len(selected),
        total_employers=len(employers),
        total_municipalities=len(municipalities),
        profile_missing=profile is None,
        agent_picks=_latest_agent_picks(session),
    )
