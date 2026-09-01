from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import app.generate.posts as llm_posts
from app.db.models import Post
from app.posts import service as post_service
from app.scrape.page import ScrapedPage
from app.templates.packs import load_pack, pack_field_schema

PACK_ID = "lifestyle_tips"
EXPECTED_SEQUENCE = ["cover", "tip_left", "tip_right", "closing"]

# Deliberately out of order and missing two pages: generate_carousel is
# responsible for normalising whatever the LLM returns onto the pack sequence,
# and the alignment guarantee depends on it doing so.
CAROUSEL_PAYLOAD = {
    "post_type": "tips_carousel",
    "page_type": "feature",
    "brand": "Acme",
    "ig_fb_caption": "Four small habits",
    "tiktok_script": "Here are four habits",
    "visual_prompt": "warm editorial lifestyle photo",
    "slides": [
        {"page_id": "closing", "title": "Come say hi", "body": "Follow along"},
        {"page_id": "cover", "title": "Four habits", "script": "psst"},
    ],
}

POST_PAYLOAD = {
    "post_type": "announcement",
    "ig_fb_caption": "generated caption",
    "tiktok_script": "generated script",
    "visual_prompt": "generated prompt",
    "overlay_text": "generated overlay",
    "page_type": "feature",
}


def _llm_response(payload: dict) -> SimpleNamespace:
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _scraped_page() -> ScrapedPage:
    return ScrapedPage(
        url="https://example.com/habits",
        title="Habits",
        text="body text",
        page_type="feature",
    )


@pytest.fixture()
def stub_llm(monkeypatch):
    """Stub only the network call, so the real generation logic still runs."""

    def _stub(payload: dict) -> None:
        async def fake_acompletion(**_kwargs):
            return _llm_response(payload)

        monkeypatch.setattr(llm_posts.litellm, "acompletion", fake_acompletion)

    return _stub


@pytest.fixture()
def stub_scrape(monkeypatch):
    async def fake_scrape_page(url: str, timeout: float = 30.0) -> ScrapedPage:
        return _scraped_page()

    monkeypatch.setattr(post_service, "scrape_page", fake_scrape_page)


def _create_pack_draft(db, tenant, settings):
    return asyncio.run(
        post_service.create_draft_post(
            db,
            tenant_id=tenant.id,
            url="https://example.com/habits",
            brand_id=None,
            pack_id=PACK_ID,
            template_id=None,
            format_name=None,
            variant_id=None,
            with_images=False,
            settings=settings,
        )
    )


def test_generated_slides_follow_the_same_sequence_as_the_field_schema(
    settings, stub_llm
):
    stub_llm(CAROUSEL_PAYLOAD)
    pack = load_pack(PACK_ID, settings)

    carousel = asyncio.run(
        llm_posts.generate_carousel(_scraped_page(), pack, settings)
    )
    schema = pack_field_schema(pack)

    assert [p.id for p in pack.sequenced_pages()] == EXPECTED_SEQUENCE
    assert len(carousel.slides) == len(schema)
    assert [s.page_id for s in carousel.slides] == [e["page_id"] for e in schema]
    assert [e["index"] for e in schema] == [1, 2, 3, 4]


def test_pack_draft_stores_pack_pages_aligned_with_slides(
    db, tenant, settings, stub_llm, stub_scrape
):
    stub_llm(CAROUSEL_PAYLOAD)

    post = _create_pack_draft(db, tenant, settings)

    content = post.content
    pack_pages = content["pack_pages"]
    slides = content["slides"]

    assert len(pack_pages) == len(slides) == 4
    for entry, slide in zip(pack_pages, slides):
        assert entry["page_id"] == slide["page_id"]
        assert entry["fields"]
    assert [e["page_id"] for e in pack_pages] == EXPECTED_SEQUENCE
    assert [e["page_id"] for e in pack_pages] == content["pack_page_ids"]


def test_pack_pages_entries_describe_the_manifest(
    db, tenant, settings, stub_llm, stub_scrape
):
    stub_llm(CAROUSEL_PAYLOAD)

    post = _create_pack_draft(db, tenant, settings)

    by_id = {e["page_id"]: e for e in post.content["pack_pages"]}
    assert by_id["cover"] == {
        "page_id": "cover",
        "index": 1,
        "role": "cover",
        "tags": ["cover", "peek_image", "swipe", "script"],
        "images": 1,
        "fields": ["script", "title"],
    }
    assert by_id["closing"]["fields"] == [
        "page_number",
        "title",
        "body",
        "handle",
    ]
    assert by_id["closing"]["index"] == 4


def test_pack_pages_survives_the_commit(db, tenant, settings, stub_llm, stub_scrape):
    stub_llm(CAROUSEL_PAYLOAD)

    post = _create_pack_draft(db, tenant, settings)
    db.expire_all()

    reloaded = db.get(Post, post.id)
    assert reloaded is not None
    assert [e["page_id"] for e in reloaded.content["pack_pages"]] == EXPECTED_SEQUENCE


def test_single_mode_draft_has_no_pack_pages(
    db, tenant, settings, stub_llm, stub_scrape
):
    stub_llm(POST_PAYLOAD)

    post = asyncio.run(
        post_service.create_draft_post(
            db,
            tenant_id=tenant.id,
            url="https://example.com/habits",
            brand_id=None,
            pack_id=None,
            template_id="default",
            format_name=None,
            variant_id=None,
            with_images=False,
            settings=settings,
        )
    )

    assert post.content["mode"] == "single"
    assert "pack_pages" not in post.content
    assert "pack_page_ids" not in post.content


def test_rewrite_suggest_refreshes_pack_pages(
    db, make_post, settings, stub_llm, stub_scrape
):
    stub_llm(CAROUSEL_PAYLOAD)
    post = make_post(
        pack_id=PACK_ID,
        template_id=None,
        format="ig_portrait",
        content={
            "mode": "pack",
            "ig_fb_caption": "old caption",
            "slides": [{"page_id": "cover", "title": "old"}],
            "pack_page_ids": ["gone_page"],
            "pack_pages": [
                {
                    "page_id": "gone_page",
                    "index": 1,
                    "role": "cover",
                    "tags": [],
                    "images": 0,
                    "fields": ["stale_field"],
                }
            ],
        },
    )

    updated = asyncio.run(
        post_service.rewrite_post(
            db,
            post=post,
            text=None,
            caption=None,
            suggest=True,
            recompose=False,
            settings=settings,
        )
    )

    pack_pages = updated.content["pack_pages"]
    slides = updated.content["slides"]
    assert [e["page_id"] for e in pack_pages] == EXPECTED_SEQUENCE
    assert [s["page_id"] for s in slides] == EXPECTED_SEQUENCE
    assert updated.content["pack_page_ids"] == EXPECTED_SEQUENCE
    assert all(e["fields"] for e in pack_pages)


def test_rewrite_without_suggest_leaves_content_keys_alone(
    db, make_post, settings, stub_scrape
):
    post = make_post(
        pack_id=PACK_ID,
        template_id=None,
        content={
            "mode": "pack",
            "ig_fb_caption": "old caption",
            "slides": [{"page_id": "cover", "title": "old"}],
        },
    )

    updated = asyncio.run(
        post_service.rewrite_post(
            db,
            post=post,
            text=None,
            caption="new caption",
            suggest=False,
            recompose=False,
            settings=settings,
        )
    )

    assert updated.content["ig_fb_caption"] == "new caption"
    assert "pack_pages" not in updated.content
