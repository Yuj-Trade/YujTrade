"""TradingService paper execution: submit, fill, persist, resolve, restart."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from common.core import SignalType, TradingSignal
from config.settings import ConfigManager
from domain.costs import CostProfile
from services.trading_service import TradingService
from trading.ledger import PaperLedger
from trading.paper_trading import PaperTradingEngine
from trading.portfolio import PortfolioManager
from trading.risk_manager import RiskConfig, RiskManager

PROFILE = CostProfile(
    version="cost-model-v2",
    maker_fee_rate=0.001,
    taker_fee_rate=0.001,
    entry_liquidity="taker",
    target_exit_liquidity="maker",
    stop_exit_liquidity="taker",
    expiry_exit_liquidity="taker",
    entry_slippage_rate=0.0005,
    market_exit_slippage_rate=0.0005,
    target_exit_slippage_rate=0.0,
    funding_rate_per_period=0.0001,
    funding_period_hours=8.0,
    max_volume_participation=0.05,
)

_NOW = datetime.now(UTC)
_CLOSED = _NOW.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


def _signal(**overrides) -> TradingSignal:
    base = {
        "symbol": "BTC/USDT",
        "signal_type": SignalType.BUY,
        "entry_price": 100.0,
        "exit_price": 120.0,
        "stop_loss": 90.0,
        "timestamp": _CLOSED,
        "timeframe": "1h",
        "confidence_score": 90.0,
        "reasons": ["trend"],
        "risk_reward_ratio": 3.0,
        "predicted_profit": 20.0,
        "volume_analysis": {"volume_ratio": 2.0},
        "market_context": {"trend_strength": "STRONG"},
        "dynamic_levels": {},
    }
    base.update(overrides)
    return TradingSignal(**base)


def _frame(rows, start=_CLOSED):
    return pd.DataFrame(
        [
            {"open": close, "high": high, "low": low, "close": close, "volume": volume}
            for high, low, close, volume in rows
        ],
        index=[start + timedelta(hours=index) for index in range(len(rows))],
    )


def _service(tmp_path, *, provider=None, enabled=True, ledger=None, engine=None):
    service = TradingService.__new__(TradingService)
    config = ConfigManager(
        config_path=str(tmp_path / "config.json"),
        weights_path=str(tmp_path / "weights.json"),
    )
    config.set("paper_execution_enabled", enabled)
    service.config_manager = config
    service.market_data_provider = provider or SimpleNamespace(
        fetch_ohlcv_data=AsyncMock(return_value=_frame([(121.0, 99.0, 100.0, 1e9)])),
        fetch_ohlcv_range=AsyncMock(return_value=_frame([(101.0, 99.0, 100.0, 1e9)])),
    )
    service.performance_ledger = ledger or PaperLedger(tmp_path / "paper_ledger.db")
    service.portfolio = PortfolioManager(100000.0)
    service.paper_engine = engine or PaperTradingEngine(
        portfolio=service.portfolio,
        risk_manager=RiskManager(RiskConfig(min_risk_reward=2.0)),
        fee_rate=0.001,
        slippage_rate=0.0005,
        cost_profile=PROFILE,
    )
    service._paper_barriers = {}
    service._paper_positions_ready = False
    service._cycle_log = MagicMock()
    return service


async def test_an_accepted_signal_fills_and_persists(tmp_path):
    service = _service(tmp_path)

    result = await service.execute_signal(_signal())

    assert result["ok"] is True
    assert result["filled_quantity"] > 0
    assert result["fill_ratio"] == pytest.approx(1.0)
    assert result["fill_price"] == pytest.approx(100.0 * 1.0005)
    assert await service.performance_ledger.has_order(result["position_id"]) is False
    open_rows = await service.performance_ledger.load_open_positions()
    assert len(open_rows) == 1
    assert open_rows[0]["position_id"] == result["position_id"]


async def test_an_unsupported_mode_is_refused(tmp_path):
    service = _service(tmp_path)

    result = await service.execute_signal(_signal(), mode="live")

    assert result == {"ok": False, "reason": "unsupported_mode"}


async def test_the_kill_switch_refuses_execution(tmp_path):
    service = _service(tmp_path, enabled=False)

    result = await service.execute_signal(_signal())

    assert result == {"ok": False, "reason": "paper_execution_disabled"}


async def test_a_duplicate_signal_is_refused(tmp_path):
    service = _service(tmp_path)
    first = await service.execute_signal(_signal())
    assert first["ok"] is True

    second = await service.execute_signal(_signal())

    assert second == {"ok": False, "reason": "duplicate_signal"}


async def test_a_missing_mark_price_is_refused(tmp_path):
    provider = SimpleNamespace(
        fetch_ohlcv_data=AsyncMock(return_value=pd.DataFrame()),
        fetch_ohlcv_range=AsyncMock(return_value=pd.DataFrame()),
    )
    service = _service(tmp_path, provider=provider)

    result = await service.execute_signal(_signal())

    assert result == {"ok": False, "reason": "no_mark_price"}


async def test_a_risk_rejection_is_refused(tmp_path):
    service = _service(tmp_path)

    result = await service.execute_signal(_signal(risk_reward_ratio=1.0))

    assert result == {"ok": False, "reason": "risk_rejected"}


async def test_a_zero_fill_is_refused(tmp_path):
    provider = SimpleNamespace(
        fetch_ohlcv_data=AsyncMock(return_value=_frame([(121.0, 99.0, 100.0, 0.0)])),
        fetch_ohlcv_range=AsyncMock(return_value=pd.DataFrame()),
    )
    service = _service(tmp_path, provider=provider)

    result = await service.execute_signal(_signal())

    assert result == {"ok": False, "reason": "unfilled"}


async def test_a_partial_fill_is_recorded_and_the_remainder_discarded(tmp_path):
    provider = SimpleNamespace(
        fetch_ohlcv_data=AsyncMock(return_value=_frame([(121.0, 99.0, 100.0, 5.0)])),
        fetch_ohlcv_range=AsyncMock(return_value=pd.DataFrame()),
    )
    service = _service(tmp_path, provider=provider)

    result = await service.execute_signal(_signal())

    assert result["ok"] is True
    assert 0.0 < result["fill_ratio"] < 1.0
    open_rows = await service.performance_ledger.load_open_positions()
    assert open_rows[0]["quantity"] == pytest.approx(result["filled_quantity"])


async def test_resolution_closes_a_position_at_the_target(tmp_path):
    service = _service(tmp_path)
    result = await service.execute_signal(_signal())
    opened = service.portfolio.positions[result["position_id"]].opened_at
    candles = _frame(
        [(101.0, 99.0, 100.0, 1e9)] * 1 + [(121.0, 99.0, 100.0, 1e9)] * 12,
        start=opened,
    )
    service.market_data_provider.fetch_ohlcv_range = AsyncMock(return_value=candles)
    now = opened + timedelta(hours=11)

    closed = await service.resolve_open_paper_positions(now)

    assert closed == 1
    assert await service.performance_ledger.load_open_positions() == []


async def test_a_no_data_window_keeps_the_position_open(tmp_path):
    service = _service(tmp_path)
    result = await service.execute_signal(_signal())
    opened = service.portfolio.positions[result["position_id"]].opened_at
    service.market_data_provider.fetch_ohlcv_range = AsyncMock(return_value=pd.DataFrame())
    now = opened + timedelta(hours=1)

    closed = await service.resolve_open_paper_positions(now)

    assert closed == 0
    assert result["position_id"] in service.portfolio.positions


async def test_a_restart_rehydrates_open_positions_and_skips_closed(tmp_path):
    service = _service(tmp_path)
    first = await service.execute_signal(_signal())
    assert first["ok"] is True
    await service.performance_ledger.append_position_closed(
        "closed-1",
        110.0,
        "target",
        _NOW,
        0.0,
        0.0,
        10.0,
        _NOW,
    )
    await service.performance_ledger.append_position_opened(
        "closed-1", "sig-closed", "BTC/USDT", "1h", "buy", 1.0, 100.0, 90.0, 110.0, 0.0, _NOW
    )

    restarted = _service(tmp_path)
    count = await restarted.rehydrate_paper_positions()

    assert count == 1
    assert first["position_id"] in restarted.portfolio.positions
    assert "closed-1" not in restarted.portfolio.positions


async def test_portfolio_snapshot_reports_the_paper_book(tmp_path):
    service = _service(tmp_path)
    await service.execute_signal(_signal())

    snap = await service.portfolio_snapshot()

    assert set(snap) == {
        "equity",
        "cash",
        "exposure_pct",
        "open_positions",
        "unrealized_pnl",
        "realized_pnl",
    }
    assert snap["open_positions"] == 1
