import pytest

from common.core import OrderSide, OrderStatus, OrderType, PositionSide
from trading.orders import BracketOrder, OrderManager


@pytest.fixture
def manager() -> OrderManager:
    return OrderManager()


def test_bracket_builds_entry_stop_target(manager):
    bracket = manager.bracket("BTC/USDT", OrderSide.BUY, 2.0, 100.0, 95.0, 110.0)
    assert isinstance(bracket, BracketOrder)
    assert bracket.entry.order_type is OrderType.LIMIT
    assert bracket.entry.price == 100.0
    assert bracket.stop.order_type is OrderType.STOP
    assert bracket.stop.stop_price == 95.0
    assert bracket.target.order_type is OrderType.LIMIT
    assert bracket.target.price == 110.0
    assert bracket.position_id is None


def test_bracket_stop_and_target_use_opposite_side(manager):
    bracket = manager.bracket("BTC/USDT", OrderSide.BUY, 1.0, 100.0, 95.0, 110.0)
    assert bracket.stop.side is OrderSide.SELL
    assert bracket.target.side is OrderSide.SELL

    sell = manager.bracket("ETH/USDT", OrderSide.SELL, 1.0, 100.0, 105.0, 90.0)
    assert sell.stop.side is OrderSide.BUY
    assert sell.target.side is OrderSide.BUY


def test_bracket_registers_orders_and_paper_flag(manager):
    bracket = manager.bracket("BTC/USDT", OrderSide.BUY, 1.0, 100.0, 95.0, 110.0)
    assert len(manager.orders) == 3
    for order in (bracket.entry, bracket.stop, bracket.target):
        assert order.paper is True
        assert order.status is OrderStatus.OPEN
        assert manager.orders[order.order_id] is order


def test_bracket_ids_are_unique(manager):
    bracket = manager.bracket("BTC/USDT", OrderSide.BUY, 1.0, 100.0, 95.0, 110.0)
    ids = {bracket.entry.order_id, bracket.stop.order_id, bracket.target.order_id}
    assert len(ids) == 3


def test_bracket_propagates_signal_and_timeframe(manager):
    bracket = manager.bracket(
        "BTC/USDT",
        OrderSide.BUY,
        1.0,
        100.0,
        95.0,
        110.0,
        signal_id="sig-1",
        timeframe="1d",
    )
    assert bracket.entry.signal_id == "sig-1"
    assert bracket.stop.timeframe == "1d"
    assert bracket.target.signal_id == "sig-1"


def test_trailing_ignores_zero_distance(manager):
    manager.set_trailing("pos-1", 0.0)
    assert manager.update_trailing("pos-1", PositionSide.LONG, 110.0, 103.0) == 103.0


def test_trailing_ignores_missing_position(manager):
    assert manager.update_trailing("missing", PositionSide.LONG, 110.0, 103.0) == 103.0


def test_trailing_raises_long_stop(manager):
    manager.set_trailing("pos-1", 2.0)
    result = manager.update_trailing("pos-1", PositionSide.LONG, 110.0, 103.0, highest=105.0)
    assert result == pytest.approx(107.8)


def test_trailing_never_lowers_long_stop(manager):
    manager.set_trailing("pos-1", 5.0)
    result = manager.update_trailing("pos-1", PositionSide.LONG, 100.0, 115.0, highest=100.0)
    assert result == 115.0


def test_trailing_lowers_short_stop(manager):
    manager.set_trailing("pos-1", 2.0)
    result = manager.update_trailing("pos-1", PositionSide.SHORT, 90.0, 94.0, lowest=95.0)
    assert result == pytest.approx(91.8)


def test_trailing_short_without_existing_stop(manager):
    manager.set_trailing("pos-1", 2.0)
    result = manager.update_trailing("pos-1", PositionSide.SHORT, 90.0, 0.0, lowest=95.0)
    assert result == pytest.approx(91.8)


def test_trailing_ignores_non_positive_price(manager):
    manager.set_trailing("pos-1", 2.0)
    assert manager.update_trailing("pos-1", PositionSide.LONG, 0.0, 103.0) == 103.0


def test_cancel_bracket_cancels_open_and_pending_only(manager):
    bracket = manager.bracket("BTC/USDT", OrderSide.BUY, 1.0, 100.0, 95.0, 110.0)
    bracket.entry.status = OrderStatus.FILLED
    before = bracket.entry.updated_at
    manager.cancel_bracket(bracket)
    assert bracket.entry.status is OrderStatus.FILLED
    assert bracket.entry.updated_at == before
    assert bracket.stop.status is OrderStatus.CANCELLED
    assert bracket.target.status is OrderStatus.CANCELLED


def test_open_orders_filters_finished(manager):
    bracket = manager.bracket("BTC/USDT", OrderSide.BUY, 1.0, 100.0, 95.0, 110.0)
    bracket.entry.status = OrderStatus.FILLED
    bracket.target.status = OrderStatus.CANCELLED
    open_orders = manager.open_orders()
    assert [o.order_id for o in open_orders] == [bracket.stop.order_id]


def test_open_orders_empty_initially():
    assert OrderManager().open_orders() == []
