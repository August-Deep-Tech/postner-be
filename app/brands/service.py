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


def _normalize_formats(
    raw: list[str] | str | None,
    *,
    default: list[str] | None = None,
) -> list[str]:
    """Normalize to a non-empty unique ordered list of SocialFormat values."""
    if default is None:
        default = ["ig_feed"]
    if raw is None:
        return list(default)
    if isinstance(raw, str):
        items = [raw]
    else:
        items = list(raw)
    out: list[str] = []
    for item in items:
        value = str(item).strip()
        if not value:
            continue
        if value not in _VALID_FORMATS:
            raise ValueError(
                f"Invalid format '{value}'. Expected one of: {', '.join(sorted(_VALID_FORMATS))}"
            )
        if value not in out:
            out.append(value)
    if not out:
        return list(default)
    return out


def brand_formats(brand: Brand) -> list[str]:
    raw = getattr(brand, "formats", None) or []
    if isinstance(raw, str):
        return _normalize_formats(raw)
    try:
        return _normalize_formats(list(raw))
    except ValueError:
        return ["ig_feed"]


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
    formats: list[str] | str | None = None,
    settings: Settings | None = None,
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
        formats=_normalize_formats(formats),
    )
    db.add(brand)
    db.commit()
    db.refresh(brand)
    if settings is not None:
        from app.brands.variants import seed_brand_variants_from_disk

        seed_brand_variants_from_disk(db, brand, settings)
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
    formats: list[str] | str | None = None,
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
    if formats is not None:
        brand.formats = _normalize_formats(formats)
    db.commit()
    db.refresh(brand)
    return brand


__all__ = [
    "brand_formats",
    "brand_to_profile",
    "create_brand",
    "get_tenant_brand",
    "list_brand_ids",
    "list_tenant_brands",
    "load_brand",
    "resolve_logo_path",
    "update_brand",
]
