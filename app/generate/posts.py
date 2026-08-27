from __future__ import annotations

import json
import os
import re
from typing import Any

import litellm

from app.config import Settings, resolve_llm_model
from app.generate.prompts import (
    CAROUSEL_SYSTEM_PROMPT,
    PACK_PROPOSE_SYSTEM_PROMPT,
    POST_SYSTEM_PROMPT,
    VARIANT_SYSTEM_PROMPT,
    build_carousel_user_prompt,
    build_pack_propose_user_prompt,
    build_post_user_prompt,
    build_variant_user_prompt,
)
from app.models.schemas import CarouselSlide, GeneratedCarousel, GeneratedPost
from app.scrape.page import ScrapedPage
from app.templates.packs import TemplatePack, pack_field_schema


def _extract_json(content: str) -> Any:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


def _ensure_llm_keys(settings: Settings) -> None:
    if settings.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)


async def generate_post(
    page: ScrapedPage,
    settings: Settings,
    *,
    brand_name: str = "",
    brand_tagline: str = "",
    brand_description: str = "",
) -> GeneratedPost:
    _ensure_llm_keys(settings)
    response = await litellm.acompletion(
        model=resolve_llm_model(settings),
        messages=[
            {"role": "system", "content": POST_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_post_user_prompt(
                    url=page.url,
                    title=page.title,
                    page_type_hint=page.page_type,
                    text=page.text,
                    brand_name=brand_name,
                    brand_tagline=brand_tagline,
                    brand_description=brand_description,
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    raw = response.choices[0].message.content or "{}"
    data = _extract_json(raw)
    return GeneratedPost.model_validate(data)


async def generate_carousel(
    page: ScrapedPage,
    pack: TemplatePack,
    settings: Settings,
    *,
    brand_name: str = "",
    brand_tagline: str = "",
    brand_description: str = "",
) -> GeneratedCarousel:
    _ensure_llm_keys(settings)
    response = await litellm.acompletion(
        model=resolve_llm_model(settings),
        messages=[
            {"role": "system", "content": CAROUSEL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_carousel_user_prompt(
                    url=page.url,
                    title=page.title,
                    page_type_hint=page.page_type,
                    text=page.text,
                    pack_id=pack.id,
                    pack_label=pack.label,
                    default_brand=pack.default_brand,
                    page_schema=pack_field_schema(pack),
                    brand_name=brand_name,
                    brand_tagline=brand_tagline,
                    brand_description=brand_description,
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    raw = response.choices[0].message.content or "{}"
    data = _extract_json(raw)
    carousel = GeneratedCarousel.model_validate(data)

    by_id = {s.page_id: s for s in carousel.slides}
    ordered: list[CarouselSlide] = []
    shared_series = ""
    for slide in carousel.slides:
        if slide.series.strip():
            shared_series = slide.series.strip()
            break

    for index, page_def in enumerate(pack.sequenced_pages(), start=1):
        slide = by_id.get(page_def.id) or CarouselSlide(page_id=page_def.id)
        if "page_number" in page_def.fields and not slide.page_number:
            slide.page_number = f"{index:02d}"
        if "next" in page_def.fields and not slide.next:
            slide.next = f"{index + 1:02d}"
        if "series" in page_def.fields:
            slide.series = slide.series.strip() or shared_series
            if slide.series:
                shared_series = slide.series
        if "handle" in page_def.fields and not slide.handle and brand_name:
            slide.handle = "@" + brand_name.replace(" ", "")
        if brand_name:
            slide.brand = brand_name
        elif not slide.brand:
            slide.brand = carousel.brand or pack.default_brand
        if page_def.images > 0 and not slide.visual_prompt:
            slide.visual_prompt = carousel.visual_prompt
        ordered.append(slide)
    carousel.slides = ordered
    if brand_name:
        carousel.brand = brand_name
    elif not carousel.brand:
        carousel.brand = pack.default_brand
    return carousel


async def propose_variant_palettes(
    *,
    design_html: str,
    count: int,
    settings: Settings,
    design_label: str = "template",
    required_css_keys: list[str] | None = None,
    brand_name: str = "",
    brand_tagline: str = "",
    brand_description: str = "",
) -> list[dict[str, Any]]:
    _ensure_llm_keys(settings)
    response = await litellm.acompletion(
        model=resolve_llm_model(settings),
        messages=[
            {"role": "system", "content": VARIANT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_variant_user_prompt(
                    design_html=design_html,
                    count=count,
                    design_label=design_label,
                    required_css_keys=required_css_keys,
                    brand_name=brand_name,
                    brand_tagline=brand_tagline,
                    brand_description=brand_description,
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.8,
    )
    raw = response.choices[0].message.content or "{}"
    data = _extract_json(raw)
    variants = data.get("variants", data if isinstance(data, list) else [])
    if not isinstance(variants, list):
        raise ValueError("LLM did not return a variants list")
    return variants


async def propose_pack_structures(
    *,
    catalog: list[dict[str, Any]],
    count: int,
    format_name: str,
    settings: Settings,
    brief: str = "",
    brand_name: str = "",
    brand_tagline: str = "",
    brand_description: str = "",
) -> list[dict[str, Any]]:
    _ensure_llm_keys(settings)
    response = await litellm.acompletion(
        model=resolve_llm_model(settings),
        messages=[
            {"role": "system", "content": PACK_PROPOSE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_pack_propose_user_prompt(
                    catalog=catalog,
                    count=count,
                    format_name=format_name,
                    brief=brief,
                    brand_name=brand_name,
                    brand_tagline=brand_tagline,
                    brand_description=brand_description,
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    raw = response.choices[0].message.content or "{}"
    data = _extract_json(raw)
    packs = data.get("packs", data if isinstance(data, list) else [])
    if not isinstance(packs, list):
        raise ValueError("LLM did not return a packs list")
    return packs
