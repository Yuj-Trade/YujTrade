## 1. Pure cost foundation (P1)
- [ ] 1.1 `domain/costs.py`: `CostProfile`, `from_mapping`, `cost_profile_from_config`
- [ ] 1.2 `fee_rate`, `cost_per_unit`, `net_r`, `fill_fraction`, `first_candle_quote_volume`
- [ ] 1.3 `legacy_report_profile`, `legacy_simulator_profile`
- [ ] 1.4 Route `net_r_multiple` through `net_r` with the legacy profile
- [ ] 1.5 `tests/unit/domain/test_costs.py`

## 2. Paper engine and report (P3)
- [ ] 2.1 `signal_resolutions.entry_quote_volume` column
- [ ] 2.2 `Resolution.entry_quote_volume` and the resolver fill
- [ ] 2.3 `paper_cost_model` defaults and `build_cost_profile`
- [ ] 2.4 Paper engine cost model, fill fraction, funding; remove `apply_funding`
- [ ] 2.5 Report v2 with the profile and the coverage block
- [ ] 2.6 `tests/unit/trading/test_paper_cost_model_v2.py`, worked example v2

## 3. Simulator and golden (P5)
- [ ] 3.1 `SimulatorConfig.cost_profile`, `RunStats.skipped_unfilled`, v2 branch
- [ ] 3.2 Scripts pass the profile
- [ ] 3.3 `record_cost_v2_baseline()` and the v2 golden
- [ ] 3.4 `tests/unit/backtesting/test_simulator_cost_v2.py`, golden test
