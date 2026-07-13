from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from typing import Any

import httpx

from edgefinder.config import Settings


@dataclass(slots=True)
class RawSignal:
    external_id: str
    url: str
    title: str
    excerpt: str
    observed_at: datetime
    language: str = "und"
    region: str = "global"
    metadata: dict[str, Any] = field(default_factory=dict)
    deadline_at: datetime | None = None


class BaseCollector(ABC):
    key: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    async def collect(self, client: httpx.AsyncClient) -> list[RawSignal]:
        raise NotImplementedError

    @staticmethod
    def timestamp(value: Any, naive_tz: tzinfo = timezone.utc) -> datetime:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            try:
                result = datetime.fromisoformat(normalized)
                return result if result.tzinfo else result.replace(tzinfo=naive_tz)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

