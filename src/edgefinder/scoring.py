from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone


WEIGHTS: dict[str, float] = {
    "asymmetry": 25.0,
    "timing": 20.0,
    "pain": 15.0,
    "novelty": 15.0,
    "distribution": 10.0,
    "norway_to_global": 10.0,
    "capital_efficiency": 5.0,
}


def calculate_score(breakdown: dict[str, float]) -> float:
    missing = set(WEIGHTS) - set(breakdown)
    extra = set(breakdown) - set(WEIGHTS)
    if missing or extra:
        raise ValueError(f"Invalid scoring keys; missing={sorted(missing)}, extra={sorted(extra)}")
    for key, value in breakdown.items():
        if not 0 <= value <= 10:
            raise ValueError(f"{key} must be between 0 and 10")
    return round(sum((breakdown[key] / 10) * weight for key, weight in WEIGHTS.items()), 1)


def calculate_confidence(evidence: Iterable[dict[str, object]]) -> float:
    items = list(evidence)
    if not items:
        return 0.0
    urls = {str(item.get("source_url", "")) for item in items}
    sources = {str(item.get("source_name", "")) for item in items}
    directness = sum(float(item.get("directness", 0.5)) for item in items) / len(items)
    quality = sum(float(item.get("quality", 0.5)) for item in items) / len(items)
    now = datetime.now(timezone.utc)
    recency_values: list[float] = []
    for item in items:
        observed = item.get("observed_at")
        if isinstance(observed, datetime):
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            days = max(0, (now - observed).days)
            recency_values.append(max(0.1, 1 - days / 365))
        else:
            recency_values.append(0.5)
    recency = sum(recency_values) / len(recency_values)
    count_score = min(1.0, len(items) / 4)
    independence = min(1.0, min(len(urls), len(sources)) / 3)
    result = 100 * (
        count_score * 0.20
        + independence * 0.25
        + directness * 0.20
        + quality * 0.20
        + recency * 0.15
    )
    return round(min(100.0, max(0.0, result)), 1)

