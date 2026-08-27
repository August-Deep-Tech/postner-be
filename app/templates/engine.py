from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.config import Settings


PLACEHOLDER_CAPTION = "{{caption}}"
PLACEHOLDER_IMAGE = "{{image_url}}"
PLACEHOLDER_CTA = "{{cta_link}}"

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def fill_placeholders(html: str, values: dict[str, str]) -> str:
    """Replace {{key}} tokens; unknown keys become empty string."""

    def _repl(match: re.Match[str]) -> str:
        return values.get(match.group(1), "")

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


def path_to_file_url(path: Path) -> str:
    resolved = path.resolve().as_posix()
    # Windows paths need an extra slash: file:///C:/...
    if re.match(r"^[A-Za-z]:/", resolved):
        return "file:///" + quote(resolved, safe="/:")
    return "file://" + quote(resolved, safe="/")


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
    image_path: Path,
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
        image_url=path_to_file_url(image_path),
        cta_link=cta_link,
        brand=brand,
        tagline=tagline,
        logo_url=logo_url,
    )


def list_variant_ids(settings: Settings) -> list[str]:
    if not settings.variants_dir.exists():
        return []
    return sorted(p.stem for p in settings.variants_dir.glob("*.json") if p.is_file())


def load_variant(variant_id: str, settings: Settings) -> dict[str, Any]:
    path = settings.variants_dir / f"{variant_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Variant '{variant_id}' not found in {settings.variants_dir}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if "css_vars" in data and isinstance(data["css_vars"], dict):
        return data
    # Allow raw { "--bg": "..." } files
    if all(str(k).startswith("--") for k in data.keys()):
        return {"id": variant_id, "css_vars": data}
    raise ValueError(f"Variant '{variant_id}' missing css_vars object")


def save_variant(variant: dict[str, Any], settings: Settings) -> str:
    settings.variants_dir.mkdir(parents=True, exist_ok=True)
    variant_id = str(variant.get("id") or "variant").strip()
    variant_id = re.sub(r"[^\w\-]+", "_", variant_id).strip("_").lower() or "variant"
    css_vars = variant.get("css_vars") or {}
    if not isinstance(css_vars, dict):
        raise ValueError("variant.css_vars must be an object")

    # Strip any font-related keys
    cleaned = {
        (k if str(k).startswith("--") else f"--{k}"): v
        for k, v in css_vars.items()
        if not str(k).lower().lstrip("-").startswith("font")
    }
    payload = {
        "id": variant_id,
        "label": variant.get("label") or variant_id,
        "css_vars": cleaned,
    }
    path = settings.variants_dir / f"{variant_id}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return variant_id
