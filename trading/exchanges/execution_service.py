import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from application.exchange_policy import risk_check, submission_mode
from common import metrics
from config.logger import logger
from config.settings import ConfigManager
from domain.exchange_types import (
    REJECTED,
    SHADOW,
    SUBMITTED,
    TERMINAL_STATUSES,
    OrderIntent,
)
from trading.exchanges.confirmation import (
    check_confirmation,
    consume_confirmation,
    issue_confirmation,
)
from trading.exchanges.credentials import credentials_usable, load_exchange_credentials
from trading.exchanges.errors import ExchangeConfigError, sanitize
from trading.exchanges.gate_inputs import ExchangeSettings, build_gate_input, profile_accepts
from trading.exchanges.registry import ExchangeSpec, get_spec
from trading.live_ledger import LiveLedger

Notify = Callable[[str], Awaitable[None]]


class GatewayLike(Protocol):
    exchange_id: str

    async def load_markets(self) -> None: ...

    async def fetch_last(self, symbol: str) -> float: ...

    async def fetch_top_of_book(self, symbol: str) -> tuple[float, float]: ...

    async def normalize(self, symbol: str, amount: float, price: float) -> tuple[float, float]: ...

    async def place_limit_order(self, intent: OrderIntent) -> Any: ...

    async def fetch_free_balance(self, currency: str) -> float: ...

    async def cancel_order(self, symbol: str, exchange_order_id: str) -> tuple[bool, str]: ...

    async def close(self) -> None: ...


GatewayFactory = Callable[[ExchangeSpec, bool, Any], Any]
PermissionCheck = Callable[[ExchangeSpec], Awaitable[bool]]


@dataclass(frozen=True)
class SubmitResult:
    ok: bool
    mode: str = ""
    reason: str = ""
    status: str = ""
    client_order_id: str = ""
    exchange_order_id: str = ""
    details: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "reason": self.reason,
            "status": self.status,
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            **self.details,
        }


def make_client_order_id(exchange_id: str, signal_id: str, max_len: int = 32) -> str:
    digest = hashlib.sha256(f"{exchange_id}:{signal_id}".encode()).hexdigest()
    return digest[: max(8, int(max_len))]


def is_network_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in {"NetworkError", "RequestTimeout", "ExchangeNotAvailable", "TimeoutError"}:
        return True
    if isinstance(exc, TimeoutError):
        return True
    module = type(exc).__module__ or ""
    return module.startswith("ccxt") and name in {
        "NetworkError",
        "RequestTimeout",
        "ExchangeNotAvailable",
        "DDoSProtection",
        "RateLimitExceeded",
    }


def _market_limits(gateway: Any, symbol: str) -> tuple[float, float]:
    limits = getattr(gateway, "market_limits", None)
    if not callable(limits):
        return 0.0, 0.0
    try:
        min_amount, min_cost = limits(symbol)
    except ExchangeConfigError:
        return 0.0, 0.0
    return float(min_amount), float(min_cost)


