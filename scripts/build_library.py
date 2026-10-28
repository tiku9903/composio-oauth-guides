"""Grow the library toward the 100-app catalog with the live agent.

    python scripts/build_library.py --limit 10          # next 10 apps without a guide
    python scripts/build_library.py zendesk pipedrive   # specific catalog slugs
    python scripts/build_library.py --concurrency 2 --limit 100

Generated guides land in data/guides/generated/ and appear in the library immediately. They are
labelled "Agent-generated" until a person spot-checks them (see docs/VERIFICATION.md for the method),
at which point they can be moved to data/guides/curated/ with verification.status = "spot_checked".
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oauthguides.agent.graph import run  # noqa: E402
from oauthguides.config import settings  # noqa: E402
from oauthguides.store import GuideStore  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()
    if not settings.llm_configured:
        sys.exit(f"No API key configured for {settings.model}")

    store = GuideStore()
    catalog = json.loads(settings.catalog_path.read_text())
    todo = [c for c in catalog if (not args.slugs or c["slug"] in args.slugs) and not (store.get(c["slug"]) or store.find(c["name"]))]
    todo = todo[: args.limit]
    print(f"Investigating {len(todo)} apps with concurrency {args.concurrency}")
    sem = asyncio.Semaphore(args.concurrency)
    results: list[tuple[str, str]] = []

    async def one(c: dict) -> None:
        async with sem:
            t0 = time.time()
            try:
                g = await run(f"{c['name']} ({c['website']})")
                results.append((c["name"], f"tier {g.tier}, {len(g.sources)} sources, {time.time() - t0:.0f}s"))
            except Exception as e:
                results.append((c["name"], f"FAILED {type(e).__name__}: {e}"))
            print(f"  {c['name']}: {results[-1][1]}", flush=True)

    await asyncio.gather(*(one(c) for c in todo))
    failed = [r for r in results if r[1].startswith("FAILED")]
    print(f"\nDone: {len(results) - len(failed)} ok, {len(failed)} failed")


if __name__ == "__main__":
    asyncio.run(main())
