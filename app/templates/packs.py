from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, SocialFormat
from app.templates.engine import (
    apply_color_variant,
    ensure_locked_font,
    fill_placeholders,
    path_to_file_url,
)


@dataclass
class PackPage:
    id: str
    file: str
    role: str
    tags: list[str]
    images: int
    fields: list[str]


@dataclass
class TemplatePack:
    id: str
    label: str
    format: SocialFormat
    description: str
    css_vars: dict[str, str]
    pages: list[PackPage]
    sequence: list[str]
    default_brand: str
    root: Path

    def page_by_id(self, page_id: str) -> PackPage:
        for page in self.pages:
            if page.id == page_id:
                return page
        raise KeyError(f"Pack '{self.id}' has no page '{page_id}'")

    def sequenced_pages(self) -> list[PackPage]:
        return [self.page_by_id(pid) for pid in self.sequence]

    def total_images(self) -> int:
        return sum(p.images for p in self.sequenced_pages())


def packs_dir(settings: Settings) -> Path:
    return settings.templates_dir / "packs"


def list_pack_ids(settings: Settings) -> list[str]:
    root = packs_dir(settings)
    if not root.exists():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "pack.json").is_file()
    )


def load_pack(pack_id: str, settings: Settings) -> TemplatePack:
    root = packs_dir(settings) / pack_id
    manifest = root / "pack.json"
    if not manifest.is_file():
        raise FileNotFoundError(
            f"Pack '{pack_id}' not found (expected {manifest}). "
            "See templates/README.md."
        )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    pages = [
        PackPage(
            id=str(p["id"]),
            file=str(p["file"]),
            role=str(p.get("role") or "body"),
            tags=list(p.get("tags") or []),
            images=int(p.get("images") or 0),
            fields=list(p.get("fields") or []),
        )
        for p in data.get("pages") or []
    ]
    fmt = data.get("format") or "ig_portrait"
    return TemplatePack(
        id=str(data.get("id") or pack_id),
        label=str(data.get("label") or pack_id),
        format=fmt,  # type: ignore[arg-type]
        description=str(data.get("description") or ""),
        css_vars=dict(data.get("css_vars") or {}),
        pages=pages,
        sequence=list(data.get("sequence") or [p.id for p in pages]),
        default_brand=str(data.get("default_brand") or ""),
        root=root,
    )


def load_pack_page_html(pack: TemplatePack, page: PackPage) -> str:
    path = pack.root / "pages" / page.file
    if not path.is_file():
        # also allow file at pack root
        alt = pack.root / page.file
        if alt.is_file():
            path = alt
        else:
            raise FileNotFoundError(f"Pack page file missing: {path}")
    return path.read_text(encoding="utf-8")


def pack_field_schema(pack: TemplatePack) -> list[dict[str, Any]]:
    """Describe sequenced pages for the LLM prompt."""
    out: list[dict[str, Any]] = []
    for index, page in enumerate(pack.sequenced_pages(), start=1):
        out.append(
            {
                "page_id": page.id,
                "index": index,
                "role": page.role,
                "tags": page.tags,
                "images": page.images,
                "fields": page.fields,
            }
        )
    return out


def render_pack_page_html(
    *,
    pack: TemplatePack,
    page: PackPage,
    fields: dict[str, str],
    settings: Settings,
    image_paths: list[Path] | None = None,
    variant_css: dict[str, str] | None = None,
) -> str:
    html = load_pack_page_html(pack, page)
    html = ensure_locked_font(html, settings)

    css = dict(pack.css_vars)
    if variant_css:
        css.update(variant_css)
    if css:
        html = apply_color_variant(html, css)

    values = {k: "" for k in page.fields}
    values.update({k: str(v) for k, v in fields.items() if v is not None})
    values.setdefault("brand", pack.default_brand)
    values.setdefault("tagline", "")
    values.setdefault("logo_url", "")

    images = image_paths or []
    if page.images > 0 and images:
        values["image_url"] = path_to_file_url(images[0])
        for i, path in enumerate(images[1:], start=2):
            values[f"image_{i}"] = path_to_file_url(path)
            values[f"image_url_{i}"] = path_to_file_url(path)

    return fill_placeholders(html, values)


def _extract_css_keys_from_html(html: str) -> list[str]:
    keys = sorted(set(re.findall(r"--[\w-]+", html)))
    return [k for k in keys if not k.startswith("--font")]


