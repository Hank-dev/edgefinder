"""Add deadline_at to signals and opportunities.

Revision ID: 0002_deadlines
Revises: 0001_initial
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_deadlines"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("opportunities", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("opportunities", "deadline_at")
    op.drop_column("signals", "deadline_at")
