from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.config import SocialFormat


class GenerateRequest(BaseModel):
    url: HttpUrl
    template_id: str | None = None
    pack_id: str | None = None
    variant_id: str | None = None
    brand_id: str | None = None
    format: SocialFormat | None = None
    brand: str | None = None
    animate: bool = False
    motion_preset: str = "fade_kenburns"

    @model_validator(mode="after")
    def _require_template_or_pack(self) -> GenerateRequest:
        if self.pack_id and self.template_id:
            raise ValueError("Provide only one of template_id or pack_id")
        if not self.pack_id and not self.template_id:
            self.template_id = "default"
        if self.template_id and self.format is None:
            self.format = "ig_feed"
        return self


class ProposeVariantsRequest(BaseModel):
    template_id: str | None = None
    pack_id: str | None = None
    brand_id: str | None = None
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


class GenerateResponse(BaseModel):
    run_id: str
    post_type: str
    ig_fb_caption: str
    tiktok_script: str
    visual_prompt: str
    overlay_text: str
    page_type: str
    cta_link: str
    image_path: str | None
    final_path: str | None
    page_paths: list[str] = Field(default_factory=list)
    video_path: str | None = None
    page_video_paths: list[str] = Field(default_factory=list)
    meta_path: str
    template_id: str | None
    pack_id: str | None = None
    brand_id: str | None = None
    variant_id: str | None
    format: SocialFormat


class ProposeVariantsResponse(BaseModel):
    variants: list[dict[str, Any]]
    saved_ids: list[str]


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
