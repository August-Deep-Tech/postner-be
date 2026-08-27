from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; PostnerBot/0.1; +https://github.com/postner)"
)


@dataclass
class ScrapedPage:
    url: str
    title: str
    text: str
    page_type: str


def infer_page_type(url: str, title: str = "", text: str = "") -> str:
    path = urlparse(url).path.lower().rstrip("/")
    haystack = f"{path} {title.lower()} {text[:500].lower()}"

    if path in ("", "/") or path.endswith("/home"):
        return "homepage"
    if any(k in haystack for k in ("/pricing", "pricing", "plans", "subscription")):
        return "pricing"
    if any(
        k in haystack
        for k in ("/blog/", "/posts/", "/articles/", "blog post", "published")
    ):
        return "blog"
    if any(
        k in haystack
        for k in ("/feature", "/product", "/solutions", "how it works", "capabilities")
    ):
        return "feature"
    return "feature"


def _clean_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer"]):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


async def scrape_page(url: str, timeout: float = 30.0) -> ScrapedPage:
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = str(og["content"]).strip() or title

    text = _clean_text(soup)
    if len(text) > 12_000:
        text = text[:12_000] + "\n…"

    page_type = infer_page_type(url, title, text)
    return ScrapedPage(url=url, title=title or url, text=text, page_type=page_type)
