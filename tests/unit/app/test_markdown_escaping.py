"""The Telegram messages must be valid MarkdownV2.

The Bot API rejects a message whose reserved characters are not escaped
with "Can't parse entities". The validator below mirrors the rule: a
reserved character must be preceded by an odd number of backslashes, a
backslash must escape a reserved character or another backslash, and
inside a code span only the backtick and the backslash need escaping.

The regression that started this file: the welcome text escaped its
parentheses in the source and `escape_markdown_v2` escaped them a second
time, so Telegram received `\\(` and rejected the message.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.telegram_bot import (
    TelegramBotHandler,
    escape_code_span,
    escape_markdown_v2,
)
from common.core import SignalType, TradingSignal

RESERVED = set("_*[]()~`>#+-=|{}.!")


def _violations(text: str, allow_bold: bool = False) -> list[str]:
    problems: list[str] = []
    in_code = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            following = text[index + 1] if index + 1 < len(text) else ""
            if not following or not (following in RESERVED or following == "\\"):
                problems.append(f"dangling escape before {following!r}")
            index += 2
            continue
        if char == "`":
            in_code = not in_code
            index += 1
            continue
        if in_code:
            index += 1
            continue
        if char in RESERVED and not (allow_bold and char == "*"):
            problems.append(f"unescaped {char!r}")
        index += 1
    return problems


def _handler(trading_service=None):
    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.trading_service = trading_service or MagicMock(name="TradingService")
    handler.config_manager = MagicMock(name="ConfigManager")
    handler.admin_chat_id = "123"
    return handler


def _update():
    update = MagicMock(name="Update")
    update.message.reply_text = AsyncMock()
    context = MagicMock(name="Context")
    context.args = []
    return update, context


def _sent_texts(update) -> list[str]:
    return [str(call.args[0]) for call in update.message.reply_text.await_args_list]


def _signal(**overrides) -> TradingSignal:
    base = {
        "symbol": "BTC/USDT",
        "signal_type": SignalType.BUY,
        "entry_price": 65120.3835350434,
        "exit_price": 70000.0,
        "stop_loss": 62000.0,
        "timestamp": datetime.now(UTC),
        "timeframe": "1d",
        "confidence_score": 72.5,
        "reasons": ["RSI oversold (Score: 1.20)", "MACD bullish cross", "Trend *up*"],
        "risk_reward_ratio": 3.4,
        "predicted_profit": 7.4,
        "volume_analysis": {"volume_ratio": 1.8},
        "market_context": {
            "trend": "bullish",
            "trend_strength": "STRONG",
            "market_condition": "oversold",
            "volatility": 2.5,
            "support_levels": [61000.0],
            "resistance_levels": [71000.0],
        },
        "dynamic_levels": {
            "primary_entry": 65120.3835350434,
            "secondary_entry": 64000.0,
            "primary_exit": 70000.0,
            "secondary_exit": 71000.0,
            "tight_stop": 63000.0,
            "wide_stop": 61000.0,
            "breakeven_point": 65120.0,
        },
    }
    base.update(overrides)
    return TradingSignal(**base)


def test_escape_markdown_v2_escapes_every_reserved_character():
    escaped = escape_markdown_v2("a_b*c[d]e(f)g~h`i>j#k+l-m=n|o{p}q.r!s\\t")

    assert _violations(escaped) == []


def test_escape_markdown_v2_escapes_the_backslash():
    escaped = escape_markdown_v2(r"C:\path\to\file")

    assert escaped == r"C:\\path\\to\\file"
    assert _violations(escaped) == []


def test_escape_code_span_escapes_only_the_backtick_and_the_backslash():
    escaped = escape_code_span("a_b`c\\d.e")

    assert escaped == "a_b\\`c\\\\d.e"
    assert _violations(f"`{escaped}`", allow_bold=True) == []


def test_the_welcome_text_is_a_valid_markdown_v2_message():
    handler = _handler()
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.start(update, context))

    texts = _sent_texts(update)
    assert texts
    for text in texts:
        assert _violations(text) == []


def test_the_welcome_text_escapes_the_parentheses_once():
    handler = _handler()
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.start(update, context))

    text = _sent_texts(update)[0]
    assert "\\\\(" not in text
    assert "\\(" in text


def test_the_status_message_is_a_valid_markdown_v2_message():
    handler = _handler()
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.status(update, context))

    for text in _sent_texts(update):
        assert _violations(text) == []


def test_the_no_signal_message_is_a_valid_markdown_v2_message():
    handler = _handler()
    handler.trading_service.last_errors = 2
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.signals_command(update, context))

    for text in _sent_texts(update):
        assert _violations(text) == []


def test_the_paper_message_is_a_valid_markdown_v2_message():
    trading_service = MagicMock(name="TradingService")
    signal = MagicMock(name="Signal")
    signal.symbol = "BTC/USDT"
    signal.timeframe = "1h"
    trading_service.run_quick_analysis = AsyncMock(return_value=[signal])
    trading_service.execute_signal = AsyncMock(return_value={"ok": True})
    handler = _handler(trading_service)
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.paper_command(update, context))

    for text in _sent_texts(update):
        assert _violations(text) == []


def test_the_performance_message_is_a_valid_markdown_v2_message():
    trading_service = MagicMock(name="TradingService")
    trading_service.signal_tracker.get_performance_summary.return_value = {
        "total": 12,
        "win_rate": 50.0,
        "pending": 3,
    }
    handler = _handler(trading_service)
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.performance_command(update, context))

    for text in _sent_texts(update):
        assert _violations(text) == []


def test_the_risk_message_is_a_valid_markdown_v2_message():
    handler = _handler()
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.risk_command(update, context))

    for text in _sent_texts(update):
        assert _violations(text) == []


def test_the_health_message_is_a_valid_markdown_v2_message():
    handler = _handler()
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.health_command(update, context))

    for text in _sent_texts(update):
        assert _violations(text) == []


def test_the_signal_messages_are_valid_markdown_v2_messages():
    handler = _handler()

    for message in handler.format_signal_message(_signal()):
        assert _violations(message, allow_bold=True) == []


def test_the_signal_messages_have_no_stray_escape_inside_a_code_span():
    handler = _handler()

    for message in handler.format_signal_message(_signal()):
        inside = False
        index = 0
        while index < len(message):
            char = message[index]
            if char == "\\":
                following = message[index + 1] if index + 1 < len(message) else ""
                if inside and following not in ("`", "\\"):
                    raise AssertionError(f"stray escape inside a code span: {message!r}")
                index += 2
                continue
            if char == "`":
                inside = not inside
            index += 1


def test_the_signal_message_shows_the_prices_without_a_stray_backslash():
    handler = _handler()

    messages = handler.format_signal_message(_signal())

    assert any("`72.50%`" in message for message in messages)
    assert any("`65120.38353504`" in message for message in messages)


def test_the_portfolio_message_is_a_valid_markdown_v2_message():
    trading_service = MagicMock(name="TradingService")
    trading_service.portfolio_snapshot = AsyncMock(
        return_value={
            "equity": 10000.0,
            "cash": 9000.0,
            "exposure_pct": 10.0,
            "open_positions": 1,
            "unrealized_pnl": 12.5,
            "realized_pnl": 3.25,
        }
    )
    handler = _handler(trading_service)
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.portfolio_command(update, context))

    for text in _sent_texts(update):
        assert _violations(text) == []


def test_the_free_text_answer_is_a_valid_markdown_v2_message():
    handler = _handler()
    update, context = _update()

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.handle_message(update, context))

    for text in _sent_texts(update):
        assert _violations(text) == []


def test_the_quick_analysis_message_is_a_valid_markdown_v2_message():
    trading_service = MagicMock(name="TradingService")
    trading_service.run_quick_analysis = AsyncMock(return_value=[])
    handler = _handler(trading_service)
    handler.background_tasks = MagicMock()
    handler.background_tasks.create_task = lambda coro, name=None: coro.close()
    update = MagicMock(name="Update")
    update.callback_query = None
    context = MagicMock(name="Context")
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.args = []

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.quick_analyze(update, context))

    for call in context.bot.send_message.await_args_list:
        assert _violations(str(call.args[1])) == []


def test_the_full_analysis_message_is_a_valid_markdown_v2_message():
    trading_service = MagicMock(name="TradingService")
    trading_service.run_analysis_for_all_symbols = AsyncMock(return_value=[])
    handler = _handler(trading_service)
    handler.background_tasks = MagicMock()
    handler.background_tasks.create_task = lambda coro, name=None: coro.close()
    update = MagicMock(name="Update")
    update.callback_query = None
    context = MagicMock(name="Context")
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.args = []

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.full_analyze(update, context))

    for call in context.bot.send_message.await_args_list:
        assert _violations(str(call.args[1])) == []


def test_the_delivered_signal_messages_are_valid_markdown_v2_messages():
    trading_service = MagicMock(name="TradingService")
    handler = _handler(trading_service)
    handler.application = MagicMock()
    handler.application.bot = MagicMock()
    handler.application.bot.send_message = AsyncMock()

    asyncio.run(
        handler.send_signals_to_telegram(
            [_signal()],
            "123",
            "Full Analyze completed.",
            "No signals found across all timeframes.",
        )
    )

    for call in handler.application.bot.send_message.await_args_list:
        assert _violations(str(call.args[1]), allow_bold=True) == []


def test_the_no_signal_delivery_is_a_valid_markdown_v2_message():
    trading_service = MagicMock(name="TradingService")
    handler = _handler(trading_service)
    handler.application = MagicMock()
    handler.application.bot = MagicMock()
    handler.application.bot.send_message = AsyncMock()

    asyncio.run(
        handler.send_signals_to_telegram(
            [],
            "123",
            "Full Analyze completed.",
            "No signals found across all timeframes.",
        )
    )

    for call in handler.application.bot.send_message.await_args_list:
        assert _violations(str(call.args[1])) == []
