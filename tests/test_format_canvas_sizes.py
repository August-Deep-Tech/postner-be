from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import app.generate.posts as llm_posts
from app.config import SOCIAL_SIZES
from app.posts import service as post_service
from app.scrape.page import ScrapedPage


def _llm_response(payload: dict) -> SimpleNamespace:
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture()
def stub_scrape(monkeypatch):
    async def fake_scrape_page(url: str, timeout: float = 30.0) -> ScrapedPage:
        return ScrapedPage(
            url=url,
            title="Source",
            text="source text",
            page_type="feature",
        )

    monkeypatch.setattr(post_service, "scrape_page", fake_scrape_page)


@pytest.fixture()
def stub_llm(monkeypatch):
    def _stub(payload: dict) -> None:
        async def fake_acompletion(**_kwargs):
            return _llm_response(payload)

        monkeypatch.setattr(llm_posts.litellm, "acompletion", fake_acompletion)

    return _stub


@pytest.mark.parametrize("fmt,size", list(SOCIAL_SIZES.items()))
def test_fill_injects_canvas_css_vars_for_format(make_post, settings, fmt, size):
    post = make_post(
        format=fmt,
        content={"mode": "single", "overlay_text": "caption"},
        images={"by_page": {"main": {"url": "https://example.com/image.png"}}},
    )
    filled = post_service._fill_pages_html(  # noqa: SLF001
        post,
        settings,
        by_page=dict((post.images or {}).get("by_page") or {}),
    )
    html = filled["main"]["html_source"]
    assert f"--canvas-w: {size[0]}px;" in html
    assert f"--canvas-h: {size[1]}px;" in html
    assert "width: var(--canvas-w);" in html
    assert "height: var(--canvas-h);" in html


def test_resize_updates_dimensions_and_clears_touched_png_fields(
    db, make_post, settings
):
    post = make_post(
        format="ig_portrait",
        pack_id="gentle_reminders",
        template_id=None,
        content={
            "mode": "pack",
            "slides": [],
            "pack_images_needed": 0,
        },
        composed={
            "pages": [
                {"index": 1, "page_id": "cover", "url": "https://example.com/cover.png", "key": "cover-key"},
                {"index": 2, "page_id": "intro", "url": "https://example.com/intro.png", "key": "intro-key"},
            ]
        },
    )
    updated = asyncio.run(
        post_service.resize_post(
            db,
            post=post,
            format_name="x_post",
            pages=["cover"],
            apply_to_post=True,
            settings=settings,
        )
    )

    pages = {p["page_id"]: p for p in (updated.composed or {}).get("pages", [])}
    assert updated.format == "x_post"
    assert pages["cover"]["width"] == 1600
    assert pages["cover"]["height"] == 900
    assert "url" not in pages["cover"]
    assert "key" not in pages["cover"]
    # Unaffected page is preserved when resizing a subset.
    assert pages["intro"]["url"] == "https://example.com/intro.png"
    assert pages["intro"]["key"] == "intro-key"


def test_lifestyle_tips_accepts_all_aspect_families(
    db, tenant, settings, stub_llm, stub_scrape
):
    from app.templates.packs import load_pack

    pack = load_pack("lifestyle_tips", settings)
    assert set(pack.formats) == {
        "ig_feed",
        "ig_portrait",
        "ig_story",
        "tiktok",
        "fb_post",
        "x_post",
    }

    stub_llm(
        {
            "post_type": "tips",
            "page_type": "feature",
            "brand": "",
            "ig_fb_caption": "caption",
            "tiktok_script": "script",
            "visual_prompt": "prompt",
            "slides": [{"page_id": "cover", "title": "title"}],
        }
    )
    post = asyncio.run(
        post_service.create_draft_post(
            db,
            tenant_id=tenant.id,
            url="https://example.com/tips",
            brand_id=None,
            pack_id="lifestyle_tips",
            template_id=None,
            format_name="x_post",
            image_style="realistic",
            with_images=False,
            settings=settings,
        )
    )
    assert post.format == "x_post"


def test_catalog_packs_include_formats(client):
    response = client.get("/packs")
    assert response.status_code == 200
    payload = response.json()
    assert "packs" in payload
    assert payload["packs"]
    assert "formats" in payload["packs"][0]
