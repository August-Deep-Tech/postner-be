from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote

from app.db.models import Post

# Match file:// URLs and common url(...) / src="..." wrappers
_FILE_URL_RE = re.compile(
    r"(?P<prefix>(?:src|href)\s*=\s*[\"']|url\(\s*[\"']?)(?P<url>file:[^\"')\s]+)(?P<suffix>[\"']?\s*\)|[\"'])",
    re.IGNORECASE,
)


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def file_url_to_path(url: str) -> Path | None:
    """Convert a file:// URL to a local Path, or None if not a file URL."""
    raw = (url or "").strip()
    if not raw.lower().startswith("file:"):
        return None
    path_part = raw[5:]
    if path_part.startswith("///"):
        path_part = path_part[3:]
    elif path_part.startswith("//"):
        path_part = path_part[2:]
    path_part = unquote(path_part)
    return Path(path_part)


def path_to_data_uri(path: Path) -> str | None:
    if not path.is_file():
        return None
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{_guess_mime(path)};base64,{b64}"


def html_for_browser_preview(html: str) -> str:
    """Rewrite file:// asset refs to data URIs so FE iframes/srcdoc can render."""

    def _replace(match: re.Match[str]) -> str:
        url = match.group("url")
        path = file_url_to_path(url)
        if path is None:
            return match.group(0)
        data_uri = path_to_data_uri(path)
        if not data_uri:
            return match.group(0)
        return f"{match.group('prefix')}{data_uri}{match.group('suffix')}"

    return _FILE_URL_RE.sub(_replace, html)


def resolve_page_html_path(post: Post, page: dict) -> Path | None:
    """Locate filled HTML for a composed page on disk."""
    run_dir = Path(post.asset_dir)
    name = page.get("html")
    if name:
        candidate = run_dir / str(name)
        if candidate.is_file():
            return candidate
    page_id = page.get("page_id") or "main"
    index = int(page.get("index") or 1)
    for candidate in (
        run_dir / f"filled_{index:02d}_{page_id}.html",
        run_dir / "filled.html",
        run_dir / f"filled_{page_id}.html",
    ):
        if candidate.is_file():
            return candidate
    return None


def raw_page_html(post: Post, page: dict) -> str | None:
    """Prefer DB html_source; fall back to disk cache."""
    source = page.get("html_source")
    if isinstance(source, str) and source.strip():
        return source
    path = resolve_page_html_path(post, page)
    if path is None:
        return None
    return path.read_text(encoding="utf-8")


def page_preview_html(post: Post, page: dict) -> str | None:
    raw = raw_page_html(post, page)
    if raw is None:
        return None
    return html_for_browser_preview(raw)


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
