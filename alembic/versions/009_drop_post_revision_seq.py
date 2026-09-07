"""Drop posts.revision_seq (orphaned column, unused by the Post model)

This column exists in some databases due to a manual/out-of-band schema
change that was never reflected in app/db/models.py or any prior
migration. It has no default, so every new post insert violates its
NOT NULL constraint. It is not referenced anywhere in the codebase, so
we drop it here to bring the schema back in line with the ORM model.

Revision ID: 009_drop_post_revision_seq
Revises: 008_drop_post_asset_dir
Create Date: 2026-09-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_drop_post_revision_seq"
down_revision: Union[str, None] = "008_drop_post_asset_dir"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col["name"] for col in inspector.get_columns("posts")}
    if "revision_seq" in columns:
        op.drop_column("posts", "revision_seq")


def downgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("revision_seq", sa.Integer(), nullable=False, server_default="0"),
    )
