from trading.exchanges.factory import build_gateway
from trading.exchanges.registry import get_spec


def test_the_configured_timeout_reaches_the_venue_client():
    spec = get_spec("kraken")
    gateway = build_gateway(spec, False, None, timeout_ms=7000)

    assert gateway.client.timeout == 7000


def test_the_default_timeout_is_used_when_none_is_given():
    spec = get_spec("kraken")
    gateway = build_gateway(spec, False, None)

    assert gateway.client.timeout == 15000


def test_an_explicit_timeout_overrides_the_default():
    spec = get_spec("kraken")
    gateway = build_gateway(spec, False, None, timeout_ms=1234)

    assert gateway.client.timeout == 1234


def test_the_service_factory_applies_the_configured_timeout(tmp_path):
    from config.settings import ConfigManager
    from services.trading_service import _build_exchange_service

    manager = ConfigManager.__new__(ConfigManager)
    manager.config = {
        **ConfigManager.DEFAULT_CONFIG,
        "exchange_enabled": ["kraken"],
        "exchange_sandbox": False,
        "exchange_request_timeout_ms": 7000,
        "exchange_ledger_path": str(tmp_path / "live.db"),
    }

    service = _build_exchange_service(manager)

    assert service is not None
    gateway = service.gateway_factory(get_spec("kraken"), False, None)
    assert gateway.client.timeout == 7000
