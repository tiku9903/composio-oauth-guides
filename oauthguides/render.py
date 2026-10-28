"""Presentation helpers shared by the web UI and exports (markdown)."""
from __future__ import annotations

import math

from .schema import Guide

PHASE_LABELS = {
    "prepare": "Prepare", "register": "Register the app", "configure": "Configure",
    "test": "Test", "review": "Review & approval", "launch": "Launch",
}
OWNER_LABELS = {"agent": "Agent can do this", "you": "You do this", "you_with_agent": "You, with agent prep"}
EVIDENCE_LABELS = {
    "tested": "Tested live",
    "sourced": "From official source",
    "inferred": "Inferred",
    "uncertain": "Uncertain",
}
EVIDENCE_HELP = {
    "tested": "An agent probe observed this directly.",
    "sourced": "A cited source states this.",
    "inferred": "Reasoned from sources or comparable providers; not stated directly.",
    "uncertain": "Anecdotal, conflicting or not found. Confirm with the provider.",
}

def _num(x: float) -> str:
    return f"{x:.0f}" if x >= 10 or float(x).is_integer() else f"{x:.1f}".rstrip("0").rstrip(".")


def short_effort(g: Guide) -> str:
    lo, hi = g.time.active_hours_low, g.time.active_hours_high
    if hi < 1:
        return f"{round(lo * 60)}–{round(hi * 60)} min"
    if lo < 1:
        return f"{round(lo * 60)} min–{_num(hi)} h"
    return f"{_num(lo)}–{_num(hi)} h"


def short_wait(g: Guide) -> str:
    lo, hi = g.time.wait_days_low, g.time.wait_days_high
    if not hi:
        return "no approval wait"
    unit, div = ("wk", 7) if hi >= 14 else ("days", 1)
    lo_s, hi_s = _num(round(lo / div)), _num(round(hi / div))
    return f"up to {hi_s} {unit}" if not lo else f"{lo_s}–{hi_s} {unit}"


# Path bar: one log-ish scale from 10 minutes to 120 days so hours and weeks share a ruler.
_MIN_H, _MAX_H = 1 / 6, 120 * 24


def _pos(hours: float) -> float:
    hours = min(max(hours, _MIN_H), _MAX_H)
    return 100 * (math.log10(hours) - math.log10(_MIN_H)) / (math.log10(_MAX_H) - math.log10(_MIN_H))


def path_bar(g: Guide) -> dict:
    """Geometry for the effort→wait bar. Positions are % of width on a log time axis."""
    t = g.time
    active_hi = max(t.active_hours_high, t.active_hours_low, _MIN_H)
    wait_lo_h = active_hi + t.wait_days_low * 24
    wait_hi_h = active_hi + t.wait_days_high * 24
    return {
        "active_end": round(_pos(active_hi), 2),
        "wait_lo": round(_pos(wait_lo_h), 2) if t.wait_days_high else None,
        "wait_hi": round(_pos(wait_hi_h), 2) if t.wait_days_high else None,
        "ticks": [
            {"label": "10 min", "pos": round(_pos(1 / 6), 2)},
            {"label": "1 hr", "pos": round(_pos(1), 2)},
            {"label": "1 day", "pos": round(_pos(24), 2)},
            {"label": "1 wk", "pos": round(_pos(24 * 7), 2)},
            {"label": "1 mo", "pos": round(_pos(24 * 30), 2)},
            {"label": "4 mo", "pos": 100.0},
        ],
    }


def to_markdown(g: Guide, base_url: str = "") -> str:
    smap = g.source_map()

    def cite(ids: list[str]) -> str:
        return " ".join(f"[{i}]" for i in ids if i in smap)

    L: list[str] = []
    L.append(f"# Getting a {g.app_name} OAuth app ready\n")
    L.append(f"> {g.tagline}\n")
    L.append(f"**Difficulty:** Tier {g.tier} — {g.tier_label}. {g.tier_reason}  ")
    L.append(f"**Hands-on effort:** {g.time.active_effort} · **Wait for approval:** {g.time.wait}  ")
    L.append(f"**In one line:** {g.time.summary} _({EVIDENCE_LABELS[g.time.evidence]})_  ")
    L.append(f"**Composio-managed OAuth app:** {g.composio.managed_oauth}" + (f" — {g.composio.note}" if g.composio.note else ""))
    if base_url:
        L.append(f"\nLive guide: {base_url}/guides/{g.slug}")
    L.append(f"\n## Start here\n\n{g.start_here}\n")
    L.append("## Steps\n")
    for n, s in enumerate(g.steps, 1):
        meta = [OWNER_LABELS[s.owner]] + [x for x in (s.effort, f"wait {s.wait}" if s.wait else None) if x]
        L.append(f"### {n}. {s.title}  \n_{PHASE_LABELS[s.phase]} · {' · '.join(meta)} · {EVIDENCE_LABELS[s.evidence]} {cite(s.source_ids)}_\n")
        L.append(s.detail.strip() + "\n")
        if s.agent_help:
            L.append(f"*Agent help:* {s.agent_help}\n")
    if g.requirements:
        L.append("## Requirements and nuances\n")
        for r in g.requirements:
            L.append(f"- **{r.title}** ({r.severity}; {EVIDENCE_LABELS[r.evidence]} {cite(r.source_ids)}): {r.detail}")
        L.append("")
    if g.blockers:
        L.append("## If you get blocked\n")
        for b in g.blockers:
            L.append(f"- **{b.title}** — {b.symptom} → {b.what_to_do} {cite(b.source_ids)}")
        L.append("")
    L.append("## Who does what\n")
    L.append("**An agent can:**\n" + "\n".join(f"- {x}" for x in g.agent_can))
    L.append("\n**You must:**\n" + "\n".join(f"- {x}" for x in g.you_must) + "\n")
    if g.ready_to_paste:
        L.append("## Ready to paste\n")
        for r in g.ready_to_paste:
            L.append(f"**{r.label}**" + (f" — {r.note}" if r.note else "") + f"\n\n```\n{r.value}\n```\n")
    if g.open_questions:
        L.append("## Open questions\n" + "\n".join(f"- {q}" for q in g.open_questions) + "\n")
    if g.probes:
        L.append("## What the agent tested\n")
        for p in g.probes:
            L.append(f"- **{p.name}** ({p.target}): {p.observed} → {p.conclusion}")
        L.append("")
    v = g.verification
    L.append("## Verification\n")
    L.append(f"Status: {v.status.replace('_', ' ')}" + (f" on {v.checked_on}" if v.checked_on else "") + (f". {v.method}" if v.method else ""))
    for c in v.corrections:
        L.append(f"- Corrected **{c.claim}**: was “{c.was}”, now “{c.now}” {cite(c.source_ids)}")
    if v.unverified:
        L.append("\nNot verified:\n" + "\n".join(f"- {u}" for u in v.unverified))
    L.append("\n## Sources\n")
    for s in g.sources:
        L.append(f"- [{s.id}] [{s.title}]({s.url}) — {s.kind.replace('_', ' ')}" + (f", accessed {s.accessed}" if s.accessed else ""))
    L.append(f"\n_Generated {g.generated_at} · {g.method.replace('_', ' ')}_\n")
    return "\n".join(L)
