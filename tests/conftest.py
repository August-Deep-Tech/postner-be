from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.auth.deps import AuthContext, get_current_auth  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Post, Tenant, User  # noqa: E402
from app.db.session import SessionLocal, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def db(engine: Engine) -> Iterator[Session]:
    """Session built from the app's own sessionmaker, so its options are under test."""
    session = SessionLocal(bind=engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def settings() -> Settings:
    return get_settings().model_copy(
        update={"anthropic_api_key": "test-key", "openai_api_key": ""}
    )


@pytest.fixture()
def tenant(db: Session) -> Tenant:
    row = Tenant(name="Test Tenant")
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def user(db: Session) -> User:
    row = User(
        email=f"{uuid.uuid4().hex}@example.test",
        password_hash="not-a-real-hash",
        name="Tester",
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def auth(tenant: Tenant, user: User) -> AuthContext:
    return AuthContext(
        user_id=user.id, tenant_id=tenant.id, user=user, tenant=tenant
    )


@pytest.fixture()
def client(db: Session, auth: AuthContext) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_auth] = lambda: auth
    try:
        # Not used as a context manager on purpose: the lifespan would run
        # init_db() against the configured Postgres URL.
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_auth, None)


@pytest.fixture()
def make_post(db: Session, tenant: Tenant) -> Callable[..., Post]:
    def _make(**overrides: Any) -> Post:
        fields: dict[str, Any] = {
            "tenant_id": tenant.id,
            "status": "drafted",
            "url": "https://example.com/launch",
            "format": "ig_feed",
            "template_id": "default",
            "content": {
                "mode": "single",
                "ig_fb_caption": "original caption",
                "overlay_text": "original caption",
            },
            "images": {},
            "composed": {},
            "meta": {"run_id": "test-run", "mode": "single"},
        }
        fields.update(overrides)
        post = Post(**fields)
        db.add(post)
        db.commit()
        return post

    return _make


@pytest.fixture()
def commit_count(db: Session) -> Iterator[dict[str, int]]:
    counter = {"n": 0}

    def _after_commit(_session: Session) -> None:
        counter["n"] += 1

    event.listen(db, "after_commit", _after_commit)
    try:
        yield counter
    finally:
        event.remove(db, "after_commit", _after_commit)


@pytest.fixture()
def capture_sql(engine: Engine) -> Callable[[], Any]:
    @contextmanager
    def _capture() -> Iterator[list[str]]:
        statements: list[str] = []

        def _before_cursor_execute(
            _conn: Any,
            _cursor: Any,
            statement: str,
            _params: Any,
            _context: Any,
            _executemany: bool,
        ) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", _before_cursor_execute)
        try:
            yield statements
        finally:
            event.remove(engine, "before_cursor_execute", _before_cursor_execute)

    return _capture
