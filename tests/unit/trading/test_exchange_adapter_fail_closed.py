import pytest

from common.core import OrderSide, OrderStatus, OrderType
from trading.execution import ExchangeAdapter, ExecutionEngine


class FakeExchange:
    def __init__(self, create_result=None, create_error=None, last_price=100.0):
        self.create_result = create_result
        self.create_error = create_error
        self.last_price = last_price
        self.created = []

    async def fetch_ticker(self, symbol):
        return {"last": self.last_price}

    async def create_order(self, symbol, order_type, side, amount, price):
        self.created.append(
            {
                "symbol": symbol,
                "order_type": order_type,
                "side": side,
                "amount": amount,
                "price": price,
            }
        )
        if self.create_error is not None:
            raise self.create_error
        return self.create_result


@pytest.mark.asyncio
async def test_missing_exchange_fails_closed():
    adapter = ExchangeAdapter(exchange=None, dry_run=False)
    result = await adapter.create_order("BTC/USDT", OrderSide.BUY, 1.0, 100.0, OrderType.LIMIT)
    assert result.ok is False
    assert result.error == "exchange_not_configured"
    assert result.order_id == ""


@pytest.mark.asyncio
async def test_dry_run_keeps_synthetic_success():
    adapter = ExchangeAdapter(exchange=None, dry_run=True)
    result = await adapter.create_order("BTC/USDT", OrderSide.BUY, 2.0, 50.0, OrderType.LIMIT)
    assert result.ok is True
    assert result.order_id
    assert result.fee == pytest.approx(2.0 * 50.0 * adapter.fee_rate)


@pytest.mark.asyncio
async def test_missing_order_id_is_not_fabricated():
    exchange = FakeExchange(create_result={"status": "closed", "filled": 1.0, "fee": {"cost": 0.1}})
    adapter = ExchangeAdapter(exchange=exchange, dry_run=False)
    result = await adapter.create_order("BTC/USDT", OrderSide.BUY, 1.0, 100.0, OrderType.LIMIT)
    assert result.ok is False
    assert result.error == "missing_order_id"
    assert len(exchange.created) == 1


@pytest.mark.asyncio
async def test_unreported_fill_is_not_assumed():
    exchange = FakeExchange(create_result={"id": "abc123", "status": "open", "fee": {"cost": 0.1}})
    adapter = ExchangeAdapter(exchange=exchange, dry_run=False)
    result = await adapter.create_order("BTC/USDT", OrderSide.BUY, 1.0, 100.0, OrderType.LIMIT)
    assert result.ok is False
    assert result.error == "fill_unknown"
    assert result.order_id == "abc123"


@pytest.mark.asyncio
async def test_fee_comes_from_response_not_fee_rate():
    exchange = FakeExchange(
        create_result={
            "id": "abc123",
            "status": "closed",
            "filled": 1.0,
            "average": 100.5,
            "fee": {"cost": 0.37, "currency": "USDT"},
        }
    )
    adapter = ExchangeAdapter(exchange=exchange, dry_run=False, fee_rate=0.5)
    result = await adapter.create_order("BTC/USDT", OrderSide.BUY, 1.0, 100.0, OrderType.LIMIT)
    assert result.ok is True
    assert result.fee == pytest.approx(0.37)
    assert result.price == pytest.approx(100.5)


@pytest.mark.asyncio
async def test_missing_fee_is_not_estimated():
    exchange = FakeExchange(create_result={"id": "abc123", "status": "closed", "filled": 1.0})
    adapter = ExchangeAdapter(exchange=exchange, dry_run=False, fee_rate=0.5)
    result = await adapter.create_order("BTC/USDT", OrderSide.BUY, 1.0, 100.0, OrderType.LIMIT)
    assert result.ok is False
    assert result.error == "fee_unknown"
    assert result.fee == 0.0


@pytest.mark.asyncio
async def test_network_error_returns_not_ok():
    exchange = FakeExchange(create_error=RuntimeError("timeout"))
    adapter = ExchangeAdapter(exchange=exchange, dry_run=False)
    result = await adapter.create_order("BTC/USDT", OrderSide.SELL, 1.0, 100.0, OrderType.LIMIT)
    assert result.ok is False
    assert result.error == "timeout"


@pytest.mark.asyncio
async def test_open_limit_order_is_not_recorded_as_filled():
    exchange = FakeExchange(
        create_result={"id": "abc123", "status": "open", "filled": 0.0, "fee": {"cost": 0.0}}
    )
    adapter = ExchangeAdapter(exchange=exchange, dry_run=False)
    engine = ExecutionEngine(adapter=adapter)
    result = await engine.execute(
        "BTC/USDT", OrderSide.BUY, 1.0, 100.0, OrderType.LIMIT, signal_id="sig-1"
    )
    assert result.ok is True
    recorded = engine.orders["abc123"]
    assert recorded.status is OrderStatus.OPEN
    assert recorded.status is not OrderStatus.FILLED
    assert recorded.paper is False


@pytest.mark.asyncio
async def test_filled_order_is_recorded_as_filled():
    exchange = FakeExchange(
        create_result={
            "id": "abc123",
            "status": "closed",
            "filled": 1.0,
            "average": 100.0,
            "fee": {"cost": 0.1},
        }
    )
    adapter = ExchangeAdapter(exchange=exchange, dry_run=False)
    engine = ExecutionEngine(adapter=adapter)
    await engine.execute("BTC/USDT", OrderSide.BUY, 1.0, 100.0, OrderType.LIMIT)
    assert engine.orders["abc123"].status is OrderStatus.FILLED


@pytest.mark.asyncio
async def test_rejected_status_maps_to_rejected_order():
    exchange = FakeExchange(
        create_result={"id": "abc123", "status": "canceled", "filled": 0.0, "fee": {"cost": 0.0}}
    )
    adapter = ExchangeAdapter(exchange=exchange, dry_run=False)
    engine = ExecutionEngine(adapter=adapter)
    await engine.execute("BTC/USDT", OrderSide.BUY, 1.0, 100.0, OrderType.LIMIT)
    assert engine.orders["abc123"].status is OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_failed_order_does_not_fabricate_order_id():
    exchange = FakeExchange(create_result={})
    adapter = ExchangeAdapter(exchange=exchange, dry_run=False)
    engine = ExecutionEngine(adapter=adapter)
    result = await engine.execute("BTC/USDT", OrderSide.BUY, 1.0, 100.0, OrderType.LIMIT)
    assert result.ok is False
    assert result.order_id == ""
    assert engine.orders == {}
