from datetime import datetime, timedelta, timezone

import pandas as pd

from application.decide import decide
from application.snapshot import build_snapshot
from domain.types import Candle, GateConfig, ReasonCode, Reject, SignalDraft

BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles(count=5):
    return [
        Candle(
            timestamp=BASE + timedelta(hours=i),
            open=100.0 + i,
            high=102.0 + i,
            low=99.0 + i,
            close=101.0 + i,
            volume=1000.0,
        )
        for i in range(count)
    ]


def _snapshot(candles, score=0.9, side="buy"):
    return build_snapshot(
        "BTC/USDT",
        "1h",
        candles,
        score=score,
        confidence=0.8,
        side=side,
        entry=105.0,
        stop=100.0,
        target=115.0,
        trend_strength="STRONG",
        volume_surge=2.0,
    )


def test_live_and_backtest_paths_agree_on_identical_data():
    config = GateConfig()
    live = decide(_snapshot(_candles()), config)
    backtest = decide(_snapshot(_candles()), config)
    assert isinstance(live, SignalDraft)
    assert live == backtest


def test_low_score_rejects_without_side_effects():
    outcome = decide(_snapshot(_candles(), score=0.1), GateConfig())
    assert isinstance(outcome, Reject)
    assert outcome.reason == ReasonCode.SCORE_TOO_LOW


def test_unknown_side_rejects():
    outcome = decide(_snapshot(_candles(), side="hold"), GateConfig())
    assert isinstance(outcome, Reject)
    assert outcome.reason == ReasonCode.DIRECTION_CONFLICT


def test_weak_trend_rejects_when_strong_required():
    snapshot = _snapshot(_candles())
    rigid = GateConfig(min_trend_strength="STRONG")
    weak = build_snapshot(
        snapshot.symbol,
        snapshot.timeframe,
        list(snapshot.candles),
        score=snapshot.score,
        confidence=snapshot.confidence,
        side=snapshot.side,
        entry=snapshot.entry,
        stop=snapshot.stop,
        target=snapshot.target,
        trend_strength="WEAK",
        volume_surge=snapshot.volume_surge,
    )
    outcome = decide(weak, rigid)
    assert isinstance(outcome, Reject)
    assert outcome.reason == ReasonCode.TREND_TOO_WEAK


def test_fixture_prefixes_decide_identically_on_both_paths():
    frame = pd.read_csv(
        "tests/fixtures/ohlcv_1h.csv", index_col=0, parse_dates=True
    ).tail(300)
    config = GateConfig()
    for end in range(10, len(frame) + 1, 10):
        window = frame.iloc[:end]
        candles = [
            Candle(
                timestamp=stamp.to_pydatetime(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for stamp, row in window.iterrows()
        ]
        live = decide(_snapshot(candles), config)
        backtest = decide(_snapshot(list(candles)), config)
        assert live == backtest
