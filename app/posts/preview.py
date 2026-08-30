from __future__ import annotations

from app.db.models import Post


def page_preview_html(post: Post, page: dict) -> str | None:
    """Browser-ready filled HTML from DB html_source (assets are http(s) URLs)."""
    source = page.get("html_source")
    if isinstance(source, str) and source.strip():
        return source
    return None


def enrich_composed_with_html(post: Post) -> dict:
    """Return composed payload with html_content on each page for FE preview.

    Does not persist html_content back to the database.
    """
    composed = dict(post.composed or {})
    pages = []
    for entry in list(composed.get("pages") or []):
        item = dict(entry)
        preview = page_preview_html(post, item)
        if preview is not None:
            item["html_content"] = preview
        pages.append(item)
    composed["pages"] = pages
    return composed
