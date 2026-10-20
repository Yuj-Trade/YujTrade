"""The paper engine takes its cost rates from the configuration.

Before the performance work the engine hard-coded a fee rate of 0.001 and a
slippage rate of 0.0005. The values are unchanged, they now come from
`ConfigManager`, so the engine behaviour is identical.
"""

from config.settings import ConfigManager
from trading.paper_trading import PaperTradingEngine


def _config(tmp_path, **overrides) -> ConfigManager:
    manager = ConfigManager(
        config_path=str(tmp_path / "config.json"),
        weights_path=str(tmp_path / "weights.json"),
    )
    for key, value in overrides.items():
        manager.set(key, value)
    return manager


def test_the_configured_defaults_match_the_previous_hard_coded_values():
    defaults = ConfigManager.DEFAULT_CONFIG

    assert defaults["paper_fee_rate"] == 0.001
    assert defaults["paper_slippage_rate"] == 0.0005


def test_the_engine_uses_the_configured_rates(tmp_path):
    config = _config(tmp_path, paper_fee_rate=0.002, paper_slippage_rate=0.001)

    engine = PaperTradingEngine(
        fee_rate=float(config.get("paper_fee_rate")),
        slippage_rate=float(config.get("paper_slippage_rate")),
    )

    assert engine.fee_rate == 0.002
    assert engine.slippage_rate == 0.001


def test_the_engine_rejects_a_missing_cost_rate(tmp_path):
    try:
        PaperTradingEngine()
    except TypeError as exc:
        assert "fee_rate" in str(exc)
    else:
        raise AssertionError("PaperTradingEngine must require the cost rates")
