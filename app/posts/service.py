from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.brands.service import brand_formats, brand_to_profile, get_tenant_brand
from app.brands.store import BrandProfile, resolve_logo_path
from app.brands.variants import get_brand_variant
from app.config import Settings, SocialFormat, has_llm_credentials
from app.db.models import Brand, Feedback, Post, PostRevision
from app.generate.posts import generate_carousel, generate_post
from app.images.recraft import generate_recraft_image
from app.render.screenshot import screenshot_html
from app.render.video import render_html_video
from app.scrape.page import scrape_page
from app.storage import get_storage
from app.templates.engine import path_to_file_url, render_filled_html
from app.templates.packs import load_pack, render_pack_page_html
from app.templates.variants import propose_and_save_variants


def _load_post_variant_css(db: Session, post: Post) -> dict[str, Any] | None:
    if not post.variant_id:
        return None
    brand = db.get(Brand, post.brand_id) if post.brand_id else None
    row = get_brand_variant(
        db,
        tenant_id=post.tenant_id,
        brand=brand,
        variant_id=post.variant_id,
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"Variant '{post.variant_id}' not found"
        )
    return dict(row.css_vars or {})


def _resolve_format(
    *,
    format_name: SocialFormat | None,
    brand_row,
    pack_fallback: SocialFormat | None = None,
) -> SocialFormat:
    """Request format (must be in brand.formats) > first brand format > pack > ig_feed."""
    allowed = brand_formats(brand_row) if brand_row is not None else []
    if format_name:
        if allowed and format_name not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Format '{format_name}' is not enabled for this brand. "
                    f"Allowed: {', '.join(allowed)}"
                ),
            )
        return format_name
    if allowed:
        return allowed[0]  # type: ignore[return-value]
    if pack_fallback:
        return pack_fallback
    return "ig_feed"


def _new_run_dir(settings: Settings) -> tuple[str, Path]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = settings.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir


def _brand_fields(
    profile: BrandProfile | None,
) -> tuple[str, str, str, str]:
    if not profile:
        return "", "", "", ""
    logo_url = ""
    logo_path = resolve_logo_path(profile)
    if logo_path:
        logo_url = path_to_file_url(logo_path)
    return profile.name, profile.tagline, profile.description, logo_url


def _next_revision_version(db: Session, post_id: UUID) -> int:
    current = db.scalar(
        select(func.max(PostRevision.version)).where(PostRevision.post_id == post_id)
    )
    return int(current or 0) + 1


def _post_snapshot(post: Post) -> dict[str, Any]:
    return {
        "status": post.status,
        "format": post.format,
        "pack_id": post.pack_id,
        "template_id": post.template_id,
        "variant_id": post.variant_id,
        "content": dict(post.content or {}),
        "images": dict(post.images or {}),
        "composed": dict(post.composed or {}),
        "meta": dict(post.meta or {}),
    }


def _add_revision(
    db: Session,
    post: Post,
    kind: str,
    extra: dict[str, Any] | None = None,
) -> PostRevision:
    version = _next_revision_version(db, post.id)
    payload = _post_snapshot(post)
    payload["version"] = version
    if extra:
        payload["extra"] = extra
    row = PostRevision(
        post_id=post.id,
        tenant_id=post.tenant_id,
        kind=kind,
        version=version,
        payload=payload,
    )
    db.add(row)
    return row


def _object_key(post: Post, version: int, relative: str) -> str:
    rel = relative.lstrip("/").replace("\\", "/")
    return f"tenants/{post.tenant_id}/posts/{post.id}/v{version}/{rel}"


