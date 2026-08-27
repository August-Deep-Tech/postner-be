from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import decode_token
from app.config import Settings, get_settings
from app.db.models import Membership, Tenant, User
from app.db.session import get_db

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    user: User | None = None
    tenant: Tenant | None = None


def get_current_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials, settings)
        user_id = uuid.UUID(str(payload["sub"]))
        tenant_id = uuid.UUID(str(payload["tenant_id"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.tenant_id == tenant_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this tenant")

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=403, detail="Tenant not found")

    return AuthContext(user_id=user.id, tenant_id=tenant.id, user=user, tenant=tenant)


def get_current_tenant(auth: AuthContext = Depends(get_current_auth)) -> uuid.UUID:
    return auth.tenant_id
