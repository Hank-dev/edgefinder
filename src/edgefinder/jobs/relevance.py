from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from .taxonomy import compile_term, extract_skills

WEIGHTS = {"role_match": 40.0, "skills": 30.0, "location": 15.0, "seniority": 15.0}

_SENIORITY_TERMS: dict[str, list[str]] = {
    "internship": ["sommerjobb", "internship", "intern", "praktikant", "summer job"],
    "graduate": ["nyutdannet", "nyutdannede", "graduate", "trainee"],
    "junior": ["junior"],
    "senior": ["senior", "lead", "principal", "leder", "sjef", "direktør", "head", "manager"],
}
_SENIORITY_PATTERNS = [
    (bucket, compile_term(term)) for bucket, terms in _SENIORITY_TERMS.items() for term in terms
]
_REMOTE_PATTERN = compile_term("remote")
_REMOTE_TERMS_NO = ["hjemmekontor", "hybrid"]


class JobProfile(BaseModel):
    skills_have: list[str] = []
    skills_learning: list[str] = []
    target_roles: list[str] = []
    locations: dict[str, float] = {}
    default_location_weight: float = 0.5
    seniority: dict[str, float] = {}
    unspecified_seniority_weight: float = 0.7


def load_profile(path: Path) -> JobProfile | None:
    """None when no profile exists; loud ValueError when one exists but is broken."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return JobProfile.model_validate(payload)
    except (yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"Invalid jobs profile at {path}: {exc}") from exc


def classify_seniority(text: str) -> str:
    for bucket in ("internship", "graduate", "junior", "senior"):
        if any(pattern.search(text) for candidate, pattern in _SENIORITY_PATTERNS if candidate == bucket):
            return bucket
    return "unspecified"


def score_job(title: str, excerpt: str, municipality: str, profile: JobProfile | None) -> tuple[float, dict[str, float]]:
    if profile is None:
        return 50.0, {}
    text = f"{title} {excerpt}"
    text_folded = text.casefold()
    title_folded = title.casefold()

    role = 0.0
    for phrase in profile.target_roles:
        folded = phrase.casefold()
        if folded in title_folded:
            role = 1.0
            break
        if folded in text_folded:
            role = max(role, 0.5)

    ad_skills = {skill.casefold() for _cluster, skill in extract_skills(text)}
    have = {item.casefold() for item in profile.skills_have}
    learning = {item.casefold() for item in profile.skills_learning}
    if ad_skills:
        skills = min(1.0, (len(ad_skills & have) + 0.5 * len(ad_skills & learning)) / len(ad_skills))
    else:
        skills = 0.5  # an ad naming no known skills is neutral, not disqualifying

    municipality_folded = (municipality or "").casefold()
    location = profile.default_location_weight
    for name, weight in profile.locations.items():
        if name.casefold() == "remote":
            if _REMOTE_PATTERN.search(text) or any(term in text_folded for term in _REMOTE_TERMS_NO):
                location = max(location, weight)
        elif name.casefold() in municipality_folded:
            location = max(location, weight)

    bucket = classify_seniority(text)
    if bucket == "unspecified":
        seniority = profile.unspecified_seniority_weight
    else:
        seniority = profile.seniority.get(bucket, profile.unspecified_seniority_weight)

    breakdown = {
        "role_match": round(role * WEIGHTS["role_match"], 1),
        "skills": round(skills * WEIGHTS["skills"], 1),
        "location": round(location * WEIGHTS["location"], 1),
        "seniority": round(seniority * WEIGHTS["seniority"], 1),
    }
    return round(sum(breakdown.values()), 1), breakdown
