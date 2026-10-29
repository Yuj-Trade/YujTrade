import dataclasses

import pytest

from domain.exchange_types import (
    CANCELED,
    EXPIRED,
    FILLED,
    NON_TERMINAL_STATUSES,
    OPEN,
    PARTIALLY_FILLED,
    PENDING_SUBMIT,
    REJECTED,
    SHADOW,
    SUBMITTED,
    TERMINAL_STATUSES,
    UNKNOWN,
    OrderIntent,
    OrderSnapshot,
    PlacementResult,
)


def test_status_values_are_lowercase_names():
    assert PENDING_SUBMIT == "pending_submit"
    assert SUBMITTED == "submitted"
    assert OPEN == "open"
    assert PARTIALLY_FILLED == "partially_filled"
    assert FILLED == "filled"
    assert CANCELED == "canceled"
    assert REJECTED == "rejected"
    assert EXPIRED == "expired"
    assert UNKNOWN == "unknown"
    assert SHADOW == "shadow"


def test_terminal_statuses():
    assert TERMINAL_STATUSES == frozenset({FILLED, CANCELED, REJECTED, EXPIRED, SHADOW})


def test_non_terminal_statuses():
    assert NON_TERMINAL_STATUSES == frozenset(
        {PENDING_SUBMIT, SUBMITTED, OPEN, PARTIALLY_FILLED, UNKNOWN}
    )


def test_terminal_and_non_terminal_are_disjoint():
    assert TERMINAL_STATUSES.isdisjoint(NON_TERMINAL_STATUSES)


def test_order_intent_is_frozen():
    intent = OrderIntent(
        exchange_id="binance",
        signal_id="sig-1",
        symbol="BTC/USDT",
        side="buy",
        amount=0.01,
        price=51000.0,
        client_order_id="abc",
        sandbox=True,
    )
    assert intent.side == "buy"
    assert intent.sandbox is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        intent.amount = 1.0


def test_placement_result_defaults():
    result = PlacementResult(accepted=True, exchange_order_id="x1")
    assert result.error == ""
    assert result.fee_cost == 0.0
    assert result.fee_currency == ""


def test_order_snapshot_fields():
    snapshot = OrderSnapshot(
        exchange_order_id="x1",
        client_order_id="c1",
        status=FILLED,
        filled=1.0,
        average_price=100.0,
        fee_cost=0.1,
        fee_currency="USDT",
    )
    assert snapshot.status in TERMINAL_STATUSES
