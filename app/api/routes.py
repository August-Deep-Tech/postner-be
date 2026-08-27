from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.brands.store import BrandProfile, load_brand, resolve_logo_path
from app.config import Settings, SocialFormat, get_settings, has_llm_credentials
from app.generate.posts import generate_carousel, generate_post
from app.images.recraft import generate_recraft_image
from app.models.schemas import (
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    ListIdsResponse,
    ListPacksResponse,
    PackSummary,
    ProposePacksRequest,
    ProposePacksResponse,
    ProposeVariantsRequest,
    ProposeVariantsResponse,
)
from app.render.screenshot import screenshot_html
from app.render.video import render_html_video
from app.scrape.page import scrape_page
from app.templates.engine import (
    list_template_ids,
    list_variant_ids,
    load_variant,
    path_to_file_url,
    render_filled_html,
)
from app.templates.packs import list_pack_ids, load_pack, render_pack_page_html
from app.templates.pack_propose import propose_and_save_packs
from app.templates.variants import propose_and_save_variants

router = APIRouter(tags=["catalog"])


def _settings() -> Settings:
    return get_settings()


def _resolve_brand(
    body: GenerateRequest,
    settings: Settings,
) -> tuple[BrandProfile | None, str, str, str, str]:
    """File-brand resolver for legacy /generate."""
    profile: BrandProfile | None = None
    if body.brand_id:
        try:
            profile = load_brand(body.brand_id, settings)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    name = (body.brand or "").strip()
    tagline = ""
    description = ""
    logo_url = ""

    if profile:
        name = name or profile.name
        tagline = profile.tagline
        description = profile.description
        logo_path = resolve_logo_path(profile)
        if logo_path:
            logo_url = path_to_file_url(logo_path)

    return profile, name, tagline, description, logo_url


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    try:
        from sqlalchemy import text

        from app.db.session import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return HealthResponse(status="ok")
    except Exception:  # noqa: BLE001
        return HealthResponse(status="degraded")


@router.get("/templates", response_model=ListIdsResponse)
async def templates() -> ListIdsResponse:
    return ListIdsResponse(ids=list_template_ids(_settings()))


@router.get("/packs", response_model=ListPacksResponse)
async def packs() -> ListPacksResponse:
    settings = _settings()
    summaries: list[PackSummary] = []
    for pack_id in list_pack_ids(settings):
        pack = load_pack(pack_id, settings)
        summaries.append(
            PackSummary(
                id=pack.id,
                label=pack.label,
                format=pack.format,
                pages=len(pack.sequence),
                images=pack.total_images(),
                description=pack.description,
            )
        )
    return ListPacksResponse(packs=summaries)


@router.get("/variants", response_model=ListIdsResponse)
async def variants() -> ListIdsResponse:
    return ListIdsResponse(ids=list_variant_ids(_settings()))


