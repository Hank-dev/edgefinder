from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    DRAFT = "draft"
    PUBLISHED = "published"
    FAILED = "failed"


class OpportunityKind(str, enum.Enum):
    RANKED = "ranked"
    WATCH = "watch"


class OpportunityStatus(str, enum.Enum):
    NEW = "new"
    VALIDATE = "validate"
    WATCH = "watch"
    REJECT = "reject"
    SEEN_BEFORE = "seen_before"
    SUPERSEDED = "superseded"


class JobStatusValue(str, enum.Enum):
    INTERESTED = "interested"
    APPLIED = "applied"
    DISMISSED = "dismissed"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    region: Mapped[str] = mapped_column(String(40), default="global")
    base_url: Mapped[str] = mapped_column(String(1000))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quality: Mapped[float] = mapped_column(Float, default=0.7)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    signals: Mapped[list[Signal]] = relationship(back_populates="source")


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_signal_source_external"),
        Index("ix_signals_observed_at", "observed_at"),
        Index("ix_signals_content_hash", "content_hash"),
        Index("ix_signals_fingerprint", "fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(500))
    canonical_url: Mapped[str] = mapped_column(String(2000), index=True)
    title: Mapped[str] = mapped_column(String(500))
    excerpt: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(12), default="und")
    region: Mapped[str] = mapped_column(String(40), default="global")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    suspicious_instructions: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str | None] = mapped_column(String(16))

    source: Mapped[Source] = relationship(back_populates="signals")
    evidence: Mapped[list[Evidence]] = relationship(back_populates="signal")


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, native_enum=False), default=RunStatus.RUNNING, index=True)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    estimated_cost_eur: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model_name: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)
    signal_ids_seen: Mapped[list[str]] = mapped_column(JSON, default=list)

    opportunities: Mapped[list[Opportunity]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opportunity_score", "score"),
        UniqueConstraint("run_id", "canonical_key", name="uq_opportunity_run_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    canonical_key: Mapped[str] = mapped_column(String(180), index=True)
    kind: Mapped[OpportunityKind] = mapped_column(Enum(OpportunityKind, native_enum=False))
    status: Mapped[OpportunityStatus] = mapped_column(Enum(OpportunityStatus, native_enum=False), default=OpportunityStatus.NEW, index=True)
    title: Mapped[str] = mapped_column(String(300))
    buyer: Mapped[str] = mapped_column(Text)
    observed_pain: Mapped[str] = mapped_column(Text)
    proposed_wedge: Mapped[str] = mapped_column(Text)
    why_now: Mapped[str] = mapped_column(Text)
    norway_advantage: Mapped[str] = mapped_column(Text)
    global_path: Mapped[str] = mapped_column(Text)
    business_model: Mapped[str] = mapped_column(Text)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_effort: Mapped[str] = mapped_column(Text)
    next_experiment: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    score_breakdown: Mapped[dict[str, float]] = mapped_column(JSON)
    update_of_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id", ondelete="SET NULL"))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ResearchRun] = relationship(back_populates="opportunities")
    evidence: Mapped[list[Evidence]] = relationship(back_populates="opportunity", cascade="all, delete-orphan")
    reviews: Mapped[list[AgentReview]] = relationship(back_populates="opportunity", cascade="all, delete-orphan")
    feedback: Mapped[list[Feedback]] = relationship(back_populates="opportunity", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    signal_id: Mapped[str | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    stance: Mapped[str] = mapped_column(String(20), default="supports")
    source_url: Mapped[str] = mapped_column(String(2000))
    source_name: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    opportunity: Mapped[Opportunity] = relationship(back_populates="evidence")
    signal: Mapped[Signal | None] = relationship(back_populates="evidence")


class AgentReview(Base):
    __tablename__ = "agent_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    verdict: Mapped[str] = mapped_column(String(40))
    reasoning: Mapped[str] = mapped_column(Text)
    score_delta: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    opportunity: Mapped[Opportunity] = relationship(back_populates="reviews")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    action: Mapped[OpportunityStatus] = mapped_column(Enum(OpportunityStatus, native_enum=False))
    reason: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    opportunity: Mapped[Opportunity] = relationship(back_populates="feedback")


class JobStatus(Base):
    __tablename__ = "job_status"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fingerprint: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    status: Mapped[JobStatusValue] = mapped_column(Enum(JobStatusValue, native_enum=False))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobPick(Base):
    __tablename__ = "job_picks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), index=True)
    reasoning: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
