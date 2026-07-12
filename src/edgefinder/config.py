from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Edgefinder"
    environment: str = "development"
    database_url: str = "sqlite:///./data/edgefinder.db"
    agent_token: str = Field(default="change-me", min_length=8)
    internal_token: str = Field(default="change-me-too", min_length=8)
    public_base_url: str = "http://127.0.0.1:8787"
    timezone: str = "Europe/Oslo"
    max_signals_per_run: int = Field(default=120, ge=10, le=500)
    max_candidates_per_run: int = Field(default=12, ge=1, le=30)
    max_deep_reviews: int = Field(default=8, ge=1, le=20)
    weekly_budget_eur: float = Field(default=7.0, gt=0, le=100)
    retention_backups: int = Field(default=30, ge=1, le=365)
    collection_user_agent: str = "Edgefinder/0.1 (+private research; contact configured by operator)"
    request_timeout_seconds: float = Field(default=20.0, ge=2, le=120)
    github_token: str | None = None
    nav_api_token: str | None = None
    extra_feed_urls: str = ""
    data_dir: Path = Path("./data")
    backup_dir: Path = Path("./backups")

    @property
    def feeds(self) -> list[str]:
        return [item.strip() for item in self.extra_feed_urls.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def assert_safe_production_config(self) -> None:
        if not self.is_production:
            return
        unsafe = {
            "change-me",
            "change-me-too",
            "replace-with-a-long-random-value",
            "replace-with-a-different-long-random-value",
        }
        if self.agent_token in unsafe or self.internal_token in unsafe:
            raise RuntimeError("Production requires non-default AGENT_TOKEN and INTERNAL_TOKEN")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
