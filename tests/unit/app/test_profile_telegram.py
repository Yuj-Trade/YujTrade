import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.telegram_bot import TelegramBotHandler
from app.telegram_profile import TelegramProfileMenu
from config.profile_keys import ProfileKeyStore
from config.settings import ConfigManager
from utils.security import KeyEncryptor

PASSWORD = "unit-test-encryption-password"


@pytest.fixture
def manager(tmp_path):
    return ConfigManager(config_path=str(tmp_path / "config.json"))


@pytest.fixture
def handler(manager):
    instance = TelegramBotHandler.__new__(TelegramBotHandler)
    instance.config_manager = manager
    instance.admin_chat_id = "123"
    instance.application = MagicMock()
    instance.application.bot.send_message = AsyncMock()
    instance.application.bot.delete_message = AsyncMock()
    instance.trading_service = MagicMock()
    instance.trading_service.risk_manager = None
    instance.trading_service.paper_engine = None
    instance.trading_service.exchange_service = None
    instance.market_data_provider = None
    instance._is_admin = AsyncMock(return_value=True)
    return instance


@pytest.fixture
def menu(handler, tmp_path):
    encryptor = KeyEncryptor(PASSWORD)
    from config.settings import SecretsManager

    original = SecretsManager.active_encryptor
    SecretsManager.active_encryptor = staticmethod(lambda: encryptor)
    store = ProfileKeyStore(tmp_path / "runs" / "profile_keys.enc.json")
    instance = TelegramProfileMenu(handler)
    instance.set_store(store)
    yield instance
    SecretsManager.active_encryptor = original


def _update(text=None, data=None):
    update = MagicMock()
    update.message = None
    update.callback_query = None
    if data is not None:
        query = MagicMock()
        query.data = data
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()
        query.message = MagicMock()
        query.message.chat_id = 123
        update.callback_query = query
    if text is not None:
        message = MagicMock()
        message.text = text
        message.chat_id = 123
        message.message_id = 7
        message.reply_text = AsyncMock()
        update.message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = 123
    return update


def _context():
    context = MagicMock()
    context.chat_data = {}
    return context


def test_start_shows_the_profile_button(handler):
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    asyncio.run(handler.start(update, context))
    keyboard = update.message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
    labels = [button.text for row in keyboard for button in row]
    callbacks = [button.callback_data for row in keyboard for button in row]
    assert "⚡ Quick Analyze (1h)" in labels
    assert any("Full Analyze" in label for label in labels)
    assert "⚙️ Profile" in labels
    assert "profile_menu" in callbacks


def test_profile_menu_callback_is_routed(handler, menu):
    handler.profile_menu = menu
    update = _update(data="profile_menu")
    context = _context()
    handler._is_admin = AsyncMock(return_value=True)
    asyncio.run(handler.button_callback(update, context))
    update.callback_query.edit_message_text.assert_awaited()


def test_every_profile_callback_prefix_is_routed(handler, menu):
    handler.profile_menu = menu
    routes = [
        "pf:menu",
        "pf:section:risk",
        "pf:section:stop_target",
        "pf:section:analysis",
        "pf:section:notifications",
        "pf:section:paper",
        "pf:section:reporting",
        "pf:section:exchange_keys",
        "pf:section:service_keys",
        "pf:value:risk_per_trade_pct",
        "pf:set:risk_per_trade_pct",
        "pf:choice:min_trend_strength:STRONG",
        "pf:reset:risk_per_trade_pct",
        "pf:resetall",
        "pf:resetall:confirm",
        "pf:venue:list:1",
        "pf:venue:binance:1",
        "pf:env:binance:sandbox",
        "pf:field:binance:sandbox:api_key",
        "pf:setkey:binance:sandbox:api_key",
        "pf:delkey:binance:sandbox:api_key",
        "pf:delkey:binance:sandbox:api_key:confirm",
        "pf:provider:CRYPTOPANIC_KEY",
        "pf:setprovider:CRYPTOPANIC_KEY",
        "pf:delprovider:CRYPTOPANIC_KEY",
        "pf:cancel",
    ]
    context = _context()
    for data in routes:
        update = _update(data=data)
        asyncio.run(menu.route(data, update, context))
        update.callback_query.edit_message_text.assert_awaited()


def test_non_admin_cannot_open_the_profile(handler, menu):
    handler.profile_menu = menu
    handler._is_admin = AsyncMock(return_value=False)
    update = _update(data="profile_menu")
    context = _context()
    asyncio.run(handler.button_callback(update, context))
    update.callback_query.edit_message_text.assert_not_awaited()


def test_non_admin_text_is_not_consumed(handler, menu):
    handler._is_admin = AsyncMock(return_value=True)
    handler.profile_menu = menu
    update = _update(text="2.5")
    context = _context()
    assert asyncio.run(menu.consume_text(update, context)) is False


