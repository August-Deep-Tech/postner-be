from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.config import SocialFormat


class ProposePacksRequest(BaseModel):
    brand_id: str | None = None
    format: SocialFormat = "ig_portrait"
    count: int = Field(default=2, ge=1, le=4)
    brief: str = ""


class ProposePacksResponse(BaseModel):
    packs: list[dict[str, Any]]
    saved_pack_ids: list[str]


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