def build_pack_design_context(pack_id: str, settings: Settings) -> dict[str, Any]:
    """HTML + required CSS keys for variant propose against a pack."""
    pack = load_pack(pack_id, settings)
    chunks: list[str] = [
        f"<!-- pack.css_vars -->\n:root {{\n"
        + "\n".join(f"  {k}: {v};" for k, v in pack.css_vars.items())
        + "\n}\n"
    ]
    css_keys = set(pack.css_vars.keys())
    per_page_budget = max(1500, 10000 // max(len(pack.sequence), 1))
    for page in pack.sequenced_pages():
        html = load_pack_page_html(pack, page)
        css_keys.update(_extract_css_keys_from_html(html))
        snippet = html if len(html) <= per_page_budget else html[:per_page_budget] + "\n<!-- truncated -->"
        chunks.append(f"<!-- page {page.id} ({page.file}) -->\n{snippet}")
    if not css_keys:
        css_keys.update(["--bg", "--text", "--accent", "--accent-shape"])
    return {
        "html": "\n\n".join(chunks),
        "css_keys": sorted(css_keys),
        "pack": pack,
    }


def page_catalog(settings: Settings) -> list[dict[str, Any]]:
    """Flat catalog of existing pack page templates for pack propose."""
    catalog: list[dict[str, Any]] = []
    for pack_id in list_pack_ids(settings):
        pack = load_pack(pack_id, settings)
        for page in pack.pages:
            catalog.append(
                {
                    "source": f"{pack.id}/{page.file}",
                    "pack_id": pack.id,
                    "file": page.file,
                    "role": page.role,
                    "tags": page.tags,
                    "images": page.images,
                    "fields": page.fields,
                }
            )
    return catalog


def _normalize_pack_id(raw: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", (raw or "").strip()).strip("_").lower()
    return cleaned or "pack"


def _unique_pack_id(base: str, settings: Settings) -> str:
    candidate = _normalize_pack_id(base)
    existing = set(list_pack_ids(settings))
    if candidate not in existing:
        return candidate
    for i in range(2, 50):
        alt = f"{candidate}_{i}"
        if alt not in existing:
            return alt
    return f"{candidate}_{uuid.uuid4().hex[:6]}"


def materialize_proposed_pack(
    proposed: dict[str, Any],
    *,
    settings: Settings,
    format_name: str | None = None,
) -> dict[str, Any]:
    """Clone catalog page HTML into a new pack directory; return saved summary."""
    catalog_by_source = {c["source"]: c for c in page_catalog(settings)}
    pack_id = _unique_pack_id(str(proposed.get("id") or "pack"), settings)
    label = str(proposed.get("label") or pack_id)
    description = str(proposed.get("description") or "")
    fmt = format_name or proposed.get("format") or "ig_portrait"
    css_vars = dict(proposed.get("css_vars") or {})
    if not css_vars:
        css_vars = {
            "--bg": "#F3F0E8",
            "--text": "#0B0B0B",
            "--accent": "#3B6FD8",
            "--accent-shape": "#3B6FD8",
            "--on-accent": "#FFFFFF",
        }

    raw_pages = list(proposed.get("pages") or [])
    if not raw_pages:
        raise ValueError(f"Proposed pack '{pack_id}' has no pages")

    root = packs_dir(settings) / pack_id
    pages_dir = root / "pages"
    pages_dir.mkdir(parents=True, exist_ok=False)

    pages_out: list[dict[str, Any]] = []
    sequence: list[str] = []
    used_ids: set[str] = set()

    for index, raw in enumerate(raw_pages, start=1):
        source = str(raw.get("source") or "").strip()
        if source not in catalog_by_source:
            raise ValueError(f"Unknown page source '{source}' in proposed pack '{pack_id}'")
        cat = catalog_by_source[source]
        src_pack = load_pack(str(cat["pack_id"]), settings)
        src_page = next(p for p in src_pack.pages if p.file == cat["file"])
        src_html_path = src_pack.root / "pages" / src_page.file
        if not src_html_path.is_file():
            src_html_path = src_pack.root / src_page.file

        page_id = str(raw.get("id") or src_page.id).strip() or f"page_{index}"
        page_id = re.sub(r"[^\w\-]+", "_", page_id).strip("_").lower() or f"page_{index}"
        if page_id in used_ids:
            page_id = f"{page_id}_{index}"
        used_ids.add(page_id)

        dest_file = f"{index:02d}_{page_id}.html"
        dest_path = pages_dir / dest_file
        dest_path.write_text(src_html_path.read_text(encoding="utf-8"), encoding="utf-8")

        page_entry = {
            "id": page_id,
            "file": dest_file,
            "role": str(raw.get("role") or cat["role"]),
            "tags": list(raw.get("tags") or cat["tags"]),
            "images": int(raw.get("images") if raw.get("images") is not None else cat["images"]),
            "fields": list(raw.get("fields") or cat["fields"]),
        }
        pages_out.append(page_entry)
        sequence.append(page_id)

    seq_from_llm = [str(x) for x in (proposed.get("sequence") or []) if str(x) in used_ids]
    if seq_from_llm and set(seq_from_llm) == used_ids:
        sequence = seq_from_llm

    manifest = {
        "id": pack_id,
        "label": label,
        "format": fmt,
        "description": description,
        "default_brand": "",
        "css_vars": css_vars,
        "pages": pages_out,
        "sequence": sequence,
    }
    (root / "pack.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "id": pack_id,
        "label": label,
        "description": description,
        "format": fmt,
        "pages": len(sequence),
        "images": sum(int(p["images"]) for p in pages_out),
        "css_vars": css_vars,
    }

