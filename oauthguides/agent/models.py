"""Structured outputs for intermediate agent steps."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..schema import (
    Blocker,
    ComposioStatus,
    DifficultyTier,
    EvidenceLevel,
    OAuthDetails,
    ReadyToPaste,
    Requirement,
    Step,
    TimeEstimate,
)


class AppIdentity(BaseModel):
    app_name: str
    slug: str = Field(description="lowercase toolkit-style slug, e.g. google_calendar")
    website: Optional[str] = None
    official_domains: list[str] = Field(default_factory=list)
    category: Optional[str] = None
    developer_console_url: Optional[str] = None
    developer_docs_url: Optional[str] = None
    supports_oauth: Literal["yes", "no", "unclear"] = "unclear"
    notes: Optional[str] = None
    search_queries: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    topic: Literal[
        "registration", "scopes", "review", "verification", "redirect_uri", "tokens",
        "rate_limits", "partner_access", "pricing_or_plan", "timeline", "endpoints",
        "admin_consent", "branding", "lifecycle", "other",
    ]
    statement: str
    support: str = Field(description="Short phrase from the page (<=20 words) supporting the statement")
    confidence: Literal["high", "medium", "low"] = "medium"


class PageExtraction(BaseModel):
    relevant: bool = True
    facts: list[Fact] = Field(default_factory=list)
    authorize_url: Optional[str] = None
    token_url: Optional[str] = None
    console_url: Optional[str] = None
    scopes: list[str] = Field(default_factory=list)


class GuideDraft(BaseModel):
    """What the LLM writes. Identity, sources, probes and verification are attached deterministically."""

    category: Optional[str] = None
    tagline: str
    notice: Optional[str] = Field(default=None, description="Deprecation/shutdown/successor-API warning, with dates, if sources show one")
    supports_oauth: Literal["yes", "no", "unclear"] = "yes"
    tier: DifficultyTier
    tier_reason: str
    time: TimeEstimate
    composio: ComposioStatus
    oauth: OAuthDetails
    start_here: str
    steps: list[Step]
    requirements: list[Requirement] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    agent_can: list[str] = Field(default_factory=list)
    you_must: list[str] = Field(default_factory=list)
    ready_to_paste: list[ReadyToPaste] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Adjustment(BaseModel):
    item: str = Field(description="e.g. steps[2], requirements[0], blockers[1], time")
    evidence: EvidenceLevel
    note: str = Field(description="Why; what is wrong or what would confirm it")
    corrected_text: Optional[str] = Field(default=None, description="If the statement itself is wrong, the corrected statement")
    source_ids: list[str] = Field(default_factory=list, description="The S#/P# ids that actually support the item, if any")


class Critique(BaseModel):
    adjustments: list[Adjustment] = Field(default_factory=list)
    tier_ok: bool = True
    suggested_tier: Optional[DifficultyTier] = None
    tier_note: Optional[str] = None
    time_ok: bool = True
    time_note: Optional[str] = None
    unverified: list[str] = Field(default_factory=list)
    extra_open_questions: list[str] = Field(default_factory=list)
