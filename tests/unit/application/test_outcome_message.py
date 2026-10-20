from datetime import UTC, datetime

from application.outcome_message import OUTCOME_LABELS, render_outcome
from domain.outcome import OutcomeEvent


def _event(kind: str = "target", price: float = 110.0) -> OutcomeEvent:
    return OutcomeEvent("sig-1", kind, price, datetime(2026, 10, 1, 14, tzinfo=UTC))


def test_a_buy_target_is_rendered_with_a_positive_move():
    text = render_outcome("BTC/USDT", "1h", "buy", 100.0, _event())

    assert text.splitlines()[0] == "TP hit | BTC/USDT 1h BUY"
    assert "Entry: 100.00000000" in text
    assert "Exit: 110.00000000" in text
    assert "Move: +10.00%" in text


def test_a_sell_stop_is_rendered_with_a_negative_move():
    text = render_outcome("BTC/USDT", "1h", "sell", 100.0, _event("stop", 90.0))

    assert text.splitlines()[0] == "SL hit | BTC/USDT 1h SELL"
    assert "Exit: 90.00000000" in text
    assert "Move: +10.00%" in text


def test_a_sell_target_is_rendered_as_a_profit_for_the_seller():
    text = render_outcome("BTC/USDT", "1h", "sell", 100.0, _event("target", 90.0))

    assert "Move: +10.00%" in text


def test_a_sell_stop_is_rendered_as_a_loss_for_the_seller():
    text = render_outcome("BTC/USDT", "1h", "sell", 100.0, _event("stop", 110.0))

    assert "Move: -10.00%" in text


def test_a_buy_stop_is_rendered_with_a_negative_move():
    text = render_outcome("BTC/USDT", "1h", "buy", 100.0, _event("stop", 90.0))

    assert "Move: -10.00%" in text


def test_an_expired_event_is_rendered_with_its_label():
    text = render_outcome("ETH/USDT", "1d", "buy", 100.0, _event("expired", 105.0))

    assert text.splitlines()[0] == "Expired | ETH/USDT 1d BUY"
    assert "Move: +5.00%" in text


def test_the_candle_time_is_part_of_the_message():
    text = render_outcome("BTC/USDT", "1h", "buy", 100.0, _event())

    assert "2026-10-01T14:00:00+00:00" in text


def test_a_zero_entry_omits_the_move():
    text = render_outcome("BTC/USDT", "1h", "buy", 0.0, _event())

    assert "Move:" not in text


def test_the_message_has_no_markdown_syntax():
    text = render_outcome("BTC/USDT", "1h", "buy", 100.0, _event())

    for character in ("*", "_", "[", "]", "`"):
        assert character not in text


def test_every_kind_has_a_label():
    assert set(OUTCOME_LABELS) == {"target", "stop", "expired"}
