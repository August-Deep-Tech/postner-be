"""Widen brands.logo for public object URLs

Revision ID: 006_brand_logo_url
Revises: 005_brand_variants
Create Date: 2026-08-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_brand_logo_url"
down_revision: Union[str, None] = "005_brand_variants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "brands",
        "logo",
        existing_type=sa.String(length=512),
        type_=sa.String(length=2048),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "brands",
        "logo",
        existing_type=sa.String(length=2048),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
