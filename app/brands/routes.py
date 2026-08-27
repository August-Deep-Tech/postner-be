from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import AuthContext, get_current_auth
from app.brands import service as brand_service
from app.config import SocialFormat
from app.config import Settings, get_settings
from app.db.session import get_db

router = APIRouter(prefix="/brands", tags=["brands"])


class CreateBrandBody(BaseModel):
    id: str | None = None
    name: str
    tagline: str = ""
    description: str = ""
    website: str | None = None
    logo: str | None = None
    formats: list[SocialFormat] = Field(default_factory=lambda: ["ig_feed"])


class PatchBrandBody(BaseModel):
    name: str | None = None
    tagline: str | None = None
    description: str | None = None
    website: str | None = None
    logo: str | None = None
    formats: list[SocialFormat] | None = None


class BrandOut(BaseModel):
    id: str
    slug: str
    name: str
    tagline: str = ""
    description: str = ""
    website: str | None = None
    logo: str | None = None
    formats: list[SocialFormat] = Field(default_factory=list)


class ListBrandsOut(BaseModel):
    brands: list[BrandOut]


def _out(brand) -> BrandOut:
    return BrandOut(
        id=str(brand.id),
        slug=brand.slug,
        name=brand.name,
        tagline=brand.tagline,
        description=brand.description,
        website=brand.website,
        logo=brand.logo,
        formats=brand_service.brand_formats(brand),  # type: ignore[arg-type]
    )


@router.get("", response_model=ListBrandsOut)
def list_brands(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> ListBrandsOut:
    brands = brand_service.list_tenant_brands(db, auth.tenant_id)
    return ListBrandsOut(brands=[_out(b) for b in brands])


@router.get("/{brand_id}", response_model=BrandOut)
def get_brand(
    brand_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> BrandOut:
    brand = brand_service.get_tenant_brand(db, auth.tenant_id, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return _out(brand)


@router.post("", response_model=BrandOut)
def create_brand(
    body: CreateBrandBody,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BrandOut:
    try:
        brand = brand_service.create_brand(
            db,
            tenant_id=auth.tenant_id,
            name=body.name,
            slug=body.id,
            tagline=body.tagline,
            description=body.description,
            website=body.website,
            logo=body.logo,
            formats=list(body.formats),
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(brand)


@router.patch("/{brand_id}", response_model=BrandOut)
def patch_brand(
    brand_id: str,
    body: PatchBrandBody,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> BrandOut:
    brand = brand_service.get_tenant_brand(db, auth.tenant_id, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    try:
        brand = brand_service.update_brand(
            db,
            brand,
            name=body.name,
            tagline=body.tagline,
            description=body.description,
            website=body.website,
            logo=body.logo,
            formats=list(body.formats) if body.formats is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(brand)