class ExchangeExecutionService:
    def __init__(
        self,
        settings: ExchangeSettings,
        ledger: LiveLedger,
        gateway_factory: GatewayFactory,
        notify: Notify | None = None,
        execution_dry_run: bool | None = None,
        permission_check: PermissionCheck | None = None,
        review_ok: bool | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.gateway_factory = gateway_factory
        self.notify = notify
        self.permission_check = permission_check
        self.review_ok = review_ok
        self._clock = clock or time.monotonic
        self._permission_cache: dict[str, tuple[bool, float]] = {}
        self.reconciled_venues: set[str] = set()
        self.reconcile_blockers: dict[str, str] = {}
        self.execution_dry_run = (
            bool(ConfigManager.DEFAULT_CONFIG.get("execution_dry_run", True))
            if execution_dry_run is None
            else execution_dry_run
        )

    def drop_venue_state(self, exchange_id: str) -> None:
        self._permission_cache.pop(exchange_id, None)
        self.reconciled_venues.discard(exchange_id)
        self.reconcile_blockers.pop(exchange_id, None)
        attested = tuple(item for item in self.settings.attested_keys if item != exchange_id)
        if attested != self.settings.attested_keys:
            self.settings = replace(self.settings, attested_keys=attested)

    async def _announce(self, text: str) -> None:
        if self.notify is None:
            return
        try:
            await self.notify(text)
        except Exception as exc:
            logger.error(f"Exchange notification failed: {exc}")

    async def _refuse(
        self,
        reason: str,
        mode: str = "",
        cid: str = "",
        exchange_id: str = "",
        signal_id: str = "",
    ) -> SubmitResult:
        logger.warning(f"Exchange submission refused: {reason}")
        if exchange_id and signal_id and reason != "unknown_exchange":
            try:
                await self.ledger.record_refusal(exchange_id, signal_id, reason)
            except Exception as exc:
                logger.debug(f"Refusal recording skipped: {exc}")
        return SubmitResult(ok=False, mode=mode, reason=reason, client_order_id=cid)

    async def _permissions_ok(self, spec: ExchangeSpec, use_sandbox: bool) -> bool:
        if spec.permission_endpoint is None:
            return True
        if use_sandbox or self.settings.shadow_mode:
            return True
        cached = self._permission_cache.get(spec.exchange_id)
        now = self._clock()
        if cached is not None and now - cached[1] < self.settings.permission_cache_seconds:
            return cached[0]
        if self.permission_check is None:
            return False
        try:
            verdict = bool(await self.permission_check(spec))
        except Exception as exc:
            logger.error(f"Permission verdict unavailable for {spec.exchange_id}: {exc}")
            verdict = False
        self._permission_cache[spec.exchange_id] = (verdict, now)
        return verdict

    async def _evaluate_gate(
        self, spec: ExchangeSpec
    ) -> tuple[str | None, str, bool, list[str], bool]:
        use_sandbox = bool(self.settings.sandbox)
        creds_ok, secrets = credentials_usable(spec, use_sandbox)
        global_halted = (await self.ledger.get_control("halted", "0")) == "1"
        venue_halted = (await self.ledger.get_control(f"halted:{spec.exchange_id}", "0")) == "1"
        halted = global_halted or venue_halted
        permissions_ok = await self._permissions_ok(spec, use_sandbox)
        gate = build_gate_input(
            spec=spec,
            settings=self.settings,
            creds_ok=creds_ok,
            permissions_ok=permissions_ok,
            halted=halted,
            sandbox_mode_flag=use_sandbox,
            execution_dry_run=self.execution_dry_run,
            review_ok=self.review_ok,
        )
        mode, reason = submission_mode(gate)
        return mode, reason, use_sandbox, secrets, halted

    async def submit_signal(
        self,
        exchange_id: str,
        signal_id: str,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        confirmation_code: str = "",
    ) -> SubmitResult:
        try:
            spec = get_spec(exchange_id)
        except KeyError:
            return await self._refuse("unknown_exchange")
        mode, reason, use_sandbox, secrets, _halted = await self._evaluate_gate(spec)
        if mode is None:
            return await self._refuse(reason, exchange_id=exchange_id, signal_id=signal_id)
        if mode in {"sandbox", "live"} and exchange_id not in self.reconciled_venues:
            return await self._refuse(
                f"reconciliation_pending:{exchange_id}",
                exchange_id=exchange_id,
                signal_id=signal_id,
            )
        if mode == "live":
            allowed, code_reason = await check_confirmation(
                self.ledger, confirmation_code, exchange_id, signal_id
            )
            if not allowed:
                return await self._refuse(
                    code_reason, mode, exchange_id=exchange_id, signal_id=signal_id
                )
        cid = make_client_order_id(exchange_id, signal_id, spec.client_id_max_len)
        intent = OrderIntent(
            exchange_id=exchange_id,
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            amount=float(amount),
            price=float(price),
            client_order_id=cid,
            sandbox=mode == "sandbox",
        )
        credentials = None if mode == "shadow" else load_exchange_credentials(spec, use_sandbox)
        try:
            gateway = self.gateway_factory(spec, use_sandbox, credentials)
        except ExchangeConfigError as exc:
            return await self._refuse(str(exc), mode, exchange_id=exchange_id, signal_id=signal_id)
        except Exception as exc:
            logger.error(f"Gateway construction failed for {exchange_id}: {exc}")
            return await self._refuse(
                "gateway_unavailable", mode, exchange_id=exchange_id, signal_id=signal_id
            )
        try:
            return await self._submit_with_gateway(
                gateway=gateway,
                spec=spec,
                intent=intent,
                mode=mode,
                use_sandbox=use_sandbox,
                secrets=secrets,
                signal_id=signal_id,
                side=side,
                exchange_id=exchange_id,
                confirmation_code=confirmation_code,
            )
        finally:
            try:
                await gateway.close()
            except Exception as exc:
                logger.debug(f"Gateway close failed: {exc}")

    async def _submit_with_gateway(
        self,
        gateway: Any,
        spec: ExchangeSpec,
        intent: OrderIntent,
        mode: str,
        use_sandbox: bool,
        secrets: list[str],
        signal_id: str,
        side: str,
        exchange_id: str,
        confirmation_code: str = "",
    ) -> SubmitResult:
        cid = intent.client_order_id
        try:
            await gateway.load_markets()
            bid, ask = await gateway.fetch_top_of_book(intent.symbol)
            last = await gateway.fetch_last(intent.symbol)
            norm_amount, norm_price = await gateway.normalize(
                intent.symbol, intent.amount, intent.price
            )
            min_amount, min_cost = _market_limits(gateway, intent.symbol)
            daily = await self.ledger.daily_notional(exchange_id, datetime.now(UTC).date())
            held = None
            if side == "sell" and mode != "shadow":
                held = await gateway.fetch_free_balance(intent.symbol.split("/")[0])
        except ExchangeConfigError as exc:
            return await self._refuse(
                sanitize(str(exc), secrets),
                mode,
                cid,
                exchange_id=exchange_id,
                signal_id=signal_id,
            )
        except Exception as exc:
            return self._fail_unresolved(cid, exchange_id, mode, secrets, exc)
        accepted, why = risk_check(
            symbol=intent.symbol,
            side=side,
            amount=norm_amount,
            price=norm_price,
            last=last,
            bid=bid,
            ask=ask,
            daily_notional=daily,
            held_amount=held,
            min_amount=min_amount,
            min_cost=min_cost,
            symbol_allowlist=self.settings.symbol_allowlist,
            max_order_notional=self.settings.max_order_notional,
            max_daily_notional=self.settings.max_daily_notional,
            max_deviation_pct=self.settings.max_deviation_pct,
            max_spread_pct=self.settings.max_spread_pct,
        )
        if not accepted:
            return await self._refuse(why, mode, cid, exchange_id=exchange_id, signal_id=signal_id)
        if not await self.ledger.append_pending(intent, mode, mode, reference_price=last):
            return await self._refuse(
                "duplicate_signal", mode, cid, exchange_id=exchange_id, signal_id=signal_id
            )
        if mode == "live":
            consumed, consume_reason = await consume_confirmation(
                self.ledger, confirmation_code, exchange_id, signal_id
            )
            if not consumed:
                await self.ledger.set_status(cid, exchange_id, REJECTED, consume_reason)
                return await self._refuse(
                    consume_reason, mode, cid, exchange_id=exchange_id, signal_id=signal_id
                )
        if mode == "shadow":
            await self._announce(
                f"Shadow signal {signal_id} on {exchange_id}: {intent.symbol} {side} "
                f"{norm_amount} @ {norm_price}"
            )
            metrics.record_exchange_order(exchange_id, mode, SHADOW)
            return SubmitResult(
                ok=True,
                mode=mode,
                reason="shadow",
                status=SHADOW,
                client_order_id=cid,
            )
        try:
            result = await gateway.place_limit_order(intent)
        except Exception as exc:
            return await self._fail_unresolved(cid, exchange_id, mode, secrets, exc)
        if result.accepted:
            await self.ledger.set_exchange_order_id(cid, exchange_id, result.exchange_order_id)
            await self.ledger.set_status(cid, exchange_id, SUBMITTED, "submitted")
            metrics.record_exchange_order(exchange_id, mode, SUBMITTED)
            await self._announce(
                f"Order {cid} submitted on {exchange_id} (mode={mode}, {intent.symbol} {side})"
            )
            return SubmitResult(
                ok=True,
                mode=mode,
                reason="ok",
                status=SUBMITTED,
                client_order_id=cid,
                exchange_order_id=result.exchange_order_id,
            )
        cleaned = sanitize(result.error, secrets)
        await self.ledger.set_status(cid, exchange_id, REJECTED, cleaned)
        metrics.record_exchange_order(exchange_id, mode, REJECTED)
        await self._announce(f"Order {cid} rejected on {exchange_id}: {cleaned}")
        return SubmitResult(
            ok=False,
            mode=mode,
            reason=cleaned or "rejected",
            status=REJECTED,
            client_order_id=cid,
        )

    async def _fail_unresolved(
        self, cid: str, exchange_id: str, mode: str, secrets: list[str], exc: BaseException
    ) -> SubmitResult:
        if is_network_error(exc):
            logger.warning(f"Network failure for {cid} on {exchange_id}; left for reconciliation")
            return SubmitResult(
                ok=False, mode=mode, reason="pending_reconcile", client_order_id=cid
            )
        cleaned = sanitize(str(exc), secrets)
        row = await self.ledger.get_row(cid, exchange_id)
        if row is not None:
            await self.ledger.set_status(cid, exchange_id, REJECTED, cleaned)
        logger.error(f"Exchange submission failed for {cid} on {exchange_id}: {cleaned}")
        return SubmitResult(
            ok=False, mode=mode, reason=cleaned, status=REJECTED, client_order_id=cid
        )

    async def preview_mode(self, exchange_id: str) -> str | None:
        mode, _reason = await self.preview_gate(exchange_id)
        return mode

    async def preview_gate(self, exchange_id: str) -> tuple[str | None, str]:
        try:
            spec = get_spec(exchange_id)
        except KeyError:
            return None, "unknown_exchange"
        if not profile_accepts(self.settings.access_profile, spec):
            return None, "scope_mismatch"
        mode, reason, _sandbox, _secrets, _halted = await self._evaluate_gate(spec)
        return mode, reason

    async def request_confirmation(self, exchange_id: str, signal_id: str) -> str:
        return await issue_confirmation(self.ledger, exchange_id, signal_id)

    async def reconcile(self) -> list[str]:
        from trading.exchanges.credentials import load_exchange_credentials
        from trading.exchanges.registry import get_spec
        from trading.reconciliation import reconcile_once

        gateways: dict[str, Any] = {}
        blockers: dict[str, str] = {}
        reconciled_now: set[str] = set()
        if not self.settings.enabled:
            blockers["no_enabled_exchange"] = "no_enabled_exchange"
        for exchange_id in self.settings.enabled:
            try:
                spec = get_spec(exchange_id)
            except KeyError:
                blockers[exchange_id] = f"unknown_exchange:{exchange_id}"
                logger.warning(f"Reconciliation skipped unknown exchange {exchange_id}")
                continue
            if spec.ccxt_id is None:
                continue
            credentials = load_exchange_credentials(spec, self.settings.sandbox)
            if credentials is None:
                blockers[exchange_id] = f"no_credentials:{exchange_id}"
                logger.warning(
                    f"Reconciliation has no credentials for {exchange_id}; "
                    "sandbox and live submissions stay blocked."
                )
                continue
            try:
                gateways[exchange_id] = self.gateway_factory(
                    spec, self.settings.sandbox, credentials
                )
            except ExchangeConfigError as exc:
                blockers[exchange_id] = f"gateway_unavailable:{exchange_id}"
                logger.warning(f"Reconciliation gateway unavailable for {exchange_id}: {exc}")
            except Exception as exc:
                blockers[exchange_id] = f"gateway_failed:{exchange_id}"
                logger.error(f"Reconciliation gateway failed for {exchange_id}: {exc}")
            else:
                reconciled_now.add(exchange_id)
        changed: list[str] = []
        try:
            changed = await reconcile_once(
                self.ledger,
                gateways,
                self.settings.unknown_after_seconds,
                notify=self._announce,
            )
        except Exception as exc:
            blockers["pass_failed"] = "pass_failed"
            reconciled_now.clear()
            logger.error(f"Reconciliation pass failed: {exc}")
        finally:
            for gateway in gateways.values():
                try:
                    await gateway.close()
                except Exception as exc:
                    logger.debug(f"Reconciliation gateway close failed: {exc}")
        self.reconciled_venues = reconciled_now
        self.reconcile_blockers = blockers
        if self.reconcile_blockers:
            logger.warning(
                "Exchange submissions stay blocked until reconciliation succeeds: "
                + ", ".join(sorted(self.reconcile_blockers.values()))
            )
        return changed

    async def halt(self, reason: str = "operator_halt", exchange_id: str | None = None) -> None:
        key = f"halted:{exchange_id}" if exchange_id else "halted"
        await self.ledger.set_control(key, "1")
        scope = exchange_id or "all exchanges"
        await self._announce(f"{scope} halted ({reason})")

    async def resume(self, exchange_id: str | None = None) -> None:
        key = f"halted:{exchange_id}" if exchange_id else "halted"
        await self.ledger.set_control(key, "0")
        scope = exchange_id or "all exchanges"
        await self._announce(f"{scope} resumed")

    async def halt_state(self, exchange_id: str | None = None) -> dict:
        global_halted = (await self.ledger.get_control("halted", "0")) == "1"
        venue_halted = (
            (await self.ledger.get_control(f"halted:{exchange_id}", "0")) == "1"
            if exchange_id
            else False
        )
        return {
            "global": global_halted,
            "venue": venue_halted,
            "halted": global_halted or venue_halted,
        }

    async def order_status(self, client_order_id: str, exchange_id: str) -> dict | None:
        return await self.ledger.get_row(client_order_id, exchange_id)

    async def cancel(self, exchange_id: str, client_order_id: str) -> dict:
        from trading.reconciliation import fetch_snapshot

        row = await self.ledger.get_row(client_order_id, exchange_id)
        if row is None:
            return {"ok": False, "reason": "unknown_order", "status": ""}
        status = str(row["status"])
        if status in TERMINAL_STATUSES:
            return {"ok": False, "reason": "already_terminal", "status": status}
        if str(row["mode"]) == "shadow":
            return {"ok": False, "reason": "shadow_has_no_venue_order", "status": status}
        exchange_order_id = str(row.get("exchange_order_id") or "")
        if not exchange_order_id:
            return {"ok": False, "reason": "no_venue_order_id", "status": status}
        try:
            spec = get_spec(exchange_id)
        except KeyError:
            return {"ok": False, "reason": "unknown_exchange", "status": status}
        use_sandbox = str(row["mode"]) == "sandbox"
        credentials = load_exchange_credentials(spec, use_sandbox)
        if credentials is None:
            return {"ok": False, "reason": "credentials_missing", "status": status}
        gateway = self.gateway_factory(spec, use_sandbox, credentials)
        try:
            ok, reason = await gateway.cancel_order(str(row["symbol"]), exchange_order_id)
            if not ok:
                return {"ok": False, "reason": reason, "status": status}
            refreshed = await fetch_snapshot(gateway, row)
        finally:
            try:
                await gateway.close()
            except Exception as exc:
                logger.debug(f"Cancel gateway close failed: {exc}")
        if refreshed is not None:
            await self.ledger.update_from_snapshot(client_order_id, exchange_id, refreshed)
        latest = await self.ledger.get_row(client_order_id, exchange_id)
        new_status = str(latest["status"]) if latest is not None else status
        return {"ok": True, "reason": reason, "status": new_status}
