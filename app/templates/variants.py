from __future__ import annotations

import re
from typing import Any

from app.brands.store import load_brand
from app.config import Settings
from app.generate.posts import propose_variant_palettes
from app.templates.engine import load_template_html, save_variant
from app.templates.packs import build_pack_design_context


def _brand_voice(
    brand_id: str | None, settings: Settings
) -> tuple[str, str, str]:
    if not brand_id:
        return "", "", ""
    try:
        brand = load_brand(brand_id, settings)
    except FileNotFoundError:
        return "", "", ""
    return brand.name, brand.tagline, brand.description


async def propose_and_save_variants(
    *,
    count: int,
    settings: Settings,
    template_id: str | None = None,
    pack_id: str | None = None,
    brand_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if pack_id and template_id:
        raise ValueError("Provide only one of template_id or pack_id")
    if not pack_id and not template_id:
        template_id = "default"

    brand_name, brand_tagline, brand_description = _brand_voice(brand_id, settings)

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
        # Prefer color-ish keys; still pass all --* except font
        required_css_keys = [k for k in required_css_keys if not k.startswith("--font")]
        if not required_css_keys:
            required_css_keys = ["--bg", "--text", "--accent", "--accent-shape"]

    variants = await propose_variant_palettes(
        design_html=design_html,
        count=count,
        settings=settings,
        design_label=design_label,
        required_css_keys=required_css_keys,
        brand_name=brand_name,
        brand_tagline=brand_tagline,
        brand_description=brand_description,
    )
    saved_ids: list[str] = []
    for variant in variants:
        saved_ids.append(save_variant(variant, settings))
    return variants, saved_ids
