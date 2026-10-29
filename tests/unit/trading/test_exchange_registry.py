import pytest

from trading.exchanges.registry import (
    EXCHANGE_REGISTRY,
    all_secret_names,
    get_spec,
    iran_only_exchange_ids,
)


def test_registry_has_twenty_two_venues():
    assert len(EXCHANGE_REGISTRY) == 22


def test_exchange_ids_are_unique():
    ids = [spec.exchange_id for spec in EXCHANGE_REGISTRY]
    assert len(ids) == len(set(ids))


def test_env_prefixes_are_unique():
    prefixes = [spec.env_prefix for spec in EXCHANGE_REGISTRY]
    assert len(prefixes) == len(set(prefixes))


def test_iran_only_ids_are_lbank_and_ourbit():
    assert iran_only_exchange_ids() == ("lbank", "ourbit")


def test_other_venues_are_general():
    general = [spec.exchange_id for spec in EXCHANGE_REGISTRY if spec.access_scope == "general"]
    assert len(general) == 20
    assert "lbank" not in general
    assert "ourbit" not in general


def test_ourbit_is_pending_without_ccxt_class():
    spec = get_spec("ourbit")
    assert spec.status == "pending_docs_verification"
    assert spec.ccxt_id is None


def test_ready_venues_have_a_ccxt_class():
    for spec in EXCHANGE_REGISTRY:
        if spec.status == "ready":
            assert spec.ccxt_id is not None, spec.exchange_id


def test_secret_names_are_deduplicated():
    names = all_secret_names()
    assert len(names) == len(set(names))


def test_secret_names_follow_the_prefix_contract():
    spec = get_spec("binance")
    assert spec.secret_names(False) == ("BINANCE_API_KEY", "BINANCE_API_SECRET")
    assert spec.secret_names(True) == ("BINANCE_SANDBOX_API_KEY", "BINANCE_SANDBOX_API_SECRET")


def test_passphrase_venues_include_passphrase_name():
    spec = get_spec("okx")
    assert spec.secret_names(False) == (
        "OKX_API_KEY",
        "OKX_API_SECRET",
        "OKX_API_PASSPHRASE",
    )


def test_all_secret_names_cover_every_spec():
    for spec in EXCHANGE_REGISTRY:
        for sandbox in (True, False):
            for name in spec.secret_names(sandbox):
                assert name in all_secret_names()


def test_get_spec_returns_the_matching_entry():
    assert get_spec("kraken").display_name == "Kraken"


def test_get_spec_unknown_raises_key_error():
    with pytest.raises(KeyError):
        get_spec("not-a-venue")


def test_deribit_is_not_spot():
    assert get_spec("deribit").spot_supported is False


def test_lbank_uses_verified_v2_class_and_endpoint():
    spec = get_spec("lbank")
    assert spec.ccxt_id == "lbank"
    assert spec.permission_endpoint == "supplement/api_Restrictions"
    assert spec.sandbox_expected is False


def test_binance_permission_endpoint():
    assert get_spec("binance").permission_endpoint == "sapi/v1/account/apiRestrictions"


def test_base64_encoding_for_multiline_key_venues():
    assert get_spec("coinbase").secret_encoding == "base64"
    assert get_spec("bullish").secret_encoding == "base64"


def test_secret_encoding_values_are_valid():
    for spec in EXCHANGE_REGISTRY:
        assert spec.secret_encoding in {"plain", "base64"}


def test_sandbox_expectation_is_tristate():
    for spec in EXCHANGE_REGISTRY:
        assert spec.sandbox_expected in {True, False, None}
