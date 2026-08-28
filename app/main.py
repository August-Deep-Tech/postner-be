from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.auth.routes import router as auth_router
from app.brands.routes import router as brands_router
from app.config import get_settings
from app.db.session import init_db
from app.posts.routes import router as posts_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


settings = get_settings()
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or [
    "*"
]

app = FastAPI(
    title="Postner BE",
    description="Multi-tenant URL → drafted post → Recraft → composed social PNG",
    version=__version__,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(auth_router)
app.include_router(brands_router)
app.include_router(posts_router)
