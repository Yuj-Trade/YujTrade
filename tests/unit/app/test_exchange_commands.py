import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.telegram_bot import TelegramBotHandler
from domain.exchange_types import SHADOW, SUBMITTED
from trading.exchanges.execution_service import SubmitResult


def _handler(exchange_service=None, enabled=("binance",), profile="general"):
    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.trading_service = MagicMock(name="TradingService")
    handler.trading_service.exchange_service = exchange_service
    handler.config_manager = MagicMock(name="ConfigManager")
    handler.config_manager.get = MagicMock(
        side_effect=lambda key, default=None: {
            "exchange_access_profile": profile,
            "exchange_enabled": list(enabled),
        }.get(key, default)
    )
    return handler


def _update(args=None):
    update = MagicMock(name="Update")
    update.message.reply_text = AsyncMock()
    context = MagicMock(name="Context")
    context.args = args or []
    return update, context


class FakeExchangeService:
    def __init__(self, result=None):
        self.result = result or SubmitResult(
            ok=True, mode="sandbox", status=SUBMITTED, client_order_id="cid-1"
        )
        self.ledger = MagicMock()
        self.ledger.get_non_terminal = AsyncMock(
            return_value=[
                {
                    "client_order_id": "cid-1",
                    "exchange_id": "binance",
                    "status": "submitted",
                    "mode": "sandbox",
                    "filled": 0.0,
                    "reason": "submitted",
                }
            ]
        )
        self.submitted = []
        self.halted = 0
        self.resumed = 0

    async def order_status(self, client_order_id, exchange_id):
        return {
            "client_order_id": client_order_id,
            "exchange_id": exchange_id,
            "status": "submitted",
            "mode": "sandbox",
            "filled": 0.0,
            "reason": "",
        }

    async def submit_signal(self, **kwargs):
        self.submitted.append(kwargs)
        return self.result

    async def halt(self):
        self.halted += 1

    async def resume(self):
        self.resumed += 1


def _texts(update):
    return [str(call.args[0]) for call in update.message.reply_text.await_args_list]


def test_exchanges_lists_registry_with_profile():
    handler = _handler(exchange_service=FakeExchangeService())
    update, context = _update()
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchanges_command(update, context))
    text = "\n".join(_texts(update))
    assert "Binance" in text
    assert "iran profile" in text


def test_exchanges_marks_iran_venues_under_general_profile():
    handler = _handler(exchange_service=FakeExchangeService())
    update, context = _update()
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchanges_command(update, context))
    text = "\n".join(_texts(update))
    assert "iran users only" in text


def test_exchanges_rejects_non_admin():
    handler = _handler(exchange_service=FakeExchangeService())
    update, context = _update()
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=False)):
        asyncio.run(handler.exchanges_command(update, context))
    update.message.reply_text.assert_not_called()


def test_exchange_status_reports_row():
    handler = _handler(exchange_service=FakeExchangeService())
    update, context = _update(["cid-1"])
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchange_status_command(update, context))
    text = "\n".join(_texts(update))
    assert "cid" in text
    assert "submitted" in text


def test_exchange_status_without_service():
    handler = _handler(exchange_service=None)
    update, context = _update(["cid-1"])
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchange_status_command(update, context))
    assert "not configured" in "\n".join(_texts(update))


def test_exchange_status_requires_argument():
    handler = _handler(exchange_service=FakeExchangeService())
    update, context = _update()
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchange_status_command(update, context))
    assert "Usage" in "\n".join(_texts(update))


def test_exchange_halt_and_resume():
    service = FakeExchangeService()
    handler = _handler(exchange_service=service)
    update, context = _update()
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchange_halt_command(update, context))
        asyncio.run(handler.exchange_resume_command(update, context))
    assert service.halted == 1
    assert service.resumed == 1


def test_exchange_halt_rejects_non_admin():
    service = FakeExchangeService()
    handler = _handler(exchange_service=service)
    update, context = _update()
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=False)):
        asyncio.run(handler.exchange_halt_command(update, context))
    assert service.halted == 0
    update.message.reply_text.assert_not_called()


