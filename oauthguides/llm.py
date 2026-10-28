"""Model access. Provider-agnostic through LangChain's init_chat_model.

MODEL=google_genai:gemini-3.8-flash (default, free tier) or e.g. anthropic:claude-sonnet-5-5, openai:gpt-5.
Tests inject a fake via set_llm_factory().

Every agent call goes through `call_structured`, which:
  * logs start / finish / failure with timings (visible in the host's logs),
  * enforces a hard wall-clock limit so a stuck call can't hang a run,
  * retries once without "thinking" if a model rejects the thinking setting,
  * falls back from MODEL to FAST_MODEL when the main model keeps failing.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from .config import settings

log = logging.getLogger("oauthguides.llm")
_factory: Callable[[str], Any] | None = None


def set_llm_factory(factory: Callable[[str], Any] | None) -> None:
    """Override model construction (used by tests and offline demos)."""
    global _factory
    _factory = factory


def model_name(kind: str) -> str:
    return settings.model if kind == "main" else settings.fast_model


def get_llm(kind: str = "main", thinking: bool = True) -> Any:
    name = model_name(kind)
    if _factory is not None:
        return _factory(name)
    from langchain.chat_models import init_chat_model

    kwargs: dict[str, Any] = dict(temperature=0, max_tokens=16000, timeout=settings.llm_timeout,
                                  max_retries=settings.llm_retries)
    if name.startswith("google_genai:") and thinking and settings.gemini_thinking:
        # Large structured outputs are much faster with little or no "thinking".
        kwargs["thinking_config"] = {"thinking_level": settings.gemini_thinking}
    return init_chat_model(name, **kwargs)


def structured(model_cls: type, kind: str = "main", thinking: bool = True) -> Any:
    """A runnable that returns an instance of `model_cls`."""
    return get_llm(kind, thinking).with_structured_output(model_cls)


async def call_structured(model_cls: type, prompt: str, kind: str = "main", label: str = "",
                          notify: Optional[Callable[[str], None]] = None) -> Any:
    kinds = [kind]
    if kind == "main" and settings.fast_model != settings.model:
        kinds.append("fast")
    last: Exception | None = None
    for i, k in enumerate(kinds):
        name = model_name(k)
        for thinking in (True, False):
            t0 = time.monotonic()
            log.info("llm start %s model=%s thinking=%s prompt_chars=%d", label, name, thinking, len(prompt))
            try:
                res = await asyncio.wait_for(structured(model_cls, k, thinking).ainvoke(prompt),
                                             timeout=settings.llm_hard_timeout)
                if res is None:
                    raise ValueError("model returned no structured output")
                log.info("llm ok %s model=%s %.1fs", label, name, time.monotonic() - t0)
                return res
            except Exception as e:  # noqa: BLE001 - we log and fall back
                last = e
                kind_err = "timed out" if isinstance(e, asyncio.TimeoutError) else f"{type(e).__name__}: {str(e)[:300]}"
                log.warning("llm fail %s model=%s after %.1fs: %s", label, name, time.monotonic() - t0, kind_err)
                if thinking and "thinking" in str(e).lower():
                    continue  # retry the same model without the thinking setting
                break
        if i + 1 < len(kinds) and notify:
            notify(f"{label}: {name} failed ({type(last).__name__}); retrying with {model_name(kinds[i + 1])}")
    assert last is not None
    raise last
