"""Guards for exception-narrowing and mutable-default fixes.

Covers the [behavior-change] lint fixes: bare `except:` narrowed to
`except Exception` (BaseException such as CancelledError / KeyboardInterrupt
must propagate) and mutable `["BTC", "ETH"]` defaults replaced with a
None sentinel (each call gets a fresh list).
"""

import asyncio
import inspect
from datetime import datetime, timezone

import pandas as pd
import pytest

import app.telegram_bot as telegram_bot_mod
import common.utils as utils_mod
from common.core import SignalType, TradingSignal
from data.data_provider import MarketDataProvider
from data.sources.news_fetcher import NewsFetcher


def _ohlcv_frame(n: int = 60) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1000.0] * n,
        }
    )


def _signal(reasons: list) -> TradingSignal:
    return TradingSignal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        entry_price=100.0,
        exit_price=110.0,
        stop_loss=95.0,
        timestamp=datetime.now(timezone.utc),
        timeframe="1h",
        confidence_score=80.0,
        reasons=reasons,
        risk_reward_ratio=2.0,
        predicted_profit=10.0,
        volume_analysis={},
        market_context={},
        dynamic_levels={},
    )


def test_detect_market_regime_propagates_base_exception(monkeypatch):
    """KeyboardInterrupt from TA-Lib must not be swallowed as adx=20."""

    def _boom(*args, **kwargs):
        raise KeyboardInterrupt("simulated interrupt")

    monkeypatch.setattr(utils_mod.talib, "ADX", _boom)
    with pytest.raises(KeyboardInterrupt):
        utils_mod.detect_market_regime(_ohlcv_frame())


def test_format_signal_message_propagates_cancelled(monkeypatch):
    """CancelledError during reason formatting must propagate (clean shutdown)."""
    handler = telegram_bot_mod.TelegramBotHandler.__new__(telegram_bot_mod.TelegramBotHandler)
    calls = {"n": 0}
    real_escape = telegram_bot_mod.escape_markdown_v2

    def _flaky(text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.CancelledError("simulated cancellation")
        return real_escape(text)

    monkeypatch.setattr(telegram_bot_mod, "escape_markdown_v2", _flaky)
    with pytest.raises(asyncio.CancelledError):
        handler.format_signal_message(_signal(["trend up (Score: 1.5)"]))


class _FakeCryptoPanic:
    def __init__(self):
        self.seen: list = []

    async def fetch_posts(self, currencies=None, kind=None):
        self.seen.append(list(currencies) if currencies else [])
        return [{"id": 1, "title": "btc up", "currencies": [{"code": "BTC"}]}]

    async def close(self):
        return None


class _FakeAlternativeMe:
    async def fetch_fear_greed(self, limit=1):
        return [{"value": "50", "value_classification": "Neutral"}]

    async def close(self):
        return None


def _news_fetcher() -> NewsFetcher:
    return NewsFetcher(
        cryptopanic_fetcher=_FakeCryptoPanic(),
        alternativeme_fetcher=_FakeAlternativeMe(),
        redis_client=None,
    )


def test_fetch_news_default_currencies_are_fresh():
    """fetch_news() with no args resolves ["BTC","ETH"] without shared state."""

    async def _run():
        fetcher = _news_fetcher()
        first = await fetcher.fetch_news()
        second = await fetcher.fetch_news()
        seen = fetcher.cryptopanic.seen
        assert seen[0] == ["BTC", "ETH"]
        assert seen[1] == ["BTC", "ETH"]
        assert seen[0] is not seen[1]
        expected = [{"id": 1, "title": "btc up", "currencies": [{"code": "BTC"}]}]
        assert first == second == expected

    asyncio.run(_run())


def test_fetch_sentiment_default_currencies_are_fresh():
    """fetch_sentiment_analysis() defaults without a shared mutable default."""

    async def _run():
        fetcher = _news_fetcher()
        first = await fetcher.fetch_sentiment_analysis()
        second = await fetcher.fetch_sentiment_analysis()
        assert first["news_count"] == 1
        assert second["news_count"] == 1
        seen = fetcher.cryptopanic.seen
        assert seen[0] == ["BTC", "ETH"]
        assert seen[0] is not seen[1]

    asyncio.run(_run())


@pytest.mark.parametrize(
    "obj,method",
    [
        (NewsFetcher, "fetch_news"),
        (NewsFetcher, "fetch_sentiment_analysis"),
        (MarketDataProvider, "get_news_sentiment"),
    ],
)
def test_no_mutable_list_defaults(obj, method):
    """Guard against reintroducing shared mutable argument defaults."""
    sig = inspect.signature(getattr(obj, method))
    for param in sig.parameters.values():
        assert not isinstance(param.default, (list, dict, set)), (
            f"{obj.__name__}.{method}: mutable default for {param.name}"
        )
