# Research brief for curated guides

You are writing a curated OAuth-app setup guide for a developer who builds an AI agent and
wants their end users to connect a third-party app (via Composio). The developer must create
an OAuth app with the provider ("bring your own OAuth app") and possibly get it approved
before real users can connect.

Output: one JSON file per app at `data/guides/curated/<slug>.json` that validates against
`oauthguides.schema.Guide` (read `oauthguides/schema.py` first — field descriptions matter).
Validate with, from the repo root `/home/claude/oauth-guides`:

    python3 -c "import json,sys; from oauthguides.schema import Guide; g=Guide(**json.load(open('data/guides/curated/<slug>.json'))); print('ok', g.dangling_source_ids())"

`dangling_source_ids()` must print `[]`.

## What the guide must answer
1. How easy/hard is it (tier 1-4, see TIER_BLURBS in schema.py) and why.
2. Time: hands-on effort AND calendar wait for any approval, as ranges, with what drives the range.
3. Requirements and nuances: account/plan needed, scopes (especially sensitive/restricted ones),
   redirect URI rules, verification (domain, publisher, brand), privacy policy / ToS / homepage,
   demo video, security assessment, token lifetimes / refresh behaviour, rate limits, multi-tenant
   or admin-consent quirks, per-customer instance URLs, test-user limits, unverified-app warnings.
4. Agent vs human: which steps an AI agent could do (research, draft scope justifications, draft
   privacy policy text, fill form values, run test auth flows, check endpoints) vs. what only the
   human/org owner can do (log into console, accept terms, verify domain DNS, pay, record video,
   sign agreements).
5. Blockers: concrete failure modes ("redirect_uri mismatch", "app not verified screen",
   "access_denied for 101st user") and what to do.
6. `start_here`: the single first action.
7. `ready_to_paste`: values the developer can paste (redirect URI for Composio custom auth,
   suggested scopes list, app description, scope-justification template).
   Composio's callback/redirect URI for custom OAuth apps — find it in Composio docs
   (docs.composio.dev) and cite it; if you cannot confirm it, mark the note as unverified.
8. `composio`: is there a Composio-managed OAuth app for this toolkit? Check
   https://docs.composio.dev/toolkits/<toolkit> pages (or the managed-auth directory).
   Mark `unknown` if you can't confirm.

## Evidence rules (most important)
- Every step / requirement / blocker carries `evidence` + `source_ids`.
- `sourced` only if a cited page actually says it. Prefer official provider docs/policies.
- `tested` only if YOU actually observed it this session. You can run real probes with
  WebFetch, e.g. fetch the provider's authorize URL with `client_id=test_invalid_client` and
  record the error the provider returns (proves endpoint + how it handles unknown clients),
  fetch `/.well-known/openid-configuration`, fetch the developer console URL and note whether it
  redirects to a login wall. Record each in `probes` (name, target, method, observed, conclusion,
  ok, at=today 2026-10-28). If a fetch fails/blocked, record that honestly (ok=null).
- `inferred` for reasoning not directly stated; `uncertain` for anecdotal/conflicting/old info.
  Review-time numbers are often only anecdotal: say so, cite community sources with kind=community.
- Put anything you couldn't confirm in `verification.unverified` and `open_questions`.
- If you discover that a commonly-repeated claim is wrong/outdated, add a `verification.corrections`
  entry (claim, was, now, source_ids). These are valuable — look for them.
- Set `method`="curated", `verification.status`="spot_checked" only for apps where you
  re-opened the cited sources to confirm the key claims (do this), `checked_on`="2026-10-28",
  `verification.method` describes what you checked. `model`="research-agent".
- Sources: `accessed`="2026-10-28". Do not quote more than a short phrase from any source; write
  in your own words.
- Today is 2026-10-28. Things change; search for the current state rather than relying on memory.

## Style
Plain, specific, developer-to-developer. Step `detail` is markdown with exact field names /
menu paths where known. 6-10 steps typical, phases: prepare → register → configure → test →
review → launch (skip review phase if none). Keep tagline under 140 chars.
