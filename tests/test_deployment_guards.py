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



def test_schema_is_owned_by_alembic_not_create_all() -> None:
    migration = (PROJECT_ROOT / "alembic" / "versions" / "0001_initial.py").read_text()
    assert "create_all" not in migration
    assert "op.create_table" in migration
    for app_module in ("main.py", "cli.py"):
        source = (PROJECT_ROOT / "src" / "edgefinder" / app_module).read_text()
        assert "init_db" not in source
        assert "create_all" not in source


def test_missing_schema_fails_with_a_clear_migration_hint() -> None:
    from edgefinder.db import Base, assert_schema_ready, engine

    assert_schema_ready()
    Base.metadata.drop_all(engine)
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        assert_schema_ready()


def test_sources_point_at_live_apis() -> None:
    from edgefinder.collectors.registry import source_definitions

    definitions = {item["key"]: item for item in source_definitions(Settings(agent_token="test-agent-token", internal_token="test-internal-token"))}
    assert definitions["nav-jobs"]["base_url"] == "https://pam-stilling-feed.nav.no"
    assert definitions["eurlex"]["base_url"] == "https://eur-lex.europa.eu/EN/display-feed.rss?rssId=222"
