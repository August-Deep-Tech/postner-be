from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.storage.base import ObjectStorage
from app.storage.local import LocalStorage
from app.storage.s3 import S3CompatibleStorage


def build_storage(settings: Settings) -> ObjectStorage:
    backend = (settings.storage_backend or "local").strip().lower()
    if backend == "local":
        return LocalStorage()
    if backend == "s3":
        return S3CompatibleStorage(
            bucket=settings.storage_bucket,
            access_key_id=settings.storage_access_key_id,
            secret_access_key=settings.storage_secret_access_key,
            public_base_url=settings.storage_public_base_url,
            endpoint_url=settings.storage_endpoint_url or None,
            region=settings.storage_region or "auto",
        )
    raise ValueError(f"Unknown STORAGE_BACKEND '{backend}' (expected 'local' or 's3')")


@lru_cache
def _cached_storage() -> ObjectStorage:
    return build_storage(get_settings())


def get_storage(settings: Settings | None = None) -> ObjectStorage:
    """Return storage for the given settings (or cached process defaults)."""
    if settings is None:
        return _cached_storage()
    # Avoid stale cache when tests pass explicit settings
    return build_storage(settings)
