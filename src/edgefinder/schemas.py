from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from .models import OpportunityKind, OpportunityStatus, RunStatus
from .scoring import WEIGHTS, calculate_score


class SignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_name: str
    title: str
    excerpt: str
    canonical_url: str
    language: str
    region: str
    observed_at: datetime
    suspicious_instructions: bool


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: RunStatus
    cutoff_at: datetime
    started_at: datetime
    estimated_cost_eur: float


class EvidenceInput(BaseModel):
    signal_id: str | None = None
    claim: str = Field(min_length=10, max_length=2000)
    stance: Literal["supports", "contradicts", "context"] = "supports"
    source_url: HttpUrl
    source_name: str = Field(min_length=2, max_length=300)
    directness: float = Field(default=0.6, ge=0, le=1)
    quality: float = Field(default=0.6, ge=0, le=1)
    observed_at: datetime | None = None


class CandidateInput(BaseModel):
    canonical_key: str = Field(min_length=4, max_length=180, pattern=r"^[a-z0-9][a-z0-9-]+$")
    kind: OpportunityKind
    title: str = Field(min_length=8, max_length=300)
    buyer: str = Field(min_length=10, max_length=2000)
    observed_pain: str = Field(min_length=20, max_length=5000)
    proposed_wedge: str = Field(min_length=20, max_length=5000)
    why_now: str = Field(min_length=20, max_length=5000)
    norway_advantage: str = Field(min_length=10, max_length=3000)
    global_path: str = Field(min_length=10, max_length=3000)
    business_model: str = Field(min_length=10, max_length=3000)
    risks: list[str] = Field(min_length=1, max_length=8)
    validation_effort: str = Field(min_length=10, max_length=2000)
    next_experiment: str = Field(min_length=20, max_length=3000)
    score_breakdown: dict[str, float]
    evidence: list[EvidenceInput] = Field(min_length=1, max_length=12)
    update_of_id: str | None = None
    deadline_at: datetime | None = None

    @field_validator("score_breakdown")
    @classmethod
    def validate_breakdown(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) != set(WEIGHTS):
            raise ValueError(f"score_breakdown keys must be exactly: {', '.join(WEIGHTS)}")
        calculate_score(value)
        return value


class ReviewInput(BaseModel):
    role: Literal["scout", "synthesizer", "skeptic", "judge"]
    verdict: Literal["advance", "watch", "reject", "revise"]
    reasoning: str = Field(min_length=20, max_length=5000)
    score_delta: float = Field(default=0, ge=-25, le=25)


class UsageInput(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_eur: float = Field(default=0, ge=0)
    model_name: str | None = Field(default=None, max_length=200)


class FeedbackInput(BaseModel):
    action: OpportunityStatus
    reason: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=3000)

