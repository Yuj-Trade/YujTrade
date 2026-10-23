from loguru import logger

from data.sources.coindesk_fetcher import CoinDeskFetcher


def test_supports_ohlcv_only_for_btc_and_eth():
    fetcher = CoinDeskFetcher(api_key="FAKE_TOKEN_123", session=None)
    assert fetcher.supports_ohlcv("BTC/USDT") is True
    assert fetcher.supports_ohlcv("ETH/USDT") is True
    assert fetcher.supports_ohlcv("SOL/USDT") is False
    assert fetcher.supports_ohlcv("ASTR/USDT") is False


async def test_unsupported_symbol_does_not_call_coindesk():
    calls: list[str] = []

    class _Session:
        closed = False

        def get(self, url, **kwargs):
            calls.append(url)
            raise AssertionError("CoinDesk should not be called for an unsupported symbol")

    fetcher = CoinDeskFetcher(api_key="FAKE_TOKEN_123", session=_Session())

    messages: list[str] = []

    def sink(message):
        messages.append(message.record["message"])

    handler_id = logger.add(sink, format="{message}", level="DEBUG")
    try:
        result = await fetcher.get_historical_ohlc("SOL/USDT", "1h", 100)
    finally:
        logger.remove(handler_id)

    assert result is None
    assert calls == []
    assert not any("Source coindesk failed" in m for m in messages)