def _upload_composed_assets(
    db: Session,
    post: Post,
    settings: Settings,
) -> dict[str, Any]:
    """Upload composed PNG/MP4 via ObjectStorage; attach url/key on composed payload."""
    storage = get_storage(settings)
    ver = _next_revision_version(db, post.id)
    is_pack = (post.content or {}).get("mode") == "pack"
    composed = dict(post.composed or {})

    pages_out: list[dict[str, Any]] = []
    for entry in list(composed.get("pages") or []):
        item = dict(entry)
        local = item.get("path")
        if local and Path(local).is_file():
            name = Path(local).name
            relative = f"pages/{name}" if is_pack else name
            key = _object_key(post, ver, relative)
            try:
                url = storage.upload(Path(local), key)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=502, detail=f"Asset upload failed: {exc}"
                ) from exc
            item["key"] = key
            item["url"] = url
        pages_out.append(item)

    composed["pages"] = pages_out
    composed["page_paths"] = [p.get("url") or p.get("path") for p in pages_out]
    composed["final_path"] = (
        (pages_out[0].get("url") or pages_out[0].get("path")) if pages_out else None
    )

    videos_in = dict(composed.get("videos") or {})
    videos_out: dict[str, str] = {}
    video_urls: dict[str, str] = dict(composed.get("video_urls") or {})
    video_keys: dict[str, str] = dict(composed.get("video_keys") or {})
    for pid, local in videos_in.items():
        if not local or not Path(local).is_file():
            if local:
                videos_out[pid] = local
            continue
        name = Path(local).name
        relative = f"pages/{name}" if is_pack else name
        key = _object_key(post, ver, relative)
        try:
            url = storage.upload(Path(local), key)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"Video upload failed: {exc}"
            ) from exc
        videos_out[pid] = local
        video_urls[pid] = url
        video_keys[pid] = key

    if videos_out or video_urls:
        composed["videos"] = videos_out or videos_in
        composed["video_urls"] = video_urls
        composed["video_keys"] = video_keys
        first_url = next(iter(video_urls.values()), None)
        composed["video_path"] = first_url or next(
            iter((videos_out or videos_in).values()), None
        )
        composed["page_video_paths"] = [
            video_urls.get(pid) or path
            for pid, path in (videos_out or videos_in).items()
        ]

    return composed


def get_post_for_tenant(db: Session, tenant_id: UUID, post_id: UUID) -> Post:
    post = db.get(Post, post_id)
    if post is None or post.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


