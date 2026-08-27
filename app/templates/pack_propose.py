from __future__ import annotations

from typing import Any

from app.brands.store import load_brand
from app.config import Settings, SocialFormat
from app.generate.posts import propose_pack_structures
from app.templates.packs import materialize_proposed_pack, page_catalog
from app.templates.variants import propose_and_save_variants


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


async def propose_and_save_packs(
    *,
    count: int,
    format_name: SocialFormat,
    settings: Settings,
    brief: str = "",
    brand_id: str | None = None,
    with_variants: bool = True,
    variant_count: int = 3,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[str]]:
    catalog = page_catalog(settings)
    if not catalog:
        raise ValueError("No pack page catalog available — add at least one pack under templates/packs/")

    brand_name, brand_tagline, brand_description = _brand_voice(brand_id, settings)
    proposed = await propose_pack_structures(
        catalog=catalog,
        count=count,
        format_name=format_name,
        settings=settings,
        brief=brief,
        brand_name=brand_name,
        brand_tagline=brand_tagline,
        brand_description=brand_description,
    )

    saved_summaries: list[dict[str, Any]] = []
    saved_pack_ids: list[str] = []
    for item in proposed:
        summary = materialize_proposed_pack(
            item,
            settings=settings,
            format_name=format_name,
        )
        saved_summaries.append(summary)
        saved_pack_ids.append(str(summary["id"]))

    variants: list[dict[str, Any]] = []
    saved_variant_ids: list[str] = []
    if with_variants and saved_pack_ids:
        # Propose variants against the first new pack (shared skins for the batch)
        variants, saved_variant_ids = await propose_and_save_variants(
            pack_id=saved_pack_ids[0],
            count=variant_count,
            settings=settings,
            brand_id=brand_id,
        )

    return saved_summaries, saved_pack_ids, variants, saved_variant_ids
