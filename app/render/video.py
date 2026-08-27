from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

from app.config import SocialFormat, get_size
from app.render.motion import MOTION_DURATION_S, MOTION_FPS, apply_motion_preset


async def render_html_video(
    *,
    html: str,
    dest: Path,
    format_name: SocialFormat,
    work_dir: Path,
    motion_preset: str = "fade_kenburns",
    html_name: str = "filled_motion.html",
    duration_s: float = MOTION_DURATION_S,
    fps: int = MOTION_FPS,
) -> Path:
    """Apply a motion preset, capture frames with Playwright, encode MP4 via ffmpeg."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed or not on PATH")

    width, height = get_size(format_name)
    work_dir.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    motion_html = apply_motion_preset(html, motion_preset)
    html_path = work_dir / html_name
    html_path.write_text(motion_html, encoding="utf-8")

    frame_count = max(1, int(round(duration_s * fps)))
    frames_dir = Path(tempfile.mkdtemp(prefix="postner_frames_", dir=str(work_dir)))

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                )
                await page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
                await page.wait_for_timeout(400)
                await page.evaluate("() => document.fonts.ready")

                # Freeze timeline so we can scrub currentTime per frame
                await page.evaluate(
                    """() => {
                      for (const a of document.getAnimations({subtree: true})) {
                        a.pause();
                        a.currentTime = 0;
                      }
                    }"""
                )

                root = page.locator("#canvas, .post, body").first
                box = await root.bounding_box()
                use_root = bool(box and box["width"] > 0 and box["height"] > 0)

                for i in range(frame_count):
                    t_ms = (i / fps) * 1000.0
                    await page.evaluate(
                        """(t) => {
                          for (const a of document.getAnimations({subtree: true})) {
                            a.pause();
                            a.currentTime = t;
                          }
                        }""",
                        t_ms,
                    )
                    frame_path = frames_dir / f"frame_{i:04d}.png"
                    if use_root:
                        await root.screenshot(path=str(frame_path), type="png")
                    else:
                        await page.screenshot(
                            path=str(frame_path),
                            type="png",
                            clip={"x": 0, "y": 0, "width": width, "height": height},
                        )
            finally:
                await browser.close()

        pattern = str(frames_dir / "frame_%04d.png")
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            pattern,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(dest),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = (stderr or b"").decode("utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"ffmpeg failed (code {proc.returncode}): {err}")
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)

    return dest
