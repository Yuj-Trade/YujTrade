import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.telegram_bot import TelegramBotHandler
from application.performance_report import (
    DrawdownSummary,
    PerformanceReport,
)
from config.settings import ConfigManager


def _report(**overrides) -> PerformanceReport:
    base = {
        "report_version": "performance-report-v1",
        "mode": "paper",
        "as_of": "2026-10-20T12:00:00.000000+00:00",
        "period_start": "2026-10-01",
        "period_end": "2026-10-20",
        "status": "ok",
        "total_resolved": 12,
        "exit_counts": {"stop": 3, "target": 6, "expired": 2, "no_data": 1},
        "win_rate": 0.5,
        "profit_factor": 1.85,
        "expectancy_r": 0.42,
        "initial_equity": 10000.0,
        "final_equity": 10421.0,
        "total_return": 0.0421,
        "max_drawdown": DrawdownSummary(
            depth=0.031,
            peak_index=2,
            trough_index=7,
            peak_time="2026-10-05T10:00:00.000000+00:00",
            trough_time="2026-10-11T10:00:00.000000+00:00",
            duration_trades=5,
        ),
        "sharpe": 1.24,
        "sortino": 1.8,
        "parameters": {
            "initial_cash": 10000.0,
            "risk_per_trade_pct": 1.0,
            "fee_rate": 0.001,
            "slippage_rate": 0.0005,
            "rf_annual": 0.0,
            "periods_per_year": 365.0,
            "min_trades_for_ratios": 30,
        },
        "data_hash": "abcdef0123456789" * 4,
        "config_hash": "1234567890abcdef" * 4,
    }
    base.update(overrides)
    return PerformanceReport(**base)


def _handler(tmp_path, report):
    config_manager = ConfigManager(
        config_path=str(tmp_path / "config.json"),
        weights_path=str(tmp_path / "weights.json"),
    )
    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.trading_service = MagicMock(name="TradingService")
    handler.trading_service.signal_tracker.get_performance_summary.return_value = {
        "total": 12,
        "win_rate": 50.0,
        "pending": 3,
    }
    handler.trading_service.build_performance_report = AsyncMock(return_value=report)
    handler.config_manager = config_manager
    return handler


def _update():
    update = MagicMock(name="Update")
    update.message.reply_text = AsyncMock()
    return update


def test_the_command_keeps_the_summary_lines_and_adds_the_report(tmp_path):
    handler = _handler(tmp_path, _report())
    update = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.performance_command(update, MagicMock(name="Context")))

    update.message.reply_text.assert_awaited_once()
    text = str(update.message.reply_text.await_args.args[0])
    assert "Total: 12" in text
    assert "Win rate: 50\\.0%" in text
    assert "Pending: 3" in text
    assert "Trades: 12" in text
    assert "Status: ok" in text
    assert "Profit factor: 1\\.85" in text
    assert "Expectancy: 0\\.42R" in text
    assert "Return: 4\\.21%" in text
    assert "MDD: \\-3\\.10%" in text
    assert "Sharpe: 1\\.24" in text
    assert "Sortino: 1\\.80" in text
    assert "No data: 1" in text
    assert "Data hash: abcdef01" in text


def test_the_command_stays_below_the_telegram_limit(tmp_path):
    handler = _handler(tmp_path, _report())
    update = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.performance_command(update, MagicMock(name="Context")))

    text = str(update.message.reply_text.await_args.args[0])
    assert len(text) < 4096


def test_the_command_renders_a_missing_ratio(tmp_path):
    handler = _handler(tmp_path, _report(sharpe=None, sortino=None))
    update = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.performance_command(update, MagicMock(name="Context")))

    text = str(update.message.reply_text.await_args.args[0])
    assert "Sharpe: n/a" in text
    assert "Sortino: n/a" in text


def test_a_non_administrator_gets_no_message(tmp_path):
    handler = _handler(tmp_path, _report())
    update = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=False)):
        asyncio.run(handler.performance_command(update, MagicMock(name="Context")))

    update.message.reply_text.assert_not_awaited()


def test_a_failing_report_still_renders_the_summary(tmp_path):
    handler = _handler(tmp_path, _report())
    handler.trading_service.build_performance_report = AsyncMock(side_effect=RuntimeError("boom"))
    update = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.performance_command(update, MagicMock(name="Context")))

    update.message.reply_text.assert_awaited_once()
    text = str(update.message.reply_text.await_args.args[0])
    assert "Total: 12" in text
    assert "Trades:" not in text
