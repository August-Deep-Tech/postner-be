from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Brand, BrandVariant


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^\w\-]+", "_", (raw or "").strip()).strip("_").lower()
    return slug or "variant"


def _clean_css_vars(css_vars: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(css_vars, dict):
        raise ValueError("css_vars must be an object")
    return {
        (k if str(k).startswith("--") else f"--{k}"): v
        for k, v in css_vars.items()
        if not str(k).lower().lstrip("-").startswith("font")
    }


def variant_to_dict(row: BrandVariant) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "slug": row.slug,
        "label": row.label,
        "css_vars": dict(row.css_vars or {}),
        "brand_id": str(row.brand_id),
    }


def list_brand_variants(db: Session, brand: Brand) -> list[BrandVariant]:
    return list(
        db.scalars(
            select(BrandVariant)
            .where(BrandVariant.brand_id == brand.id)
            .order_by(BrandVariant.created_at.asc())
        ).all()
    )


def get_brand_variant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    brand: Brand | None,
    variant_id: str,
) -> BrandVariant | None:
    """Lookup by UUID or slug. Prefer brand scope when provided."""
    raw = (variant_id or "").strip()
    if not raw:
        return None

    try:
        vid = uuid.UUID(raw)
        row = db.get(BrandVariant, vid)
        if row is None or row.tenant_id != tenant_id:
            return None
        if brand is not None and row.brand_id != brand.id:
            return None
        return row
    except ValueError:
        pass

    if brand is None:
        return None
    return db.scalar(
        select(BrandVariant).where(
            BrandVariant.brand_id == brand.id,
            BrandVariant.slug == raw,
        )
    )


def create_brand_variant(
    db: Session,
    *,
    brand: Brand,
    slug: str,
    label: str,
    css_vars: dict[str, Any],
    commit: bool = True,
) -> BrandVariant:
    cleaned = _clean_css_vars(css_vars)
    base = _slugify(slug)
    candidate = base
    n = 2
    while db.scalar(
        select(BrandVariant.id).where(
            BrandVariant.brand_id == brand.id,
            BrandVariant.slug == candidate,
        )
    ):
        candidate = f"{base}_{n}"
        n += 1

    row = BrandVariant(
        tenant_id=brand.tenant_id,
        brand_id=brand.id,
        slug=candidate,
        label=(label or candidate).strip() or candidate,
        css_vars=cleaned,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def seed_brand_variants_from_disk(
    db: Session,
    brand: Brand,
    settings: Settings,
) -> list[BrandVariant]:
    """Copy starter JSON palettes from variants/ into the brand (skip if any exist)."""
    existing = list_brand_variants(db, brand)
    if existing:
        return existing

    root: Path = settings.variants_dir
    if not root.is_dir():
        return []

    created: list[BrandVariant] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "css_vars" in data and isinstance(data["css_vars"], dict):
            css_vars = data["css_vars"]
            slug = str(data.get("id") or path.stem)
            label = str(data.get("label") or slug)
        elif isinstance(data, dict) and all(str(k).startswith("--") for k in data):
            css_vars = data
            slug = path.stem
            label = path.stem
        else:
            continue
        try:
            created.append(
                create_brand_variant(
                    db,
                    brand=brand,
                    slug=slug,
                    label=label,
                    css_vars=css_vars,
                    commit=False,
                )
            )
        except ValueError:
            continue
    if created:
        db.commit()
        for row in created:
            db.refresh(row)
    return created
