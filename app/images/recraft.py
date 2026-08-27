from __future__ import annotations

from pathlib import Path

import fal_client
import httpx

from app.config import Settings


async def generate_recraft_image(
    *,
    prompt: str,
    dest: Path,
    settings: Settings,
) -> Path:
    """Generate an image with Recraft V3 via fal.ai and save it to dest."""
    if not settings.fal_key:
        raise RuntimeError("FAL_KEY is not set")

    # fal_client reads FAL_KEY from the environment
    import os

    os.environ.setdefault("FAL_KEY", settings.fal_key)

    result = await fal_client.run_async(
        settings.recraft_model,
        arguments={
            "prompt": prompt,
            "image_size": "square_hd",
        },
    )

    images = result.get("images") or []
    if not images:
        raise RuntimeError(f"Recraft returned no images: {result!r}")

    image_url = images[0].get("url")
    if not image_url:
        raise RuntimeError(f"Recraft image missing url: {images[0]!r}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
        resp = await client.get(image_url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)

    return dest