async def create_draft_post(
    db: Session,
    *,
    tenant_id: UUID,
    url: str,
    brand_id: str | None,
    pack_id: str | None,
    template_id: str | None,
    format_name: SocialFormat | None,
    variant_id: str | None,
    with_images: bool,
    settings: Settings,
) -> Post:
    if not has_llm_credentials(settings):
        raise HTTPException(
            status_code=500,
            detail="Set ANTHROPIC_API_KEY or OPENAI_API_KEY",
        )

    profile: BrandProfile | None = None
    brand_row = None
    if brand_id:
        brand_row = get_tenant_brand(db, tenant_id, brand_id)
        if brand_row is None:
            raise HTTPException(status_code=404, detail=f"Brand '{brand_id}' not found")
        profile = brand_to_profile(brand_row, settings)

    brand_name, tagline, description, logo_url = _brand_fields(profile)
    run_id, run_dir = _new_run_dir(settings)

    try:
        page = await scrape_page(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Scrape failed: {exc}") from exc

    mode = "pack" if pack_id else "single"
    content: dict[str, Any]
    fmt: SocialFormat

    if pack_id:
        try:
            pack = load_pack(pack_id, settings)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # Explicit request > first brand format > pack default
        fmt = _resolve_format(
            format_name=format_name,
            brand_row=brand_row,
            pack_fallback=pack.format,
        )
        try:
            carousel = await generate_carousel(
                page,
                pack,
                settings,
                brand_name=brand_name,
                brand_tagline=tagline,
                brand_description=description,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"LLM carousel generation failed: {exc}"
            ) from exc
        if brand_name:
            carousel.brand = brand_name
            for slide in carousel.slides:
                slide.brand = brand_name
        content = {
            "mode": "pack",
            "post_type": carousel.post_type,
            "page_type": carousel.page_type,
            "brand": carousel.brand,
            "ig_fb_caption": carousel.ig_fb_caption,
            "tiktok_script": carousel.tiktok_script,
            "visual_prompt": carousel.visual_prompt,
            "source_title": page.title,
            "logo_url": logo_url,
            "tagline": tagline,
            "slides": [s.model_dump() for s in carousel.slides],
            "pack_page_ids": [p.id for p in pack.sequenced_pages()],
            "pack_images_needed": pack.total_images(),
        }
        template_id = None
    else:
        tid = template_id or "default"
        fmt = _resolve_format(
            format_name=format_name,
            brand_row=brand_row,
            pack_fallback=None,
        )
        try:
            post_data = await generate_post(
                page,
                settings,
                brand_name=brand_name,
                brand_tagline=tagline,
                brand_description=description,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"LLM generation failed: {exc}"
            ) from exc
        content = {
            "mode": "single",
            "post_type": post_data.post_type,
            "page_type": post_data.page_type,
            "ig_fb_caption": post_data.ig_fb_caption,
            "tiktok_script": post_data.tiktok_script,
            "visual_prompt": post_data.visual_prompt,
            "overlay_text": post_data.overlay_text,
            "source_title": page.title,
            "logo_url": logo_url,
            "tagline": tagline,
            "brand": brand_name,
            "pack_images_needed": 1,
        }
        template_id = tid
        pack_id = None

    if variant_id:
        if brand_row is None:
            raise HTTPException(
                status_code=400,
                detail="brand_id is required when setting variant_id",
            )
        row = get_brand_variant(
            db,
            tenant_id=tenant_id,
            brand=brand_row,
            variant_id=variant_id,
        )
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"Variant '{variant_id}' not found"
            )
        variant_id = str(row.id)

    post = Post(
        tenant_id=tenant_id,
        brand_id=brand_row.id if brand_row else None,
        status="drafted",
        url=url,
        format=fmt,
        pack_id=pack_id,
        template_id=template_id,
        variant_id=variant_id,
        asset_dir=str(run_dir),
        content=content,
        images={},
        composed={},
        meta={"run_id": run_id, "mode": mode},
    )
    db.add(post)
    db.flush()
    _add_revision(db, post, "draft")
    db.commit()
    db.refresh(post)

    if with_images:
        post = await generate_post_images(
            db, post=post, pages=None, regenerate=False, settings=settings
        )

    return post


def _page_image_slots(post: Post, settings: Settings) -> list[dict[str, Any]]:
    """Return list of {page_id, prompt, index} needing Recraft images."""
    content = post.content or {}
    slots: list[dict[str, Any]] = []
    if content.get("mode") == "pack" and post.pack_id:
        pack = load_pack(post.pack_id, settings)
        slides_by_id = {s["page_id"]: s for s in content.get("slides", [])}
        for index, page_def in enumerate(pack.sequenced_pages(), start=1):
            if page_def.images <= 0:
                continue
            slide = slides_by_id.get(page_def.id, {})
            prompt = (
                (slide.get("visual_prompt") or content.get("visual_prompt") or "")
            ).strip()
            slots.append(
                {
                    "page_id": page_def.id,
                    "prompt": prompt,
                    "index": index,
                    "filename": f"image_{index:02d}_{page_def.id}.png",
                }
            )
    else:
        prompt = (content.get("visual_prompt") or "").strip()
        slots.append(
            {
                "page_id": "main",
                "prompt": prompt,
                "index": 1,
                "filename": "image.png",
            }
        )
    return slots


