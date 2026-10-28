"""Live probes: things an agent can *actually try* without the developer's credentials.

Each probe returns a schema.Probe with what was attempted and what was observed. These are the
only basis for evidence level "tested". None of them create accounts, submit forms, or send
credentials; they are read-only requests a browser would make.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

from ..config import COMPOSIO_REDIRECT_URI, settings
from ..schema import Probe
from .fetch import client, html_to_text

DUMMY_CLIENT_ID = "oauth-guide-probe-invalid-client"
LOGIN_MARKERS = ("login", "signin", "sign-in", "sign_in", "auth", "sso", "account", "session")
PASSWORD_FIELD = re.compile(r"<input[^>]+type=[\"']?password", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short(s: str, n: int = 240) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


async def probe_oidc_discovery(domains: list[str]) -> tuple[Probe, dict | None]:
    """Look for /.well-known/openid-configuration (and OAuth AS metadata) on likely hosts."""
    candidates: list[str] = []
    for d in domains:
        d = d.strip().lower().removeprefix("www.")
        for host in (d, f"auth.{d}", f"login.{d}", f"accounts.{d}", f"api.{d}", f"oauth.{d}"):
            for path in ("/.well-known/openid-configuration", "/.well-known/oauth-authorization-server"):
                candidates.append(f"https://{host}{path}")
    tried: list[str] = []
    reached = 0  # responses that clearly came from a real server (not a network block)
    async with client() as c:
        for url in candidates[:18]:
            tried.append(url)
            try:
                r = await c.get(url)
                if r.status_code in (200, 301, 302, 400, 401, 404, 405, 410):
                    reached += 1
                if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                    meta = r.json()
                    if "authorization_endpoint" in meta:
                        return (
                            Probe(
                                name="OAuth/OIDC discovery document",
                                target=url,
                                method="GET well-known metadata",
                                observed=f"200 JSON; authorization_endpoint={meta.get('authorization_endpoint')}; "
                                f"token_endpoint={meta.get('token_endpoint')}; "
                                f"PKCE methods={meta.get('code_challenge_methods_supported')}",
                                conclusion="Provider publishes standard metadata, so endpoints and PKCE support are machine-verifiable.",
                                ok=True,
                                at=_now(),
                            ),
                            meta,
                        )
            except Exception:
                continue
    if reached == 0:
        return (
            Probe(
                name="OAuth/OIDC discovery document",
                target=", ".join(dict.fromkeys(urlparse(u).netloc for u in tried[:6])),
                method=f"GET well-known metadata on {len(tried)} candidate URLs",
                observed="No candidate host gave a usable response (blocked or unreachable from the agent's network).",
                conclusion="Inconclusive: could not check for discovery metadata.",
                ok=None,
                at=_now(),
            ),
            None,
        )
    return (
        Probe(
            name="OAuth/OIDC discovery document",
            target=", ".join(dict.fromkeys(urlparse(u).netloc for u in tried[:6])),
            method=f"GET /.well-known/openid-configuration and oauth-authorization-server on {len(tried)} candidate URLs",
            observed="No discovery document found on the candidate hosts.",
            conclusion="Endpoints must come from the provider's docs; not every OAuth provider publishes metadata (common for non-OIDC APIs).",
            ok=False,
            at=_now(),
        ),
        None,
    )


def _interpret_authorize(status: int, final_url: str, body_text: str, location: str | None,
                         requested_url: str = "") -> tuple[str, bool | None]:
    loc_q = parse_qs(urlparse(location).query) if location else {}
    text = body_text.lower()
    if "error" in loc_q:
        return (f"Provider redirected back with error={loc_q['error'][0]} — endpoint is live and validates client_id.", True)
    if any(k in text for k in ("invalid_client", "invalid client", "client_id", "application not found", "app not found",
                               "unknown client", "does not exist", "not found", "invalid request", "unauthorized_client",
                               "invalid_request", "something went wrong", "doesn't exist", "redirect_uri")):
        return ("Endpoint is live and rejected the unknown client_id (expected).", True)
    moved = bool(location) and urlparse(final_url).path.rstrip("/") != urlparse(requested_url).path.rstrip("/")
    if status in (200, 302, 303) and moved and any(m in urlparse(final_url).path.lower() for m in ("login", "signin", "sign-in", "sign_in", "sso", "session")):
        return ("Endpoint is live; it sends unauthenticated users to a login page before validating the client.", True)
    if status == 200 and not moved:
        return ("Endpoint is live and serves an authorization page; it didn't reject the fake client before sign-in.", True)
    if status >= 500:
        return ("Endpoint returned a server error for an unknown client.", None)
    if status == 404:
        return ("404 — this is probably not the authorize endpoint (or it requires a tenant/instance host).", False)
    return ("Endpoint responded but behaviour was ambiguous.", None)


async def probe_authorize(authorize_url: str, scopes: list[str] | None = None) -> Probe:
    """Hit the authorize endpoint with a deliberately invalid client_id and Composio's redirect URI."""
    params = {
        "client_id": DUMMY_CLIENT_ID,
        "redirect_uri": COMPOSIO_REDIRECT_URI,
        "response_type": "code",
        "state": "probe",
    }
    if scopes:
        params["scope"] = " ".join(scopes[:3])
    sep = "&" if "?" in authorize_url else "?"
    url = authorize_url + sep + urlencode(params)
    try:
        async with client(follow_redirects=False) as c:
            r = await c.get(url)
            location = r.headers.get("location")
            hops = 0
            final = r
            while final.status_code in (301, 302, 303, 307, 308) and hops < 5 and final.headers.get("location"):
                nxt = httpx.URL(str(final.url)).join(final.headers["location"])
                final = await c.get(nxt)
                hops += 1
        text = html_to_text(final.text) if "html" in final.headers.get("content-type", "") else final.text
        if r.status_code in (403, 407, 429) and not location:
            return Probe(
                name="Authorize endpoint with an invalid client_id",
                target=authorize_url,
                method="GET authorize URL with a fake client_id and Composio's redirect URI",
                observed=f"HTTP {r.status_code} before reaching the provider's OAuth logic",
                conclusion="Inconclusive: request was blocked or rate-limited (network policy or bot protection).",
                ok=None,
                at=_now(),
            )
        conclusion, ok = _interpret_authorize(final.status_code, str(final.url), text, location, authorize_url)
        observed = f"HTTP {r.status_code}" + (f" → {final.status_code} at {_short(str(final.url), 120)}" if final is not r else "")
        if text:
            observed += f"; page says: “{_short(text, 160)}”"
        return Probe(
            name="Authorize endpoint with an invalid client_id",
            target=authorize_url,
            method="GET authorize URL with a fake client_id and Composio's redirect URI (no login, no credentials)",
            observed=observed,
            conclusion=conclusion,
            ok=ok,
            at=_now(),
        )
    except Exception as e:
        return Probe(
            name="Authorize endpoint with an invalid client_id",
            target=authorize_url,
            method="GET authorize URL with a fake client_id",
            observed=f"Request failed: {type(e).__name__}: {_short(str(e), 120)}",
            conclusion="Could not reach the endpoint from the agent's network; not evidence either way.",
            ok=None,
            at=_now(),
        )


