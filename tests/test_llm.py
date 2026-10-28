"""call_structured: hard timeout, fallback to FAST_MODEL, retry without thinking."""
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


def _patch(monkeypatch, plan):
    """plan: list of async callables, consumed one per model construction."""
    calls = []

    def fake_structured(model_cls, kind="main", thinking=True):
        calls.append((kind, thinking))
        return Runner(plan.pop(0))

    monkeypatch.setattr(llm, "structured", fake_structured)
    object.__setattr__(config.settings, "llm_hard_timeout", 0.2)
    object.__setattr__(config.settings, "model", "google_genai:main-model")
    object.__setattr__(config.settings, "fast_model", "google_genai:fast-model")
    return calls


def test_stuck_main_model_falls_back_to_fast(monkeypatch):
    async def hang():
        await asyncio.sleep(5)

    async def ok():
        return Out()

    calls = _patch(monkeypatch, [hang, ok])
    notes = []
    res = asyncio.run(llm.call_structured(Out, "p", "main", "synthesize", notes.append))
    assert res.ok and calls == [("main", True), ("fast", True)]
    assert notes and "retrying with google_genai:fast-model" in notes[0]


def test_thinking_rejected_retries_same_model_without_it(monkeypatch):
    async def reject():
        raise ValueError("Invalid argument: thinking_level is not supported for this model")

    async def ok():
        return Out()

    calls = _patch(monkeypatch, [reject, ok])
    res = asyncio.run(llm.call_structured(Out, "p", "fast", "extract"))
    assert res.ok and calls == [("fast", True), ("fast", False)]


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
