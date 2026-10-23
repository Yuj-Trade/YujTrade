from contextlib import asynccontextmanager

from data.sources.defillama_fetcher import DeFiLlamaFetcher


class _RecordingSession:
    def __init__(self, payload):
        self.payload = payload
        self.urls: list[str] = []
        self.closed = False

    def get(self, url, params=None, headers=None, **kwargs):
        self.urls.append(url)
        payload = self.payload

        @asynccontextmanager
        async def _ctx():
            class _Response:
                status = 200

                async def json(self):
                    return payload

                async def text(self):
                    return ""

            yield _Response()

        return _ctx()


async def test_chain_tvl_uses_v2_chains_endpoint():
    payload = [{"name": "Ethereum", "tvl": 1.0}, {"name": "Solana", "tvl": 2.0}]
    session = _RecordingSession(payload)
    fetcher = DeFiLlamaFetcher(session=session)

    result = await fetcher.get_total_tvl_for_chains()

    assert session.urls[0].endswith("/v2/chains")
    assert result == payload
