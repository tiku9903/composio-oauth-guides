"""End-to-end agent test with a fake LLM and stubbed network: proves the graph wiring,
event stream, evidence guards and persistence without API keys."""
from __future__ import annotations

import asyncio

import pytest

from oauthguides import llm
from oauthguides.agent import graph as G
from oauthguides.agent.models import AppIdentity, Critique, Adjustment, GuideDraft, PageExtraction, Fact
from oauthguides.schema import Probe, Step, Requirement, TimeEstimate, ComposioStatus, OAuthDetails
from oauthguides.tools.fetch import Page
from oauthguides.tools.search import SearchHit


class FakeRunnable:
    def __init__(self, cls):
        self.cls = cls

    async def ainvoke(self, prompt):
        c = self.cls
        if c is AppIdentity:
            return AppIdentity(app_name="Acme CRM", slug="acme_crm", website="https://acme.example",
                               official_domains=["acme.example"], developer_console_url="https://acme.example/dev",
                               supports_oauth="yes", search_queries=["acme oauth"])
        if c is PageExtraction:
            return PageExtraction(relevant=True, authorize_url="https://acme.example/oauth/authorize",
                                  facts=[Fact(topic="review", statement="Public apps need review", support="must be reviewed")])
        if c is GuideDraft:
            return GuideDraft(
                tagline="Self-serve app, review for listing", tier=2, tier_reason="listing review",
                time=TimeEstimate(active_effort="30-60 min", active_hours_low=0.5, active_hours_high=1,
                                  wait="3-5 days", wait_days_low=3, wait_days_high=5, summary="An hour plus a few days."),
                composio=ComposioStatus(managed_oauth="no"), oauth=OAuthDetails(),
                start_here="Create a developer account.",
                steps=[
                    Step(phase="register", title="Create app", owner="you", detail="x", evidence="sourced", source_ids=["S1"]),
                    Step(phase="test", title="Endpoint live", owner="agent", detail="x", evidence="tested", source_ids=["S1"]),
                    Step(phase="review", title="Submit", owner="you", detail="x", evidence="sourced", source_ids=["S9"]),
                ],
                requirements=[Requirement(title="Privacy policy", detail="x", evidence="sourced", source_ids=["S2"])],
            )
        if c is Critique:
            return Critique(adjustments=[Adjustment(item="requirements[0]", evidence="uncertain", note="community only",
                                                    corrected_text="Privacy policy URL required only for listing")],
                            unverified=["Review SLA"])
        raise AssertionError(c)


class FakeLLM:
    def with_structured_output(self, cls):
        return FakeRunnable(cls)


@pytest.fixture
def patched(monkeypatch, tmp_path):
    llm.set_llm_factory(lambda name: FakeLLM())
    from oauthguides import config
    object.__setattr__(config.settings, "generated_dir", tmp_path)

    async def fake_search(q, n=None):
        return [SearchHit("Acme OAuth", "https://acme.example/docs/oauth", "", q)]

    async def fake_search_many(qs, n=None):
        return [SearchHit("Acme OAuth", "https://acme.example/docs/oauth", "", "q"),
                SearchHit("Forum", "https://community.acme.example/t/1", "", "q")]

    async def fake_fetch_many(urls):
        return [Page(u, u, 200, "Title", "text " * 100) for u in urls]

    def mkprobe(name):
        return Probe(name=name, target="https://acme.example", method="GET", observed="200", conclusion="ok", ok=True)

    async def fake_disc(domains):
        return mkprobe("OAuth/OIDC discovery document"), None

    async def fake_console(url):
        return mkprobe("Developer console access")

    async def fake_composio(slug):
        return mkprobe("Composio toolkit docs")

    async def fake_auth(url, scopes=None):
        return mkprobe("Authorize endpoint with an invalid client_id")

    for name, fn in [("search", fake_search), ("search_many", fake_search_many), ("fetch_many", fake_fetch_many),
                     ("probe_oidc_discovery", fake_disc), ("probe_console", fake_console),
                     ("probe_composio", fake_composio), ("probe_authorize", fake_auth)]:
        monkeypatch.setattr(G, name, fn)
    yield tmp_path
    llm.set_llm_factory(None)


def test_agent_end_to_end(patched):
    events = []
    guide = asyncio.run(G.run("acme crm", on_event=events.append))
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "stage" and kinds[-1] == "done"
    assert sum(1 for e in events if e["kind"] == "probe") == 4  # 3 early + authorize
    assert guide.slug == "acme_crm" and guide.method == "live_agent"
    # guards: tested without probe → inferred; unknown S9 dropped → sourced→inferred
    assert guide.steps[1].evidence == "inferred"
    assert guide.steps[2].evidence == "inferred" and guide.steps[2].source_ids == []
    # critic adjustment applied, recorded as correction
    assert guide.requirements[0].evidence == "uncertain"
    assert guide.verification.corrections and "Privacy policy" in guide.verification.corrections[0].claim
    assert "Review SLA" in guide.verification.unverified
    # probes become P-sources
    assert any(s.id.startswith("P") and s.kind == "probe" for s in guide.sources)
    assert guide.dangling_source_ids() == []
    assert (patched / "acme_crm.json").exists()


def test_guards_unit():
    draft = {"steps": [{"evidence": "sourced", "source_ids": ["S1"]}, {"evidence": "tested", "source_ids": ["P1"]}],
             "requirements": [], "blockers": [], "time": {"source_ids": ["S5"]}}
    out, notes = G.apply_guards(draft, {"S1": "community", "P1": "probe"})
    assert out["steps"][0]["evidence"] == "uncertain"
    assert out["steps"][1]["evidence"] == "tested"
    assert out["time"]["source_ids"] == []


def test_relevance_filter_drops_lookalike_products():
    from oauthguides.agent.graph import is_relevant
    from oauthguides.agent.models import AppIdentity
    ident = AppIdentity(app_name="Cal.com", slug="cal", official_domains=["cal.com"])
    keep = SearchHit("How to register your own Cal.com OAuth app - Nango", "https://nango.dev/docs/cal-com", "", "q")
    official = SearchHit("OAuth", "https://cal.com/docs/oauth", "", "q")
    calendly = SearchHit("Refresh tokens | Calendly Developer", "https://developer.calendly.com/x", "", "q")
    figma = SearchHit("Pending OAuth App Approval | Figma Forum", "https://forum.figma.com/t/1", "", "q")
    assert is_relevant(keep, ident) and is_relevant(official, ident)
    assert not is_relevant(calendly, ident) and not is_relevant(figma, ident)
