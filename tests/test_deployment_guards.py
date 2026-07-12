from __future__ import annotations

from pathlib import Path

import pytest

from edgefinder.config import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_container_is_python_312_and_compose_is_loopback_only() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text()
    assert "FROM python:3.12-slim" in dockerfile
    assert '127.0.0.1:${APP_PORT:-8787}:8787' in compose
    assert "0.0.0.0:${APP_PORT" not in compose


def test_production_refuses_example_tokens() -> None:
    settings = Settings(
        environment="production",
        agent_token="replace-with-a-long-random-value",
        internal_token="replace-with-a-different-long-random-value",
    )
    with pytest.raises(RuntimeError, match="non-default"):
        settings.assert_safe_production_config()

