"""Learning alerts: renderer, buffer and isolation (P8)."""

from datetime import UTC, datetime

import pytest

from application.learning_alerts import (
    AlertBuffer,
    LearningEvent,
    render_learning_event,
)


def _event(kind="promoted", **overrides) -> LearningEvent:
    base = {
        "kind": kind,
        "key": "xgboost-BTC/USDT-1h",
        "model_type": "xgboost",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "version": "v2",
        "reasons": ("rmse_ok",),
        "at": datetime(2026, 10, 29, 12, tzinfo=UTC),
    }
    base.update(overrides)
    return LearningEvent(**base)


def test_the_renderer_is_plain_text():
    text = render_learning_event(_event())

    assert text.startswith("[learning] promoted: xgboost-BTC/USDT-1h")
    assert "BTC/USDT 1h" in text
    assert "version v2" in text
    assert "reasons: rmse_ok" in text
    assert "2026-10-29T12:00:00Z" in text


def test_an_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        _event(kind="exploded")


def test_a_naive_instant_is_rejected():
    with pytest.raises(ValueError):
        _event(at=datetime(2026, 10, 29, 12))


async def test_the_buffer_holds_events_before_attach():
    buffer = AlertBuffer()
    await buffer.send(_event())
    await buffer.send(_event(kind="rejected"))

    assert len(buffer) == 2


async def test_attach_flushes_in_order():
    buffer = AlertBuffer()
    await buffer.send(_event())
    await buffer.send(_event(kind="rejected"))
    sent: list[str] = []

    async def sender(text: str) -> None:
        sent.append(text)

    buffer.attach(sender)
    assert await buffer.flush() == 2
    assert sent[0].startswith("[learning] promoted")
    assert sent[1].startswith("[learning] rejected")
    assert len(buffer) == 0


async def test_a_sender_failure_is_reported_to_the_caller():
    buffer = AlertBuffer()

    async def sender(text: str) -> None:
        raise RuntimeError("telegram down")

    buffer.attach(sender)
    with pytest.raises(RuntimeError):
        await buffer.send(_event())


def test_the_buffer_is_bounded():
    buffer = AlertBuffer(maxlen=3)

    import asyncio

    async def _fill():
        for index in range(5):
            await buffer.send(_event(key=f"key-{index}"))

    asyncio.run(_fill())
    assert len(buffer) == 3
