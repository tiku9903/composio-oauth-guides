"""Web app: library, shareable guide pages, live generation with streamed agent progress."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

import markdown as md
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sse_starlette.sse import EventSourceResponse

from oauthguides import render
from oauthguides.config import COMPOSIO_REDIRECT_URI, settings
from oauthguides.schema import TIER_BLURBS, TIER_LABELS
from oauthguides.store import GuideStore

from .jobs import JobManager

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

HERE = Path(__file__).parent
app = FastAPI(title="OAuth App Readiness Guides")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
store = GuideStore()


async def _runner(query, on_event):
    from oauthguides.agent.graph import run  # imported lazily: heavy deps

    return await run(query, on_event=on_event)


jobs = JobManager(_runner)


_INLINE_BULLET = re.compile(r"(?<=[:.;)])\s+-\s+(?=[*`A-Za-z0-9])")


def _md(text: str) -> Markup:
    text = text or ""
    if "\n- " not in text and " - " in text:
        # Writers sometimes inline lists ("needs: - a homepage; - a policy"); render them as real lists.
        text = _INLINE_BULLET.sub("\n\n- ", text)
    return Markup(md.markdown(text, extensions=["fenced_code", "sane_lists"]))


templates.env.filters["md"] = _md


def _mdi(text: str) -> Markup:
    """Inline markdown (code, bold, links) without wrapping paragraphs."""
    html = md.markdown(text or "")
    return Markup(re.sub(r"^<p>|</p>$", "", html.strip()))


templates.env.filters["mdi"] = _mdi
templates.env.globals.update(
    TIER_LABELS=TIER_LABELS, TIER_BLURBS=TIER_BLURBS, EVIDENCE_LABELS=render.EVIDENCE_LABELS,
    EVIDENCE_HELP=render.EVIDENCE_HELP, OWNER_LABELS=render.OWNER_LABELS, PHASE_LABELS=render.PHASE_LABELS,
    path_bar=render.path_bar, short_effort=render.short_effort, short_wait=render.short_wait, TIER_STAMPS=render.TIER_STAMPS, TIER_PLAIN=render.TIER_PLAIN, mrz=render.mrz, REDIRECT_URI=COMPOSIO_REDIRECT_URI,
)


def _catalog() -> list[dict]:
    try:
        return json.loads(settings.catalog_path.read_text())
    except FileNotFoundError:
        return []


# ------------------------------------------------------------------ pages

@app.get("/", response_class=HTMLResponse)
async def library(request: Request, tier: int | None = None):
    store.reload()
    guides = store.all()
    have = {g.slug for g in guides}
    shown = [g for g in guides if tier is None or g.tier == tier]
    pending = [c for c in _catalog() if c["slug"] not in have and not store.find(c["name"])]
    tier_counts = {t: sum(1 for g in guides if g.tier == t) for t in range(1, 5)}
    return templates.TemplateResponse(request, "library.html", {
        "guides": shown, "all_count": len(guides), "tier": tier, "pending": pending, "tier_counts": tier_counts,
        "catalog_total": len(_catalog()), "llm_ready": settings.llm_configured,
    })


@app.get("/lookup")
async def lookup(q: str = "", refresh: bool = False):
    """Search box target: existing guide → open it; otherwise start live generation."""
    q = q.strip()
    if not q:
        return RedirectResponse("/", 303)
    if not refresh and (g := store.find(q)) and store.is_fresh(g):
        return RedirectResponse(f"/guides/{g.slug}", 303)
    return RedirectResponse(f"/generate?q={quote(q)}", 303)


@app.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request, q: str = ""):
    return templates.TemplateResponse(request, "generate.html", {
        "q": q.strip(), "llm_ready": settings.llm_configured, "model": settings.model,
        "search_backend": "Tavily" if settings.tavily_key else "DuckDuckGo",
    })


@app.get("/guides/{slug}.md", response_class=PlainTextResponse)
async def guide_markdown(request: Request, slug: str):
    g = store.get(slug) or (store.reload() or store.get(slug))
    if not g:
        raise HTTPException(404, "No guide for that app yet")
    base = str(request.base_url).rstrip("/")
    return PlainTextResponse(render.to_markdown(g, base), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'inline; filename="{slug}-oauth-guide.md"'})


@app.get("/guides/{slug}", response_class=HTMLResponse)
async def guide_page(request: Request, slug: str):
    store.reload()
    g = store.get(slug)
    if not g:
        return RedirectResponse(f"/generate?q={quote(slug)}", 303)
    return templates.TemplateResponse(request, "guide.html", {
        "g": g, "src": g.source_map(), "bar": render.path_bar(g), "counts": g.evidence_counts(),
        "share_url": str(request.url_for("guide_page", slug=g.slug)),
    })


@app.get("/method", response_class=HTMLResponse)
async def method_page(request: Request):
    return templates.TemplateResponse(request, "method.html", {})


# ------------------------------------------------------------------ API

@app.get("/api/guides")
async def api_guides():
    store.reload()
    return [{"slug": g.slug, "app_name": g.app_name, "tier": g.tier, "tier_label": g.tier_label,
             "tagline": g.tagline, "effort": g.time.active_effort, "wait": g.time.wait,
             "composio_managed": g.composio.managed_oauth, "method": g.method,
             "verification": g.verification.status, "generated_at": g.generated_at} for g in store.all()]


@app.get("/api/guides/{slug}")
async def api_guide(slug: str):
    g = store.get(slug) or (store.reload() or store.get(slug))
    if not g:
        raise HTTPException(404, "No guide for that app yet")
    return JSONResponse(json.loads(g.model_dump_json()))


@app.post("/api/generate")
async def api_generate(q: str = Form(...)):
    if not settings.llm_configured:
        raise HTTPException(503, f"Live generation needs an API key for {settings.model.split(':')[0]}. See README → Setup.")
    q = q.strip()[:120]
    if len(q) < 2:
        raise HTTPException(400, "Enter an app name or website")
    job = jobs.start(q)
    return jobs.summary(job)


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return jobs.summary(job)


@app.get("/api/jobs/{job_id}/events")
async def api_job_events(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")

    async def gen():
        async for ev in job.follow():
            yield {"event": "progress", "data": json.dumps(ev)}
        yield {"event": "end", "data": json.dumps(jobs.summary(job))}

    return EventSourceResponse(gen(), ping=15)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "guides": len(store.all()), "llm_configured": settings.llm_configured, "model": settings.model}

