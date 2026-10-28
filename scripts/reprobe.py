"""Re-run live probes for guides (curated by default) and record what was actually observed.

    python scripts/reprobe.py              # all curated guides
    python scripts/reprobe.py gmail slack  # selected guides
    python scripts/reprobe.py --dry-run    # print results, don't write

Probes are read-only: the authorize endpoint is called with a fake client_id and Composio's
redirect URI; the console URL is fetched without a session; discovery metadata is fetched.
Inconclusive probes (ok=null) in the guide are replaced by the new observations; probes that already
succeeded, or that check documentation rather than the provider (e.g. "Composio callback URI in docs"),
are kept as they are.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oauthguides.config import settings  # noqa: E402
from oauthguides.schema import Guide, Probe  # noqa: E402
from oauthguides.tools.probes import probe_authorize, probe_console, probe_oidc_discovery  # noqa: E402


def _clean(url: str | None) -> str | None:
    if not url:
        return None
    url = url.split()[0].strip()
    return url if url.startswith("http") and "{" not in url else None


async def reprobe(g: Guide) -> list[Probe]:
    auth = _clean(g.oauth.authorize_url)
    console = _clean(g.oauth.developer_console_url)
    domains = [urlparse(u).netloc.removeprefix("www.") for u in (auth, g.website) if u and urlparse(u).netloc]
    disc, _ = await probe_oidc_discovery(domains or [g.slug + ".com"])
    out: list[Probe] = [disc]
    if auth:
        out.append(await probe_authorize(auth.split("?")[0], g.oauth.example_scopes[:3] or None))
    if console:
        out.append(await probe_console(console))
    return out


def _kind(name: str) -> str:
    n = name.lower()
    if "authoriz" in n:
        return "authorize"
    if "console" in n or "login wall" in n:
        return "console"
    if "openid" in n or "discovery" in n or "oidc" in n:
        return "discovery"
    return n


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    files = sorted(settings.curated_dir.glob("*.json"))
    if args.slugs:
        files = [f for f in files if f.stem in args.slugs]
    for f in files:
        g = Guide(**json.loads(f.read_text()))
        fresh = await reprobe(g)
        print(f"\n== {g.app_name}")
        for p in fresh:
            print(f"  [{ {True: 'ok', False: 'no', None: '??'}[p.ok] }] {p.name}: {p.observed[:150]}")
        if args.dry_run:
            continue
        fresh_by_kind = {_kind(p.name): p for p in fresh if p.ok is not None}
        kept, used = [], set()
        for old in g.probes:
            k = _kind(old.name)
            if old.ok is None and k in fresh_by_kind:
                kept.append(fresh_by_kind[k]); used.add(k)
            else:
                kept.append(old)
        kept += [p for k, p in fresh_by_kind.items() if k not in used and k not in {_kind(o.name) for o in g.probes}]
        g.probes = kept
        f.write_text(json.dumps(json.loads(g.model_dump_json()), indent=2, ensure_ascii=False) + "\n")
        print(f"  wrote {f.name}")


if __name__ == "__main__":
    asyncio.run(main())
