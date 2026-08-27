"""brand_variants table (per-brand color palettes)

Revision ID: 005_brand_variants
Revises: 004_post_revision_version
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_brand_variants"
down_revision: Union[str, None] = "004_post_revision_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JsonType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "brand_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("css_vars", JsonType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_id", "slug", name="uq_brand_variant_brand_slug"),
    )
    op.create_index("ix_brand_variants_tenant_id", "brand_variants", ["tenant_id"])
    op.create_index("ix_brand_variants_brand_id", "brand_variants", ["brand_id"])


def downgrade() -> None:
    op.drop_index("ix_brand_variants_brand_id", table_name="brand_variants")
    op.drop_index("ix_brand_variants_tenant_id", table_name="brand_variants")
    op.drop_table("brand_variants")
