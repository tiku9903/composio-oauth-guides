"""Model access. Provider-agnostic through LangChain's init_chat_model.

MODEL=google_genai:gemini-3.8-flash (default, free tier) or e.g. anthropic:claude-sonnet-5-5, openai:gpt-5.
Tests inject a fake via set_llm_factory().

Every agent call goes through `call_structured`, which:
  * tries a chain of candidate models (for Gemini, discovered from the key's own model list, so a
    renamed or quota-exhausted free model never breaks a run),
  * logs start / finish / failure with timings (visible in the host's logs),
  * enforces a hard wall-clock limit so a stuck call can't hang a run,
  * retries once without "thinking" if a model rejects the thinking setting.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Callable, Optional

from .config import settings

log = logging.getLogger("oauthguides.llm")
_factory: Callable[[str], Any] | None = None
_gemini_models: list[str] | None = None
_gemini_checked = False

_SKIP = ("tts", "live", "image", "audio", "embed", "transcribe", "translate", "vision", "aqa", "learnlm", "nano")


def set_llm_factory(factory: Callable[[str], Any] | None) -> None:
    """Override model construction (used by tests and offline demos)."""
    global _factory
    _factory = factory


def model_name(kind: str) -> str:
    return settings.model if kind == "main" else settings.fast_model


def _version(name: str) -> float:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def gemini_available() -> list[str] | None:
    """Text models this key can call (generateContent), newest first. None if unknown."""
    global _gemini_models, _gemini_checked
    if _gemini_checked:
        return _gemini_models
    _gemini_checked = True
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return None
    try:
        from google import genai

        names = []
        for m in genai.Client(api_key=key).models.list():
            actions = getattr(m, "supported_actions", None) or []
            name = (m.name or "").removeprefix("models/")
            if "generateContent" in actions and name.startswith("gemini") and not any(s in name for s in _SKIP):
                names.append(name)
        names.sort(key=lambda n: (_version(n), "preview" not in n and "exp" not in n), reverse=True)
        _gemini_models = names
        log.info("gemini models available to this key: %s", ", ".join(names[:12]))
    except Exception as e:  # noqa: BLE001 - discovery is best-effort
        log.warning("could not list gemini models: %s", e)
        _gemini_models = None
    return _gemini_models


def candidates(kind: str) -> list[str]:
    """Ordered model names to try for a call of this kind."""
    primary, fast = settings.model, settings.fast_model
    chain = [primary, fast] if kind == "main" else [fast, primary]
    if _factory is None and primary.startswith("google_genai:"):
        avail = gemini_available()
        if avail:
            flash = [f"google_genai:{n}" for n in avail if "flash" in n and "lite" not in n]
            lite = [f"google_genai:{n}" for n in avail if "lite" in n]
            pro = [f"google_genai:{n}" for n in avail if "pro" in n]
            configured_ok = [c for c in (primary, fast) if c.split(":", 1)[1] in avail]
            if kind == "main":
                chain = [c for c in [primary] if c in configured_ok] + flash[:2] + pro[:1] + \
                        [c for c in [fast] if c in configured_ok] + lite[:1]
            else:
                chain = [c for c in [fast] if c in configured_ok] + lite[:2] + flash[:1] + \
                        [c for c in [primary] if c in configured_ok]
    return list(dict.fromkeys(chain))[:4]


def get_llm(name: str, thinking: bool = True) -> Any:
    if _factory is not None:
        return _factory(name)
    from langchain.chat_models import init_chat_model

    kwargs: dict[str, Any] = dict(temperature=0, max_tokens=16000, timeout=settings.llm_timeout,
                                  max_retries=settings.llm_retries)
    if name.startswith("google_genai:") and thinking and settings.gemini_thinking:
        # Large structured outputs are much faster with little or no "thinking".
        kwargs["thinking_config"] = {"thinking_level": settings.gemini_thinking}
    return init_chat_model(name, **kwargs)


def structured(model_cls: type, name: str, thinking: bool = True) -> Any:
    """A runnable that returns an instance of `model_cls`."""
    return get_llm(name, thinking).with_structured_output(model_cls)


async def call_structured(model_cls: type, prompt: str, kind: str = "main", label: str = "",
                          notify: Optional[Callable[[str], None]] = None) -> Any:
    chain = await asyncio.to_thread(candidates, kind)
    last: Exception | None = None
    for i, name in enumerate(chain):
        for thinking in (True, False):
            t0 = time.monotonic()
            log.info("llm start %s model=%s thinking=%s prompt_chars=%d", label, name, thinking, len(prompt))
            try:
                res = await asyncio.wait_for(structured(model_cls, name, thinking).ainvoke(prompt),
                                             timeout=settings.llm_hard_timeout)
                if res is None:
                    raise ValueError("model returned no structured output")
                log.info("llm ok %s model=%s %.1fs", label, name, time.monotonic() - t0)
                return res
            except Exception as e:  # noqa: BLE001 - we log and fall back
                last = e
                err = "timed out" if isinstance(e, asyncio.TimeoutError) else f"{type(e).__name__}: {str(e)[:400]}"
                log.warning("llm fail %s model=%s after %.1fs: %s", label, name, time.monotonic() - t0, err)
                if thinking and "thinking" in str(e).lower():
                    continue  # retry the same model without the thinking setting
                break
        if i + 1 < len(chain) and notify:
            short = name.split(":", 1)[-1]
            notify(f"{label}: {short} unavailable ({type(last).__name__}); trying {chain[i + 1].split(':', 1)[-1]}")
    assert last is not None
    raise last
