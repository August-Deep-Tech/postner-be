from __future__ import annotations

from pathlib import Path

from playwright.async_api import async_playwright

from app.config import SocialFormat, get_size


async def screenshot_html(
    *,
    html: str,
    dest: Path,
    format_name: SocialFormat,
) -> Path:
    """Screenshot HTML at the social canvas size (assets must be http(s) URLs)."""
    width, height = get_size(format_name)
    dest.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            await page.set_content(html, wait_until="networkidle")
            await page.wait_for_timeout(500)
            await page.evaluate("() => document.fonts.ready")

            root = page.locator("#canvas, .post, body").first
            box = await root.bounding_box()
            if box and box["width"] > 0 and box["height"] > 0:
                await root.screenshot(path=str(dest), type="png")
            else:
                await page.screenshot(
                    path=str(dest),
                    type="png",
                    clip={"x": 0, "y": 0, "width": width, "height": height},
                )
        finally:
            await browser.close()

    return dest
