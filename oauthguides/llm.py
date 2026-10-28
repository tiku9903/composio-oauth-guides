"""Model access. Provider-agnostic through LangChain's init_chat_model.

MODEL=google_genai:gemini-3.8-flash (default, free tier) or e.g. anthropic:claude-sonnet-5-5, openai:gpt-5.
Tests inject a fake via set_llm_factory().
"""
from __future__ import annotations

from typing import Any, Callable

from .config import settings

_factory: Callable[[str], Any] | None = None


def set_llm_factory(factory: Callable[[str], Any] | None) -> None:
    """Override model construction (used by tests and offline demos)."""
    global _factory
    _factory = factory


def get_llm(kind: str = "main") -> Any:
    name = settings.model if kind == "main" else settings.fast_model
    if _factory is not None:
        return _factory(name)
    from langchain.chat_models import init_chat_model

    return init_chat_model(name, temperature=0, max_tokens=16000, timeout=180, max_retries=6)


def structured(model_cls: type, kind: str = "main") -> Any:
    """A runnable that returns an instance of `model_cls`."""
    return get_llm(kind).with_structured_output(model_cls)
