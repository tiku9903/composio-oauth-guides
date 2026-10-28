"""The investigation agent, as a LangGraph state machine.

    resolve ──► research ──┬──► extract ────┐
                           └──► early_probes ┴──► authorize_probe ──► synthesize ──► verify ──► finalize

* resolve        identify the provider, official domains, console URL and search plan
* research       targeted web searches, rank official docs first, fetch pages
* extract        per-page fact extraction (parallel, fast model) with supporting phrases
* early_probes   OIDC discovery, console login wall, Composio toolkit check (runs alongside extract)
* authorize_probe  hit the real authorize endpoint with a fake client_id (needs extracted endpoints)
* synthesize     write the guide from facts + probes only, with evidence levels and citations
* verify         an LLM critic + deterministic guards downgrade anything overclaimed
* finalize       attach sources/probes/verification, persist, return

Every node emits progress events through LangGraph's custom stream so the UI can show the
investigation live.
"""
from __future__ import annotations

import asyncio
import json
import operator
import re
from collections import Counter
from datetime import date
from typing import Annotated, Any, Optional, TypedDict
from urllib.parse import urlparse

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from ..config import COMPOSIO_REDIRECT_URI, settings
from ..llm import structured
from ..schema import Correction, Guide, Probe, Source, Verification
from ..store import GuideStore, slugify
from ..tools.fetch import fetch_many
from ..tools.probes import probe_authorize, probe_composio, probe_console, probe_oidc_discovery
from ..tools.search import SearchHit, classify_url, rank_hits, search, search_many
from . import prompts
from .models import AppIdentity, Critique, GuideDraft, PageExtraction


class AgentState(TypedDict, total=False):
    query: str
    identity: dict
    pages: list[dict]
    extractions: dict[str, dict]
    probes: Annotated[list[dict], operator.add]
    discovery: Optional[dict]
    draft: dict
    critique: dict
    guide: dict
    warnings: Annotated[list[str], operator.add]


# ---------------------------------------------------------------- helpers

def emit(kind: str, message: str, **data: Any) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return
    writer({"kind": kind, "message": message, **data})


def _ctx(app: str) -> str:
    return prompts.CONTEXT.format(app=app, redirect=COMPOSIO_REDIRECT_URI, today=date.today().isoformat())


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host or None


def _root_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _probe_sources(probes: list[dict]) -> list[Source]:
    out = []
    for i, p in enumerate(probes, 1):
        target = p["target"] if p["target"].startswith("http") else f"https://{p['target'].split(',')[0].strip()}"
        out.append(Source(id=f"P{i}", title=f"Live probe: {p['name']}", url=target, kind="probe",
                          accessed=(p.get("at") or "")[:10] or None, note=p["conclusion"]))
    return out


def _fmt_probes(probes: list[dict]) -> str:
    if not probes:
        return "(none)"
    return "\n".join(
        f"P{i}: {p['name']} | target={p['target']} | method={p['method']} | observed={p['observed']} | "
        f"conclusion={p['conclusion']} | ok={p['ok']}"
        for i, p in enumerate(probes, 1)
    )


def _fmt_sources(pages: list[dict]) -> str:
    return "\n".join(f"{p['sid']}: [{p['kind']}] {p['title'] or p['url']} — {p['url']}" for p in pages) or "(none)"


def _fmt_facts(pages: list[dict], extractions: dict[str, dict]) -> str:
    lines = []
    for p in pages:
        ex = extractions.get(p["sid"])
        if not ex or not ex.get("relevant") or not ex.get("facts"):
            continue
        lines.append(f"## {p['sid']} ({p['kind']}) {p['url']}")
        for f in ex["facts"]:
            lines.append(f"- [{f['topic']}|{f['confidence']}] {f['statement']}  (supports: “{f['support']}”)")
    return "\n".join(lines) or "(no facts extracted)"


# ---------------------------------------------------------------- nodes

async def resolve(state: AgentState) -> dict:
    q = state["query"].strip()
    emit("stage", f"Identifying “{q}”", stage="resolve")
    hits = await search(f"{q} developer OAuth app client ID", n=6)
    hits_txt = "\n".join(f"- {h.title} — {h.url} — {h.snippet[:200]}" for h in hits) or "(search unavailable)"
    ident: AppIdentity = await structured(AppIdentity, "fast").ainvoke(
        prompts.RESOLVE.format(context=_ctx(q), query=q, hits=hits_txt)
    )
    ident.slug = slugify(ident.slug or ident.app_name)
    doms = {d.lower().removeprefix("www.") for d in ident.official_domains if d}
    if (w := _domain(ident.website)):
        doms.add(_root_domain(w))
    ident.official_domains = sorted(doms)
    emit("found", f"{ident.app_name} · {', '.join(ident.official_domains) or 'domain unknown'}",
         stage="resolve", identity=ident.model_dump())
    if ident.supports_oauth == "no":
        emit("warn", "Provider may not offer third-party OAuth; the guide will explain the alternative.", stage="resolve")
    return {"identity": ident.model_dump()}


