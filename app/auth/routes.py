from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import AuthContext, get_current_auth
from app.auth.security import create_access_token, hash_password, verify_password
from app.config import Settings, get_settings
from app.db.models import Membership, Tenant, User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    user_id: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    name: str
    tenant_id: str
    tenant_name: str


@router.post("/register", response_model=TokenResponse)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    email = body.email.lower().strip()
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    display = (body.name or "").strip() or email.split("@")[0]
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=display,
    )
    tenant = Tenant(name=f"{display}'s workspace")
    db.add(user)
    db.add(tenant)
    db.flush()
    db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(user)
    db.refresh(tenant)

    token = create_access_token(user_id=user.id, tenant_id=tenant.id, settings=settings)
    return TokenResponse(
        access_token=token,
        tenant_id=str(tenant.id),
        user_id=str(user.id),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    email = body.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    membership = db.scalar(
        select(Membership)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at.asc())
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="No tenant membership")

    token = create_access_token(
        user_id=user.id,
        tenant_id=membership.tenant_id,
        settings=settings,
    )
    return TokenResponse(
        access_token=token,
        tenant_id=str(membership.tenant_id),
        user_id=str(user.id),
    )


@router.get("/me", response_model=MeResponse)
def me(auth: AuthContext = Depends(get_current_auth)) -> MeResponse:
    if auth.user is None or auth.tenant is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return MeResponse(
        user_id=str(auth.user_id),
        email=auth.user.email,
        name=auth.user.name,
        tenant_id=str(auth.tenant_id),
        tenant_name=auth.tenant.name,
    )
