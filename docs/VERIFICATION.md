# Verification log

What was checked, how, and what changed as a result. Last updated 2026-10-28.

The library has eight curated guides. Each was written by a separate research agent from official docs and then
re-checked twice: first by that agent re-opening its own sources, then by an independent spot-check of the
claims most likely to be wrong (recent changes, surprising numbers, anything a developer would plan around).
The spot-check is recorded in each guide's `verification.method`.

## 1. Spot-check results

| App | Claim checked | Primary source | Result |
|---|---|---|---|
| GitHub | OAuth Apps now allow up to 10 callback URLs; new OAuth apps get expiring tokens by default (8 h access / 6-month refresh) | [GitHub changelog, 2026-08-14](https://github.blog/changelog/2026-08-14-multiple-redirect-uris-and-token-refresh-for-oauth-apps) | **Confirmed.** Opt-in for existing apps, default for new ones, plus a per-URI wildcard-matching toggle. This contradicts most older guides, which say OAuth App tokens never expire. |
| HubSpot | Unlisted marketplace-distribution apps are capped at 25 installs | [HubSpot changelog](https://developers.hubspot.com/changelog/new-marketplace-distribution-app-install-limits) | **Confirmed**, effective 2025-09-22, and enforced on migrated legacy apps. **Added** a missing requirement: private distribution is capped at 10 customers (100 for Solution Partners). |
| Gmail | `gmail.send` is sensitive, not restricted; `gmail.readonly`/`modify`/`compose`/`metadata` are restricted | [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes) | **Confirmed.** This changes the plan for a send-only agent: it needs sensitive-scope review (days), not a CASA security assessment (weeks). |
| Outlook | Microsoft's default user-consent policy blocks Mail.Read / Mail.ReadWrite for user consent | [Topedia summary of Microsoft message-center posts](https://blog.topedia.com/posts/microsoft-managed-default-app-consent-policy-will-block-8-additional-permissions) (secondary) | **Confirmed, and extended.** The same policy also blocks Calendars.\*, Chat.\* and Mailbox\* (Nov 2025), and Contacts.\*, People.Read and Tasks.\* (rolling out to July 2026). Added to the guide as a correction. The source is secondary, so it is labelled "other". |
| Slack | Non-Marketplace apps are throttled to 1 req/min on `conversations.history` | [Slack changelog, 2025-05-29](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps/) | **Partly confirmed.** It applies to new apps and new installs. The official page says existing installs are **not** affected. The research agent had also found a claimed 2026-03-03 extension to existing installs, but only in non-official sources, so it is now listed under "not verified". |
| Slack | Marketplace submission needs 10 active installs | [Slack changelog, 2026-09-01](https://docs.slack.dev/changelog/2026/09/01/slack-marketplace-install-requirement) | **Confirmed** (raised back to 10 in July 2026). |
| Linear | Access tokens last 24 h, refresh tokens rotate, all apps moved to refresh tokens on 2026-04-01 | [Linear OAuth docs](https://linear.app/developers/oauth-2-0-authentication) | **Confirmed.** Older guides describe roughly 10-year tokens. |
| All | Composio's redirect URI for bring-your-own OAuth apps | [Composio: custom auth configs](https://docs.composio.dev/docs/custom-auth-configs) | **Confirmed:** `https://backend.composio.dev/api/v3/toolkits/auth/callback`. Some Composio toolkit pages still show an older v1 URL. Composio says v1 still works, but recommends setting v3 in both places to avoid `redirect_uri_mismatch`. The Slack guide tells you to use what your auth config displays. |

## 2. Corrections the research agents found

These are recorded per guide in `verification.corrections` and shown on each guide page under "What we corrected".

- **HubSpot:** legacy public apps can no longer be created in the UI (since 2026-06-23); new apps are built with the CLI (`hs project`). Separate developer accounts were folded into standard accounts (2026-03-09). `/oauth/v1/token` is deprecated and ends 2027-02-16.
- **LinkedIn:** `r_liteprofile`/`r_emailaddress` were replaced by `openid profile email`. Refresh tokens are only for approved partners and have a fixed 365-day lifetime.
- **Gmail:** the often-quoted $15k–$75k CASA cost is outdated; assessor list prices are far lower (vendor prices, labelled "uncertain"). Projects created on or after 2026-05-01 have new per-user quotas.
- **Outlook:** client secrets can no longer be set to never expire; the maximum is 24 months.
- **Notion:** integrations are now "connections". Tokens now refresh. Rate limits are per plan, not a flat ~3 req/s.
- **Composio's own docs:** several provider setup pages show screenshots of the old UI or the v1 callback URL.

## 3. What could not be verified

- **Live probes for the curated guides.** The build environment's network blocked requests to the providers, so the probes recorded in the curated files are mostly *inconclusive* (`ok: null`). The one exception is Notion: its authorize URL with a fake client ID returned a 302. This is shown honestly on each guide. Run `python scripts/reprobe.py` from a normal network to replace them with real observations (see README). The live agent runs the same probes on every investigation.
- **Review and approval wait times** beyond provider-published targets: Google's restricted-scope review, HubSpot listing, Slack Marketplace and LinkedIn partner programs. These come from community reports and are labelled "uncertain".
- **Composio-managed OAuth status** for Linear, LinkedIn, Notion and Outlook (marked `unknown`; the managed-auth directory renders client-side). Set `COMPOSIO_API_KEY` and the agent reads `composio_managed_auth_schemes` from the API instead.
- **Whether Composio's custom auth accepts GitHub *App* credentials**, or passes Linear's `actor=app`.
- Each guide's own `verification.unverified` list.

## 4. How the live agent verifies itself

For agent-generated guides, the same discipline is enforced in code (`oauthguides/agent/graph.py`):

1. **Extraction keeps the evidence.** Every extracted fact carries a supporting phrase from its page, so the writer and verifier work from statements that are actually on the page, not from memory.
2. **The verifier is a separate pass.** A second model call reviews each step, requirement and blocker against the facts and probes, downgrades overclaims and records corrections. These appear live in the progress log and on the guide.
3. **Deterministic guards apply after the model.**
   - "Tested" must cite a live probe.
   - "Sourced" must cite a page the agent actually read.
   - A claim backed only by community or other non-official pages becomes "uncertain".
   - Citations to pages that were never fetched are removed.

   These rules are unit-tested in `tests/test_agent.py`.

## 5. A live-generated guide that was wrong, and what changed

**Fitbit (checked live, 2026-10-28).** The agent rated Fitbit "Visa-free": self-serve registration on
dev.fitbit.com with no review. A spot-check found that wrong in the way that matters most. Per
[Google's Health API overview](https://developers.google.com/health/about), the Fitbit Web API is being replaced
by the Google Health API. Legacy support ends 2026-09-30, and the Fitbit API and OAuth endpoints are turned off on
**2026-11-02**. The successor uses Google OAuth, and *all* of its scopes are restricted, so it needs a privacy and
security review. A new integration should therefore be rated "Visa required" and built on the successor.

**Why the agent missed it:** none of its searches looked for deprecations, and nothing in the guide format could
express "this API is going away".

**What changed:**
- Every investigation now searches for deprecation, sunset, shutdown and migration news.
- Fact extraction has a `lifecycle` topic.
- The writer must target the successor API when one exists.
- Guides have a `notice` field, shown as a red "Before you build" banner above the visa page.

## 6. Other fixes driven by live runs

| Seen in | Problem | Fix |
|---|---|---|
| Cal.com | Steps showed "Inferred" although the verifier confirmed S1/S7 (citations written only in prose) | Citation ids are normalised, recovered from verifier notes when they point at pages actually read, and the verifier returns `source_ids` |
| Cal.com | Console probe called a 404 "reachable"; `/auth/` in the provider's own URL was read as a login redirect | Probe interpretation fixed; regression tests use the exact Cal.com responses |
| Cal.com / Vercel | Look-alike products (Calendly, Figma) read as sources; provider forums labelled "official" | Relevance filter, and forums on the provider's domain are classified as community |
| PayPal / Vercel | Main model failed silently; a lite model wrote 3-step guides marked "formal review" with a 1–3 day wait | Model discovery from the key's own model list, a deterministic quality bar with one rewrite, and rate-limit wait-and-retry before falling back |
| Fitbit | A redirect-loop URL thousands of characters long ended up in a step's links | Runaway URLs are dropped at fetch time and when the guide is assembled |