def test_exchange_execute_unknown_signal():
    service = FakeExchangeService()
    handler = _handler(exchange_service=service)
    handler.trading_service.run_quick_analysis = AsyncMock(return_value=[])
    update, context = _update(["binance", "missing-signal"])
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchange_execute_command(update, context))
    assert service.submitted == []
    assert "not found" in "\n".join(_texts(update))


def test_exchange_execute_matches_signal_id():
    service = FakeExchangeService()
    handler = _handler(exchange_service=service)
    signal = MagicMock()
    signal.symbol = "BTC/USDT"
    signal.timeframe = "1h"
    signal.timestamp = __import__("datetime").datetime(
        2026, 1, 1, tzinfo=__import__("datetime").UTC
    )
    signal.signal_type.value = "buy"
    signal.entry_price = 50_000.0
    signal.stop_loss = 49_000.0
    signal.position_size = 0.001
    handler.trading_service.run_quick_analysis = AsyncMock(return_value=[signal])
    from strategy.signal_tracker import make_signal_id

    sid = make_signal_id("BTC/USDT", "1h", signal.timestamp, "buy")
    update, context = _update(["binance", sid])
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchange_execute_command(update, context))
    assert len(service.submitted) == 1
    sent = service.submitted[0]
    assert sent["exchange_id"] == "binance"
    assert sent["side"] == "buy"
    assert sent["amount"] == 0.001
    assert sent["price"] == 50_000.0


def test_exchange_execute_non_admin_does_nothing():
    service = FakeExchangeService()
    handler = _handler(exchange_service=service)
    handler.trading_service.run_quick_analysis = AsyncMock(return_value=[])
    update, context = _update(["binance", "x"])
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=False)):
        asyncio.run(handler.exchange_execute_command(update, context))
    handler.trading_service.run_quick_analysis.assert_not_called()
    assert service.submitted == []


def test_exchange_confirm_records_code_without_live_activation():
    handler = _handler(exchange_service=FakeExchangeService())
    update, context = _update(["ABCD1234"])
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchange_confirm_command(update, context))
    assert handler._pending_confirmation == "ABCD1234"
    assert handler.config_manager.get("exchange_live_enabled", False) is False


def test_exchange_commands_never_print_secret_values():
    service = FakeExchangeService(
        result=SubmitResult(
            ok=False, mode="sandbox", status="rejected", reason="api_key=*** invalid"
        )
    )
    handler = _handler(exchange_service=service)
    update, context = _update(["binance", "x"])
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        asyncio.run(handler.exchange_confirm_command(update, context))
        asyncio.run(handler.exchange_status_command(update, context))
    text = "\n".join(_texts(update))
    assert "API_KEY" not in text.upper()


def test_handlers_are_registered():
    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.application = MagicMock()
    handler._register_handlers()
    names = {
        next(iter(call.args[0].commands))
        for call in handler.application.add_handler.call_args_list
        if getattr(call.args[0], "commands", None)
    }
    assert {
        "exchanges",
        "exchange_status",
        "exchange_execute",
        "exchange_halt",
        "exchange_resume",
        "exchange_confirm",
    } <= names


def test_shadow_result_does_not_enable_live():
    service = FakeExchangeService(
        result=SubmitResult(ok=True, mode="shadow", status=SHADOW, client_order_id="cid-1")
    )
    handler = _handler(exchange_service=service)
    assert handler.config_manager.get("exchange_live_enabled", False) is False


@pytest.mark.parametrize("command", ["halt", "resume"])
def test_halt_resume_require_admin(command):
    service = FakeExchangeService()
    handler = _handler(exchange_service=service)
    update, context = _update()
    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=False)):
        if command == "halt":
            asyncio.run(handler.exchange_halt_command(update, context))
        else:
            asyncio.run(handler.exchange_resume_command(update, context))
    assert service.halted == 0
    assert service.resumed == 0
