# Cost-model-v2 — worked example

Every number below is produced by the implementation and is pinned by
`tests/unit/application/test_performance_worked_example_v2.py`. The example
uses the same three trades as `docs/performance-worked-example.md` (one
target, one stop, one expired) and runs them through the cost-model-v2
profile instead of the legacy profile.

## Inputs

| Item | Value |
|---|---|
| Mode | `paper` |
| `as_of` | `2026-10-03T23:59:59+00:00` |
| `initial_cash` | `10000.0` |
| `risk_per_trade_pct` | `1.0` |
| `cost_model_version` | `cost-model-v2` |
| `maker_fee_rate` | `0.001` |
| `taker_fee_rate` | `0.001` |
| `entry_liquidity` | `taker` |
| `target_exit_liquidity` | `maker` |
| `stop_exit_liquidity` | `taker` |
| `expiry_exit_liquidity` | `taker` |
| `entry_slippage_rate` | `0.0005` |
| `market_exit_slippage_rate` | `0.0005` |
| `target_exit_slippage_rate` | `0.0` |
| `funding_rate_per_period` | `0.0001` |
| `funding_period_hours` | `8.0` |
| `max_volume_participation` | `0.05` |
| `performance_rf_annual` | `0` |
| `performance_periods_per_year` | `365` |
| `performance_min_trades_for_ratios` | `30` (and `3` for the ratio variant) |

| Signal | Symbol | Side | Entry | Stop | Exit | Reason | Created (UTC) | Exit (UTC) | Entry quote volume |
|---|---|---|---|---|---|---|---|---|---|
| `sig-a` | BTC/USDT | buy | 100 | 90 | 120 | target | 2026-10-01T10:00:00 | 2026-10-01T14:00:00 | 250000 |
| `sig-b` | BTC/USDT | buy | 100 | 90 | 90 | stop | 2026-10-02T10:00:00 | 2026-10-02T14:00:00 | 250000 |
| `sig-c` | BTC/USDT | buy | 100 | 90 | 110 | expired | 2026-10-03T10:00:00 | 2026-10-03T14:00:00 | 250000 |

The risk distance of every trade is `|100 - 90| = 10`. The holding time of
every trade is `4` hours.

## Step 1 — the fill fraction

The notional is the reference notional, so it does not depend on the
equity path:

```
reference_risk = initial_cash * risk_per_trade_pct / 100 = 10000 * 1 / 100 = 100
notional       = reference_risk * entry / |entry - stop| = 100 * 100 / 10 = 1000
fill_fraction  = min(1, max_volume_participation * quote_volume / notional)
               = min(1, 0.05 * 250000 / 1000)
               = min(1, 12.5) = 1.0
```

Every trade in this example fills completely. A quote volume below `20`
would yield a positive but tiny fraction; a zero volume yields `0.0` and the
trade is counted in `coverage.unfilled_trades` and excluded.

## Step 2 — the per-unit cost

The entry leg is taker (fee `0.001`, slippage `0.0005`). The target exit
leg is maker (fee `0.001`, no slippage); the stop and the expiry exit legs
are taker (fee `0.001`, slippage `0.0005`). Funding is charged once at close
on the entry notional:

```
funding_unit = funding_rate_per_period * (H / funding_period_hours) * entry
             = 0.0001 * (4 / 8) * 100 = 0.005
```

Trade `sig-a` (target, maker exit):

```
cost_unit = (0.001 + 0.0005) * 100 + (0.001 + 0.0) * 120 + 0.005
          = 0.15 + 0.12 + 0.005 = 0.275
```

Trade `sig-b` (stop, taker exit):

```
cost_unit = (0.001 + 0.0005) * 100 + (0.001 + 0.0005) * 90 + 0.005
          = 0.15 + 0.135 + 0.005 = 0.29
```

Trade `sig-c` (expired, taker exit):

```
cost_unit = (0.001 + 0.0005) * 100 + (0.001 + 0.0005) * 110 + 0.005
          = 0.15 + 0.165 + 0.005 = 0.32
```

## Step 3 — the net R multiple

```
gross_unit = (exit - entry)                   (buy)
R_net      = fill_fraction * (gross_unit - cost_unit) / |entry - stop|
```

| Trade | `gross_unit` | `cost_unit` | `R_net` |
|---|---|---|---|
| `sig-a` | 20 | 0.275 | `(20 - 0.275) / 10 = 1.9725` |
| `sig-b` | -10 | 0.29 | `(-10 - 0.29) / 10 = -1.029` |
| `sig-c` | 10 | 0.32 | `(10 - 0.32) / 10 = 0.968` |

The legacy profile gives `1.967`, `-1.0285` and `0.9685` for the same
trades: the maker target exit saves `0.0005 * 120 = 0.06` of R, the
explicit funding adds `0.0005` of R to the expired trade, and the maker
target exit cost is `0.275` instead of the legacy `0.33`.

## Step 4 — the equity curve and the statistics

```
r_i = R_net_i * risk_per_trade_pct / 100
E_i = E_(i-1) * (1 + r_i)
```

| Trade | `r_i` | equity after the trade |
|---|---|---|
| — | — | `E_0 = 10000.0` |
| `sig-a` | 0.019725 | `10197.25` |
| `sig-b` | -0.01029 | `10092.305798...` |
| `sig-c` | 0.00968 | `10190.0139579798` |

```
total_return  = 10190.0139579798 / 10000 - 1 = 0.01900139579798
win_rate      = 2 / 3 = 0.6666666666666666
profit_factor = (1.9725 + 0.968) / 1.029 = 2.8576287657920316
expectancy_R  = (1.9725 - 1.029 + 0.968) / 3 = 0.6371666666666668
```

The daily series is `[0.019725, -0.01029, 0.00968]`. With
`min_trades_for_ratios = 3`:

```
Sharpe  = 7.9674171420056314
Sortino = 20.490130880473146
```

With the committed default `min_trades_for_ratios = 30` the status is
`insufficient_sample` and both ratios are `null`.

## Step 5 — the maximum drawdown

The equity curve is `[10000.0, 10197.25, 10092.305798..., 10190.0139579798]`:

```
depth        = (10197.25 - 10092.305798...) / 10197.25 = 0.010289999999999962
peak_index   = 1   (exit of sig-a)
trough_index = 2   (exit of sig-b)
duration     = 1 trade
```

## Step 6 — the coverage block and the hashes

All three records carry a volume, so no record is a legacy full fill and
none is unfilled:

```json
{
  "legacy_resolutions_included": false,
  "legacy_full_fill_records": 0,
  "unfilled_trades": 0
}
```

```
data_hash   = 897c2213b6432ce82063e8e7482abceaa5d2ef7f29881ff1a941a88babbcb208
config_hash = cb33d4d919045e51b9ff5fcb38e983229b07985f92d099fc0dde72016f010704
```

`equity_source` is `"signal_model"`: this curve compounds fixed fractions of
the signal model, not the executed paper portfolio (decision G7).