async def research(state: AgentState) -> dict:
    ident = AppIdentity(**state["identity"])
    name = ident.app_name
    queries = list(dict.fromkeys([
        *ident.search_queries[:8],
        f"{name} OAuth create app client id redirect URI",
        f"{name} OAuth scopes list",
        f"{name} app review OR verification OR marketplace approval OAuth",
        f"{name} API partner program access requirements",
        f"{name} OAuth app approval how long took",
    ]))
    emit("stage", f"Searching {len(queries)} angles: registration, scopes, review, partner access, timelines", stage="research")
    hits = await search_many(queries)
    ranked = rank_hits(hits, ident.official_domains)
    chosen, per_host = [], Counter()
    for h in ranked:
        if per_host[h.host] >= 3:
            continue
        chosen.append(h)
        per_host[h.host] += 1
        if len(chosen) >= settings.max_pages:
            break
    composio_url = f"https://docs.composio.dev/toolkits/{ident.slug.replace('_', '-')}"
    if composio_url not in {h.url for h in chosen}:
        chosen.append(SearchHit(f"Composio toolkit: {name}", composio_url, "", "composio"))
    emit("stage", f"Reading {len(chosen)} pages ({sum(1 for h in chosen if classify_url(h.url, ident.official_domains).startswith('official'))} official)",
         stage="research", urls=[h.url for h in chosen])
    pages_raw = await fetch_many([h.url for h in chosen])
    pages, warnings = [], []
    for h, pg in zip(chosen, pages_raw):
        if pg.error or pg.status >= 400 or len(pg.text) < 200:
            warnings.append(f"Could not read {h.url} ({pg.error or pg.status})")
            continue
        sid = f"S{len(pages) + 1}"
        pages.append({"sid": sid, "url": pg.final_url or h.url, "title": pg.title or h.title,
                      "kind": classify_url(pg.final_url or h.url, ident.official_domains), "text": pg.text})
    emit("stage", f"Read {len(pages)} pages; {len(warnings)} unreadable", stage="research",
         sources=[{k: p[k] for k in ("sid", "url", "title", "kind")} for p in pages])
    return {"pages": pages, "warnings": warnings}


async def extract(state: AgentState) -> dict:
    ident = AppIdentity(**state["identity"])
    pages = state.get("pages", [])
    runner = structured(PageExtraction, "fast")
    sem = asyncio.Semaphore(5)

    async def one(p: dict) -> tuple[str, dict]:
        async with sem:
            try:
                ex: PageExtraction = await runner.ainvoke(prompts.EXTRACT.format(
                    context=_ctx(ident.app_name), sid=p["sid"], url=p["url"], kind=p["kind"],
                    app=ident.app_name, text=p["text"]))
            except Exception as e:
                emit("warn", f"{p['sid']}: extraction failed ({type(e).__name__})", stage="extract")
                return p["sid"], PageExtraction(relevant=False).model_dump()
            emit("read", f"{p['sid']} {p['title'][:70] or p['url']}: {len(ex.facts)} facts", stage="extract",
                 sid=p["sid"], facts=len(ex.facts))
            return p["sid"], ex.model_dump()

    emit("stage", f"Extracting facts from {len(pages)} pages", stage="extract")
    results = await asyncio.gather(*(one(p) for p in pages))
    return {"extractions": dict(results)}


async def early_probes(state: AgentState) -> dict:
    ident = AppIdentity(**state["identity"])
    emit("stage", "Probing the provider live (discovery metadata, console, Composio toolkit)", stage="probe")
    jobs = [probe_oidc_discovery(ident.official_domains[:3] or [ident.slug + ".com"])]
    if ident.developer_console_url:
        jobs.append(probe_console(ident.developer_console_url))
    jobs.append(probe_composio(ident.slug))
    res = await asyncio.gather(*jobs)
    disc_probe, meta = res[0]
    probes: list[Probe] = [disc_probe, *res[1:]]
    for p in probes:
        emit("probe", f"{p.name}: {p.conclusion}", stage="probe", probe=p.model_dump())
    return {"probes": [p.model_dump() for p in probes], "discovery": meta}


