from data.sources.news_fetcher import NewsFetcher


class _StubConfig:
    def get(self, key, default=None):
        return default

    def get_cache_ttl(self, _name):
        return 60


class _StubCryptoPanic:
    async def fetch_posts(self, currencies, kind):
        return []


async def test_coindesk_news_disabled_makes_no_request():
    requested: list[str] = []

    class _CoinDesk:
        async def get_news(self, currencies):
            requested.append(currencies)
            return []

    fetcher = NewsFetcher(
        cryptopanic_fetcher=_StubCryptoPanic(),
        alternativeme_fetcher=None,
        coindesk_fetcher=None,
        messari_fetcher=None,
        redis_client=None,
        config_manager=_StubConfig(),
    )

    assert fetcher.coindesk is None
    await fetcher.fetch_news(["BTC"])
    assert requested == []


async def test_coindesk_news_enabled_uses_fetcher():
    requested: list[str] = []

    class _CoinDesk:
        async def get_news(self, currencies):
            requested.append(currencies)
            return []

    fetcher = NewsFetcher(
        cryptopanic_fetcher=_StubCryptoPanic(),
        alternativeme_fetcher=None,
        coindesk_fetcher=_CoinDesk(),
        messari_fetcher=None,
        redis_client=None,
        config_manager=_StubConfig(),
    )

    await fetcher.fetch_news(["BTC"])
    assert requested == [["BTC"]]
