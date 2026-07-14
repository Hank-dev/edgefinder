"""Add signal fingerprints, job_status, and job_picks.

Revision ID: 0003_jobs_intelligence
Revises: 0002_deadlines
Create Date: 2026-07-14
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

from edgefinder.normalization import job_fingerprint

revision = "0003_jobs_intelligence"
down_revision = "0002_deadlines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("fingerprint", sa.String(length=16), nullable=True))
    op.create_index("ix_signals_fingerprint", "signals", ["fingerprint"])
    op.create_table(
        "job_status",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("fingerprint", sa.String(length=16), nullable=False, unique=True, index=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "job_picks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("signal_id", sa.String(length=36), sa.ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT signals.id AS id, signals.title AS title, signals.metadata_json AS metadata_json "
            "FROM signals JOIN sources ON sources.id = signals.source_id WHERE sources.kind = 'jobs'"
        )
    ).fetchall()
    for row in rows:
        raw_meta = row.metadata_json
        if isinstance(raw_meta, str):
            try:
                meta = json.loads(raw_meta)
            except ValueError:
                meta = {}
        else:
            meta = raw_meta or {}
        fingerprint = job_fingerprint(meta.get("employer"), row.title)
        if fingerprint:
            connection.execute(
                sa.text("UPDATE signals SET fingerprint = :fp WHERE id = :id"),
                {"fp": fingerprint, "id": row.id},
            )


def downgrade() -> None:
    op.drop_table("job_picks")
    op.drop_table("job_status")
    op.drop_index("ix_signals_fingerprint", table_name="signals")
    op.drop_column("signals", "fingerprint")
