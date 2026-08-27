from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.deps import AuthContext, get_current_auth
from app.brands.service import get_tenant_brand
from app.brands.variants import (
    list_brand_variants,
    seed_brand_variants_from_disk,
    variant_to_dict,
)
from app.config import Settings, get_settings, has_llm_credentials
from app.db.session import get_db
from app.models.schemas import (
    HealthResponse,
    ListIdsResponse,
    ListPacksResponse,
    ListVariantsResponse,
    PackSummary,
    ProposePacksRequest,
    ProposePacksResponse,
    ProposeVariantsRequest,
    ProposeVariantsResponse,
    VariantOut,
)
from app.templates.engine import list_template_ids
from app.templates.packs import list_pack_ids, load_pack
from app.templates.pack_propose import propose_and_save_packs
from app.templates.variants import propose_and_save_variants

router = APIRouter(tags=["catalog"])


def _settings() -> Settings:
    return get_settings()


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


@router.get("/variants", response_model=ListVariantsResponse)
def variants(
    brand_id: str = Query(..., description="Brand UUID or slug"),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ListVariantsResponse:
    brand = get_tenant_brand(db, auth.tenant_id, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail=f"Brand '{brand_id}' not found")
    rows = list_brand_variants(db, brand)
    if not rows:
        rows = seed_brand_variants_from_disk(db, brand, settings)
    return ListVariantsResponse(
        variants=[VariantOut(**variant_to_dict(r)) for r in rows]
    )


@router.post("/variants/propose", response_model=ProposeVariantsResponse)
async def variants_propose(
    body: ProposeVariantsRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProposeVariantsResponse:
    if not has_llm_credentials(settings):
        raise HTTPException(
            status_code=500,
            detail="Set ANTHROPIC_API_KEY or OPENAI_API_KEY",
        )
    brand = get_tenant_brand(db, auth.tenant_id, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail=f"Brand '{body.brand_id}' not found")
    try:
        variants, saved_ids = await propose_and_save_variants(
            db=db,
            brand=brand,
            template_id=body.template_id,
            pack_id=body.pack_id,
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
async def packs_propose(
    body: ProposePacksRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProposePacksResponse:
    """Propose multi-page packs from the existing page catalog; optionally pair with variants."""
    if not has_llm_credentials(settings):
        raise HTTPException(
            status_code=500,
            detail="Set ANTHROPIC_API_KEY or OPENAI_API_KEY",
        )
    brand = None
    if body.brand_id:
        brand = get_tenant_brand(db, auth.tenant_id, body.brand_id)
        if brand is None:
            raise HTTPException(status_code=404, detail=f"Brand '{body.brand_id}' not found")
    elif body.with_variants:
        raise HTTPException(
            status_code=400,
            detail="brand_id is required when with_variants is true",
        )
    try:
        packs, saved_pack_ids, variants, saved_variant_ids = await propose_and_save_packs(
            count=body.count,
            format_name=body.format,
            settings=settings,
            brief=body.brief,
            brand=brand,
            db=db,
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
