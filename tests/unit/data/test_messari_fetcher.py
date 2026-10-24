from contextlib import asynccontextmanager

from data.sources.messari_fetcher import MessariFetcher


class _StubConfig:
    def get(self, key, default=None):
        if key == "messari_enabled":
            return False
        return default

    def get_cache_ttl(self, _name):
        return 60


class _RecordingSession:
    def __init__(self):
        self.calls: list[str] = []
        self.closed = False

    def get(self, url, params=None, headers=None, **kwargs):
        self.calls.append(url)

        @asynccontextmanager
        async def _ctx():
            class _Response:
                status = 200

                async def json(self):
                    return {"data": {}}

                async def text(self):
                    return ""

            yield _Response()

        return _ctx()


async def test_disabled_messari_makes_no_request():
    session = _RecordingSession()
    fetcher = MessariFetcher(
        api_key="FAKE_TOKEN_123", session=session, config_manager=_StubConfig()
    )

    assert await fetcher.get_asset_metrics("BTC/USDT") is None
    assert await fetcher.get_news("BTC/USDT") == []
    assert session.calls == []
