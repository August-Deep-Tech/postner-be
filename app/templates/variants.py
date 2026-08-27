from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.brands.variants import create_brand_variant, variant_to_dict
from app.config import Settings
from app.db.models import Brand
from app.generate.posts import propose_variant_palettes
from app.templates.engine import load_template_html
from app.templates.packs import build_pack_design_context


async def propose_and_save_variants(
    *,
    db: Session,
    brand: Brand,
    count: int,
    settings: Settings,
    template_id: str | None = None,
    pack_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Propose palettes for a pack/template and save them on the brand."""
    if pack_id and template_id:
        raise ValueError("Provide only one of template_id or pack_id")
    if not pack_id and not template_id:
        template_id = "default"

    if pack_id:
        ctx = build_pack_design_context(pack_id, settings)
        design_html = ctx["html"]
        design_label = f"pack '{pack_id}'"
        required_css_keys = ctx["css_keys"]
    else:
        assert template_id is not None
        design_html = load_template_html(template_id, settings)
        design_label = f"template '{template_id}'"
        required_css_keys = sorted(set(re.findall(r"--[\w-]+", design_html)))
        required_css_keys = [k for k in required_css_keys if not k.startswith("--font")]
        if not required_css_keys:
            required_css_keys = ["--bg", "--text", "--accent", "--accent-shape"]

    proposed = await propose_variant_palettes(
        design_html=design_html,
        count=count,
        settings=settings,
        design_label=design_label,
        required_css_keys=required_css_keys,
        brand_name=brand.name,
        brand_tagline=brand.tagline,
        brand_description=brand.description,
    )

    saved: list[dict[str, Any]] = []
    saved_ids: list[str] = []
    for item in proposed:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("id") or item.get("slug") or "variant")
        label = str(item.get("label") or slug)
        css_vars = item.get("css_vars") or {}
        row = create_brand_variant(
            db,
            brand=brand,
            slug=slug,
            label=label,
            css_vars=css_vars,
            commit=True,
        )
        saved.append(variant_to_dict(row))
        saved_ids.append(str(row.id))
    return saved, saved_ids
