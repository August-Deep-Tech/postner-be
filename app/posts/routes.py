from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl, model_validator
from sqlalchemy.orm import Session

from app.auth.deps import AuthContext, get_current_auth
from app.config import Settings, SocialFormat, get_settings
from app.db.models import Post
from app.db.session import get_db
from app.posts import service as post_service

router = APIRouter(prefix="/posts", tags=["posts"])


class CreatePostRequest(BaseModel):
    url: HttpUrl
    brand_id: str | None = None
    pack_id: str | None = None
    template_id: str | None = None
    format: SocialFormat | None = None
    variant_id: str | None = None
    with_images: bool = False

    @model_validator(mode="after")
    def _template_or_pack(self) -> CreatePostRequest:
        if self.pack_id and self.template_id:
            raise ValueError("Provide only one of template_id or pack_id")
        if not self.pack_id and not self.template_id:
            self.template_id = "default"
        return self


class ImagesRequest(BaseModel):
    pages: list[str] | None = None
    regenerate: bool = False


class ComposeRequest(BaseModel):
    pages: list[str] | None = None
    ensure_images: bool = True


class AnimateRequest(BaseModel):
    page_id: str | None = None
    pages: list[str] | None = None
    motion_preset: str = "fade_kenburns"


class ResizeRequest(BaseModel):
    format: SocialFormat
    pages: list[str] | None = None
    apply_to_post: bool = True


class RedesignRequest(BaseModel):
    variant_id: str | None = None
    propose: bool = False
    regenerate_images: bool = False
    recompose: bool = True


class RewriteRequest(BaseModel):
    text: dict[str, Any] | None = None
    caption: str | None = None
    suggest: bool = False
    recompose: bool = False


class FeedbackRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|needs_changes)$")
    reasons: list[str] = Field(default_factory=list)
    note: str = ""
    page_id: str | None = None


class PostResponse(BaseModel):
    id: str
    tenant_id: str
    brand_id: str | None
    status: str
    url: str
    format: str
    pack_id: str | None
    template_id: str | None
    variant_id: str | None
    asset_dir: str
    content: dict[str, Any]
    images: dict[str, Any]
    composed: dict[str, Any]
    meta: dict[str, Any]
    created_at: str
    updated_at: str


class FeedbackResponse(BaseModel):
    id: str
    post_id: str
    decision: str
    reasons: list[Any]
    note: str
    page_id: str | None
    created_at: str


class ListPostsResponse(BaseModel):
    posts: list[PostResponse]


def _post_response(post: Post) -> PostResponse:
    return PostResponse(
        id=str(post.id),
        tenant_id=str(post.tenant_id),
        brand_id=str(post.brand_id) if post.brand_id else None,
        status=post.status,
        url=post.url,
        format=post.format,
        pack_id=post.pack_id,
        template_id=post.template_id,
        variant_id=post.variant_id,
        asset_dir=post.asset_dir,
        content=post.content or {},
        images=post.images or {},
        composed=post.composed or {},
        meta=post.meta or {},
        created_at=post.created_at.isoformat() if post.created_at else "",
        updated_at=post.updated_at.isoformat() if post.updated_at else "",
    )


@router.get("", response_model=ListPostsResponse)
def list_posts(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> ListPostsResponse:
    posts = post_service.list_posts(db, auth.tenant_id)
    return ListPostsResponse(posts=[_post_response(p) for p in posts])


@router.post("", response_model=PostResponse)
async def create_post(
    body: CreatePostRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PostResponse:
    post = await post_service.create_draft_post(
        db,
        tenant_id=auth.tenant_id,
        url=str(body.url),
        brand_id=body.brand_id,
        pack_id=body.pack_id,
        template_id=body.template_id,
        format_name=body.format,
        variant_id=body.variant_id,
        with_images=body.with_images,
        settings=settings,
    )
    return _post_response(post)


@router.get("/{post_id}", response_model=PostResponse)
def get_post(
    post_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> PostResponse:
    post = post_service.get_post_for_tenant(db, auth.tenant_id, post_id)
    return _post_response(post)


@router.post("/{post_id}/images", response_model=PostResponse)
async def post_images(
    post_id: uuid.UUID,
    body: ImagesRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PostResponse:
    post = post_service.get_post_for_tenant(db, auth.tenant_id, post_id)
    post = await post_service.generate_post_images(
        db,
        post=post,
        pages=body.pages,
        regenerate=body.regenerate,
        settings=settings,
    )
    return _post_response(post)


@router.post("/{post_id}/compose", response_model=PostResponse)
async def post_compose(
    post_id: uuid.UUID,
    body: ComposeRequest | None = None,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PostResponse:
    body = body or ComposeRequest()
    post = post_service.get_post_for_tenant(db, auth.tenant_id, post_id)
    post = await post_service.compose_post(
        db,
        post=post,
        pages=body.pages,
        ensure_images=body.ensure_images,
        settings=settings,
    )
    return _post_response(post)


@router.post("/{post_id}/animate", response_model=PostResponse)
async def post_animate(
    post_id: uuid.UUID,
    body: AnimateRequest | None = None,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PostResponse:
    body = body or AnimateRequest()
    post = post_service.get_post_for_tenant(db, auth.tenant_id, post_id)
    post = await post_service.animate_post(
        db,
        post=post,
        page_id=body.page_id,
        pages=body.pages,
        motion_preset=body.motion_preset,
        settings=settings,
    )
    return _post_response(post)


@router.post("/{post_id}/resize", response_model=PostResponse)
async def post_resize(
    post_id: uuid.UUID,
    body: ResizeRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PostResponse:
    post = post_service.get_post_for_tenant(db, auth.tenant_id, post_id)
    post = await post_service.resize_post(
        db,
        post=post,
        format_name=body.format,
        pages=body.pages,
        apply_to_post=body.apply_to_post,
        settings=settings,
    )
    return _post_response(post)


@router.post("/{post_id}/redesign", response_model=PostResponse)
async def post_redesign(
    post_id: uuid.UUID,
    body: RedesignRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PostResponse:
    post = post_service.get_post_for_tenant(db, auth.tenant_id, post_id)
    post = await post_service.redesign_post(
        db,
        post=post,
        variant_id=body.variant_id,
        propose=body.propose,
        regenerate_images=body.regenerate_images,
        recompose=body.recompose,
        settings=settings,
    )
    return _post_response(post)


@router.post("/{post_id}/rewrite", response_model=PostResponse)
async def post_rewrite(
    post_id: uuid.UUID,
    body: RewriteRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PostResponse:
    post = post_service.get_post_for_tenant(db, auth.tenant_id, post_id)
    post = await post_service.rewrite_post(
        db,
        post=post,
        text=body.text,
        caption=body.caption,
        suggest=body.suggest,
        recompose=body.recompose,
        settings=settings,
    )
    return _post_response(post)


@router.post("/{post_id}/feedback", response_model=FeedbackResponse)
def post_feedback(
    post_id: uuid.UUID,
    body: FeedbackRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    post = post_service.get_post_for_tenant(db, auth.tenant_id, post_id)
    row = post_service.add_feedback(
        db,
        post=post,
        user_id=auth.user_id,
        decision=body.decision,
        reasons=body.reasons,
        note=body.note,
        page_id=body.page_id,
    )
    return FeedbackResponse(
        id=str(row.id),
        post_id=str(row.post_id),
        decision=row.decision,
        reasons=row.reasons or [],
        note=row.note,
        page_id=row.page_id,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )
