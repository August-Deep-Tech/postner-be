from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStorage(Protocol):
    """Provider-neutral object storage. App code depends only on this protocol."""

    def upload(self, local_path: Path, key: str, *, content_type: str | None = None) -> str:
        """Upload a local file and return a public URL."""
        ...

    def upload_bytes(
        self, data: bytes, key: str, *, content_type: str | None = None
    ) -> str:
        """Upload raw bytes and return a public URL."""
        ...
