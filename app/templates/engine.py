from __future__ import annotations

import html as html_lib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.config import Settings


PLACEHOLDER_CAPTION = "{{caption}}"
PLACEHOLDER_IMAGE = "{{image_url}}"
PLACEHOLDER_CTA = "{{cta_link}}"

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")
_URL_KEYS = {"image_url", "logo_url", "cta_link"}
_SAFE_URL_SCHEMES = {"https", "http"}  # http kept for local dev backends; no file:, no data:


def _safe_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if urlsplit(raw).scheme.lower() not in _SAFE_URL_SCHEMES:
        return ""
    return html_lib.escape(raw, quote=True)


def fill_placeholders(html: str, values: dict[str, str]) -> str:
    """Replace {{key}} tokens; unknown keys become empty string.

    Text values are HTML-escaped. URL-like keys are also scheme-allowlisted
    (http/https only) so they cannot break out of src/href attributes.
    """

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        raw = values.get(key)
        if raw is None:
            return ""
        text = str(raw)
        if key in _URL_KEYS or key.startswith("image_") or key.endswith("_url"):
            return _safe_url(text)
        return html_lib.escape(text, quote=True)

    return _PLACEHOLDER_RE.sub(_repl, html)


def fill_template(
    html: str,
    *,
    caption: str,
    image_url: str,
    cta_link: str = "",
    brand: str = "",
    tagline: str = "",
    logo_url: str = "",
) -> str:
    return fill_placeholders(
        html,
        {
            "caption": caption,
            "image_url": image_url,
            "cta_link": cta_link,
            "brand": brand,
            "tagline": tagline,
            "logo_url": logo_url,
        },
    )


def list_template_ids(settings: Settings) -> list[str]:
    if not settings.templates_dir.exists():
        return []
    return sorted(
        p.stem
        for p in settings.templates_dir.glob("*.html")
        if p.is_file()
    )


def resolve_template_path(template_id: str, settings: Settings) -> Path:
    path = settings.templates_dir / f"{template_id}.html"
    if path.is_file():
        return path

    # Fallback: first available html if requesting default
    ids = list_template_ids(settings)
    if template_id == "default" and ids:
        return settings.templates_dir / f"{ids[0]}.html"

    raise FileNotFoundError(
        f"Template '{template_id}' not found in {settings.templates_dir}. "
        "Drop an HTML file there (see templates/README.md)."
    )


def load_template_html(template_id: str, settings: Settings) -> str:
    return resolve_template_path(template_id, settings).read_text(encoding="utf-8")


_ROOT_BLOCK_RE = re.compile(
    r"(:root\s*\{)(.*?)(\})",
    re.DOTALL | re.IGNORECASE,
)
_VAR_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")


def apply_color_variant(html: str, css_vars: dict[str, str]) -> str:
    """Rewrite only :root custom properties; leave layout and font-family alone."""
    if not css_vars:
        return html

    normalized = {
        (k if k.startswith("--") else f"--{k}"): v for k, v in css_vars.items()
    }

    def _replace_root(match: re.Match[str]) -> str:
        prefix, body, suffix = match.group(1), match.group(2), match.group(3)
        existing = {m.group(1): m.group(2).strip() for m in _VAR_RE.finditer(body)}
        # Never allow font vars from a variant
        for key, value in normalized.items():
            if key.lower().startswith("--font"):
                continue
            existing[key] = value

        lines = [f"  {k}: {v};" for k, v in existing.items()]
        return prefix + "\n" + "\n".join(lines) + "\n" + suffix

    if _ROOT_BLOCK_RE.search(html):
        return _ROOT_BLOCK_RE.sub(_replace_root, html, count=1)

    # No :root block — inject one before </head> or at top
    decls = "\n".join(f"  {k}: {v};" for k, v in normalized.items())
    block = f"<style>:root {{\n{decls}\n}}</style>\n"
    if "</head>" in html.lower():
        # preserve original case of </head>
        idx = html.lower().rfind("</head>")
        return html[:idx] + block + html[idx:]
    return block + html


def ensure_locked_font(html: str, settings: Settings) -> str:
    """Inject Google Fonts link + set --font-family if not already present."""
    font_family = settings.locked_font_family
    font_url = settings.locked_font_url

    if "fonts.googleapis.com" not in html and font_url:
        link = (
            f'<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            f'<link href="{font_url}" rel="stylesheet">\n'
        )
        lower = html.lower()
        if "</head>" in lower:
            idx = lower.rfind("</head>")
            html = html[:idx] + link + html[idx:]
        else:
            html = link + html

    # Ensure a CSS variable for the locked font without overriding author font-family rules
    if "--font-family" not in html:
        html = apply_color_variant(html, {"--font-family": f'"{font_family}", sans-serif'})

    return html


def render_filled_html(
    *,
    template_id: str,
    caption: str,
    image_url: str,
    cta_link: str,
    settings: Settings,
    css_vars: dict[str, str] | None = None,
    brand: str = "",
    tagline: str = "",
    logo_url: str = "",
) -> str:
    html = load_template_html(template_id, settings)
    html = ensure_locked_font(html, settings)
    if css_vars:
        html = apply_color_variant(html, css_vars)
    return fill_template(
        html,
        caption=caption,
        image_url=image_url,
        cta_link=cta_link,
        brand=brand,
        tagline=tagline,
        logo_url=logo_url,
    )
