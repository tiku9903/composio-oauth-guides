"""call_structured: candidate chain, hard timeout, retry without thinking, Gemini model discovery."""
import asyncio

from pydantic import BaseModel

from oauthguides import config, llm


class Out(BaseModel):
    ok: bool = True


class Runner:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    async def ainvoke(self, prompt):
        return await self.behaviour()


def _patch(monkeypatch, plan, available=None):
    calls = []

    def fake_structured(model_cls, name, thinking=True):
        calls.append((name.split(":")[-1], thinking))
        return Runner(plan.pop(0))

    monkeypatch.setattr(llm, "structured", fake_structured)
    monkeypatch.setattr(llm, "_gemini_checked", True)
    monkeypatch.setattr(llm, "_gemini_models", available)
    object.__setattr__(config.settings, "llm_hard_timeout", 0.2)
    object.__setattr__(config.settings, "rate_limit_wait", 0)
    object.__setattr__(config.settings, "model", "google_genai:main-model")
    object.__setattr__(config.settings, "fast_model", "google_genai:fast-model")
    return calls


async def _ok():
    return Out()


def test_stuck_main_model_falls_back(monkeypatch):
    async def hang():
        await asyncio.sleep(5)

    calls = _patch(monkeypatch, [hang, _ok])
    notes = []
    res = asyncio.run(llm.call_structured(Out, "p", "main", "synthesize", notes.append))
    assert res.ok and calls == [("main-model", True), ("fast-model", True)]
    assert notes and "trying fast-model" in notes[0]


def test_thinking_rejected_retries_same_model_without_it(monkeypatch):
    async def reject():
        raise ValueError("Invalid argument: thinking_level is not supported for this model")

    calls = _patch(monkeypatch, [reject, _ok])
    res = asyncio.run(llm.call_structured(Out, "p", "fast", "extract"))
    assert res.ok and calls == [("fast-model", True), ("fast-model", False)]


def test_unusable_configured_model_is_skipped_for_discovered_ones(monkeypatch):
    # The key can't use "main-model" (wrong name / no free quota); discovery finds real flash models.
    calls = _patch(monkeypatch, [_ok], available=["gemini-9.1-flash", "gemini-9.0-flash", "gemini-9.1-flash-lite", "fast-model"])
    res = asyncio.run(llm.call_structured(Out, "p", "main", "synthesize"))
    assert res.ok and calls == [("gemini-9.1-flash", True)]
    assert llm.candidates("main")[:2] == ["google_genai:gemini-9.1-flash", "google_genai:gemini-9.0-flash"]
    assert llm.candidates("fast")[0] == "google_genai:fast-model"


def test_raises_after_all_fallbacks(monkeypatch):
    async def boom():
        raise RuntimeError("quota exceeded")

    _patch(monkeypatch, [boom, boom])
    try:
        asyncio.run(llm.call_structured(Out, "p", "main", "synthesize"))
    except RuntimeError as e:
        assert "quota" in str(e)
    else:
        raise AssertionError("expected failure")


def test_rate_limit_waits_and_retries_same_model_before_falling_back(monkeypatch):
    async def limited():
        raise RuntimeError("429 RESOURCE_EXHAUSTED: rate limit")

    calls = _patch(monkeypatch, [limited, _ok])
    object.__setattr__(config.settings, "rate_limit_wait", 0.01)
    notes = []
    res = asyncio.run(llm.call_structured(Out, "p", "main", "synthesize", notes.append))
    assert res.ok and calls == [("main-model", True), ("main-model", False)]  # same model, not the lite one
    assert "rate-limited" in notes[0]
