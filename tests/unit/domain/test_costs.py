from datetime import UTC, datetime

import pytest

from domain.costs import (
    LEGACY_REPORT_VERSION,
    LEGACY_SIMULATOR_VERSION,
    CostProfile,
    cost_per_unit,
    cost_profile_from_config,
    fee_rate,
    fill_fraction,
    first_candle_quote_volume,
    legacy_report_profile,
    legacy_simulator_profile,
    net_r,
)
from domain.performance import ResolutionRecord, net_r_multiple


def _defaults() -> dict[str, object]:
    return {
        "version": "cost-model-v2",
        "maker_fee_rate": 0.001,
        "taker_fee_rate": 0.002,
        "entry_liquidity": "taker",
        "target_exit_liquidity": "maker",
        "stop_exit_liquidity": "taker",
        "expiry_exit_liquidity": "taker",
        "entry_slippage_rate": 0.0005,
        "market_exit_slippage_rate": 0.0004,
        "target_exit_slippage_rate": 0.0,
        "funding_rate_per_period": 0.0001,
        "funding_period_hours": 8,
        "max_volume_participation": 0.05,
    }


def _profile(**overrides) -> CostProfile:
    payload = _defaults()
    payload.update(overrides)
    return CostProfile.from_mapping(payload)


def test_legacy_report_profile_reproduces_the_original_formula_over_random_records():
    import random

    rng = random.Random(20261029)
    fee = 0.0017
    slippage = 0.00043
    profile = legacy_report_profile(fee, slippage)
    for _ in range(200):
        entry = rng.uniform(50.0, 500.0)
        stop = entry * (1.0 - rng.uniform(0.005, 0.05))
        exit_price = entry * (1.0 + rng.uniform(-0.08, 0.12))
        record = ResolutionRecord(
            signal_id=f"sig-{rng.randrange(10**6)}",
            symbol="BTC/USDT",
            timeframe="1h",
            side="buy",
            entry=entry,
            stop=stop,
            target=entry * 1.2,
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
            exit_at=datetime(2026, 10, 1, 5, tzinfo=UTC),
            exit_price=exit_price,
            exit_reason=rng.choice(["target", "stop", "expired"]),
            candles_used=5,
            resolver_version="paper-resolution-v1",
        )
        original = (exit_price - entry) / (entry - stop) - (fee + slippage) * (
            entry + exit_price
        ) / (entry - stop)
        actual = net_r_multiple(record, fee, slippage)
        assert actual == pytest.approx(original, rel=1e-12)
        direct = net_r(
            entry,
            stop,
            exit_price,
            "buy",
            record.exit_reason,
            4.0,
            profile,
            1.0,
        )
        assert direct == pytest.approx(original, rel=1e-12)


def test_cost_per_unit_for_each_exit_reason_with_distinct_rates():
    profile = _profile()
    entry = 100.0
    exit_price = 110.0
    holding = 4.0

    target = cost_per_unit(entry, exit_price, "target", holding, profile)
    assert target == pytest.approx(
        (0.002 + 0.0005) * 100.0 + 0.001 * 110.0 + 0.0001 * (holding / 8) * 100.0
    )

    stop = cost_per_unit(entry, exit_price, "stop", holding, profile)
    assert stop == pytest.approx(
        (0.002 + 0.0005) * 100.0 + (0.002 + 0.0004) * 110.0 + 0.0001 * (holding / 8) * 100.0
    )

    expired = cost_per_unit(entry, exit_price, "expired", holding, profile)
    assert expired == pytest.approx(stop)

    no_funding = cost_per_unit(
        entry, exit_price, "target", holding, _profile(funding_rate_per_period=0.0)
    )
    assert no_funding == pytest.approx((0.002 + 0.0005) * 100.0 + 0.001 * 110.0)


def test_hand_computed_net_r_for_a_buy_target():
    profile = _profile()
    value = net_r(100.0, 90.0, 110.0, "buy", "target", 4.0, profile, 1.0)
    cost = (0.002 + 0.0005) * 100.0 + 0.001 * 110.0 + 0.0001 * 0.5 * 100.0
    assert value == pytest.approx((10.0 - cost) / 10.0)


def test_hand_computed_net_r_for_a_sell_stop():
    profile = _profile()
    value = net_r(100.0, 110.0, 110.0, "sell", "stop", 8.0, profile, 1.0)
    cost = (0.002 + 0.0005) * 100.0 + (0.002 + 0.0004) * 110.0 + 0.0001 * 1.0 * 100.0
    assert value == pytest.approx((-10.0 - cost) / 10.0)


def test_funding_is_linear_in_the_holding_time():
    profile = _profile()
    one = cost_per_unit(100.0, 100.0, "expired", 1.0, profile)
    two = cost_per_unit(100.0, 100.0, "expired", 2.0, profile)
    base = cost_per_unit(100.0, 100.0, "expired", 0.0, profile)
    assert two - base == pytest.approx(2 * (one - base))


def test_fill_fraction_boundaries():
    assert fill_fraction(1000.0, 0.0, 0.05) == 0.0
    assert fill_fraction(1000.0, 20000.0, 0.05) == 1.0
    assert fill_fraction(1000.0, 40000.0, 0.05) == 1.0
    assert fill_fraction(1000.0, 10000.0, 0.05) == pytest.approx(0.5)


