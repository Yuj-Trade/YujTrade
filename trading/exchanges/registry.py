from dataclasses import dataclass

from application.exchange_policy import (
    SCOPE_GENERAL,
    SCOPE_IRAN_ONLY,
    STATUS_PENDING_DOCS,
    STATUS_READY,
)


@dataclass(frozen=True)
class ExchangeSpec:
    exchange_id: str
    display_name: str
    ccxt_id: str | None
    access_scope: str
    status: str
    spot_supported: bool
    needs_passphrase: bool
    secret_encoding: str
    sandbox_expected: bool | None
    permission_endpoint: str | None

    @property
    def env_prefix(self) -> str:
        return self.exchange_id.upper()

    def secret_names(self, sandbox: bool) -> tuple[str, ...]:
        base = f"{self.env_prefix}_SANDBOX" if sandbox else self.env_prefix
        names = [f"{base}_API_KEY", f"{base}_API_SECRET"]
        if self.needs_passphrase:
            names.append(f"{base}_API_PASSPHRASE")
        return tuple(names)


EXCHANGE_REGISTRY: tuple[ExchangeSpec, ...] = (
    ExchangeSpec(
        "binance",
        "Binance",
        "binance",
        SCOPE_GENERAL,
        STATUS_READY,
        True,
        False,
        "plain",
        True,
        "sapi/v1/account/apiRestrictions",
    ),
    ExchangeSpec(
        "coinbase",
        "Coinbase Exchange",
        "coinbase",
        SCOPE_GENERAL,
        STATUS_READY,
        True,
        False,
        "base64",
        None,
        None,
    ),
    ExchangeSpec(
        "kraken", "Kraken", "kraken", SCOPE_GENERAL, STATUS_READY, True, False, "plain", False, None
    ),
    ExchangeSpec("okx", "OKX", "okx", SCOPE_GENERAL, STATUS_READY, True, True, "plain", True, None),
    ExchangeSpec(
        "bitstamp",
        "Bitstamp",
        "bitstamp",
        SCOPE_GENERAL,
        STATUS_READY,
        True,
        False,
        "plain",
        None,
        None,
    ),
    ExchangeSpec(
        "cryptocom",
        "Crypto.com Exchange",
        "cryptocom",
        SCOPE_GENERAL,
        STATUS_READY,
        True,
        False,
        "plain",
        None,
        None,
    ),
    ExchangeSpec(
        "bybit", "Bybit", "bybit", SCOPE_GENERAL, STATUS_READY, True, False, "plain", True, None
    ),
    ExchangeSpec(
        "bitget", "Bitget", "bitget", SCOPE_GENERAL, STATUS_READY, True, True, "plain", None, None
    ),
    ExchangeSpec(
        "gate", "Gate", "gate", SCOPE_GENERAL, STATUS_READY, True, False, "plain", None, None
    ),
    ExchangeSpec(
        "gemini", "Gemini", "gemini", SCOPE_GENERAL, STATUS_READY, True, False, "plain", None, None
    ),
    ExchangeSpec(
        "bitfinex",
        "Bitfinex",
        "bitfinex",
        SCOPE_GENERAL,
        STATUS_READY,
        True,
        False,
        "plain",
        None,
        None,
    ),
    ExchangeSpec(
        "kucoin", "KuCoin", "kucoin", SCOPE_GENERAL, STATUS_READY, True, True, "plain", True, None
    ),
    ExchangeSpec(
        "mexc", "MEXC", "mexc", SCOPE_GENERAL, STATUS_READY, True, False, "plain", None, None
    ),
    ExchangeSpec(
        "htx", "HTX", "htx", SCOPE_GENERAL, STATUS_READY, True, False, "plain", None, None
    ),
    ExchangeSpec(
        "bullish",
        "Bullish",
        "bullish",
        SCOPE_GENERAL,
        STATUS_READY,
        True,
        False,
        "base64",
        True,
        None,
    ),
    ExchangeSpec(
        "whitebit",
        "WhiteBIT",
        "whitebit",
        SCOPE_GENERAL,
        STATUS_READY,
        True,
        False,
        "plain",
        None,
        None,
    ),
    ExchangeSpec(
        "bingx", "BingX", "bingx", SCOPE_GENERAL, STATUS_READY, True, False, "plain", None, None
    ),
    ExchangeSpec(
        "bitvavo",
        "Bitvavo",
        "bitvavo",
        SCOPE_GENERAL,
        STATUS_READY,
        True,
        False,
        "plain",
        None,
        None,
    ),
    ExchangeSpec(
        "deribit",
        "Deribit",
        "deribit",
        SCOPE_GENERAL,
        STATUS_READY,
        False,
        False,
        "plain",
        True,
        None,
    ),
    ExchangeSpec(
        "phemex", "Phemex", "phemex", SCOPE_GENERAL, STATUS_READY, True, False, "plain", True, None
    ),
    ExchangeSpec(
        "lbank",
        "LBank",
        "lbank",
        SCOPE_IRAN_ONLY,
        STATUS_READY,
        True,
        False,
        "plain",
        False,
        "supplement/api_Restrictions",
    ),
    ExchangeSpec(
        "ourbit",
        "Ourbit",
        None,
        SCOPE_IRAN_ONLY,
        STATUS_PENDING_DOCS,
        True,
        False,
        "plain",
        None,
        None,
    ),
)


def get_spec(exchange_id: str) -> ExchangeSpec:
    for spec in EXCHANGE_REGISTRY:
        if spec.exchange_id == exchange_id:
            return spec
    raise KeyError(exchange_id)


def all_secret_names() -> tuple[str, ...]:
    names = {
        name
        for spec in EXCHANGE_REGISTRY
        for sandbox in (True, False)
        for name in spec.secret_names(sandbox)
    }
    return tuple(sorted(names))


def iran_only_exchange_ids() -> tuple[str, ...]:
    return tuple(
        spec.exchange_id for spec in EXCHANGE_REGISTRY if spec.access_scope == SCOPE_IRAN_ONLY
    )
