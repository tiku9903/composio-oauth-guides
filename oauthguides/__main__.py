"""Investigate one app from the terminal:  python -m oauthguides "Zendesk"  """
from __future__ import annotations

import asyncio
import sys

from .config import settings


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python -m oauthguides "<app name or website>"')
        raise SystemExit(2)
    if not settings.llm_configured:
        print(f"No API key for {settings.model}. Set GEMINI_API_KEY (free at aistudio.google.com) or MODEL + that provider's key.")
        raise SystemExit(1)
    from .agent.graph import run

    query = " ".join(sys.argv[1:])

    def show(ev: dict) -> None:
        mark = {"stage": "▸", "probe": "◉", "adjust": "↺", "warn": "!", "done": "✓", "error": "✗"}.get(ev["kind"], " ")
        print(f"{mark} {ev['message']}", flush=True)

    guide = asyncio.run(run(query, on_event=show))
    print(f"\nTier {guide.tier} ({guide.tier_label}) · {guide.time.active_effort} hands-on · wait: {guide.time.wait}")
    print(f"Saved to {settings.generated_dir / (guide.slug + '.json')}")


if __name__ == "__main__":
    main()