@pytest.mark.parametrize("notional", [0.0, -1.0])
def test_fill_fraction_rejects_a_non_positive_notional(notional):
    with pytest.raises(ValueError):
        fill_fraction(notional, 10.0, 0.05)


@pytest.mark.parametrize("participation", [0.0, 1.5, float("inf")])
def test_cost_profile_rejects_an_invalid_participation(participation):
    with pytest.raises(ValueError):
        _profile(max_volume_participation=participation)


def test_cost_profile_rejects_an_unknown_liquidity_label():
    with pytest.raises(ValueError):
        _profile(entry_liquidity="auction")


def test_cost_profile_rejects_an_empty_version():
    with pytest.raises(ValueError):
        _profile(version="")


def test_cost_profile_rejects_a_missing_key():
    payload = _defaults()
    del payload["maker_fee_rate"]
    with pytest.raises(ValueError):
        CostProfile.from_mapping(payload)


def test_cost_profile_rejects_an_unknown_key():
    payload = _defaults()
    payload["extra"] = 1
    with pytest.raises(ValueError):
        CostProfile.from_mapping(payload)


def test_cost_profile_rejects_a_negative_rate():
    with pytest.raises(ValueError):
        _profile(taker_fee_rate=-0.1)


def test_cost_profile_rejects_a_non_finite_rate():
    with pytest.raises(ValueError):
        _profile(taker_fee_rate=float("nan"))


def test_cost_profile_rejects_a_zero_funding_period():
    with pytest.raises(ValueError):
        _profile(funding_period_hours=0)


def test_cost_profile_from_config_merges_a_partial_override():
    defaults = _defaults()
    profile = cost_profile_from_config({"taker_fee_rate": 0.004}, defaults)
    assert profile.taker_fee_rate == 0.004
    assert profile.maker_fee_rate == defaults["maker_fee_rate"]
    assert profile.version == "cost-model-v2"


def test_cost_profile_from_config_with_no_override_uses_the_defaults():
    defaults = _defaults()
    profile = cost_profile_from_config(None, defaults)
    assert profile == CostProfile.from_mapping(defaults)


def test_fee_rate_selects_the_label():
    profile = _profile()
    assert fee_rate(profile, "maker") == 0.001
    assert fee_rate(profile, "taker") == 0.002
    with pytest.raises(ValueError):
        fee_rate(profile, "auction")


def test_net_r_rejects_an_unknown_exit_reason():
    profile = _profile()
    with pytest.raises(ValueError):
        net_r(100.0, 90.0, 110.0, "buy", "liquidated", 1.0, profile, 1.0)


def test_net_r_rejects_a_zero_risk():
    profile = _profile()
    with pytest.raises(ValueError):
        net_r(100.0, 100.0, 110.0, "buy", "target", 1.0, profile, 1.0)


@pytest.mark.parametrize("fill_ratio", [0.0, -0.1, 1.1])
def test_net_r_rejects_an_out_of_range_fill_ratio(fill_ratio):
    profile = _profile()
    with pytest.raises(ValueError):
        net_r(100.0, 90.0, 110.0, "buy", "target", 1.0, profile, fill_ratio)


def test_net_r_scales_with_the_fill_ratio():
    profile = _profile()
    full = net_r(100.0, 90.0, 110.0, "buy", "target", 4.0, profile, 1.0)
    half = net_r(100.0, 90.0, 110.0, "buy", "target", 4.0, profile, 0.5)
    assert half == pytest.approx(full / 2.0)


def test_cost_per_unit_rejects_a_negative_holding_time():
    profile = _profile()
    with pytest.raises(ValueError):
        cost_per_unit(100.0, 100.0, "target", -1.0, profile)


def _candles():
    base = datetime(2026, 10, 1, tzinfo=UTC)
    return [
        {
            "timestamp": base.replace(hour=hour),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0 + hour,
            "volume": 10.0,
        }
        for hour in (0, 1, 2)
    ]


def test_first_candle_quote_volume_is_none_for_an_empty_input():
    assert first_candle_quote_volume([], datetime(2026, 10, 1, tzinfo=UTC)) is None


def test_first_candle_quote_volume_is_none_without_a_candle_at_or_after():
    later = datetime(2026, 10, 2, tzinfo=UTC)
    assert first_candle_quote_volume(_candles(), later) is None


def test_first_candle_quote_volume_accepts_a_candle_exactly_at_the_bound():
    boundary = datetime(2026, 10, 1, 1, tzinfo=UTC)
    assert first_candle_quote_volume(_candles(), boundary) == pytest.approx(10.0 * 101.0)


def test_first_candle_quote_volume_uses_the_first_eligible_candle():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    assert first_candle_quote_volume(_candles(), start) == pytest.approx(10.0 * 100.0)


def test_first_candle_quote_volume_rejects_a_naive_bound():
    with pytest.raises(ValueError):
        first_candle_quote_volume(_candles(), datetime(2026, 10, 1))


def test_legacy_versions_are_distinct():
    report = legacy_report_profile(0.001, 0.0005)
    simulator = legacy_simulator_profile(0.001, 0.0005)
    assert report.version == LEGACY_REPORT_VERSION
    assert simulator.version == LEGACY_SIMULATOR_VERSION
    assert report.version != simulator.version
