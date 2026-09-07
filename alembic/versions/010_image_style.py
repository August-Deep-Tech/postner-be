"""Remove brand_variants / posts.variant_id; add posts.image_style

The brand-variant (per-brand CSS palette) feature is removed entirely in
favor of a fixed Recraft image-style choice stored directly on the post.

Revision ID: 010_image_style
Revises: 009_drop_post_revision_seq
Create Date: 2026-09-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_image_style"
down_revision: Union[str, None] = "009_drop_post_revision_seq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column(
            "image_style",
            sa.String(length=32),
            nullable=False,
            server_default="realistic",
        ),
    )
    op.drop_column("posts", "variant_id")

    op.drop_index("ix_brand_variants_brand_id", table_name="brand_variants")
    op.drop_index("ix_brand_variants_tenant_id", table_name="brand_variants")
    op.drop_table("brand_variants")


def downgrade() -> None:
    from sqlalchemy.dialects import postgresql

    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "brand_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("css_vars", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_id", "slug", name="uq_brand_variant_brand_slug"),
    )
    op.create_index("ix_brand_variants_tenant_id", "brand_variants", ["tenant_id"])
    op.create_index("ix_brand_variants_brand_id", "brand_variants", ["brand_id"])

    op.add_column(
        "posts",
        sa.Column("variant_id", sa.String(length=128), nullable=True),
    )
    op.drop_column("posts", "image_style")
