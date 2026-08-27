from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brands.store import (
    BrandProfile,
    list_brand_ids,
    load_brand,
    normalize_brand_id,
    resolve_logo_path,
)
from typing import get_args

from app.config import Settings, SocialFormat
from app.db.models import Brand

_VALID_FORMATS = set(get_args(SocialFormat))


def _normalize_format(raw: str | None, *, default: str = "ig_feed") -> str:
    if not raw:
        return default
    value = str(raw).strip()
    if value not in _VALID_FORMATS:
        raise ValueError(
            f"Invalid format '{value}'. Expected one of: {', '.join(sorted(_VALID_FORMATS))}"
        )
    return value


def brand_to_profile(brand: Brand, settings: Settings) -> BrandProfile:
    """Map DB brand to file-style BrandProfile (logo may live under brands/<slug>/)."""
    root = settings.brands_dir / brand.slug
    if not root.is_dir():
        root = None
    return BrandProfile(
        id=brand.slug,
        name=brand.name,
        tagline=brand.tagline,
        description=brand.description,
        logo=brand.logo,
        root=root,
    )


def list_tenant_brands(db: Session, tenant_id: uuid.UUID) -> list[Brand]:
    return list(
        db.scalars(
            select(Brand)
            .where(Brand.tenant_id == tenant_id)
            .order_by(Brand.name.asc())
        ).all()
    )


def get_tenant_brand(
    db: Session,
    tenant_id: uuid.UUID,
    brand_id: str | uuid.UUID,
) -> Brand | None:
    """Lookup by UUID or slug within tenant."""
    raw = str(brand_id)
    try:
        bid = uuid.UUID(raw)
        brand = db.get(Brand, bid)
        if brand and brand.tenant_id == tenant_id:
            return brand
    except ValueError:
        pass
    return db.scalar(
        select(Brand).where(Brand.tenant_id == tenant_id, Brand.slug == raw)
    )


def create_brand(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    name: str,
    slug: str | None = None,
    tagline: str = "",
    description: str = "",
    website: str | None = None,
    logo: str | None = None,
    format: str | None = None,
) -> Brand:
    bid = normalize_brand_id(slug or name)
    existing = db.scalar(
        select(Brand).where(Brand.tenant_id == tenant_id, Brand.slug == bid)
    )
    if existing:
        raise ValueError(f"Brand slug '{bid}' already exists")
    brand = Brand(
        tenant_id=tenant_id,
        slug=bid,
        name=name.strip() or bid,
        tagline=tagline.strip(),
        description=description.strip(),
        website=(website or None),
        logo=Path(logo).name if logo else None,
        format=_normalize_format(format),
    )
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand


def update_brand(
    db: Session,
    brand: Brand,
    *,
    name: str | None = None,
    tagline: str | None = None,
    description: str | None = None,
    website: str | None = None,
    logo: str | None = None,
    format: str | None = None,
) -> Brand:
    if name is not None:
        brand.name = name.strip() or brand.name
    if tagline is not None:
        brand.tagline = tagline.strip()
    if description is not None:
        brand.description = description.strip()
    if website is not None:
        brand.website = website.strip() or None
    if logo is not None:
        brand.logo = Path(logo).name if logo else None
    if format is not None:
        brand.format = _normalize_format(format)
    db.commit()
    db.refresh(brand)
    return brand


def seed_gradde_for_tenant(db: Session, tenant_id: uuid.UUID, settings: Settings) -> Brand | None:
    """Copy file-based Gradde into tenant brands if missing."""
    existing = db.scalar(
        select(Brand).where(Brand.tenant_id == tenant_id, Brand.slug == "gradde")
    )
    if existing:
        return existing
    try:
        file_brand = load_brand("gradde", settings)
    except FileNotFoundError:
        return None
    brand = Brand(
        tenant_id=tenant_id,
        slug=file_brand.id,
        name=file_brand.name,
        tagline=file_brand.tagline,
        description=file_brand.description,
        website=None,
        logo=file_brand.logo,
    )
    db.add(brand)
    db.commit()
    db.refresh(brand)
    return brand


def resolve_brand_for_generate(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    brand_id: str | None,
    settings: Settings,
    allow_file_fallback: bool = True,
) -> BrandProfile | None:
    """Prefer DB brand; optionally fall back to file brands (AUTH_DISABLED / legacy)."""
    if not brand_id:
        return None
    if tenant_id is not None:
        row = get_tenant_brand(db, tenant_id, brand_id)
        if row:
            return brand_to_profile(row, settings)
    if allow_file_fallback:
        try:
            return load_brand(brand_id, settings)
        except FileNotFoundError:
            return None
    return None


__all__ = [
    "brand_to_profile",
    "create_brand",
    "get_tenant_brand",
    "list_brand_ids",
    "list_tenant_brands",
    "load_brand",
    "resolve_brand_for_generate",
    "resolve_logo_path",
    "seed_gradde_for_tenant",
    "update_brand",
]
