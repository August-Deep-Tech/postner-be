"""Post responses should never carry a page's markup twice, and the lean
default for GET /posts should not cost undo the ability to still render.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import PostRevision


def _compose_single_post(client, make_post, **overrides):
    """A single-mode post with an image already attached, then composed."""
    post = make_post(
        images={"by_page": {"main": {"url": "https://cdn.example.test/photo.png"}}},
        **overrides,
    )
    resp = client.post(f"/posts/{post.id}/compose")
    assert resp.status_code == 200, resp.text
    return post


def test_response_does_not_duplicate_markup(client, make_post):
    post = _compose_single_post(client, make_post)

    page = client.get(f"/posts/{post.id}").json()["composed"]["pages"][0]
    assert "html_content" in page and page["html_content"]
    assert "html_source" not in page

    list_page = client.get("/posts").json()["posts"][0]["composed"]["pages"][0]
    assert "html_content" not in list_page
    assert "html_source" not in list_page


def test_list_posts_include_html_returns_preview(client, make_post):
    _compose_single_post(client, make_post)

    list_page = client.get("/posts?include=html").json()["posts"][0]["composed"]["pages"][0]
    assert "html_content" in list_page and list_page["html_content"]
    assert "html_source" not in list_page


def test_revision_payload_excludes_html_source(db, client, make_post):
    post = _compose_single_post(client, make_post)

    revision = db.scalars(
        select(PostRevision)
        .where(PostRevision.post_id == post.id)
        .order_by(PostRevision.version.desc())
    ).first()
    assert revision is not None
    page = revision.payload["composed"]["pages"][0]
    assert "html_source" not in page
    assert page["page_id"] == "main"


def test_undo_restores_renderable_html(client, make_post):
    post = _compose_single_post(client, make_post)
    pid = post.id

    original = client.get(f"/posts/{pid}").json()["composed"]["pages"][0]
    assert "original caption" in original["html_content"]

    resp = client.post(
        f"/posts/{pid}/rewrite",
        json={"caption": "new caption", "recompose": True},
    )
    assert resp.status_code == 200, resp.text
    rewritten = resp.json()["composed"]["pages"][0]
    assert "new caption" in rewritten["html_content"]

    resp = client.post(f"/posts/{pid}/undo")
    assert resp.status_code == 200, resp.text
    restored = resp.json()["composed"]["pages"][0]
    assert "html_content" in restored and restored["html_content"]
    assert "original caption" in restored["html_content"]
    assert "new caption" not in restored["html_content"]
