"""Web app, store, rendering and probe-interpretation tests (no network, no API keys)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app, store
from oauthguides.config import settings
from oauthguides.render import path_bar, to_markdown
from oauthguides.schema import Guide
from oauthguides.store import slugify
from oauthguides.tools.probes import _interpret_authorize

client = TestClient(app)


def curated() -> list[Guide]:
    return [Guide(**json.loads(p.read_text())) for p in sorted(settings.curated_dir.glob("*.json"))]


def test_curated_guides_valid_and_varied():
    gs = curated()
    assert len(gs) >= 6
    assert len({g.tier for g in gs}) >= 3, "library should demonstrate varied difficulty"
    for g in gs:
        assert g.dangling_source_ids() == [], g.slug
        assert g.steps and g.start_here and g.sources
        assert all(s.evidence != "tested" or any(p.ok is not None for p in g.probes) or s.source_ids for s in g.steps)


def test_catalog_has_100_unique_apps():
    cat = json.loads(settings.catalog_path.read_text())
    assert len(cat) == 100 and len({c["slug"] for c in cat}) == 100


def test_library_and_guide_pages_render():
    r = client.get("/")
    assert r.status_code == 200 and "Ready guides" in r.text
    for g in curated():
        r = client.get(f"/guides/{g.slug}")
        assert r.status_code == 200, g.slug
        assert g.app_name in r.text and "Sources" in r.text


def test_tier_filter():
    r = client.get("/?tier=3")
    assert r.status_code == 200
    names_t3 = {g.app_name for g in curated() if g.tier == 3}
    others = {g.app_name for g in curated() if g.tier != 3}
    assert all(f'<div class="name">{n}</div>' in r.text for n in names_t3)
    assert not any(f'<div class="name">{n}</div>' in r.text for n in others)


def test_markdown_and_json_exports():
    r = client.get("/guides/gmail.md")
    assert r.status_code == 200 and r.text.startswith("# Getting a Gmail OAuth app ready")
    assert "## Sources" in r.text
    r = client.get("/api/guides/gmail")
    assert r.status_code == 200 and r.json()["slug"] == "gmail"


def test_lookup_routes_known_and_unknown():
    r = client.get("/lookup", params={"q": "https://slack.com"}, follow_redirects=False)
    assert r.headers["location"] == "/guides/slack"
    r = client.get("/lookup", params={"q": "Some Unknown App"}, follow_redirects=False)
    assert r.headers["location"].startswith("/generate?q=Some%20Unknown%20App")


def test_unknown_guide_redirects_to_generate():
    r = client.get("/guides/doesnotexist", follow_redirects=False)
    assert r.status_code == 303 and "/generate" in r.headers["location"]


def test_slugify():
    assert slugify("https://www.Notion.so/") == "notion"
    assert slugify("Google Calendar") == "google_calendar"
    assert slugify("cal.com") == "cal"


def test_path_bar_monotonic():
    g = store.get("gmail")
    b = path_bar(g)
    assert 0 < b["active_end"] <= (b["wait_lo"] or 100) <= (b["wait_hi"] or 100) <= 100


def test_markdown_cites_only_known_sources():
    for g in curated():
        md = to_markdown(g)
        ids = {s.id for s in g.sources}
        import re
        for m in re.findall(r"\[(S\d+|P\d+)\]", md):
            assert m in ids, (g.slug, m)


def test_authorize_interpretation():
    assert _interpret_authorize(400, "https://x/authorize", "Error: invalid_client", None)[1] is True
    assert _interpret_authorize(302, "https://x", "", "https://cb?error=unauthorized_client")[1] is True
    assert _interpret_authorize(404, "https://x/authorize", "", None)[1] is False


def test_provider_hosted_forums_are_community():
    from oauthguides.tools.search import classify_url
    doms = ["vercel.com"]
    assert classify_url("https://vercel.com/docs/integrations/oauth", doms) == "official_docs"
    assert classify_url("https://community.vercel.com/t/how-to-create-oauth/123", doms) == "community"
    assert classify_url("https://vercel.com/community/discussions/1", doms) == "community"
    assert classify_url("https://vercel.com/legal/terms", doms) == "official_policy"