async def authorize_probe(state: AgentState) -> dict:
    exs = state.get("extractions", {}).values()
    meta = state.get("discovery") or {}
    candidates = Counter(e["authorize_url"] for e in exs if e.get("authorize_url", "") and str(e.get("authorize_url", "")).startswith("https://"))
    auth_url = meta.get("authorization_endpoint") or (candidates.most_common(1)[0][0] if candidates else None)
    if auth_url and "{" in auth_url:  # templated per-tenant URL like https://{instance}.salesforce.com
        emit("warn", f"Authorize URL is per-tenant ({auth_url}); skipping live probe.", stage="probe")
        return {"warnings": [f"Authorize URL is tenant-specific: {auth_url}"]}
    if not auth_url:
        emit("warn", "No authorize endpoint found to probe.", stage="probe")
        return {"warnings": ["No authorize endpoint found to probe"]}
    scopes = [s for e in exs for s in e.get("scopes", [])][:3]
    p = await probe_authorize(auth_url.split("?")[0], scopes)
    emit("probe", f"{p.name}: {p.conclusion}", stage="probe", probe=p.model_dump())
    return {"probes": [p.model_dump()]}


async def synthesize(state: AgentState) -> dict:
    ident = AppIdentity(**state["identity"])
    pages, exs, probes = state.get("pages", []), state.get("extractions", {}), state.get("probes", [])
    composio = next((p for p in probes if p["name"].startswith("Composio")), None)
    emit("stage", "Writing the guide from evidence", stage="synthesize")
    draft: GuideDraft = await structured(GuideDraft, "main").ainvoke(prompts.SYNTHESIZE.format(
        context=_ctx(ident.app_name), redirect=COMPOSIO_REDIRECT_URI,
        identity=ident.model_dump_json(exclude={"search_queries"}),
        composio=json.dumps(composio) if composio else "not checked",
        probes=_fmt_probes(probes), sources=_fmt_sources(pages), facts=_fmt_facts(pages, exs)))
    emit("draft", f"Draft: tier {draft.tier}, {len(draft.steps)} steps, {len(draft.requirements)} requirements",
         stage="synthesize", tier=draft.tier)
    return {"draft": draft.model_dump()}


_ITEM = re.compile(r"^(steps|requirements|blockers)\[(\d+)\]$")


def apply_guards(draft: dict, source_kinds: dict[str, str]) -> tuple[dict, list[str]]:
    """Deterministic evidence rules. Returns (draft, notes). Pure function; unit-tested."""
    notes: list[str] = []
    known = set(source_kinds)
    for section in ("steps", "requirements", "blockers"):
        for i, item in enumerate(draft.get(section, [])):
            ids = [s for s in item.get("source_ids", []) if s in known]
            dropped = set(item.get("source_ids", [])) - set(ids)
            if dropped:
                notes.append(f"{section}[{i}]: removed unknown source ids {sorted(dropped)}")
            item["source_ids"] = ids
            ev = item.get("evidence", "uncertain")
            kinds = {source_kinds[s] for s in ids}
            if ev == "tested" and "probe" not in kinds:
                item["evidence"] = "inferred"
                item["evidence_note"] = (item.get("evidence_note") or "") + " Downgraded: no live probe backs this."
                notes.append(f"{section}[{i}]: tested→inferred (no probe)")
            elif ev == "sourced" and not ids:
                item["evidence"] = "inferred"
                item["evidence_note"] = (item.get("evidence_note") or "") + " Downgraded: no source cited."
                notes.append(f"{section}[{i}]: sourced→inferred (no citation)")
            elif ev == "sourced" and kinds and kinds <= {"community", "other"}:
                item["evidence"] = "uncertain"
                item["evidence_note"] = (item.get("evidence_note") or "") + " Only non-official sources support this."
                notes.append(f"{section}[{i}]: sourced→uncertain (non-official sources only)")
    for key in ("time", "composio"):
        if key in draft:
            draft[key]["source_ids"] = [s for s in draft[key].get("source_ids", []) if s in known]
    return draft, notes


