from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings


@dataclass
class BrandProfile:
    id: str
    name: str
    tagline: str = ""
    description: str = ""
    logo: str | None = None
    root: Path | None = None

    def placeholder_map(self, *, logo_url: str = "") -> dict[str, str]:
        return {
            "brand": self.name,
            "tagline": self.tagline,
            "logo_url": logo_url,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tagline": self.tagline,
            "description": self.description,
            "logo": self.logo,
        }


_ID_RE = re.compile(r"[^\w\-]+")


def normalize_brand_id(raw: str) -> str:
    cleaned = _ID_RE.sub("_", (raw or "").strip()).strip("_").lower()
    return cleaned or "brand"


def brand_dir(brand_id: str, settings: Settings) -> Path:
    return settings.brands_dir / brand_id


def list_brand_ids(settings: Settings) -> list[str]:
    root = settings.brands_dir
    if not root.exists():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "brand.json").is_file()
    )


def load_brand(brand_id: str, settings: Settings) -> BrandProfile:
    root = brand_dir(brand_id, settings)
    path = root / "brand.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Brand '{brand_id}' not found (expected {path}). "
            "See brands/README.md."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    logo = data.get("logo")
    logo_str = str(logo).strip() if logo else None
    return BrandProfile(
        id=str(data.get("id") or brand_id),
        name=str(data.get("name") or brand_id),
        tagline=str(data.get("tagline") or ""),
        description=str(data.get("description") or ""),
        logo=logo_str or None,
        root=root,
    )


def resolve_logo_path(brand: BrandProfile) -> Path | None:
    if not brand.logo or not brand.root:
        return None
    path = brand.root / brand.logo
    if path.is_file():
        return path
    return None


def save_brand(
    *,
    brand_id: str | None,
    name: str,
    tagline: str = "",
    description: str = "",
    logo: str | None = None,
    settings: Settings,
) -> BrandProfile:
    bid = normalize_brand_id(brand_id or name)
    root = brand_dir(bid, settings)
    root.mkdir(parents=True, exist_ok=True)

    logo_name = logo
    if logo_name:
        logo_name = Path(logo_name).name

    payload = {
        "id": bid,
        "name": name.strip() or bid,
        "tagline": tagline.strip(),
        "description": description.strip(),
        "logo": logo_name,
    }
    path = root / "brand.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return BrandProfile(
        id=bid,
        name=payload["name"],
        tagline=payload["tagline"],
        description=payload["description"],
        logo=logo_name,
        root=root,
    )
