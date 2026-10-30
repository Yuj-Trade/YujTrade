"""The reserved intrabar price port and its null implementation (P9)."""

import asyncio

from application.outcome_ports import IntrabarPriceFeed
from data.intrabar_feed import NullIntrabarPriceFeed


def test_the_null_feed_returns_none():
    feed = NullIntrabarPriceFeed()

    assert asyncio.run(feed.last_price("BTC/USDT")) is None


def test_the_null_feed_conforms_to_the_protocol():
    feed: IntrabarPriceFeed = NullIntrabarPriceFeed()

    assert isinstance(feed, IntrabarPriceFeed)


def test_the_protocol_is_runtime_checkable():
    assert getattr(IntrabarPriceFeed, "_is_runtime_protocol", False) is True
