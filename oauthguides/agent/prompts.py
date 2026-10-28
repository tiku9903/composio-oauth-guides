"""Prompts for the investigation agent. Kept in one place so they can be reviewed as product copy."""

CONTEXT = """\
Context: A developer is building an AI agent on Composio. Their end users will connect their own \
account in a third-party app ("{app}"). To do that the developer needs an OAuth app (client) \
registered with the provider and, for some providers, approved before real users can connect. \
Composio can provide a managed OAuth app for some toolkits; otherwise the developer brings their \
own and registers Composio's callback URL ({redirect}) as the redirect URI.
Today is {today}."""

RESOLVE = """\
{context}

The developer typed: "{query}"
Search results for orientation:
{hits}

Identify the app/provider. Return the canonical app name, a lowercase toolkit-style slug \
(e.g. "google_calendar", "hubspot"), the main website, ALL official domains whose pages count as \
first-party docs (e.g. ["slack.com","slack.dev"]), category, your best guess of the developer \
console URL where an OAuth app is created and the developer docs URL, whether the provider offers \
third-party OAuth at all, and 5-8 targeted web search queries that will find: how to register an \
OAuth app; scopes; app review/verification/marketplace or partner requirements; redirect URI \
rules; token lifetime/refresh; rate limits; and real-world reports of approval time. If the input \
is ambiguous, pick the most likely developer-facing product and say so in notes."""

EXTRACT = """\
{context}

Below is the text of one web page (source {sid}: {url}, kind={kind}).
Extract ONLY facts this page actually states that matter for creating, configuring, testing or \
getting approval for an OAuth app for {app}. For each fact give a topic, a self-contained \
statement in your own words, and a short supporting phrase from the page (max 20 words) so a \
reviewer can find it. Mark confidence low if the page is old, community-written, about a \
different product, or ambiguous. Also pull out any concrete endpoints, console URL and scope \
names it lists. If the page is irrelevant, return relevant=false and no facts.

PAGE TEXT:
{text}"""

SYNTHESIZE = """\
{context}

You are writing the setup guide a developer will follow and forward to a teammate. Use ONLY the \
evidence below. Cite source ids (S#) for documents and probe ids (P#) for live probes.

Put citations in the source_ids list of each step/requirement/blocker (e.g. ["S1","P2"]), never only in text.
Evidence levels — be strict, the product's credibility depends on it:
- "tested": ONLY when a live probe (P#) observed it. Cite the P#.
- "sourced": a cited S# fact states it. Cite the S#.
- "inferred": reasonable conclusion from sources or from how comparable providers work.
- "uncertain": anecdotal (community), conflicting, old, or not found. Say what would confirm it.
Never invent numbers. If review timelines are only anecdotal, give a range, mark it uncertain \
or inferred, and say so in the time summary.

Tiers: 1 Self-serve (no approval for any user); 2 Self-serve + light review (listing / \
distribution toggle / lightweight review, days); 3 Formal review/verification (security \
review, app review, verification — weeks); 4 Gated/partner-only (partner application, \
contract, paid plan; approval not guaranteed). Pick the tier for the path a typical AI-agent \
product needs to let *any* customer connect with the scopes an agent realistically needs.

Owners: "agent" = an AI agent can do it alone (research, drafting text, generating values, \
running test flows with credentials the human provides, checking endpoints); "you" = needs a \
human with the account (console logins, accepting terms, DNS verification, payments, legal, \
recording a video); "you_with_agent" = human clicks, agent prepares everything.

Write steps with phases prepare → register → configure → test → review → launch (skip review \
if none). In step detail use exact menu paths/field names when the sources give them, and the \
exact redirect URI {redirect}. 'start_here' is ONE concrete first action. Put every open \
uncertainty into open_questions phrased as a question the developer could ask the provider. \
ready_to_paste: Composio redirect URI, suggested scopes, a 1-2 sentence app description, and \
(if review exists) a scope-justification template with placeholders.

Quality bar (drafts below it are rejected and rewritten):
- tagline: a VERDICT under 140 chars that names the time and the main gate, e.g. "Credentials in \
minutes; reading mail needs restricted-scope review plus a yearly security assessment". Never a \
description of the product.
- 6-10 steps covering prepare, register, configure, test and launch. If tier is 3 or 4 there MUST be \
a review-phase step that says what reviewers ask for and how long they take.
- tier, time.wait and steps must agree: tier 1 means no approval wait; tier 3+ means weeks, not days.
- at least 3 requirements and 2 blockers (real failure modes with the exact error a developer sees).
- suggested scopes: the scopes an AI agent would need for useful actions in this app (e.g. read and \
write the app's core objects), not only sign-in scopes; mark which ones trigger review.

APP: {identity}

COMPOSIO STATUS (from probe): {composio}

LIVE PROBES:
{probes}

SOURCES:
{sources}

EXTRACTED FACTS (grouped by source):
{facts}"""

CRITIQUE = """\
{context}

You are the verifier. Check the draft guide below against the evidence. For every step, \
requirement and blocker (addressed as steps[i] / requirements[i] / blockers[i]) decide whether \
its evidence level is justified by the cited sources/probes and the extracted facts. Downgrade \
anything overclaimed; never upgrade to "tested" without a P# probe. Flag factual statements that \
contradict a source. Check the tier and time estimate are consistent with the requirements \
(e.g. a restricted-scope security assessment can't be "1-3 days"). List things that remain \
unverified and good questions to ask the provider. For every item whose citations are missing or wrong but which IS supported, return an adjustment with the correct source_ids (S#/P#). Be concise; only list items that need change.

DRAFT GUIDE (JSON):
{draft}

LIVE PROBES:
{probes}

EXTRACTED FACTS:
{facts}"""
