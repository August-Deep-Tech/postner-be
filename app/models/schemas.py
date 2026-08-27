from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.config import SocialFormat


class ProposeVariantsRequest(BaseModel):
    brand_id: str
    template_id: str | None = None
    pack_id: str | None = None
    count: int = Field(default=3, ge=1, le=8)

    @model_validator(mode="after")
    def _template_or_pack(self) -> ProposeVariantsRequest:
        if self.pack_id and self.template_id:
            raise ValueError("Provide only one of template_id or pack_id")
        if not self.pack_id and not self.template_id:
            self.template_id = "default"
        return self


class ProposePacksRequest(BaseModel):
    brand_id: str | None = None
    format: SocialFormat = "ig_portrait"
    count: int = Field(default=2, ge=1, le=4)
    with_variants: bool = True
    variant_count: int = Field(default=3, ge=1, le=8)
    brief: str = ""

    @model_validator(mode="after")
    def _variants_need_brand(self) -> ProposePacksRequest:
        if self.with_variants and not self.brand_id:
            raise ValueError("brand_id is required when with_variants is true")
        return self


class ProposePacksResponse(BaseModel):
    packs: list[dict[str, Any]]
    saved_pack_ids: list[str]
    variants: list[dict[str, Any]] = Field(default_factory=list)
    saved_variant_ids: list[str] = Field(default_factory=list)


class GeneratedPost(BaseModel):
    post_type: str
    ig_fb_caption: str
    tiktok_script: str
    visual_prompt: str
    overlay_text: str
    page_type: str


class CarouselSlide(BaseModel):
    page_id: str
    title: str = ""
    subtitle: str = ""
    body: str = ""
    body_2: str = ""
    body_emphasis: str = ""
    page_number: str = ""
    cta: str = ""
    brand: str = ""
    series: str = ""
    script: str = ""
    next: str = ""
    handle: str = ""
    visual_prompt: str = ""

    def field_map(self) -> dict[str, str]:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "body": self.body,
            "body_2": self.body_2,
            "body_emphasis": self.body_emphasis,
            "page_number": self.page_number,
            "cta": self.cta,
            "brand": self.brand,
            "series": self.series,
            "script": self.script,
            "next": self.next,
            "handle": self.handle,
        }


class GeneratedCarousel(BaseModel):
    post_type: str
    page_type: str
    brand: str = ""
    ig_fb_caption: str
    tiktok_script: str = ""
    visual_prompt: str = ""
    slides: list[CarouselSlide]


class ProposeVariantsResponse(BaseModel):
    variants: list[dict[str, Any]]
    saved_ids: list[str]


class VariantOut(BaseModel):
    id: str
    slug: str
    label: str
    css_vars: dict[str, Any]
    brand_id: str


class ListVariantsResponse(BaseModel):
    variants: list[VariantOut]


class HealthResponse(BaseModel):
    status: str = "ok"


class ListIdsResponse(BaseModel):
    ids: list[str]


class PackSummary(BaseModel):
    id: str
    label: str
    format: SocialFormat
    pages: int
    images: int
    description: str = ""


class ListPacksResponse(BaseModel):
    packs: list[PackSummary]