async def verify(state: AgentState) -> dict:
    ident = AppIdentity(**state["identity"])
    pages, exs, probes = state.get("pages", []), state.get("extractions", {}), state.get("probes", [])
    draft = state["draft"]
    kinds = {p["sid"]: p["kind"] for p in pages} | {f"P{i}": "probe" for i in range(1, len(probes) + 1)}
    emit("stage", "Verifying every claim against its sources", stage="verify")
    try:
        crit: Critique = await structured(Critique, "main").ainvoke(prompts.CRITIQUE.format(
            context=_ctx(ident.app_name), draft=json.dumps(draft)[:60000], probes=_fmt_probes(probes),
            facts=_fmt_facts(pages, exs)))
    except Exception as e:
        emit("warn", f"Critic failed ({type(e).__name__}); applying deterministic checks only", stage="verify")
        crit = Critique()
    corrections: list[dict] = []
    for adj in crit.adjustments:
        m = _ITEM.match(adj.item.strip())
        if not m:
            continue
        section, idx = m.group(1), int(m.group(2))
        items = draft.get(section, [])
        if idx >= len(items):
            continue
        it = items[idx]
        before = it.get("evidence")
        it["evidence"] = adj.evidence
        it["evidence_note"] = ((it.get("evidence_note") or "") + f" Verifier: {adj.note}").strip()
        if adj.corrected_text:
            field = "detail" if section != "blockers" else "what_to_do"
            old = it.get(field, "")
            it[field] = f"{old}\n\n**Correction (verifier):** {adj.corrected_text}"
            corrections.append(Correction(claim=it.get("title", adj.item), was=old[:300], now=adj.corrected_text).model_dump())
        if before != adj.evidence:
            emit("adjust", f"{adj.item}: {before} → {adj.evidence} — {adj.note[:120]}", stage="verify")
    if not crit.tier_ok and crit.suggested_tier:
        emit("adjust", f"Tier {draft['tier']} → {crit.suggested_tier}: {crit.tier_note or ''}", stage="verify")
        corrections.append(Correction(claim="Difficulty tier", was=str(draft["tier"]), now=str(crit.suggested_tier)).model_dump())
        draft["tier"] = crit.suggested_tier
        draft["tier_reason"] += f" (Adjusted by verifier: {crit.tier_note})"
    if not crit.time_ok and crit.time_note:
        draft["time"]["summary"] += f" Verifier note: {crit.time_note}"
        draft["time"]["evidence"] = "uncertain"
    draft, guard_notes = apply_guards(draft, kinds)
    for n in guard_notes:
        emit("adjust", n, stage="verify")
    draft["open_questions"] = list(dict.fromkeys([*draft.get("open_questions", []), *crit.extra_open_questions]))
    return {"draft": draft, "critique": {**crit.model_dump(), "corrections": corrections, "guard_notes": guard_notes}}


async def finalize(state: AgentState) -> dict:
    ident = AppIdentity(**state["identity"])
    pages, probes, draft = state.get("pages", []), state.get("probes", []), state["draft"]
    crit = state.get("critique", {})
    today = date.today().isoformat()
    sources = [Source(id=p["sid"], title=p["title"] or p["url"], url=p["url"], kind=p["kind"], accessed=today) for p in pages]
    sources += _probe_sources(probes)
    unverified = list(dict.fromkeys([*crit.get("unverified", []), *state.get("warnings", [])]))
    guide = Guide(
        slug=ident.slug, app_name=ident.app_name, website=ident.website,
        **{k: v for k, v in draft.items() if k in GuideDraft.model_fields},
        sources=sources, probes=[Probe(**p) for p in probes],
        verification=Verification(
            status="agent_generated", checked_on=today,
            method=("LLM verifier re-checked each claim against extracted facts and probes; deterministic guards "
                    "removed unknown citations and downgraded unsupported 'tested'/'sourced' claims."),
            corrections=[Correction(**c) for c in crit.get("corrections", [])],
            unverified=unverified),
        method="live_agent", model=settings.model,
    )
    GuideStore().save_generated(guide)
    emit("done", f"Guide ready: {guide.app_name} — tier {guide.tier} ({guide.tier_label})", stage="done", slug=guide.slug)
    return {"guide": guide.model_dump()}


# ---------------------------------------------------------------- graph

def build_graph():
    g = StateGraph(AgentState)
    for name, fn in [("resolve", resolve), ("research", research), ("extract", extract),
                     ("early_probes", early_probes), ("authorize_probe", authorize_probe),
                     ("synthesize", synthesize), ("verify", verify), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "resolve")
    g.add_edge("resolve", "research")
    g.add_edge("research", "extract")
    g.add_edge("research", "early_probes")
    g.add_edge(["extract", "early_probes"], "authorize_probe")
    g.add_edge("authorize_probe", "synthesize")
    g.add_edge("synthesize", "verify")
    g.add_edge("verify", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


graph = build_graph()


async def run(query: str, on_event=None) -> Guide:
    """Run the agent, forwarding progress events to `on_event(dict)`. Returns the final Guide."""
    final: dict = {}
    async for mode, chunk in graph.astream({"query": query}, stream_mode=["custom", "values"]):
        if mode == "custom" and on_event:
            res = on_event(chunk)
            if asyncio.iscoroutine(res):
                await res
        elif mode == "values":
            final = chunk
    return Guide(**final["guide"])