@router.post("/variants/propose", response_model=ProposeVariantsResponse)
async def variants_propose(body: ProposeVariantsRequest) -> ProposeVariantsResponse:
    settings = _settings()
    if not has_llm_credentials(settings):
        raise HTTPException(
            status_code=500,
            detail="Set ANTHROPIC_API_KEY or OPENAI_API_KEY",
        )
    try:
        variants, saved_ids = await propose_and_save_variants(
            template_id=body.template_id,
            pack_id=body.pack_id,
            brand_id=body.brand_id,
            count=body.count,
            settings=settings,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Variant proposal failed: {exc}") from exc

    return ProposeVariantsResponse(variants=variants, saved_ids=saved_ids)


@router.post("/packs/propose", response_model=ProposePacksResponse)
async def packs_propose(body: ProposePacksRequest) -> ProposePacksResponse:
    """Propose multi-page packs from the existing page catalog; optionally pair with variants."""
    settings = _settings()
    if not has_llm_credentials(settings):
        raise HTTPException(
            status_code=500,
            detail="Set ANTHROPIC_API_KEY or OPENAI_API_KEY",
        )
    try:
        packs, saved_pack_ids, variants, saved_variant_ids = await propose_and_save_packs(
            count=body.count,
            format_name=body.format,
            settings=settings,
            brief=body.brief,
            brand_id=body.brand_id,
            with_variants=body.with_variants,
            variant_count=body.variant_count,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Pack proposal failed: {exc}") from exc

    return ProposePacksResponse(
        packs=packs,
        saved_pack_ids=saved_pack_ids,
        variants=variants,
        saved_variant_ids=saved_variant_ids,
    )


@router.post("/generate", response_model=GenerateResponse)
async def generate(body: GenerateRequest) -> GenerateResponse:
    """Legacy one-shot generate (local/dev). Prefer /posts lifecycle in product mode."""
    settings = _settings()
    if not settings.auth_disabled:
        # Still allow when authenticated is not required at route level —
        # product clients should use /posts. Keep usable for smoke when AUTH_DISABLED.
        pass
    if not has_llm_credentials(settings):
        raise HTTPException(
            status_code=500,
            detail="Set ANTHROPIC_API_KEY or OPENAI_API_KEY",
        )

    if body.pack_id:
        return await _generate_pack(body, settings)
    return await _generate_single(body, settings)


async def _generate_single(body: GenerateRequest, settings: Settings) -> GenerateResponse:
    if not settings.fal_key:
        raise HTTPException(status_code=500, detail="FAL_KEY is not set")

    url = str(body.url)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = settings.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    fmt: SocialFormat = body.format or "ig_feed"
    profile, brand_name, tagline, description, logo_url = _resolve_brand(body, settings)

    try:
        page = await scrape_page(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Scrape failed: {exc}") from exc

    try:
        post = await generate_post(
            page,
            settings,
            brand_name=brand_name,
            brand_tagline=tagline,
            brand_description=description,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}") from exc

    image_path = run_dir / "image.png"
    try:
        await generate_recraft_image(
            prompt=post.visual_prompt,
            dest=image_path,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Recraft generation failed: {exc}") from exc

    css_vars = None
    if body.variant_id:
        try:
            variant = load_variant(body.variant_id, settings)
            css_vars = variant.get("css_vars") or {}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        filled = render_filled_html(
            template_id=body.template_id or "default",
            caption=post.overlay_text,
            image_path=image_path,
            cta_link=url,
            settings=settings,
            css_vars=css_vars,
            brand=brand_name,
            tagline=tagline,
            logo_url=logo_url,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    final_path = run_dir / "final.png"
    try:
        await screenshot_html(
            html=filled,
            dest=final_path,
            format_name=fmt,
            work_dir=run_dir,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Render failed: {exc}") from exc

    video_path: str | None = None
    video_error: str | None = None
    if body.animate:
        try:
            dest_video = run_dir / "final.mp4"
            await render_html_video(
                html=filled,
                dest=dest_video,
                format_name=fmt,
                work_dir=run_dir,
                motion_preset=body.motion_preset,
                html_name="filled_motion.html",
            )
            video_path = str(dest_video)
        except Exception as exc:  # noqa: BLE001
            video_error = str(exc)

    brand_id = profile.id if profile else body.brand_id
    meta = {
        "run_id": run_id,
        "mode": "single",
        "post_type": post.post_type,
        "ig_fb_caption": post.ig_fb_caption,
        "tiktok_script": post.tiktok_script,
        "visual_prompt": post.visual_prompt,
        "overlay_text": post.overlay_text,
        "page_type": post.page_type,
        "cta_link": url,
        "image_path": str(image_path),
        "final_path": str(final_path),
        "page_paths": [],
        "video_path": video_path,
        "page_video_paths": [],
        "video_error": video_error,
        "animate": body.animate,
        "motion_preset": body.motion_preset if body.animate else None,
        "template_id": body.template_id,
        "pack_id": None,
        "brand_id": brand_id,
        "brand_name": brand_name or None,
        "variant_id": body.variant_id,
        "format": fmt,
        "source_title": page.title,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = run_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    return GenerateResponse(
        run_id=run_id,
        post_type=post.post_type,
        ig_fb_caption=post.ig_fb_caption,
        tiktok_script=post.tiktok_script,
        visual_prompt=post.visual_prompt,
        overlay_text=post.overlay_text,
        page_type=post.page_type,
        cta_link=url,
        image_path=str(image_path),
        final_path=str(final_path),
        page_paths=[],
        video_path=video_path,
        page_video_paths=[],
        meta_path=str(meta_path),
        template_id=body.template_id,
        pack_id=None,
        brand_id=brand_id,
        variant_id=body.variant_id,
        format=fmt,
    )


async def _generate_pack(body: GenerateRequest, settings: Settings) -> GenerateResponse:
    url = str(body.url)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = settings.output_dir / run_id
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    try:
        pack = load_pack(body.pack_id or "", settings)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    fmt: SocialFormat = body.format or pack.format
    needs_images = pack.total_images() > 0
    if needs_images and not settings.fal_key:
        raise HTTPException(status_code=500, detail="FAL_KEY is not set")

    profile, brand_name, tagline, description, logo_url = _resolve_brand(body, settings)

    try:
        page = await scrape_page(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Scrape failed: {exc}") from exc

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
        raise HTTPException(status_code=502, detail=f"LLM carousel generation failed: {exc}") from exc

    if brand_name:
        carousel.brand = brand_name
        for slide in carousel.slides:
            slide.brand = brand_name

    variant_css = None
    if body.variant_id:
        try:
            variant = load_variant(body.variant_id, settings)
            variant_css = variant.get("css_vars") or {}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    shared_images: list[Path] = []
    image_path: Path | None = None
    page_image_map: dict[str, Path] = {}
    if needs_images:
        for index, (page_def, slide) in enumerate(
            zip(pack.sequenced_pages(), carousel.slides), start=1
        ):
            if page_def.images <= 0:
                continue
            prompt = (slide.visual_prompt or carousel.visual_prompt or "").strip()
            if not prompt:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Pack page '{page_def.id}' needs an image but no visual_prompt "
                        "was returned"
                    ),
                )
            dest_img = run_dir / f"image_{index:02d}_{page_def.id}.png"
            try:
                await generate_recraft_image(
                    prompt=prompt,
                    dest=dest_img,
                    settings=settings,
                )
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=502,
                    detail=f"Recraft generation failed for {page_def.id}: {exc}",
                ) from exc
            page_image_map[page_def.id] = dest_img
            if image_path is None:
                image_path = dest_img
                shared_images = [dest_img]

    page_paths: list[str] = []
    page_video_paths: list[str] = []
    video_error: str | None = None
    slides_meta: list[dict] = []
    sequenced = pack.sequenced_pages()

    try:
        for index, (page_def, slide) in enumerate(zip(sequenced, carousel.slides), start=1):
            fields = slide.field_map()
            fields["brand"] = brand_name or slide.brand or carousel.brand or pack.default_brand
            fields["tagline"] = tagline
            fields["logo_url"] = logo_url
            if "page_number" in page_def.fields and not fields.get("page_number"):
                fields["page_number"] = f"{index:02d}"
            if "handle" in page_def.fields and not fields.get("handle") and brand_name:
                fields["handle"] = "@" + brand_name.replace(" ", "")
            if "series" in page_def.fields and not fields.get("series") and tagline:
                fields["series"] = tagline.upper()

            if page_def.images > 0:
                img = page_image_map.get(page_def.id)
                page_images = [img] if img else shared_images[: page_def.images]
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
            dest = pages_dir / f"{index:02d}_{page_def.id}.png"
            await screenshot_html(
                html=filled,
                dest=dest,
                format_name=fmt,
                work_dir=run_dir,
                html_name=f"filled_{index:02d}_{page_def.id}.html",
            )
            page_paths.append(str(dest))

            video_dest_str: str | None = None
            if body.animate and video_error is None:
                try:
                    video_dest = pages_dir / f"{index:02d}_{page_def.id}.mp4"
                    await render_html_video(
                        html=filled,
                        dest=video_dest,
                        format_name=fmt,
                        work_dir=run_dir,
                        motion_preset=body.motion_preset,
                        html_name=f"filled_motion_{index:02d}_{page_def.id}.html",
                    )
                    video_dest_str = str(video_dest)
                    page_video_paths.append(video_dest_str)
                except Exception as exc:  # noqa: BLE001
                    video_error = str(exc)

            slides_meta.append(
                {
                    "index": index,
                    "page_id": page_def.id,
                    "role": page_def.role,
                    "tags": page_def.tags,
                    "path": str(dest),
                    "video_path": video_dest_str,
                    "fields": fields,
                    "visual_prompt": slide.visual_prompt or None,
                }
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Pack render failed: {exc}") from exc

    overlay = ""
    if carousel.slides:
        overlay = carousel.slides[0].title or carousel.slides[0].subtitle

    brand_id = profile.id if profile else body.brand_id
    video_path = page_video_paths[0] if page_video_paths else None
    meta = {
        "run_id": run_id,
        "mode": "pack",
        "pack_id": pack.id,
        "post_type": carousel.post_type,
        "ig_fb_caption": carousel.ig_fb_caption,
        "tiktok_script": carousel.tiktok_script,
        "visual_prompt": carousel.visual_prompt,
        "overlay_text": overlay,
        "page_type": carousel.page_type,
        "brand": carousel.brand,
        "brand_id": brand_id,
        "cta_link": url,
        "image_path": str(image_path) if image_path else None,
        "final_path": page_paths[0] if page_paths else None,
        "page_paths": page_paths,
        "video_path": video_path,
        "page_video_paths": page_video_paths,
        "video_error": video_error,
        "animate": body.animate,
        "motion_preset": body.motion_preset if body.animate else None,
        "slides": slides_meta,
        "template_id": None,
        "variant_id": body.variant_id,
        "format": fmt,
        "source_title": page.title,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = run_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    return GenerateResponse(
        run_id=run_id,
        post_type=carousel.post_type,
        ig_fb_caption=carousel.ig_fb_caption,
        tiktok_script=carousel.tiktok_script,
        visual_prompt=carousel.visual_prompt,
        overlay_text=overlay,
        page_type=carousel.page_type,
        cta_link=url,
        image_path=str(image_path) if image_path else None,
        final_path=page_paths[0] if page_paths else None,
        page_paths=page_paths,
        video_path=video_path,
        page_video_paths=page_video_paths,
        meta_path=str(meta_path),
        template_id=None,
        pack_id=pack.id,
        brand_id=brand_id,
        variant_id=body.variant_id,
        format=fmt,
    )
