from typing import Any

import ccxt.async_support as ccxt_async

from application.exchange_policy import map_ccxt_status
from config.logger import logger
from domain.exchange_types import OrderIntent, OrderSnapshot, PlacementResult
from trading.exchanges.credentials import ExchangeCredentials
from trading.exchanges.errors import ExchangeConfigError, sanitize
from trading.exchanges.registry import ExchangeSpec

_FEE_UNITS_PER_24H = 24 * 60 * 60 * 1000


class CcxtGateway:
    def __init__(
        self,
        spec: ExchangeSpec,
        sandbox: bool,
        credentials: ExchangeCredentials | None = None,
        timeout_ms: int = 15000,
    ) -> None:
        if spec.ccxt_id is None:
            raise ExchangeConfigError(f"{spec.exchange_id}_has_no_ccxt_class")
        exchange_class = getattr(ccxt_async, spec.ccxt_id, None)
        if exchange_class is None:
            raise ExchangeConfigError(f"ccxt_class_missing_{spec.ccxt_id}")
        self.spec = spec
        self.exchange_id = spec.exchange_id
        self.sandbox = sandbox
        self._secrets = credentials.as_list() if credentials is not None else []
        self._credentials = credentials
        options: dict[str, Any] = {
            "enableRateLimit": True,
            "timeout": int(timeout_ms),
            "verbose": False,
            "options": {"defaultType": "spot"},
        }
        if credentials is not None:
            options["apiKey"] = credentials.api_key
            options["secret"] = credentials.api_secret
            if spec.needs_passphrase:
                options["password"] = credentials.passphrase
        self.client = exchange_class(options)
        self._markets_loaded = False
        if sandbox:
            self._enable_sandbox()
        logger.debug(f"Exchange client ready for {spec.exchange_id} (sandbox={sandbox})")

    def _enable_sandbox(self) -> None:
        try:
            self.client.set_sandbox_mode(True)
        except ccxt_async.NotSupported as exc:
            self._close_quietly()
            raise ExchangeConfigError("sandbox_not_supported") from exc
        except (TypeError, AttributeError) as exc:
            self._close_quietly()
            raise ExchangeConfigError("sandbox_not_supported") from exc

    def _close_quietly(self) -> None:
        return None

    def error_text(self, exc: BaseException) -> str:
        return sanitize(str(exc), self._secrets)

    async def load_markets(self) -> None:
        await self.client.load_markets()
        self._markets_loaded = True

    def _market(self, symbol: str) -> dict[str, Any]:
        markets = getattr(self.client, "markets", None) or {}
        market = markets.get(symbol)
        if market is None:
            raise ExchangeConfigError(f"unknown_symbol_{symbol}")
        if not market.get("spot"):
            raise ExchangeConfigError(f"not_spot_{symbol}")
        return market

    async def fetch_last(self, symbol: str) -> float:
        self._market(symbol)
        ticker = await self.client.fetch_ticker(symbol)
        last = ticker.get("last") if isinstance(ticker, dict) else None
        if last is None and isinstance(ticker, dict):
            last = ticker.get("close")
        value = float(last or 0.0)
        if value <= 0:
            raise ExchangeConfigError(f"no_last_price_{symbol}")
        return value

    async def fetch_top_of_book(self, symbol: str) -> tuple[float, float]:
        self._market(symbol)
        book = await self.client.fetch_order_book(symbol, 5)
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        if not bids or not asks:
            raise ExchangeConfigError(f"empty_order_book_{symbol}")
        bid = float(bids[0][0])
        ask = float(asks[0][0])
        if bid <= 0 or ask <= 0:
            raise ExchangeConfigError(f"invalid_top_of_book_{symbol}")
        return bid, ask

    async def normalize(self, symbol: str, amount: float, price: float) -> tuple[float, float]:
        self._market(symbol)
        normalized_amount = float(self.client.amount_to_precision(symbol, amount))
        normalized_price = float(self.client.price_to_precision(symbol, price))
        return normalized_amount, normalized_price

    def market_limits(self, symbol: str) -> tuple[float, float]:
        market = self._market(symbol)
        limits = market.get("limits") or {}
        amount_limits = limits.get("amount") or {}
        cost_limits = limits.get("cost") or {}
        min_amount = float(amount_limits.get("min") or 0.0)
        min_cost = float(cost_limits.get("min") or 0.0)
        return min_amount, min_cost

    async def place_limit_order(self, intent: OrderIntent) -> PlacementResult:
        raise NotImplementedError("place_limit_order_is_phase_seven")

    async def fetch_order_by_client_id(
        self, symbol: str, client_order_id: str
    ) -> OrderSnapshot | None:
        raise NotImplementedError("fetch_order_by_client_id_is_phase_five")

    async def fetch_free_balance(self, currency: str) -> float:
        raise NotImplementedError("fetch_free_balance_is_phase_five")

    def describe(self) -> dict[str, Any]:
        described = self.client.describe()
        return described if isinstance(described, dict) else {}

    def has(self, name: str) -> bool:
        return bool(getattr(self.client, "has", {}).get(name))

    def status_from_order(self, order: dict[str, Any]) -> str:
        amount = float(order.get("amount") or 0.0)
        filled = float(order.get("filled") or 0.0)
        raw = order.get("status")
        return map_ccxt_status(raw if raw is not None else None, filled, amount)

    async def close(self) -> None:
        try:
            await self.client.close()
        finally:
            self._markets_loaded = False
