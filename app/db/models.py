from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

# JSONB on Postgres; JSON elsewhere (sqlite smoke)
JsonType = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="tenant")
    brands: Mapped[list[Brand]] = relationship(back_populates="tenant")
    posts: Mapped[list[Post]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(64), default="owner", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Brand(Base):
    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_brand_tenant_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tagline: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    website: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    logo: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Preferred social canvas; used as default post format + Recraft aspect
    format: Mapped[str] = mapped_column(String(32), default="ig_feed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    tenant: Mapped[Tenant] = relationship(back_populates="brands")
    posts: Mapped[list[Post]] = relationship(back_populates="brand")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(64), default="drafted", nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    format: Mapped[str] = mapped_column(String(32), default="ig_feed", nullable=False)
    pack_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    variant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asset_dir: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Flexible payloads
    content: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    images: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    composed: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    tenant: Mapped[Tenant] = relationship(back_populates="posts")
    brand: Mapped[Brand | None] = relationship(back_populates="posts")
    revisions: Mapped[list[PostRevision]] = relationship(back_populates="post")
    feedback_items: Mapped[list[Feedback]] = relationship(back_populates="post")


class PostRevision(Base):
    __tablename__ = "post_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    post_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    post: Mapped[Post] = relationship(back_populates="revisions")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    post_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    reasons: Mapped[list[Any]] = mapped_column(JsonType, default=list, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    page_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    post: Mapped[Post] = relationship(back_populates="feedback_items")
