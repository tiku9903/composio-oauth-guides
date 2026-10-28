"""Fetch a page and reduce it to readable text."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import httpx

from ..config import settings

log = logging.getLogger(__name__)


@dataclass
class Page:
    url: str
    final_url: str
    status: int
    title: str
    text: str
    error: str | None = None


def _title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:200] if m else ""


def html_to_text(html: str) -> str:
    try:
        import trafilatura

        text = trafilatura.extract(html, include_links=False, include_tables=True, favor_recall=True)
        if text:
            return text
    except Exception:  # pragma: no cover
        pass
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def client(**kw) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.http_timeout,
        follow_redirects=kw.pop("follow_redirects", True),
        headers={"User-Agent": settings.user_agent, "Accept-Language": "en-US,en;q=0.8"},
        **kw,
    )


async def fetch_page(url: str, limit: int | None = None) -> Page:
    limit = limit or settings.page_char_limit
    try:
        async with client() as c:
            r = await c.get(url)
        ctype = r.headers.get("content-type", "")
        if "html" in ctype or "xml" in ctype or ctype.startswith("text/"):
            body = r.text
            text = html_to_text(body) if "html" in ctype else body
            final = str(r.url)
            if len(final) > 300 or final.count("%25") > 3:  # redirect loops pile up encoded "back=" params
                final = url
            return Page(url, final, r.status_code, _title(body), text[:limit])
        return Page(url, str(r.url), r.status_code, "", "", error=f"unsupported content-type {ctype}")
    except Exception as e:
        log.info("fetch failed %s: %s", url, e)
        return Page(url, url, 0, "", "", error=f"{type(e).__name__}: {e}")


async def fetch_many(urls: list[str], concurrency: int = 6) -> list[Page]:
    sem = asyncio.Semaphore(concurrency)

    async def one(u: str) -> Page:
        async with sem:
            return await fetch_page(u)

    return await asyncio.gather(*(one(u) for u in urls))
