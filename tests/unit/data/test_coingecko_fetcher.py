from contextlib import asynccontextmanager

import pytest

from common.exceptions import ConfigurationError
from data.sources.coingecko_fetcher import CoinGeckoFetcher


class _StubConfig:
    def __init__(self, tier: str):
        self._tier = tier

    def get(self, key, default=None):
        if key == "coingecko_api_tier":
            return self._tier
        return default

    def get_cache_ttl(self, _name):
        return 60


class _RecordingSession:
    def __init__(self):
        self.calls: list[dict] = []
        self.closed = False

    def get(self, url, params=None, headers=None, **kwargs):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "headers": dict(headers or {})}
        )

        @asynccontextmanager
        async def _ctx():
            class _Response:
                status = 200

                async def json(self):
                    return {}

                async def text(self):
                    return ""

            yield _Response()

        return _ctx()


def _build(tier: str, api_key: str | None) -> tuple[CoinGeckoFetcher, _RecordingSession]:
    session = _RecordingSession()
    fetcher = CoinGeckoFetcher(
        api_key=api_key,
        session=session,
        config_manager=_StubConfig(tier),
    )
    return fetcher, session


async def test_demo_key_uses_public_host_and_demo_param():
    fetcher, session = _build("demo", "FAKE_TOKEN_123")
    await fetcher._fetch_json(f"{fetcher.base_url}/coins/list")

    call = session.calls[0]
    assert call["url"].startswith("https://api.coingecko.com/api/v3")
    assert "pro-api" not in call["url"]
    assert call["params"].get("x_cg_demo_api_key") == "FAKE_TOKEN_123"
    assert "x-cg-pro-api-key" not in call["headers"]


async def test_pro_key_uses_pro_host_and_pro_header():
    fetcher, session = _build("pro", "FAKE_TOKEN_123")
    await fetcher._fetch_json(f"{fetcher.base_url}/coins/list")

    call = session.calls[0]
    assert call["url"].startswith("https://pro-api.coingecko.com/api/v3")
    assert call["headers"].get("x-cg-pro-api-key") == "FAKE_TOKEN_123"
    assert "x_cg_demo_api_key" not in call["params"]


async def test_no_key_uses_public_host_without_credentials():
    fetcher, session = _build("demo", None)
    await fetcher._fetch_json(f"{fetcher.base_url}/coins/list")

    call = session.calls[0]
    assert call["url"].startswith("https://api.coingecko.com/api/v3")
    assert "x_cg_demo_api_key" not in call["params"]
    assert "x-cg-pro-api-key" not in call["headers"]


def test_unknown_tier_raises_configuration_error():
    with pytest.raises(ConfigurationError):
        CoinGeckoFetcher(
            api_key="FAKE_TOKEN_123",
            session=_RecordingSession(),
            config_manager=_StubConfig("bogus"),
        )
