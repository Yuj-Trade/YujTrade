import time
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from app.profile_service import ProfileService
from config.logger import logger
from config.profile_keys import ProfileKeyStore, get_store
from config.profile_schema import (
    ALL_ENTRIES,
    KIND_BOOL,
    KIND_CHOICE,
    KIND_FLOAT,
    KIND_INT,
    KIND_LIST,
    KIND_MAP,
    PENDING_INPUT_SECONDS,
    PROVIDER_KEY_NAMES,
    SECTIONS,
    entries_for_section,
    get_entry,
    is_operator_only,
)
from trading.exchanges.registry import EXCHANGE_REGISTRY

VENUES_PER_PAGE = 8

EXCHANGE_ENVIRONMENTS = ("sandbox", "live")
EXCHANGE_FIELDS = ("api_key", "api_secret", "api_passphrase")


def _escape(text: str) -> str:
    from app.telegram_bot import escape_markdown_v2

    return escape_markdown_v2(text)


def profile_button(label: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=callback)


def ready_venues() -> tuple[Any, ...]:
    from application.exchange_policy import STATUS_READY

    return tuple(spec for spec in EXCHANGE_REGISTRY if spec.status == STATUS_READY)


def venue_fields(spec: Any) -> tuple[str, ...]:
    fields = ["api_key", "api_secret"]
    if getattr(spec, "needs_passphrase", False):
        fields.append("api_passphrase")
    return tuple(fields)


