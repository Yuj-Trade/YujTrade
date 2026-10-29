import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from application.exchange_policy import risk_check, submission_mode
from config.logger import logger
from config.settings import ConfigManager
from domain.exchange_types import (
    REJECTED,
    SHADOW,
    SUBMITTED,
    OrderIntent,
)
from trading.exchanges.confirmation import consume_confirmation
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

    async def close(self) -> None: ...


GatewayFactory = Callable[[ExchangeSpec, bool, Any], Any]


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


def make_client_order_id(exchange_id: str, signal_id: str) -> str:
    return hashlib.sha256(f"{exchange_id}:{signal_id}".encode()).hexdigest()[:32]


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
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.gateway_factory = gateway_factory
        self.notify = notify
        self.execution_dry_run = (
            bool(ConfigManager.DEFAULT_CONFIG.get("execution_dry_run", True))
            if execution_dry_run is None
            else execution_dry_run
        )

    async def _announce(self, text: str) -> None:
        if self.notify is None:
            return
        try:
            await self.notify(text)
        except Exception as exc:
            logger.error(f"Exchange notification failed: {exc}")

    @staticmethod
    def _refuse(reason: str, mode: str = "", cid: str = "") -> SubmitResult:
        logger.warning(f"Exchange submission refused: {reason}")
        return SubmitResult(ok=False, mode=mode, reason=reason, client_order_id=cid)

    async def _evaluate_gate(
        self, spec: ExchangeSpec
    ) -> tuple[str | None, str, bool, list[str], bool]:
        use_sandbox = bool(self.settings.sandbox)
        creds_ok, secrets = credentials_usable(spec, use_sandbox)
        halted = (await self.ledger.get_control("halted", "0")) == "1"
        permissions_ok = True if spec.permission_endpoint is None else False
        gate = build_gate_input(
            spec=spec,
            settings=self.settings,
            creds_ok=creds_ok,
            permissions_ok=permissions_ok,
            halted=halted,
            sandbox_mode_flag=use_sandbox,
            execution_dry_run=self.execution_dry_run,
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
            return self._refuse("unknown_exchange")
        if not profile_accepts(self.settings.access_profile, spec):
            return self._refuse("scope_mismatch")
        mode, reason, use_sandbox, secrets, _halted = await self._evaluate_gate(spec)
        if mode is None:
            return self._refuse(reason)
        if mode == "live":
            allowed, code_reason = await consume_confirmation(
                self.ledger, confirmation_code, exchange_id, signal_id
            )
            if not allowed:
                return self._refuse(code_reason, mode)
        cid = make_client_order_id(exchange_id, signal_id)
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
            return self._refuse(str(exc), mode)
        except Exception as exc:
            logger.error(f"Gateway construction failed for {exchange_id}: {exc}")
            return self._refuse("gateway_unavailable", mode)
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
            return self._refuse(sanitize(str(exc), secrets), mode, cid)
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
            return self._refuse(why, mode, cid)
        if not await self.ledger.append_pending(intent, mode, mode):
            return self._refuse("duplicate_signal", mode, cid)
        if mode == "shadow":
            await self._announce(
                f"Shadow signal {signal_id} on {exchange_id}: {intent.symbol} {side} "
                f"{norm_amount} @ {norm_price}"
            )
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

    async def halt(self, reason: str = "operator_halt") -> None:
        await self.ledger.set_control("halted", "1")
        await self._announce(f"Exchange halted ({reason})")

    async def resume(self) -> None:
        await self.ledger.set_control("halted", "0")
        await self._announce("Exchange resumed")

    async def order_status(self, client_order_id: str, exchange_id: str) -> dict | None:
        return await self.ledger.get_row(client_order_id, exchange_id)
