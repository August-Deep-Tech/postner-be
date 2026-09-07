"""Drop posts.asset_dir (removed from the Post model)

Revision ID: 008_drop_post_asset_dir
Revises: 006_brand_logo_url
Create Date: 2026-09-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_drop_post_asset_dir"
down_revision: Union[str, None] = "006_brand_logo_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("posts", "asset_dir")


def downgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("asset_dir", sa.String(length=1024), nullable=False, server_default=""),
    )
