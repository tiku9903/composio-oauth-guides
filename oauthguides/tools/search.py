"""Web search: Tavily when TAVILY_API_KEY is set, otherwise DuckDuckGo (no key needed)."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from ..config import settings

log = logging.getLogger(__name__)

COMMUNITY_HOSTS = (
    "stackoverflow.com", "reddit.com", "news.ycombinator.com", "medium.com", "dev.to",
    "community.", "forum.", "github.com/orgs", "quora.com", "x.com", "twitter.com",
)
LOW_VALUE_HOSTS = ("pinterest.", "facebook.com", "youtube.com", "linkedin.com/pulse", "scribd.com")


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    query: str

    @property
    def host(self) -> str:
        return urlparse(self.url).netloc.lower()


def classify_url(url: str, official_domains: list[str]) -> str:
    """Return a Source.kind for a URL."""
    host = urlparse(url).netloc.lower()
    if "composio.dev" in host:
        return "composio_docs"
    if any(host == d or host.endswith("." + d) for d in official_domains):
        path = urlparse(url).path.lower()
        if any(k in path for k in ("policy", "policies", "terms", "legal", "guidelines")):
            return "official_policy"
        return "official_docs"
    if any(c in url.lower() for c in COMMUNITY_HOSTS):
        return "community"
    return "other"


async def _tavily(query: str, n: int) -> list[SearchHit]:
    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=settings.tavily_key)
    res = await client.search(query=query, max_results=n, search_depth="advanced")
    return [
        SearchHit(r.get("title", ""), r["url"], (r.get("content") or "")[:500], query)
        for r in res.get("results", [])
    ]


def _ddg_sync(query: str, n: int) -> list[SearchHit]:
    from ddgs import DDGS

    with DDGS() as d:
        rows = list(d.text(query, max_results=n))
    return [SearchHit(r.get("title", ""), r.get("href", ""), r.get("body", "")[:500], query) for r in rows if r.get("href")]


async def search(query: str, n: int | None = None) -> list[SearchHit]:
    n = n or settings.max_search_results
    try:
        if settings.tavily_key:
            return await _tavily(query, n)
        return await asyncio.to_thread(_ddg_sync, query, n)
    except Exception as e:  # search must never kill the run
        log.warning("search failed for %r: %s", query, e)
        return []


async def search_many(queries: list[str], n: int | None = None) -> list[SearchHit]:
    batches = await asyncio.gather(*(search(q, n) for q in queries))
    seen: set[str] = set()
    out: list[SearchHit] = []
    for batch in batches:
        for hit in batch:
            key = hit.url.split("#")[0].rstrip("/")
            if key in seen or any(h in hit.url for h in LOW_VALUE_HOSTS):
                continue
            seen.add(key)
            out.append(hit)
    return out


def rank_hits(hits: list[SearchHit], official_domains: list[str]) -> list[SearchHit]:
    """Official docs first, then Composio docs, then community, then everything else."""
    order = {"official_docs": 0, "official_policy": 0, "composio_docs": 1, "community": 2, "other": 3}

    def score(h: SearchHit) -> tuple[int, int]:
        kind = classify_url(h.url, official_domains)
        dev_bonus = 0 if any(k in h.url.lower() for k in ("developer", "docs", "oauth", "api", "auth")) else 1
        return (order.get(kind, 3), dev_bonus)

    return sorted(hits, key=score)
