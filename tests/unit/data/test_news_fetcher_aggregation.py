import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from data.sources.news_fetcher import NewsFetcher


def _fetcher(redis_client=None, coindesk=None, messari=None):
    cryptopanic = MagicMock()
    cryptopanic.fetch_posts = AsyncMock(return_value=[{"id": 1, "title": "pump"}])
    alternativeme = MagicMock()
    alternativeme.fetch_fear_greed = AsyncMock(
        return_value=[{"value": "55", "value_classification": "Neutral"}]
    )
    alternativeme.close = AsyncMock()
    cryptopanic.close = AsyncMock()

    fetcher = NewsFetcher(
        cryptopanic_fetcher=cryptopanic,
        alternativeme_fetcher=alternativeme,
        coindesk_fetcher=coindesk,
        messari_fetcher=messari,
        redis_client=redis_client,
    )
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 600
    return fetcher


class TestFetchNews:
    async def test_results_are_deduplicated_by_id(self):
        fetcher = _fetcher()
        fetcher.cryptopanic.fetch_posts = AsyncMock(
            return_value=[{"id": 1, "title": "a"}, {"id": 1, "title": "a"}, {"id": 2, "title": "b"}]
        )

        news = await fetcher.fetch_news(["BTC"])

        assert len(news) == 2

    async def test_items_without_an_id_fall_back_to_the_title(self):
        fetcher = _fetcher()
        fetcher.cryptopanic.fetch_posts = AsyncMock(
            return_value=[{"title": "same"}, {"title": "same"}, {"title": "other"}]
        )

        news = await fetcher.fetch_news(["BTC"])

        assert len(news) == 2

    async def test_coindesk_is_skipped_when_kind_is_set(self):
        coindesk = MagicMock()
        coindesk.get_news = AsyncMock(return_value=[{"id": 9}])
        fetcher = _fetcher(coindesk=coindesk)

        await fetcher.fetch_news(["BTC"], kind="media")

        coindesk.get_news.assert_not_awaited()

    async def test_coindesk_is_queried_without_kind(self):
        coindesk = MagicMock()
        coindesk.get_news = AsyncMock(return_value=[{"id": 9}])
        fetcher = _fetcher(coindesk=coindesk)

        news = await fetcher.fetch_news(["BTC"])

        coindesk.get_news.assert_awaited_once()
        assert {item["id"] for item in news} == {1, 9}

    async def test_messari_is_queried_per_currency(self):
        messari = MagicMock()
        messari.get_news = AsyncMock(return_value=[{"id": 7}])
        fetcher = _fetcher(messari=messari)

        await fetcher.fetch_news(["BTC", "ETH"])

        assert messari.get_news.await_count == 2

    async def test_a_failing_source_does_not_break_the_aggregate(self):
        fetcher = _fetcher()
        fetcher.cryptopanic.fetch_posts = AsyncMock(side_effect=RuntimeError("down"))

        assert await fetcher.fetch_news(["BTC"]) == []

    async def test_results_are_cached(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fetcher = _fetcher(redis_client=redis)

        await fetcher.fetch_news(["BTC"])

        redis.set.assert_awaited_once()

    async def test_cache_hit_skips_every_source(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps([{"id": 3}]))
        fetcher = _fetcher(redis_client=redis)

        assert await fetcher.fetch_news(["BTC"]) == [{"id": 3}]
        fetcher.cryptopanic.fetch_posts.assert_not_awaited()

    async def test_cache_read_failure_falls_through_to_the_sources(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=RuntimeError("redis down"))
        fetcher = _fetcher(redis_client=redis)

        assert await fetcher.fetch_news(["BTC"])

    async def test_empty_result_is_not_cached(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fetcher = _fetcher(redis_client=redis)
        fetcher.cryptopanic.fetch_posts = AsyncMock(return_value=[])

        await fetcher.fetch_news(["BTC"])

        redis.set.assert_not_awaited()


class TestSentiment:
    async def test_sentiment_counts_and_fear_greed(self):
        fetcher = _fetcher()
        fetcher.cryptopanic.fetch_posts = AsyncMock(
            return_value=[
                {"id": 1, "title": "rally", "votes": {"positive": 3, "negative": 1}},
                {"id": 2, "title": "crash", "votes": {"positive": 1, "negative": 4}},
            ]
        )

        sentiment = await fetcher.fetch_sentiment_analysis(["BTC"])

        assert sentiment["news_count"] == 2
        assert sentiment["positive_count"] == 1
        assert sentiment["negative_count"] == 1
        assert sentiment["fear_greed_index"] == 55
        assert sentiment["fear_greed_classification"] == "Neutral"

    async def test_sentiment_is_cached(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({"overall_score": 7}))
        fetcher = _fetcher(redis_client=redis)

        assert await fetcher.fetch_sentiment_analysis(["BTC"]) == {"overall_score": 7}

    async def test_sentiment_failure_returns_empty_dict(self):
        fetcher = _fetcher()
        fetcher.alternativeme.fetch_fear_greed = AsyncMock(side_effect=RuntimeError("down"))

        assert await fetcher.fetch_sentiment_analysis(["BTC"]) == {}


class TestTrendingTopics:
    async def test_currency_codes_are_collected_once(self):
        fetcher = _fetcher()
        fetcher.cryptopanic.fetch_posts = AsyncMock(
            return_value=[
                {"currencies": [{"code": "BTC"}, {"code": "ETH"}]},
                {"currencies": [{"code": "BTC"}]},
            ]
        )

        assert await fetcher.fetch_trending_topics() == ["BTC", "ETH"]

    async def test_trending_cache_hit(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps(["SOL"]))
        fetcher = _fetcher(redis_client=redis)

        assert await fetcher.fetch_trending_topics() == ["SOL"]

    async def test_trending_failure_returns_empty_list(self):
        fetcher = _fetcher()
        fetcher.cryptopanic.fetch_posts = AsyncMock(side_effect=RuntimeError("down"))

        assert await fetcher.fetch_trending_topics() == []


class TestLifecycle:
    async def test_close_closes_every_child(self):
        coindesk = MagicMock()
        coindesk.close = AsyncMock()
        messari = MagicMock()
        messari.close = AsyncMock()
        fetcher = _fetcher(coindesk=coindesk, messari=messari)

        await fetcher.close()

        fetcher.cryptopanic.close.assert_awaited_once()
        fetcher.alternativeme.close.assert_awaited_once()
        coindesk.close.assert_awaited_once()
        messari.close.assert_awaited_once()

    async def test_close_is_idempotent(self):
        fetcher = _fetcher()

        await fetcher.close()
        await fetcher.close()

        fetcher.cryptopanic.close.assert_awaited_once()

    async def test_use_after_close_is_rejected(self):
        fetcher = _fetcher()
        await fetcher.close()

        with pytest.raises(RuntimeError, match="closed"):
            await fetcher.fetch_news(["BTC"])

    def test_score_news_counts_votes_and_keywords(self):
        fetcher = _fetcher()

        score = fetcher.score_news(
            [
                {"title": "bull rally", "votes": {"positive": 5, "negative": 1}},
                {"title": "major hack", "votes": {"positive": 0, "negative": 2}},
            ]
        )

        assert score == 5 - 1 + 1 - 2 - 1

    def test_score_news_of_empty_input_is_zero(self):
        assert _fetcher().score_news([]) == 0
