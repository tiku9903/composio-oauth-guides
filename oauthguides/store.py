"""Guide storage: curated guides ship in the repo; live-generated guides are written to disk.

Generated guides override nothing curated unless explicitly regenerated. JSON files keep the
whole system inspectable and diff-able in git, which matters for a library meant to be reviewed.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import settings
from .schema import Guide


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("/")[0] if "." in text.split("/")[0] else text
    text = re.sub(r"\.(com|io|dev|app|co|ai|net|org|so)$", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "app"


def _load_dir(d: Path) -> dict[str, Guide]:
    out: dict[str, Guide] = {}
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            g = Guide(**json.loads(p.read_text()))
            out[g.slug] = g
        except Exception as e:  # a broken file should not take the site down
            print(f"[store] skipping {p.name}: {e}")
    return out


class GuideStore:
    def __init__(self, curated_dir: Path | None = None, generated_dir: Path | None = None):
        self.curated_dir = curated_dir or settings.curated_dir
        self.generated_dir = generated_dir or settings.generated_dir
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.reload()

    def reload(self) -> None:
        self.curated = _load_dir(self.curated_dir)
        self.generated = _load_dir(self.generated_dir)

    def all(self) -> list[Guide]:
        merged = {**self.generated, **self.curated}  # curated wins on slug clash
        return sorted(merged.values(), key=lambda g: (g.method != "curated", g.tier, g.app_name.lower()))

    def get(self, slug: str) -> Optional[Guide]:
        slug = slug.lower()
        return self.curated.get(slug) or self.generated.get(slug)

    def find(self, query: str) -> Optional[Guide]:
        """Match a free-text query (name, slug or website) to an existing guide."""
        q = slugify(query)
        if g := self.get(q):
            return g
        for g in self.all():
            names = {slugify(g.app_name), g.slug, slugify(g.website or "")}
            if q in names or q.replace("_", "") in {n.replace("_", "") for n in names}:
                return g
        return None

    def is_fresh(self, g: Guide) -> bool:
        if g.method == "curated":
            return True
        try:
            ts = datetime.strptime(g.generated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        return datetime.now(timezone.utc) - ts < timedelta(days=settings.cache_days)

    def save_generated(self, g: Guide) -> Path:
        path = self.generated_dir / f"{g.slug}.json"
        path.write_text(g.model_dump_json(indent=2))
        self.generated[g.slug] = g
        return path