async def generate_post_images(
    db: Session,
    *,
    post: Post,
    pages: list[str] | None,
    regenerate: bool,
    settings: Settings,
    record_revision: bool = True,
) -> Post:
    if not settings.fal_key:
        raise HTTPException(status_code=500, detail="FAL_KEY is not set")

    run_dir = Path(post.asset_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    existing = dict(post.images or {})
    by_page: dict[str, Any] = dict(existing.get("by_page") or {})
    slots = _page_image_slots(post, settings)
    page_filter = set(pages) if pages else None

    generated: list[str] = []
    for slot in slots:
        page_id = slot["page_id"]
        if page_filter is not None and page_id not in page_filter:
            continue
        if not regenerate and page_id in by_page and Path(by_page[page_id]).is_file():
            continue
        prompt = slot["prompt"]
        if not prompt:
            raise HTTPException(
                status_code=502,
                detail=f"Page '{page_id}' needs an image but no visual_prompt is set",
            )
        dest = run_dir / slot["filename"]
        try:
            await generate_recraft_image(prompt=prompt, dest=dest, settings=settings)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=f"Recraft generation failed for {page_id}: {exc}",
            ) from exc
        by_page[page_id] = str(dest)
        generated.append(page_id)

    paths = list(by_page.values())
    post.images = {
        "by_page": by_page,
        "paths": paths,
        "image_path": paths[0] if paths else None,
    }
    if generated or regenerate:
        post.status = "imaged" if by_page else post.status
        if record_revision:
            _add_revision(
                db,
                post,
                "images",
                {"generated": generated, "regenerate": regenerate},
            )
    db.commit()
    db.refresh(post)
    return post


