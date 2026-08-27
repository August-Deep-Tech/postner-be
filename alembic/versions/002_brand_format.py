"""add brand preferred format

Revision ID: 002_brand_format
Revises: 001_initial
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_brand_format"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column(
            "format",
            sa.String(length=32),
            nullable=False,
            server_default="ig_feed",
        ),
    )
    # Keep server_default for existing rows; drop so inserts use ORM default
    op.alter_column("brands", "format", server_default=None)


def downgrade() -> None:
    op.drop_column("brands", "format")
