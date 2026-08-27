from __future__ import annotations

from pathlib import Path


class LocalStorage:
    """Smoke / offline backend: no upload; returns the local filesystem path as the URL."""

    def upload(self, local_path: Path, key: str, *, content_type: str | None = None) -> str:
        path = Path(local_path)
        if not path.is_file():
            raise FileNotFoundError(f"Local file not found for upload: {path}")
        return str(path.resolve())
