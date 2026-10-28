"""The Guide schema: one shape shared by curated guides, the live agent and the UI.

Design rule: every factual statement a developer might act on carries an
evidence level and points at sources, so the UI can show *how we know* next to
*what we claim*.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

EvidenceLevel = Literal["tested", "sourced", "inferred", "uncertain"]
"""
tested    - an agent (or the author) actually ran a probe / attempted the step and observed the result.
sourced   - stated in a cited source (official docs preferred).
inferred  - reasoned from sources or from how similar providers behave; not stated directly.
uncertain - conflicting, outdated, anecdotal, or not found. Treat as a question to ask the provider.
"""

DifficultyTier = Literal[1, 2, 3, 4]
TIER_LABELS = {
    1: "Self-serve",
    2: "Self-serve + light review",
    3: "Formal review / verification",
    4: "Gated / partner-only",
}
TIER_BLURBS = {
    1: "Create the OAuth app yourself and ship. No approval needed to let any user connect.",
    2: "Credentials are instant, but going public needs a listing, distribution switch or lightweight review (days).",
    3: "A formal app review, verification or security assessment stands between you and production users (weeks).",
    4: "API or OAuth access requires a partner application, contract or paid plan; approval is not guaranteed.",
}

Owner = Literal["agent", "you", "you_with_agent"]
Phase = Literal["prepare", "register", "configure", "test", "review", "launch"]
SourceKind = Literal["official_docs", "official_policy", "composio_docs", "community", "probe", "other"]


class Source(BaseModel):
    id: str = Field(description="Short id like S1, S2 used by claims")
    title: str
    url: str
    kind: SourceKind = "official_docs"
    accessed: Optional[str] = Field(default=None, description="YYYY-MM-DD the source was read")
    note: Optional[str] = None


class Evidence(BaseModel):
    evidence: EvidenceLevel = "uncertain"
    source_ids: list[str] = Field(default_factory=list)
    evidence_note: Optional[str] = Field(default=None, description="Why this level; what would confirm it")


class TimeEstimate(BaseModel):
    active_effort: str = Field(description="Human hands-on work, e.g. '20-40 min'")
    active_hours_low: float
    active_hours_high: float
    wait: str = Field(description="Calendar wait for approval/review, e.g. 'none' or '3-6 weeks'")
    wait_days_low: float = 0
    wait_days_high: float = 0
    summary: str = Field(description="One sentence a developer can repeat to their manager")
    evidence: EvidenceLevel = "inferred"
    source_ids: list[str] = Field(default_factory=list)


class ComposioStatus(BaseModel):
    managed_oauth: Literal["yes", "no", "unknown"] = "unknown"
    toolkit_slug: Optional[str] = None
    note: Optional[str] = None
    evidence: EvidenceLevel = "uncertain"
    source_ids: list[str] = Field(default_factory=list)


class OAuthDetails(BaseModel):
    developer_console_url: Optional[str] = None
    docs_url: Optional[str] = None
    authorize_url: Optional[str] = None
    token_url: Optional[str] = None
    oauth_version: Optional[str] = Field(default=None, description="e.g. OAuth 2.0 authorization code")
    pkce: Optional[str] = None
    refresh_tokens: Optional[str] = Field(default=None, description="Lifetime/rotation notes")
    scopes_note: Optional[str] = None
    example_scopes: list[str] = Field(default_factory=list)
    account_needed: Optional[str] = Field(default=None, description="What account/plan you need to create the app")


class Step(Evidence):
    phase: Phase
    title: str
    owner: Owner
    effort: Optional[str] = None
    wait: Optional[str] = None
    detail: str = Field(description="Markdown: what to do, exact field values, gotchas")
    agent_help: Optional[str] = Field(default=None, description="What an agent can do for this step")
    links: list[str] = Field(default_factory=list)


class Requirement(Evidence):
    title: str
    detail: str
    severity: Literal["blocker", "important", "minor"] = "important"
    applies_when: Optional[str] = None


class Blocker(Evidence):
    title: str
    symptom: str
    what_to_do: str


class Probe(BaseModel):
    name: str
    target: str
    method: str = Field(description="What was attempted, e.g. 'GET authorize URL with dummy client_id'")
    observed: str = Field(description="What actually happened")
    conclusion: str
    ok: Optional[bool] = None
    at: Optional[str] = None


class Correction(BaseModel):
    claim: str
    was: str
    now: str
    source_ids: list[str] = Field(default_factory=list)


class Verification(BaseModel):
    status: Literal["spot_checked", "curated", "agent_generated"] = "agent_generated"
    checked_on: Optional[str] = None
    method: Optional[str] = None
    corrections: list[Correction] = Field(default_factory=list)
    unverified: list[str] = Field(default_factory=list, description="Things we could not confirm")


class ReadyToPaste(BaseModel):
    label: str
    value: str
    note: Optional[str] = None


class Guide(BaseModel):
    slug: str
    app_name: str
    website: Optional[str] = None
    category: Optional[str] = None
    tagline: str = Field(description="One-line verdict, e.g. 'Instant for testing; Gmail scopes need a paid security assessment for production'")
    supports_oauth: Literal["yes", "no", "unclear"] = Field(
        default="yes", description="Whether the provider offers third-party OAuth at all (if 'no', the guide explains the alternative)"
    )
    tier: DifficultyTier
    tier_reason: str
    time: TimeEstimate
    composio: ComposioStatus = Field(default_factory=ComposioStatus)
    oauth: OAuthDetails = Field(default_factory=OAuthDetails)
    start_here: str = Field(description="The single first action a developer should take, in one or two sentences")
    steps: list[Step]
    requirements: list[Requirement] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    agent_can: list[str] = Field(default_factory=list, description="What an agent can do end-to-end for you")
    you_must: list[str] = Field(default_factory=list, description="Hand-offs only a human/owner can do")
    ready_to_paste: list[ReadyToPaste] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list, description="Uncertainties to ask the provider about")
    sources: list[Source] = Field(default_factory=list)
    probes: list[Probe] = Field(default_factory=list)
    verification: Verification = Field(default_factory=Verification)
    method: Literal["curated", "live_agent"] = "live_agent"
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    model: Optional[str] = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return v.strip().lower()

    # ---- derived helpers used by templates & exports ----
    @property
    def tier_label(self) -> str:
        return TIER_LABELS[self.tier]

    @property
    def tier_blurb(self) -> str:
        return TIER_BLURBS[self.tier]

    def source_map(self) -> dict[str, Source]:
        return {s.id: s for s in self.sources}

    def evidence_counts(self) -> dict[str, int]:
        counts = {"tested": 0, "sourced": 0, "inferred": 0, "uncertain": 0}
        items: list[Evidence] = [*self.steps, *self.requirements, *self.blockers]
        for it in items:
            counts[it.evidence] += 1
        counts["tested"] += sum(1 for p in self.probes if p.ok is not None)
        return counts

    def dangling_source_ids(self) -> list[str]:
        known = set(self.source_map())
        refs: set[str] = set(self.time.source_ids) | set(self.composio.source_ids)
        for it in [*self.steps, *self.requirements, *self.blockers]:
            refs |= set(it.source_ids)
        return sorted(refs - known)
