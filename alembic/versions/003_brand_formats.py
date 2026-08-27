"""brand formats list (multi)

Revision ID: 003_brand_formats
Revises: 002_brand_format
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_brand_formats"
down_revision: Union[str, None] = "002_brand_format"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JsonType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column("formats", JsonType, nullable=True),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("UPDATE brands SET formats = jsonb_build_array(format)"))
    else:
        op.execute(sa.text("UPDATE brands SET formats = json_array(format)"))
    op.alter_column("brands", "formats", nullable=False)
    op.drop_column("brands", "format")


def downgrade() -> None:
    op.add_column(
        "brands",
        sa.Column(
            "format",
            sa.String(length=32),
            nullable=False,
            server_default="ig_feed",
        ),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text("UPDATE brands SET format = COALESCE(formats->>0, 'ig_feed')")
        )
    op.drop_column("brands", "formats")
    op.alter_column("brands", "format", server_default=None)