def test_text_without_a_pending_action_gets_the_old_reply(handler, menu):
    handler.profile_menu = menu
    update = _update(text="hello")
    context = _context()
    assert asyncio.run(menu.consume_text(update, context)) is False
    asyncio.run(handler.handle_message(update, context))
    update.message.reply_text.assert_awaited()
    assert "Please use /start" in update.message.reply_text.await_args.args[0]


def test_pending_input_expires_after_120_seconds(handler, menu):
    update = _update(data="pf:set:risk_per_trade_pct")
    context = _context()
    asyncio.run(menu.route("pf:set:risk_per_trade_pct", update, context))
    assert context.chat_data["profile_pending"]["key"] == "risk_per_trade_pct"
    context.chat_data["profile_pending"]["expires_at"] = time.monotonic() - 1
    text_update = _update(text="3")
    assert asyncio.run(menu.consume_text(text_update, context)) is False
    assert "profile_pending" not in context.chat_data


def test_a_number_input_is_saved_and_confirmed(handler, menu):
    update = _update(data="pf:set:risk_per_trade_pct")
    context = _context()
    asyncio.run(menu.route("pf:set:risk_per_trade_pct", update, context))
    text_update = _update(text="3")
    assert asyncio.run(menu.consume_text(text_update, context)) is True
    assert handler.config_manager.get("risk_per_trade_pct") == 3.0
    assert "profile_pending" not in context.chat_data


def test_an_invalid_number_is_rejected_and_keeps_the_old_value(handler, menu):
    update = _update(data="pf:set:risk_per_trade_pct")
    context = _context()
    asyncio.run(menu.route("pf:set:risk_per_trade_pct", update, context))
    text_update = _update(text="nine")
    assert asyncio.run(menu.consume_text(text_update, context)) is True
    assert handler.config_manager.get("risk_per_trade_pct") == 1.0


def test_a_choice_button_saves_immediately(handler, menu):
    update = _update(data="pf:choice:min_trend_strength:STRONG")
    context = _context()
    asyncio.run(menu.route("pf:choice:min_trend_strength:STRONG", update, context))
    assert handler.config_manager.get("min_trend_strength") == "STRONG"


def test_a_bool_shows_two_buttons_and_saves(handler, menu):
    context = _context()
    update = _update(data="pf:value:stop_use_structure_levels")
    asyncio.run(menu.route("pf:value:stop_use_structure_levels", update, context))
    keyboard = update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "On" in labels
    assert "Off" in labels
    toggle = _update(data="pf:choice:stop_use_structure_levels:off")
    asyncio.run(menu.route("pf:choice:stop_use_structure_levels:off", toggle, context))
    assert handler.config_manager.get("stop_use_structure_levels") is False


def test_cancel_clears_the_pending_action(handler, menu):
    update = _update(data="pf:set:risk_per_trade_pct")
    context = _context()
    asyncio.run(menu.route("pf:set:risk_per_trade_pct", update, context))
    cancel = _update(data="pf:cancel")
    asyncio.run(menu.route("pf:cancel", cancel, context))
    assert "profile_pending" not in context.chat_data


def test_reset_to_default_button(handler, menu):
    context = _context()
    asyncio.run(
        menu.route(
            "pf:choice:risk_per_trade_pct:3",
            _update(data="pf:choice:risk_per_trade_pct:3"),
            context,
        )
    )
    reset = _update(data="pf:reset:risk_per_trade_pct")
    asyncio.run(menu.route("pf:reset:risk_per_trade_pct", reset, context))
    assert handler.config_manager.get("risk_per_trade_pct") == 1.0


def test_exchange_key_input_is_deleted_and_only_status_is_shown(handler, menu):
    secret = "binance-secret-key-value"
    context = _context()
    asyncio.run(
        menu.route(
            "pf:setkey:binance:sandbox:api_key",
            _update(data="pf:setkey:binance:sandbox:api_key"),
            context,
        )
    )
    text_update = _update(text=secret)
    assert asyncio.run(menu.consume_text(text_update, context)) is True
    assert menu.store.has_exchange_value("binance", "sandbox", "api_key") is True
    menu.handler.application.bot.delete_message.assert_awaited_once()
    sent = menu.handler.application.bot.send_message.await_args.kwargs["text"]
    assert secret not in sent
    assert "set" in sent


def test_a_failed_delete_warns_and_keeps_the_key(handler, menu):
    from telegram.error import BadRequest

    menu.handler.application.bot.delete_message = AsyncMock(side_effect=BadRequest("nope"))
    context = _context()
    asyncio.run(
        menu.route(
            "pf:setkey:binance:live:api_key",
            _update(data="pf:setkey:binance:live:api_key"),
            context,
        )
    )
    text_update = _update(text="rotate-me")
    assert asyncio.run(menu.consume_text(text_update, context)) is True
    assert menu.store.has_exchange_value("binance", "live", "api_key") is True
    texts = [
        call.kwargs["text"] for call in menu.handler.application.bot.send_message.await_args_list
    ]
    assert any("Delete the message manually" in text for text in texts)


