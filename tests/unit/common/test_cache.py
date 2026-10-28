from common.cache import CacheCategory, CacheKeyBuilder


def test_all_categories_have_distinct_values():
    values = [category.value for category in CacheCategory]
    assert len(values) == len(set(values))


def test_ohlcv_key_layout():
    key = CacheKeyBuilder.ohlcv_key("Binance", "BTC/USDT", "1d")
    assert key == "cache:ohlcv:binance:btc_usdt:1d"


def test_symbol_slash_and_backslash_are_normalized():
    key = CacheKeyBuilder.ohlcv_key("SRC", "BTC/USDT", "1h")
    assert "btc_usdt" in key
    key2 = CacheKeyBuilder.build(CacheCategory.GENERIC, "src", ["id"], symbol="ETH\\USDT")
    assert "ethusdt" in key2


def test_symbol_is_lowercased():
    key = CacheKeyBuilder.build(CacheCategory.GENERIC, "SRC", ["ID"], symbol="BTC/USDT")
    assert key == "cache:generic:src:btc_usdt:id"


def test_missing_symbol_becomes_global():
    key = CacheKeyBuilder.build(CacheCategory.MACRO, "FRED", ["fed_rate"], symbol=None)
    assert key == "cache:macro:fred:global:fed_rate"


def test_empty_parts_omitted():
    key = CacheKeyBuilder.build(CacheCategory.NEWS, "cryptopanic", [])
    assert key == "cache:news:cryptopanic:global"


def test_parts_are_lowercased_and_joined():
    key = CacheKeyBuilder.derivatives_key("Binance", "FundingRate", "BTC/USDT")
    assert key == "cache:derivatives:binance:btc_usdt:fundingrate"


def test_macro_key_ignores_symbol():
    assert CacheKeyBuilder.macro_key("FRED", "CPI") == "cache:macro:fred:global:cpi"
    assert CacheKeyBuilder.macro_key("FRED", "cpi") == "cache:macro:fred:global:cpi"


def test_indices_key_ignores_symbol():
    assert CacheKeyBuilder.indices_key("Source", "BTC.D") == "cache:indices:source:global:btc.d"


def test_generic_key_passthrough():
    assert CacheKeyBuilder.generic_key("src", "ID", "btc/usdt") == "cache:generic:src:btc_usdt:id"


def test_fear_greed_category_value():
    key = CacheKeyBuilder.build(CacheCategory.FEAR_GREED, "alternative", ["index"])
    assert key.startswith("cache:fear_greed:alternative")