class TelegramProfileMenu:
    def __init__(self, handler: Any):
        self.handler = handler
        self.store: ProfileKeyStore = get_store()
        self.service = ProfileService(
            handler.config_manager,
            trading_service=getattr(handler, "trading_service", None),
            market_data_provider=getattr(handler, "market_data_provider", None),
        )

    def set_store(self, store: ProfileKeyStore) -> None:
        self.store = store

    async def route(self, data: str, update: Any, context: Any) -> None:
        if not await self.handler._is_admin(update, context):
            return
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else "menu"
        if action == "menu":
            await self.menu(update, context)
        elif action == "section":
            await self.section(update, context, parts[2])
        elif action == "value":
            await self.value(update, context, parts[2])
        elif action == "set":
            await self.ask(update, context, parts[2])
        elif action == "choice":
            await self.save_choice(update, context, parts[2], parts[3])
        elif action == "reset":
            await self.reset(update, context, parts[2])
        elif action == "resetall":
            await self.reset_all(update, context, len(parts) > 2)
        elif action == "venue":
            await self.venue(update, context, parts[2], parts[3])
        elif action == "env":
            await self.environment(update, context, parts[2], parts[3])
        elif action == "field":
            await self.field(update, context, parts[2], parts[3], parts[4])
        elif action == "setkey":
            await self.ask_secret(update, context, "exchange", parts[2], parts[3], parts[4])
        elif action == "provider":
            await self.provider(update, context, parts[2])
        elif action == "setprovider":
            await self.ask_secret(update, context, "provider", parts[2], "", parts[2])
        elif action == "delprovider":
            await self.delete_provider(update, context, parts[2], len(parts) > 3)
        elif action == "delkey":
            await self.delete_key(update, context, parts[2], parts[3], parts[4], len(parts) > 5)
        elif action == "cancel":
            await self.cancel(update, context)

    async def _answer(self, update: Any, text: str) -> None:
        query = getattr(update, "callback_query", None)
        if query is None:
            return
        try:
            await query.answer(text)
        except (TimedOut, RetryAfter, Forbidden, BadRequest):
            logger.debug("Profile callback answer skipped.")

    async def _edit(self, update: Any, text: str, keyboard: InlineKeyboardMarkup) -> None:
        query = getattr(update, "callback_query", None)
        payload = _escape(text)
        if query is not None:
            try:
                await query.edit_message_text(
                    payload, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2
                )
                return
            except BadRequest:
                message = getattr(query, "message", None)
                if message is not None:
                    await self._send_to(message, text, keyboard)
                    return
            except (TimedOut, RetryAfter, Forbidden):
                logger.warning("Profile menu reply skipped, transport unavailable.")
                return
        await self._send_to(None, text, keyboard, update=update)

    async def _send_to(
        self,
        message: Any,
        text: str,
        keyboard: InlineKeyboardMarkup,
        update: Any = None,
    ) -> None:
        payload = _escape(text)
        chat_id = self.handler.admin_chat_id
        if message is not None:
            chat_id = getattr(message, "chat_id", None) or chat_id
        if not chat_id:
            logger.warning("Profile menu has no chat to reply to.")
            return
        try:
            await self.handler.application.bot.send_message(
                chat_id=chat_id,
                text=payload,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except (TimedOut, RetryAfter, Forbidden):
            logger.warning("Profile reply skipped, transport unavailable.")

    async def menu(self, update: Any, context: Any) -> None:
        await self._answer(update, "")
        rows = []
        for index in range(0, len(SECTIONS), 2):
            chunk = SECTIONS[index : index + 2]
            rows.append([profile_button(title, callback) for _, title, callback in chunk])
        rows.append([profile_button("Reset to defaults", "pf:resetall")])
        await self._edit(update, "Profile menu. Pick a section.", InlineKeyboardMarkup(rows))

    async def section(self, update: Any, context: Any, section_id: str) -> None:
        await self._answer(update, "")
        if section_id in ("exchange_keys", "service_keys"):
            if section_id == "exchange_keys":
                await self.venues(update, context, 1)
            else:
                await self.service_keys(update, context)
            return
        rows = []
        for entry in entries_for_section(section_id):
            rows.append(
                [
                    profile_button(
                        f"{entry.label}: {self._display(entry)}",
                        f"pf:value:{entry.key}",
                    )
                ]
            )
        rows.append([profile_button("Back", "pf:menu")])
        await self._edit(update, "Choose a setting.", InlineKeyboardMarkup(rows))

    def _display(self, entry: Any) -> str:
        value = self.service.current(entry.key)
        if entry.kind == KIND_BOOL:
            return "on" if value else "off"
        if entry.kind == KIND_LIST:
            return ", ".join(str(item) for item in value) if value else "all"
        if entry.kind == KIND_MAP:
            return ", ".join(f"{key}: {value[key]:g}" for key in sorted(value))
        if entry.kind in (KIND_FLOAT, KIND_INT):
            return f"{float(value):g}"
        return str(value)

    def _is_default(self, entry: Any) -> bool:
        return self.service.is_default(entry.key)

    async def value(self, update: Any, context: Any, key: str) -> None:
        await self._answer(update, "")
        entry = get_entry(key)
        if entry is None or is_operator_only(key):
            await self._edit(update, "That setting is not personalizable.", self._back())
            return
        rows = []
        note = "default" if self._is_default(entry) else "changed"
        if entry.kind == KIND_CHOICE:
            for choice in entry.choices:
                rows.append([profile_button(str(choice), f"pf:choice:{entry.key}:{choice}")])
        elif entry.kind == KIND_BOOL:
            rows.append(
                [
                    profile_button("On", f"pf:choice:{entry.key}:true"),
                    profile_button("Off", f"pf:choice:{entry.key}:false"),
                ]
            )
        else:
            rows.append([profile_button("Send the new value", f"pf:set:{entry.key}")])
        rows.append([profile_button("Reset to default", f"pf:reset:{entry.key}")])
        rows.append([profile_button("Back", f"pf:section:{entry.section}")])
        prompt = (
            f"{entry.label}\nCurrent: {self._display(entry)} ({note})\n{self._range_text(entry)}"
        )
        await self._edit(update, prompt, InlineKeyboardMarkup(rows))

    def _range_text(self, entry: Any) -> str:
        if entry.kind == KIND_CHOICE:
            return "Allowed: " + ", ".join(str(choice) for choice in entry.choices)
        if entry.kind == KIND_BOOL:
            return "Allowed: on, off"
        if entry.kind == KIND_LIST:
            allowed = ", ".join(str(choice) for choice in entry.choices)
            return f"Allowed: {allowed}, comma separated"
        if entry.kind == KIND_MAP:
            allowed = ", ".join(str(choice) for choice in entry.choices)
            return f"Allowed keys: {allowed}. Send {{timeframe: number}}"
        if entry.minimum is not None and entry.maximum is not None:
            return f"Range {entry.minimum:g} to {entry.maximum:g}"
        if entry.minimum is not None:
            return f"Minimum {entry.minimum:g}"
        if entry.maximum is not None:
            return f"Maximum {entry.maximum:g}"
        return "Send the new value"

    async def save_choice(self, update: Any, context: Any, key: str, choice: str) -> None:
        ok, message, note = self.service.save(key, choice)
        await self._answer(update, message or note)
        if ok:
            logger.info(f"Profile setting {key} updated ({note}).")
        await self.value(update, context, key)

    async def ask(self, update: Any, context: Any, key: str) -> None:
        entry = get_entry(key)
        if entry is None or is_operator_only(key):
            await self._answer(update, "Not personalizable.")
            return
        context.chat_data["profile_pending"] = {
            "mode": "setting",
            "key": key,
            "expires_at": time.monotonic() + PENDING_INPUT_SECONDS,
        }
        await self._answer(update, "Send the new value.")
        rows = [[profile_button("Cancel", "pf:cancel")]]
        text = (
            f"Send the new value for {entry.label} "
            f"within {PENDING_INPUT_SECONDS} seconds.\n{self._range_text(entry)}"
        )
        await self._edit(update, text, InlineKeyboardMarkup(rows))

    async def cancel(self, update: Any, context: Any) -> None:
        chat_data = getattr(context, "chat_data", None) or {}
        chat_data.pop("profile_pending", None)
        await self._answer(update, "Cancelled.")
        await self.menu(update, context)

    async def reset(self, update: Any, context: Any, key: str) -> None:
        ok, message, note = self.service.reset(key)
        await self._answer(update, message or note)
        if ok:
            logger.info(f"Profile setting {key} reset ({note}).")
            await self.value(update, context, key)
            return
        await self.menu(update, context)

    async def reset_all(self, update: Any, context: Any, confirmed: bool) -> None:
        await self._answer(update, "")
        if not confirmed:
            rows = [
                [profile_button("Reset everything to defaults", "pf:resetall:confirm")],
                [profile_button("Cancel", "pf:menu")],
            ]
            await self._edit(
                update, "Reset every profile value to its default?", InlineKeyboardMarkup(rows)
            )
            return
        for entry in ALL_ENTRIES:
            self.service.reset(entry.key)
        logger.info("Profile reset to defaults.")
        await self._edit(update, "Defaults restored.", self._back())

    async def venues(self, update: Any, context: Any, page: str) -> None:
        await self._answer(update, "")
        venues = ready_venues()
        number = max(1, int(page or 1))
        start = (number - 1) * VENUES_PER_PAGE
        chunk = venues[start : start + VENUES_PER_PAGE]
        rows = []
        for spec in chunk:
            rows.append(
                [
                    profile_button(
                        f"{spec.display_name} ({spec.exchange_id})",
                        f"pf:venue:{spec.exchange_id}:{number}",
                    )
                ]
            )
        if start + VENUES_PER_PAGE < len(venues):
            rows.append([profile_button("Next page", f"pf:venue:list:{number + 1}")])
        if number > 1:
            rows.append([profile_button("Previous page", f"pf:venue:list:{number - 1}")])
        rows.append(self._back())
        await self._edit(update, "Exchange keys. Pick a venue.", InlineKeyboardMarkup(rows))

    async def venue(self, update: Any, context: Any, exchange_id: str, page: str) -> None:
        await self._answer(update, "")
        if exchange_id == "list":
            await self.venues(update, context, page)
            return
        spec = self._spec(exchange_id)
        if spec is None:
            await self._edit(update, "Unknown venue.", self._back())
            return
        rows = []
        for environment in EXCHANGE_ENVIRONMENTS:
            rows.append(
                [
                    profile_button(
                        environment.title(),
                        f"pf:env:{spec.exchange_id}:{environment}",
                    )
                ]
            )
        rows.append([profile_button("Back", "pf:venue:list:1")])
        rows.append(self._back())
        await self._edit(
            update, f"{spec.display_name}. Pick the environment.", InlineKeyboardMarkup(rows)
        )

    async def environment(
        self, update: Any, context: Any, exchange_id: str, environment: str
    ) -> None:
        await self._answer(update, "")
        spec = self._spec(exchange_id)
        if spec is None or environment not in EXCHANGE_ENVIRONMENTS:
            await self._edit(update, "Unknown venue or environment.", self._back())
            return
        rows = []
        for field in venue_fields(spec):
            stored = self.store.has_exchange_value(exchange_id, environment, field)
            status = "set" if stored else "missing"
            rows.append(
                [
                    profile_button(
                        f"{field}: {status}",
                        f"pf:field:{exchange_id}:{environment}:{field}",
                    )
                ]
            )
        rows.append([profile_button("Back", f"pf:venue:{exchange_id}:1")])
        rows.append(self._back())
        await self._edit(
            update, f"{spec.display_name} {environment} keys.", InlineKeyboardMarkup(rows)
        )

    async def field(
        self, update: Any, context: Any, exchange_id: str, environment: str, field: str
    ) -> None:
        await self._answer(update, "")
        spec = self._spec(exchange_id)
        if spec is None or field not in EXCHANGE_FIELDS:
            await self._edit(update, "Unknown key field.", self._back())
            return
        stored = self.store.has_exchange_value(exchange_id, environment, field)
        rows = [
            [profile_button("Send the key now", f"pf:setkey:{exchange_id}:{environment}:{field}")],
            [profile_button("Back", f"pf:env:{exchange_id}:{environment}")],
            self._back(),
        ]
        status = "set" if stored else "missing"
        text = f"{spec.display_name} {environment} {field}\nStatus: {status}"
        await self._edit(update, text, InlineKeyboardMarkup(rows))

    async def service_keys(self, update: Any, context: Any) -> None:
        rows = []
        for name in PROVIDER_KEY_NAMES:
            stored = self.store.has_provider_value(name)
            rows.append(
                [
                    profile_button(
                        f"{name}: {'set' if stored else 'missing'}",
                        f"pf:provider:{name}",
                    )
                ]
            )
        rows.append(self._back())
        await self._edit(update, "Service keys. All are optional.", InlineKeyboardMarkup(rows))

    async def provider(self, update: Any, context: Any, name: str) -> None:
        await self._answer(update, "")
        if name not in PROVIDER_KEY_NAMES:
            await self._edit(update, "Unknown service key.", self._back())
            return
        stored = self.store.has_provider_value(name)
        rows = [
            [profile_button("Send the key now", f"pf:setprovider:{name}")],
            [profile_button("Delete this key", f"pf:delprovider:{name}")],
            [profile_button("Back", "pf:section:service_keys")],
            self._back(),
        ]
        status = "set" if stored else "missing"
        await self._edit(update, f"{name}\nStatus: {status} (optional)", InlineKeyboardMarkup(rows))

    async def delete_provider(self, update: Any, context: Any, name: str, confirmed: bool) -> None:
        await self._answer(update, "")
        if not confirmed:
            rows = [
                [profile_button("Delete this key", f"pf:delprovider:{name}:confirm")],
                [profile_button("Cancel", f"pf:provider:{name}")],
                self._back(),
            ]
            await self._edit(
                update, f"Delete {name} from the profile store?", InlineKeyboardMarkup(rows)
            )
            return
        self.store.delete_provider_value(name)
        self.service.rebuild_provider_fetchers()
        logger.info(f"Profile provider key deleted for {name}.")
        await self._edit(update, "Key deleted.", self._back())

    async def ask_secret(
        self,
        update: Any,
        context: Any,
        kind: str,
        exchange_id: str,
        environment: str,
        field: str,
    ) -> None:
        if not self.store.available():
            await self._answer(
                update, "No encryption password is available; the key cannot be stored."
            )
            return
        context.chat_data["profile_pending"] = {
            "mode": "secret",
            "kind": kind,
            "exchange_id": exchange_id,
            "environment": environment,
            "field": field,
            "expires_at": time.monotonic() + PENDING_INPUT_SECONDS,
        }
        await self._answer(update, "Send the key now.")
        rows = [[profile_button("Cancel", "pf:cancel")]]
        await self._edit(
            update,
            f"Send the {field} now. The message is deleted after it is stored.",
            InlineKeyboardMarkup(rows),
        )

    async def consume_text(self, update: Any, context: Any) -> bool:
        chat_data = getattr(context, "chat_data", None) or {}
        pending = chat_data.get("profile_pending")
        if not pending:
            return False
        if time.monotonic() > float(pending.get("expires_at", 0)):
            chat_data.pop("profile_pending", None)
            return False
        message = getattr(update, "message", None)
        text = getattr(message, "text", "") or ""
        if pending.get("mode") == "setting":
            chat_data.pop("profile_pending", None)
            key = str(pending.get("key"))
            ok, result, note = self.service.save(key, text)
            if not ok:
                await self._send_to(message, result, self._back())
                return True
            logger.info(f"Profile setting {key} updated ({note}).")
            await self._send_to(
                message, f"{key} = {self._display(get_entry(key))} ({note})", self._back()
            )
            return True
        chat_data.pop("profile_pending", None)
        stored = await self._store_secret(pending, text)
        note = "applied" if stored["stored"] else ""
        reply = (
            f"{stored['label']} status: {'set' if stored['stored'] else 'missing'}"
            f"{f' ({note})' if note else ''}"
        )
        await self._send_to(message, reply, self._back())
        await self._delete_message(update, context, reply)
        return True

    async def _store_secret(self, pending: dict[str, Any], text: str) -> dict[str, Any]:
        value = text.strip()
        exchange_id = str(pending.get("exchange_id", ""))
        environment = str(pending.get("environment", ""))
        field = str(pending.get("field", ""))
        kind = str(pending.get("kind", ""))
        if not value:
            return {"stored": False, "label": f"{exchange_id} {environment} {field}"}
        try:
            if kind == "provider":
                self.store.set_provider_value(field, value)
                self.service.rebuild_provider_fetchers()
            else:
                self.store.set_exchange_value(exchange_id, environment, field, value)
                self.service.drop_venue_state(exchange_id)
        except (OSError, ValueError, RuntimeError):
            logger.error("Profile key save failed.")
            return {"stored": False, "label": f"{exchange_id} {environment} {field}"}
        return {"stored": True, "label": f"{exchange_id} {environment} {field}"}

    async def _delete_message(self, update: Any, context: Any, reply: str) -> None:
        message = getattr(update, "message", None)
        chat_id = getattr(message, "chat_id", None) if message is not None else None
        message_id = getattr(message, "message_id", None) if message is not None else None
        if chat_id is None or message_id is None:
            return
        bot = getattr(self.handler.application, "bot", None)
        if bot is None:
            return
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TimedOut, RetryAfter, Forbidden, BadRequest) as exc:
            logger.warning(f"Secret message deletion failed: {exc}")
            await self._send_to(
                message, "Delete the message manually. The key stays saved.", self._back()
            )
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            logger.warning(f"Secret message deletion failed: {exc}")
            await self._send_to(
                message, "Delete the message manually. The key stays saved.", self._back()
            )
            await self._send_to(
                message, "Delete the message manually. The key stays saved.", self._back()
            )

    async def delete_key(
        self,
        update: Any,
        context: Any,
        exchange_id: str,
        environment: str,
        field: str,
        confirmed: bool,
    ) -> None:
        await self._answer(update, "")
        if not confirmed:
            rows = [
                [
                    profile_button(
                        "Delete this key",
                        f"pf:delkey:{exchange_id}:{environment}:{field}:confirm",
                    )
                ],
                [profile_button("Cancel", f"pf:env:{exchange_id}:{environment}")],
                self._back(),
            ]
            await self._edit(
                update,
                f"Delete {field} for {exchange_id} {environment}?",
                InlineKeyboardMarkup(rows),
            )
            return
        self.store.delete_exchange_value(exchange_id, environment, field)
        self.service.drop_venue_state(exchange_id)
        logger.info(f"Profile exchange key deleted for {exchange_id}.")
        await self._edit(update, "Key deleted.", self._back())

    def _spec(self, exchange_id: str):
        for spec in EXCHANGE_REGISTRY:
            if spec.exchange_id == exchange_id:
                return spec
        return None

    def _back(self) -> list[InlineKeyboardButton]:
        return [profile_button("Back", "pf:menu")]