async def probe_console(console_url: str) -> Probe:
    """Can an agent open the developer console unauthenticated? Usually not: that's the human hand-off."""
    try:
        async with client() as c:
            r = await c.get(console_url)
        final = str(r.url)
        if r.status_code in (403, 407, 429) and final == console_url:
            return Probe(
                name="Developer console access",
                target=console_url,
                method="GET console URL without a session",
                observed=f"HTTP {r.status_code}",
                conclusion="Inconclusive: request was blocked (network policy or bot protection).",
                ok=None,
                at=_now(),
            )
        if r.status_code in (404, 410):
            return Probe(
                name="Developer console access",
                target=console_url,
                method="GET console URL without a session",
                observed=f"HTTP {r.status_code} at {_short(final, 140)}",
                conclusion="URL returned not-found without a session: it may be outdated, or the app hides it until you sign in. Open it while signed in to confirm.",
                ok=False,
                at=_now(),
            )
        has_pw = bool(PASSWORD_FIELD.search(r.text or ""))
        redirected_to_login = final != console_url and any(m in final.lower() for m in LOGIN_MARKERS)
        if redirected_to_login or has_pw:
            obs = f"HTTP {r.status_code}; ended at {_short(final, 140)}" + ("; page has a password field" if has_pw else "")
            return Probe(
                name="Developer console access",
                target=console_url,
                method="GET console URL without a session",
                observed=obs,
                conclusion="Console is behind a login wall: creating the app is a human step (agent can prepare every value to paste).",
                ok=True,
                at=_now(),
            )
        return Probe(
            name="Developer console access",
            target=console_url,
            method="GET console URL without a session",
            observed=f"HTTP {r.status_code}; ended at {_short(final, 140)}; no obvious login form (may be a JS app that redirects client-side).",
            conclusion="Console page is reachable; sign-in is probably still enforced client-side.",
            ok=None,
            at=_now(),
        )
    except Exception as e:
        return Probe(
            name="Developer console access",
            target=console_url,
            method="GET console URL without a session",
            observed=f"Request failed: {type(e).__name__}",
            conclusion="Could not reach the console from the agent's network.",
            ok=None,
            at=_now(),
        )


