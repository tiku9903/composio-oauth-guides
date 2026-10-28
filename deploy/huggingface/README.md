---
title: OAuth App Readiness
emoji: 🔑
colorFrom: green
colorTo: yellow
sdk: gradio
sdk_version: 6.31.0
python_version: "3.12"
app_file: space_app.py
pinned: false
license: mit
short_description: How long until your OAuth app is approved?
---

# OAuth App Readiness

Look up any app your AI agent's users need to connect, and get a shareable guide to getting your provider OAuth app
created and approved: difficulty, hands-on effort versus approval wait, blockers, what an agent can do for you, and
how sure we are about each claim.

Source code, design decisions and limitations: https://github.com/tiku9903/composio-oauth-guides

This Space needs two secrets (Settings → Variables and secrets): `GEMINI_API_KEY` (free from Google AI Studio) and
`TAVILY_API_KEY` (free from Tavily). The guide library works without them; live investigation needs them.