async def compose_post(
    db: Session,
    *,
    post: Post,
    pages: list[str] | None,
    ensure_images: bool,
    settings: Settings,
    record_revision: bool = True,
) -> Post:
    """Fill template/pack HTML for preview (no Playwright PNG)."""
    content = post.content or {}
    needed = int(content.get("pack_images_needed") or 0)
    has_images = bool((post.images or {}).get("by_page"))
    if needed > 0 and (not has_images or ensure_images):
        post = await generate_post_images(
            db,
            post=post,
            pages=pages,
            regenerate=False,
            settings=settings,
            record_revision=False,
        )

    run_dir = Path(post.asset_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    variant_css = _load_post_variant_css(db, post)

    brand_name = content.get("brand") or ""
    tagline = content.get("tagline") or ""
    logo_url = content.get("logo_url") or ""
    by_page = dict((post.images or {}).get("by_page") or {})
    page_filter = set(pages) if pages else None
    composed_pages: list[dict[str, Any]] = list((post.composed or {}).get("pages") or [])
    composed_by_id = {p["page_id"]: p for p in composed_pages}

    def _preview_entry(
        *,
        index: int,
        page_id: str,
        html_name: str,
        filled: str,
        prior: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        html_path = run_dir / html_name
        html_path.write_text(filled, encoding="utf-8")
        entry: dict[str, Any] = {
            "index": index,
            "page_id": page_id,
            "html": html_name,
            "html_source": filled,
        }
        # Drop stale PNG fields after re-fill
        if prior:
            for key in ("videos",):
                if key in prior:
                    entry[key] = prior[key]
        return entry

    try:
        if content.get("mode") == "pack" and post.pack_id:
            pack = load_pack(post.pack_id, settings)
            slides_by_id = {s["page_id"]: s for s in content.get("slides", [])}
            for index, page_def in enumerate(pack.sequenced_pages(), start=1):
                if page_filter is not None and page_def.id not in page_filter:
                    continue
                slide = slides_by_id.get(page_def.id, {})
                fields = {
                    "title": slide.get("title") or "",
                    "subtitle": slide.get("subtitle") or "",
                    "body": slide.get("body") or "",
                    "body_2": slide.get("body_2") or "",
                    "body_emphasis": slide.get("body_emphasis") or "",
                    "page_number": slide.get("page_number") or "",
                    "cta": slide.get("cta") or "",
                    "brand": brand_name or slide.get("brand") or pack.default_brand,
                    "series": slide.get("series") or "",
                    "script": slide.get("script") or "",
                    "next": slide.get("next") or "",
                    "handle": slide.get("handle") or "",
                    "tagline": tagline,
                    "logo_url": logo_url,
                }
                if "page_number" in page_def.fields and not fields.get("page_number"):
                    fields["page_number"] = f"{index:02d}"
                if "handle" in page_def.fields and not fields.get("handle") and brand_name:
                    fields["handle"] = "@" + brand_name.replace(" ", "")
                if "series" in page_def.fields and not fields.get("series") and tagline:
                    fields["series"] = tagline.upper()

                if page_def.images > 0:
                    img = by_page.get(page_def.id)
                    page_images = [Path(img)] if img else []
                else:
                    page_images = []

                filled = render_pack_page_html(
                    pack=pack,
                    page=page_def,
                    fields=fields,
                    settings=settings,
                    image_paths=page_images,
                    variant_css=variant_css,
                )
                html_name = f"filled_{index:02d}_{page_def.id}.html"
                composed_by_id[page_def.id] = _preview_entry(
                    index=index,
                    page_id=page_def.id,
                    html_name=html_name,
                    filled=filled,
                    prior=composed_by_id.get(page_def.id),
                )

            ordered = [
                composed_by_id[p.id]
                for p in pack.sequenced_pages()
                if p.id in composed_by_id
            ]
            post.composed = {
                "pages": ordered,
                "page_paths": [],
                "final_path": None,
            }
        else:
            image_path = by_page.get("main") or (post.images or {}).get("image_path")
            if not image_path:
                raise HTTPException(
                    status_code=400,
                    detail="No source image; call POST /posts/{id}/images first "
                    "or compose with ensure_images=true",
                )
            filled = render_filled_html(
                template_id=post.template_id or "default",
                caption=content.get("overlay_text") or "",
                image_path=Path(image_path),
                cta_link=post.url,
                settings=settings,
                css_vars=variant_css,
                brand=brand_name,
                tagline=tagline,
                logo_url=logo_url,
            )
            post.composed = {
                "pages": [
                    _preview_entry(
                        index=1,
                        page_id="main",
                        html_name="filled.html",
                        filled=filled,
                        prior=composed_by_id.get("main"),
                    )
                ],
                "page_paths": [],
                "final_path": None,
            }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Compose failed: {exc}") from exc

    # Clear prior render outputs at top level
    composed = dict(post.composed or {})
    for stale in ("videos", "video_path", "page_video_paths", "video_urls", "video_keys"):
        composed.pop(stale, None)
    post.composed = composed
    post.status = "preview"
    if record_revision:
        _add_revision(db, post, "preview")
    meta_path = run_dir / "meta.json"
    meta = {
        "post_id": str(post.id),
        "run_id": (post.meta or {}).get("run_id"),
        "status": post.status,
        "format": post.format,
        "pack_id": post.pack_id,
        "template_id": post.template_id,
        "composed": {
            "pages": [
                {
                    "index": p.get("index"),
                    "page_id": p.get("page_id"),
                    "html": p.get("html"),
                    "html_source_len": len(p.get("html_source") or ""),
                }
                for p in (post.composed or {}).get("pages") or []
            ]
        },
        "images": post.images,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    db.commit()
    db.refresh(post)
    return post


def _page_has_png(page: dict[str, Any]) -> bool:
    return bool(page.get("url") or page.get("path"))


def _post_has_pngs(post: Post) -> bool:
    pages = list((post.composed or {}).get("pages") or [])
    return bool(pages) and all(_page_has_png(p) for p in pages)


async def render_post(
    db: Session,
    *,
    post: Post,
    pages: list[str] | None = None,
    settings: Settings,
    record_revision: bool = True,
) -> Post:
    """Playwright PNG from filled HTML + object-storage upload."""
    composed_pages = list((post.composed or {}).get("pages") or [])
    if not composed_pages:
        raise HTTPException(
            status_code=400,
            detail="Fill HTML first via POST /posts/{id}/compose",
        )

    run_dir = Path(post.asset_dir)
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    fmt: SocialFormat = post.format  # type: ignore[assignment]
    page_filter = set(pages) if pages else None
    content = post.content or {}
    is_pack = content.get("mode") == "pack" and bool(post.pack_id)

    try:
        updated: list[dict[str, Any]] = []
        for entry in composed_pages:
            item = dict(entry)
            pid = item.get("page_id") or "main"
            if page_filter is not None and pid not in page_filter:
                updated.append(item)
                continue

            html_source = item.get("html_source")
            html_name = item.get("html") or (
                f"filled_{int(item.get('index') or 1):02d}_{pid}.html"
                if is_pack
                else "filled.html"
            )
            if not html_source:
                html_path = run_dir / html_name
                if html_path.is_file():
                    html_source = html_path.read_text(encoding="utf-8")
                    item["html_source"] = html_source
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Missing html_source for page '{pid}'; recompose first",
                    )
            else:
                # Keep disk in sync for Playwright file:// loads of nested assets
                (run_dir / html_name).write_text(html_source, encoding="utf-8")

            index = int(item.get("index") or 1)
            if is_pack:
                dest = pages_dir / f"{index:02d}_{pid}.png"
            else:
                dest = run_dir / "final.png"

            await screenshot_html(
                html=html_source,
                dest=dest,
                format_name=fmt,
                work_dir=run_dir,
                html_name=html_name,
            )
            item["path"] = str(dest)
            item["html"] = html_name
            # Drop old CDN url/key until upload refreshes them
            item.pop("url", None)
            item.pop("key", None)
            updated.append(item)

        post.composed = {
            **dict(post.composed or {}),
            "pages": updated,
            "page_paths": [p.get("path") for p in updated if p.get("path")],
            "final_path": next((p.get("path") for p in updated if p.get("path")), None),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Render failed: {exc}") from exc

    post.composed = _upload_composed_assets(db, post, settings)
    post.status = "rendered"
    if record_revision:
        _add_revision(db, post, "render")
    db.commit()
    db.refresh(post)
    return post


async def animate_post(
    db: Session,
    *,
    post: Post,
    page_id: str | None,
    pages: list[str] | None,
    motion_preset: str,
    settings: Settings,
) -> Post:
    if not post.composed or not (post.composed or {}).get("pages"):
        raise HTTPException(status_code=400, detail="Compose the post before animating")
    if not _post_has_pngs(post):
        raise HTTPException(
            status_code=400,
            detail="Render PNGs first via POST /posts/{id}/render or approve",
        )

    run_dir = Path(post.asset_dir)
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    fmt: SocialFormat = post.format  # type: ignore[assignment]
    content = post.content or {}
    target_ids: set[str] | None = None
    if page_id:
        target_ids = {page_id}
    elif pages:
        target_ids = set(pages)

    videos: dict[str, str] = dict((post.composed or {}).get("videos") or {})
    video_error: str | None = None

    composed_pages = list((post.composed or {}).get("pages") or [])
    for entry in composed_pages:
        pid = entry["page_id"]
        if target_ids is not None and pid not in target_ids:
            continue
        html_source = entry.get("html_source")
        html_name = entry.get("html") or f"filled_{entry.get('index', 1):02d}_{pid}.html"
        if html_source:
            html = html_source
            (run_dir / html_name).write_text(html, encoding="utf-8")
        else:
            html_path = run_dir / html_name
            if not html_path.is_file():
                continue
            html = html_path.read_text(encoding="utf-8")
        if content.get("mode") == "pack":
            dest = pages_dir / f"{entry['index']:02d}_{pid}.mp4"
        else:
            dest = run_dir / "final.mp4"
        try:
            await render_html_video(
                html=html,
                dest=dest,
                format_name=fmt,
                work_dir=run_dir,
                motion_preset=motion_preset,
                html_name=f"filled_motion_{pid}.html",
            )
            videos[pid] = str(dest)
        except Exception as exc:  # noqa: BLE001
            video_error = str(exc)
            break

    composed = dict(post.composed or {})
    composed["videos"] = videos
    composed["video_path"] = next(iter(videos.values()), None)
    composed["page_video_paths"] = list(videos.values())
    if video_error:
        composed["video_error"] = video_error
    post.composed = composed
    post.composed = _upload_composed_assets(db, post, settings)
    post.status = "animated" if videos and not video_error else post.status
    _add_revision(
        db,
        post,
        "animate",
        {"motion_preset": motion_preset, "video_error": video_error},
    )
    db.commit()
    db.refresh(post)
    return post


async def resize_post(
    db: Session,
    *,
    post: Post,
    format_name: SocialFormat,
    pages: list[str] | None,
    apply_to_post: bool,
    settings: Settings,
) -> Post:
    if post.brand_id:
        brand_row = db.get(Brand, post.brand_id)
        if brand_row is not None:
            # Validate against brand.formats (raises 400 if not allowed)
            _resolve_format(format_name=format_name, brand_row=brand_row)
    if apply_to_post:
        post.format = format_name
    # Re-compose into current or keep format on post for render
    original = post.format
    post.format = format_name
    post = await compose_post(
        db,
        post=post,
        pages=pages,
        ensure_images=True,
        settings=settings,
        record_revision=False,
    )
    if not apply_to_post:
        post.format = original
    _add_revision(
        db,
        post,
        "resize",
        {"format": format_name, "apply_to_post": apply_to_post},
    )
    db.commit()
    db.refresh(post)
    return post


async def redesign_post(
    db: Session,
    *,
    post: Post,
    variant_id: str | None,
    propose: bool,
    regenerate_images: bool,
    recompose: bool,
    settings: Settings,
) -> Post:
    brand = db.get(Brand, post.brand_id) if post.brand_id else None
    if propose and not variant_id:
        if brand is None:
            raise HTTPException(
                status_code=400,
                detail="Post needs a brand_id to propose variants",
            )
        if not has_llm_credentials(settings):
            raise HTTPException(
                status_code=500,
                detail="Set ANTHROPIC_API_KEY or OPENAI_API_KEY to propose variants",
            )
        try:
            _variants, saved_ids = await propose_and_save_variants(
                db=db,
                brand=brand,
                template_id=(post.template_id or "default") if not post.pack_id else None,
                pack_id=post.pack_id,
                count=1,
                settings=settings,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=f"Variant proposal failed: {exc}",
            ) from exc
        if not saved_ids:
            raise HTTPException(status_code=502, detail="Variant proposal returned no ids")
        variant_id = saved_ids[0]

    if variant_id:
        row = get_brand_variant(
            db,
            tenant_id=post.tenant_id,
            brand=brand,
            variant_id=variant_id,
        )
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"Variant '{variant_id}' not found"
            )
        post.variant_id = str(row.id)

    if regenerate_images:
        post = await generate_post_images(
            db,
            post=post,
            pages=None,
            regenerate=True,
            settings=settings,
            record_revision=False,
        )
    if recompose:
        post = await compose_post(
            db,
            post=post,
            pages=None,
            ensure_images=True,
            settings=settings,
            record_revision=False,
        )
    _add_revision(
        db,
        post,
        "redesign",
        {
            "propose": propose,
            "regenerate_images": regenerate_images,
            "recompose": recompose,
        },
    )
    db.commit()
    db.refresh(post)
    return post


async def rewrite_post(
    db: Session,
    *,
    post: Post,
    text: dict[str, Any] | None,
    caption: str | None,
    suggest: bool,
    recompose: bool,
    settings: Settings,
) -> Post:
    content = dict(post.content or {})
    if caption is not None:
        content["ig_fb_caption"] = caption
        if content.get("mode") == "single":
            content["overlay_text"] = caption
    if text:
        if content.get("mode") == "pack" and "slides" in text:
            content["slides"] = text["slides"]
        else:
            content.update({k: v for k, v in text.items() if k != "slides"})
    if suggest and has_llm_credentials(settings):
        # Re-run LLM generation into content while keeping pack/template structure
        try:
            page = await scrape_page(post.url)
            brand_name = content.get("brand") or ""
            tagline = content.get("tagline") or ""
            description = ""
            if post.pack_id:
                pack = load_pack(post.pack_id, settings)
                carousel = await generate_carousel(
                    page,
                    pack,
                    settings,
                    brand_name=brand_name,
                    brand_tagline=tagline,
                    brand_description=description,
                )
                content["ig_fb_caption"] = carousel.ig_fb_caption
                content["tiktok_script"] = carousel.tiktok_script
                content["visual_prompt"] = carousel.visual_prompt
                content["slides"] = [s.model_dump() for s in carousel.slides]
            else:
                generated = await generate_post(
                    page,
                    settings,
                    brand_name=brand_name,
                    brand_tagline=tagline,
                    brand_description=description,
                )
                content.update(generated.model_dump())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"Rewrite suggest failed: {exc}"
            ) from exc

    post.content = content
    if recompose:
        post = await compose_post(
            db,
            post=post,
            pages=None,
            ensure_images=True,
            settings=settings,
            record_revision=False,
        )
    else:
        post.status = "drafted"
    _add_revision(db, post, "rewrite", {"suggest": suggest})
    db.commit()
    db.refresh(post)
    return post


def _apply_snapshot(post: Post, snapshot: dict[str, Any]) -> None:
    if "status" in snapshot:
        post.status = snapshot["status"]
    if "format" in snapshot:
        post.format = snapshot["format"]
    if "pack_id" in snapshot:
        post.pack_id = snapshot["pack_id"]
    if "template_id" in snapshot:
        post.template_id = snapshot["template_id"]
    if "variant_id" in snapshot:
        post.variant_id = snapshot["variant_id"]
    if "content" in snapshot:
        post.content = dict(snapshot["content"] or {})
    if "images" in snapshot:
        post.images = dict(snapshot["images"] or {})
    if "composed" in snapshot:
        post.composed = dict(snapshot["composed"] or {})
    if "meta" in snapshot:
        post.meta = dict(snapshot["meta"] or {})


def list_revisions(db: Session, post: Post) -> list[PostRevision]:
    return list(
        db.scalars(
            select(PostRevision)
            .where(PostRevision.post_id == post.id)
            .order_by(PostRevision.version.asc())
        ).all()
    )


def undo_post(db: Session, post: Post) -> Post:
    rows = list(
        db.scalars(
            select(PostRevision)
            .where(PostRevision.post_id == post.id)
            .order_by(PostRevision.version.desc())
            .limit(2)
        ).all()
    )
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="Nothing to undo")
    previous = rows[1]
    snapshot = dict(previous.payload or {})
    _apply_snapshot(post, snapshot)
    _add_revision(
        db,
        post,
        "undo",
        {"restored_version": previous.version, "restored_kind": previous.kind},
    )
    db.commit()
    db.refresh(post)
    return post


async def add_feedback(
    db: Session,
    *,
    post: Post,
    user_id: UUID | None,
    decision: str,
    reasons: list[str],
    note: str,
    page_id: str | None,
    settings: Settings | None = None,
) -> Feedback:
    if decision == "approved" and settings is not None and not _post_has_pngs(post):
        if not (post.composed or {}).get("pages"):
            raise HTTPException(
                status_code=400,
                detail="Compose HTML preview before approving",
            )
        post = await render_post(
            db, post=post, pages=None, settings=settings, record_revision=True
        )

    row = Feedback(
        post_id=post.id,
        tenant_id=post.tenant_id,
        user_id=user_id,
        decision=decision,
        reasons=reasons,
        note=note or "",
        page_id=page_id,
    )
    db.add(row)
    if decision == "approved":
        post.status = "approved"
    elif decision == "rejected":
        post.status = "rejected"
    db.commit()
    db.refresh(row)
    db.refresh(post)
    return row


def list_posts(db: Session, tenant_id: UUID, *, limit: int = 50) -> list[Post]:
    return list(
        db.scalars(
            select(Post)
            .where(Post.tenant_id == tenant_id)
            .order_by(Post.created_at.desc())
            .limit(limit)
        ).all()
    )
