from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
import uvicorn

from .collectors import build_collectors, collect_all, source_definitions
from .config import get_settings
from .db import SessionLocal, assert_schema_ready
from .repository import seed_sources


def initialize() -> None:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    assert_schema_ready()
    with SessionLocal() as session:
        seed_sources(session, source_definitions(settings))


async def run_collection() -> dict[str, object]:
    initialize()
    settings = get_settings()
    with SessionLocal() as session:
        result = await collect_all(session, settings, build_collectors(settings))
    return {"inserted": result.inserted, "updated": result.updated, "skipped": result.skipped, "failures": result.failures}


def backup_database() -> Path:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        raise RuntimeError("The built-in backup command supports SQLite only")
    database_path = Path(settings.database_url.removeprefix("sqlite:///"))
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.backup_dir / f"edgefinder-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
    with sqlite3.connect(database_path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    backups = sorted(settings.backup_dir.glob("edgefinder-*.db"), reverse=True)
    for old in backups[settings.retention_backups:]:
        old.unlink()
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(prog="edgefinder")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    subparsers.add_parser("collect")
    subparsers.add_parser("backup")
    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    digest = subparsers.add_parser("digest")
    digest.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    if args.command == "init":
        initialize()
        print("Edgefinder initialized")
    elif args.command == "collect":
        print(json.dumps(asyncio.run(run_collection()), indent=2))
    elif args.command == "backup":
        print(backup_database())
    elif args.command == "digest":
        from .jobs.digest import send_digest

        initialize()
        try:
            print(json.dumps(asyncio.run(send_digest(hours=args.hours)), indent=2))
        except Exception as exc:  # cron-visible failure: non-zero exit, error on stderr
            print(f"digest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
    elif args.command == "serve":
        uvicorn.run("edgefinder.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
