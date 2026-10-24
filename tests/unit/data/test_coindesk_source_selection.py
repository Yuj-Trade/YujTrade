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


async def test_not_found_response_logs_warning_with_status():
    from contextlib import asynccontextmanager

    class _Session:
        closed = False

        def get(self, url, params=None, headers=None, **kwargs):
            @asynccontextmanager
            async def _ctx():
                class _Response:
                    status = 404

                    async def text(self):
                        return "  not   found  "

                    async def json(self):
                        return {}

                yield _Response()

            return _ctx()

    fetcher = CoinDeskFetcher(api_key="FAKE_TOKEN_123", session=_Session())

    messages: list[str] = []

    def sink(message):
        messages.append(message.record["message"])

    handler_id = logger.add(sink, format="{message}", level="DEBUG")
    try:
        result = await fetcher.get_historical_ohlc("BTC/USDT", "1h", 100)
    finally:
        logger.remove(handler_id)

    assert result is None
    assert any("404" in m for m in messages)


async def test_ohlcv_uses_documented_historical_endpoint():
    from contextlib import asynccontextmanager

    recorded: list[tuple[str, dict]] = []

    class _Session:
        closed = False

        def get(self, url, params=None, headers=None, **kwargs):
            recorded.append((url, dict(params or {})))

            @asynccontextmanager
            async def _ctx():
                class _Response:
                    status = 200

                    async def json(self):
                        return {
                            "Data": [
                                {
                                    "TIMESTAMP": 1791936000,
                                    "OPEN": 1.0,
                                    "HIGH": 2.0,
                                    "LOW": 0.5,
                                    "CLOSE": 1.5,
                                    "VOLUME": 10.0,
                                }
                            ]
                        }

                    async def text(self):
                        return ""

                yield _Response()

            return _ctx()

    fetcher = CoinDeskFetcher(api_key="FAKE_TOKEN_123", session=_Session())
    await fetcher.get_historical_ohlc("BTC/USDT", "1h", 100)

    url, params = recorded[0]
    assert "historical/ohlcv" not in url
    assert "/spot/v1/historical/" in url
    assert params.get("instrument") == "BTC-USD"
    assert "market" in params
