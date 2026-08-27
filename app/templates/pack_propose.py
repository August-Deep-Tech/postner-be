from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, SocialFormat
from app.db.models import Brand
from app.generate.posts import propose_pack_structures
from app.templates.packs import materialize_proposed_pack, page_catalog
from app.templates.variants import propose_and_save_variants


async def propose_and_save_packs(
    *,
    count: int,
    format_name: SocialFormat,
    settings: Settings,
    brief: str = "",
    brand: Brand | None = None,
    db: Session | None = None,
    with_variants: bool = True,
    variant_count: int = 3,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[str]]:
    catalog = page_catalog(settings)
    if not catalog:
        raise ValueError(
            "No pack page catalog available — add at least one pack under templates/packs/"
        )

    brand_name = brand.name if brand else ""
    brand_tagline = brand.tagline if brand else ""
    brand_description = brand.description if brand else ""
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
        if brand is None or db is None:
            raise ValueError("brand_id is required when with_variants is true")
        # Propose variants against the first new pack (skins saved on the brand)
        variants, saved_variant_ids = await propose_and_save_variants(
            db=db,
            brand=brand,
            pack_id=saved_pack_ids[0],
            count=variant_count,
            settings=settings,
        )

    return saved_summaries, saved_pack_ids, variants, saved_variant_ids