async def probe_composio(toolkit_slug: str) -> Probe:
    """Check whether Composio manages an OAuth app for this toolkit.

    With COMPOSIO_API_KEY: read `composio_managed_auth_schemes` from the toolkit API (authoritative).
    Without it: read the public toolkit docs page.
    """
    slug = toolkit_slug.strip().lower().replace(" ", "_")
    if settings.composio_key:
        url = f"https://backend.composio.dev/api/v3/toolkits/{slug}"
        try:
            async with client() as c:
                r = await c.get(url, headers={"x-api-key": settings.composio_key})
            if r.status_code == 200:
                data = r.json()
                managed = data.get("composio_managed_auth_schemes") or []
                schemes = [a.get("mode") or a.get("auth_mode") for a in (data.get("auth_config_details") or [])]
                return Probe(
                    name="Composio managed OAuth (API)",
                    target=url,
                    method="GET toolkit from Composio API",
                    observed=f"composio_managed_auth_schemes={managed}; auth schemes={schemes}",
                    conclusion=("Composio provides the OAuth app" if any("OAUTH" in str(m).upper() for m in managed)
                                else "No Composio-managed OAuth app: bring your own."),
                    ok=True,
                    at=_now(),
                )
            observed = f"HTTP {r.status_code}"
        except Exception as e:
            observed = f"{type(e).__name__}"
        api_note = f" (API check failed: {observed})"
    else:
        api_note = ""
    variants = list(dict.fromkeys([slug.replace("_", "-"), slug.replace("_", ""), slug.split("_")[0]]))
    base = f"https://docs.composio.dev/toolkits/{variants[0]}"
    text, url, status = "", base, 0
    try:
        async with client() as c:
            # The docs site renders client-side; its .md variant carries the real content.
            # Toolkit slugs vary ("cal-com" vs "cal"), so try a few spellings.
            tries = [f"https://docs.composio.dev/toolkits/{v}{ext}" for v in variants for ext in (".md", "")]
            for candidate in tries:
                r = await c.get(candidate)
                status, url = r.status_code, candidate
                if r.status_code == 200:
                    body = r.text if candidate.endswith(".md") else html_to_text(r.text)
                    if len(body) >= 150:
                        text = body
                        break
    except Exception as e:
        return Probe(name="Composio toolkit docs", target=base, method="GET public toolkit docs page" + api_note,
                     observed=f"Request failed: {type(e).__name__}", conclusion="Could not check Composio docs.",
                     ok=None, at=_now())
    low = text.lower()
    if not text and status in (404, 410):
        verdict, ok = "No toolkit page under this name; Composio may not support this app yet (or uses another slug).", False
    elif not text:
        verdict, ok = "Page had no readable content (client-rendered); managed status unknown.", None
    elif re.search(r"composio[- ]managed|managed by composio|managed (oauth|auth)", low):
        verdict, ok = "Toolkit docs mention Composio-managed auth; check which auth method it covers.", True
    elif "oauth" in low:
        verdict, ok = "Toolkit exists and supports OAuth; docs don't say Composio manages the app, so plan to bring your own.", None
    else:
        verdict, ok = "Toolkit exists; its docs don't mention OAuth.", None
    return Probe(name="Composio toolkit docs", target=url, method="GET public toolkit docs (markdown first)" + api_note,
                 observed=f"HTTP {status}" + (f"; {len(text)} chars of content" if text else "; no readable content"),
                 conclusion=verdict, ok=ok, at=_now())


async def run_probes(domains: list[str], authorize_url: str | None, console_url: str | None,
                     toolkit_slug: str | None, scopes: list[str] | None = None) -> tuple[list[Probe], dict | None]:
    disc_probe, meta = await probe_oidc_discovery(domains)
    auth_url = authorize_url or (meta or {}).get("authorization_endpoint")
    rest = []
    if auth_url:
        rest.append(probe_authorize(auth_url, scopes))
    if console_url:
        rest.append(probe_console(console_url))
    if toolkit_slug:
        rest.append(probe_composio(toolkit_slug))
    results = await asyncio.gather(*rest)
    return [disc_probe, *results], meta