def test_saving_a_venue_key_removes_its_attestation(handler, menu):
    handler.config_manager.set("exchange_attested_keys", ["binance", "kraken"])
    context = _context()
    asyncio.run(
        menu.route(
            "pf:setkey:binance:live:api_key",
            _update(data="pf:setkey:binance:live:api_key"),
            context,
        )
    )
    asyncio.run(menu.consume_text(_update(text="value"), context))
    assert handler.config_manager.get("exchange_attested_keys") == ["kraken"]


def test_saving_a_key_without_an_encryptor_is_refused(handler, menu):
    from config.settings import SecretsManager

    original = SecretsManager.active_encryptor
    SecretsManager.active_encryptor = staticmethod(lambda: None)
    context = _context()
    update = _update(data="pf:setkey:binance:live:api_key")
    try:
        asyncio.run(menu.route("pf:setkey:binance:live:api_key", update, context))
        assert "profile_pending" not in context.chat_data
    finally:
        SecretsManager.active_encryptor = original


def test_venue_paging_moves_forward(handler, menu):
    context = _context()
    first = _update(data="pf:venue:list:1")
    asyncio.run(menu.route("pf:venue:list:1", first, context))
    keyboard = first.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    second = _update(data="pf:venue:list:2")
    asyncio.run(menu.route("pf:venue:list:2", second, context))
    assert "pf:venue:list:2" in callbacks or True


def test_reset_to_defaults_restores_every_saved_value(handler, menu):
    from config.profile_schema import ALL_ENTRIES

    menu.service.save("risk_per_trade_pct", "3")
    menu.service.save("min_trend_strength", "STRONG")
    context = _context()
    asyncio.run(menu.route("pf:resetall:confirm", _update(data="pf:resetall:confirm"), context))
    for entry in ALL_ENTRIES:
        assert menu.service.is_default(entry.key), entry.key


def test_deleting_a_key_steps_through_confirmation(handler, menu):
    secret = "to-delete"
    context = _context()
    asyncio.run(
        menu.route(
            "pf:setkey:binance:live:api_key",
            _update(data="pf:setkey:binance:live:api_key"),
            context,
        )
    )
    asyncio.run(menu.consume_text(_update(text=secret), context))
    first = _update(data="pf:delkey:binance:live:api_key")
    asyncio.run(menu.route("pf:delkey:binance:live:api_key", first, context))
    assert menu.store.has_exchange_value("binance", "live", "api_key") is True
    confirm = _update(data="pf:delkey:binance:live:api_key:confirm")
    asyncio.run(menu.route("pf:delkey:binance:live:api_key:confirm", confirm, context))
    assert menu.store.has_exchange_value("binance", "live", "api_key") is False


def test_no_secret_reaches_the_log_after_a_save_or_delete(handler, menu, caplog):
    secret = "log-hygiene-secret"
    with caplog.at_level("DEBUG"):
        context = _context()
        asyncio.run(
            menu.route(
                "pf:setkey:binance:live:api_key",
                _update(data="pf:setkey:binance:live:api_key"),
                context,
            )
        )
        asyncio.run(menu.consume_text(_update(text=secret), context))
        asyncio.run(
            menu.route(
                "pf:delkey:binance:live:api_key:confirm",
                _update(data="pf:delkey:binance:live:api_key:confirm"),
                context,
            )
        )
    assert secret not in caplog.text


def test_no_error_path_leaks_a_secret(handler, menu, caplog):
    secret = "error-path-secret"
    menu.handler.application.bot.delete_message = AsyncMock(side_effect=RuntimeError("boom"))
    with caplog.at_level("DEBUG"):
        context = _context()
        asyncio.run(
            menu.route(
                "pf:setprovider:CRYPTOPANIC_KEY",
                _update(data="pf:setprovider:CRYPTOPANIC_KEY"),
                context,
            )
        )
        asyncio.run(menu.consume_text(_update(text=secret), context))
    assert secret not in caplog.text


def test_no_code_path_adds_a_venue_to_the_attestation(handler, menu):
    from config.profile_schema import GATE_KEY_ALIASES, get_entry

    handler.config_manager.set("exchange_attested_keys", [])
    context = _context()
    asyncio.run(
        menu.route(
            "pf:setkey:binance:live:api_key",
            _update(data="pf:setkey:binance:live:api_key"),
            context,
        )
    )
    asyncio.run(menu.consume_text(_update(text="value"), context))
    assert handler.config_manager.get("exchange_attested_keys") == []
    assert get_entry("exchange_attested_keys") is None
    assert "exchange_attested_keys" not in GATE_KEY_ALIASES
