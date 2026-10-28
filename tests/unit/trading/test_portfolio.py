from datetime import UTC, datetime

import pytest

from common.core import Position, PositionSide
from trading.portfolio import PortfolioManager, PortfolioSnapshot


def make_position(
    symbol: str = "BTC/USDT",
    side: PositionSide = PositionSide.LONG,
    quantity: float = 1.0,
    entry: float = 100.0,
    stop: float = 95.0,
    target: float = 110.0,
    risk_amount: float = 0.0,
) -> Position:
    return Position(
        position_id=f"{symbol}-{side.value}",
        symbol=symbol,
        side=side,
        quantity=quantity,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        risk_amount=risk_amount,
    )


@pytest.fixture
def portfolio() -> PortfolioManager:
    return PortfolioManager(initial_cash=10000.0)


def test_initial_state(portfolio):
    assert portfolio.cash == 10000.0
    assert portfolio.positions == {}
    assert portfolio.realized_pnl == 0.0


def test_equity_without_positions(portfolio):
    assert portfolio.equity({}) == 10000.0


def test_equity_long_uses_market_price(portfolio):
    portfolio.open_position(make_position(), cost=1000.0, fee=10.0)
    assert portfolio.equity({"BTC/USDT": 110.0}) == pytest.approx(8990.0 + 110.0)


def test_equity_short_uses_two_times_entry(portfolio):
    portfolio.open_position(
        make_position(side=PositionSide.SHORT, entry=100.0), cost=1000.0, fee=0.0
    )
    assert portfolio.equity({"BTC/USDT": 90.0}) == pytest.approx(9000.0 + 110.0)


def test_unrealized_pnl_long_and_short(portfolio):
    portfolio.open_position(make_position(), cost=1000.0)
    assert portfolio.unrealized_pnl({"BTC/USDT": 110.0}) == pytest.approx(10.0)
    portfolio.close_position("BTC/USDT-long", 110.0)
    portfolio.open_position(make_position(side=PositionSide.SHORT, entry=100.0), cost=1000.0)
    assert portfolio.unrealized_pnl({"BTC/USDT": 90.0}) == pytest.approx(10.0)


def test_exposure_pct(portfolio):
    portfolio.open_position(make_position(quantity=1.0, entry=100.0), cost=100.0)
    result = portfolio.exposure_pct({"BTC/USDT": 100.0})
    assert result == pytest.approx(1.0)


def test_exposure_pct_zero_when_broke(portfolio):
    assert portfolio.exposure_pct({"BTC/USDT": 100.0}) == pytest.approx(0.0)


def test_close_position_long_realizes_pnl_net_of_fee(portfolio):
    portfolio.open_position(make_position(), cost=1000.0, fee=5.0)
    assert portfolio.cash == pytest.approx(8995.0)
    result = portfolio.close_position("BTC/USDT-long", 110.0, fee=2.0)
    assert result == pytest.approx(8.0)
    assert portfolio.cash == pytest.approx(8995.0 + 110.0 - 2.0)
    assert portfolio.realized_pnl == pytest.approx(-5.0 + 10.0 - 2.0)


def test_close_position_short_signs(portfolio):
    portfolio.open_position(make_position(side=PositionSide.SHORT, entry=100.0), cost=1000.0)
    result = portfolio.close_position("BTC/USDT-short", 90.0)
    assert result == pytest.approx(10.0)


def test_close_position_missing_raises(portfolio):
    with pytest.raises(KeyError):
        portfolio.close_position("nope", 100.0)


def test_portfolio_heat(portfolio):
    portfolio.open_position(make_position(entry=100.0, risk_amount=50.0), cost=1000.0)
    heat = portfolio.portfolio_heat({"BTC/USDT": 100.0})
    assert heat == pytest.approx(50.0 / 9100.0 * 100.0)


def test_portfolio_heat_zero_when_broke(portfolio):
    portfolio.open_position(make_position(), cost=1000.0)
    assert portfolio.portfolio_heat({"BTC/USDT": 0.0}) == 0.0


def test_snapshot_fields(portfolio):
    portfolio.open_position(make_position(), cost=1000.0, fee=0.0)
    snap = portfolio.snapshot({"BTC/USDT": 110.0})
    assert isinstance(snap, PortfolioSnapshot)
    assert snap.equity == pytest.approx(9000.0 + 110.0)
    assert snap.cash == pytest.approx(9000.0)
    assert snap.open_positions == 1
    assert snap.unrealized_pnl == pytest.approx(10.0)
    assert snap.realized_pnl == 0.0
    assert snap.exposure_pct > 0.0


def test_positions_by_symbol(portfolio):
    portfolio.open_position(make_position(symbol="BTC/USDT"), cost=100.0)
    portfolio.open_position(make_position(symbol="ETH/USDT"), cost=100.0)
    assert len(portfolio.positions_by_symbol("BTC/USDT")) == 1
    assert portfolio.positions_by_symbol("SOL/USDT") == []
