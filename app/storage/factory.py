from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.storage.base import ObjectStorage
from app.storage.s3 import S3CompatibleStorage


def build_storage(settings: Settings) -> ObjectStorage:
    backend = (settings.storage_backend or "s3").strip().lower()
    if backend != "s3":
        raise ValueError(
            f"Unknown STORAGE_BACKEND '{backend}' (only 's3' is supported; "
            "use Cloudflare R2 or AWS S3)"
        )
    return S3CompatibleStorage(
        bucket=settings.storage_bucket,
        access_key_id=settings.storage_access_key_id,
        secret_access_key=settings.storage_secret_access_key,
        public_base_url=settings.storage_public_base_url,
        endpoint_url=settings.storage_endpoint_url or None,
        region=settings.storage_region or "auto",
        addressing_style=settings.storage_addressing_style or "auto",
    )


@lru_cache
def _cached_storage() -> ObjectStorage:
    return build_storage(get_settings())


def get_storage(settings: Settings | None = None) -> ObjectStorage:
    """Return storage for the given settings (or cached process defaults)."""
    if settings is None:
        return _cached_storage()
    return build_storage(settings)
