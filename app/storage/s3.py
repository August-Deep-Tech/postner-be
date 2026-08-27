from __future__ import annotations

from pathlib import Path

import boto3
from botocore.client import BaseClient


def _guess_content_type(path: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".mp4":
        return "video/mp4"
    if suffix == ".gif":
        return "image/gif"
    return None


class S3CompatibleStorage:
    """S3-compatible object storage (AWS S3, Cloudflare R2, MinIO, etc.)."""

    def __init__(
        self,
        *,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        public_base_url: str,
        endpoint_url: str | None = None,
        region: str = "auto",
    ) -> None:
        if not bucket:
            raise ValueError("STORAGE_BUCKET is required for s3 backend")
        if not access_key_id or not secret_access_key:
            raise ValueError(
                "STORAGE_ACCESS_KEY_ID and STORAGE_SECRET_ACCESS_KEY are required for s3 backend"
            )
        if not public_base_url:
            raise ValueError("STORAGE_PUBLIC_BASE_URL is required for s3 backend")

        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip("/")
        client_kwargs: dict = {
            "service_name": "s3",
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "region_name": region or "auto",
        }
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        self._client: BaseClient = boto3.client(**client_kwargs)

    def upload(self, local_path: Path, key: str, *, content_type: str | None = None) -> str:
        path = Path(local_path)
        if not path.is_file():
            raise FileNotFoundError(f"Local file not found for upload: {path}")
        extra: dict = {}
        ctype = _guess_content_type(path, content_type)
        if ctype:
            extra["ContentType"] = ctype
        if extra:
            self._client.upload_file(str(path), self._bucket, key, ExtraArgs=extra)
        else:
            self._client.upload_file(str(path), self._bucket, key)
        return f"{self._public_base_url}/{key.lstrip('/')}"
