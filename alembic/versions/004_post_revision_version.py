"""post_revisions.version for undo snapshots

Revision ID: 004_post_revision_version
Revises: 003_brand_formats
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_post_revision_version"
down_revision: Union[str, None] = "003_brand_formats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "post_revisions",
        sa.Column("version", sa.Integer(), nullable=True),
    )
    bind = op.get_bind()
    # Backfill per-post sequential versions by created_at
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                UPDATE post_revisions AS r
                SET version = s.rn
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY post_id ORDER BY created_at ASC, id ASC
                           ) AS rn
                    FROM post_revisions
                ) AS s
                WHERE r.id = s.id
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                UPDATE post_revisions
                SET version = (
                    SELECT COUNT(*)
                    FROM post_revisions AS older
                    WHERE older.post_id = post_revisions.post_id
                      AND (
                        older.created_at < post_revisions.created_at
                        OR (
                          older.created_at = post_revisions.created_at
                          AND older.id <= post_revisions.id
                        )
                      )
                )
                """
            )
        )
    op.execute(sa.text("UPDATE post_revisions SET version = 1 WHERE version IS NULL"))
    op.alter_column("post_revisions", "version", nullable=False)
    op.create_index(
        "ix_post_revisions_post_id_version",
        "post_revisions",
        ["post_id", "version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_post_revisions_post_id_version", table_name="post_revisions")
    op.drop_column("post_revisions", "version")
