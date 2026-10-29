# Paper performance report — worked example

Every number below is produced by the implementation and is pinned by
`tests/unit/application/test_performance_worked_example.py`. The example
uses three trades: one target, one stop and one expired.

## Inputs

| Item | Value |
|---|---|
| Mode | `paper` |
| `as_of` | `2026-10-03T23:59:59+00:00` |
| `initial_cash` | `10000.0` |
| `risk_per_trade_pct` | `1.0` |
| `paper_fee_rate` | `0.001` |
| `paper_slippage_rate` | `0.0005` |
| `performance_rf_annual` | `0` |
| `performance_periods_per_year` | `365` |
| `performance_min_trades_for_ratios` | `30` (and `3` for the ratio variant below) |

| Signal | Symbol | Side | Entry | Stop | Exit | Reason | Exit time (UTC) |
|---|---|---|---|---|---|---|---|
| `sig-a` | BTC/USDT | buy | 100 | 90 | 120 | target | 2026-10-01T14:00:00 |
| `sig-b` | BTC/USDT | buy | 100 | 90 | 90 | stop | 2026-10-02T14:00:00 |
| `sig-c` | ETH/USDT | buy | 100 | 90 | 110 | expired | 2026-10-03T14:00:00 |

The risk distance of every trade is `|100 - 90| = 10`.

## Step 1 — the net R multiple

The cost is charged on both legs, so `entry` and `exit` both appear in the
formula:

```
cost_R = (fee_rate + slippage_rate) * (entry + exit) / |entry - stop|
R_net  = R_gross - cost_R
R_gross(buy) = (exit - entry) / (entry - stop)
```

Trade `sig-a`:

```
R_gross = (120 - 100) / 10            = 2.0
cost_R  = (0.001 + 0.0005) * (100 + 120) / 10
        = 0.0015 * 220 / 10           = 0.033
R_net   = 2.0 - 0.033                 = 1.967
```

Trade `sig-b`:

```
R_gross = (90 - 100) / 10             = -1.0
cost_R  = 0.0015 * (100 + 90) / 10    = 0.0285
R_net   = -1.0 - 0.0285               = -1.0285
```

Trade `sig-c`:

```
R_gross = (110 - 100) / 10            = 1.0
cost_R  = 0.0015 * (100 + 110) / 10   = 0.0315
R_net   = 1.0 - 0.0315                = 0.9685
```

## Step 2 — the fixed fraction and the equity curve

```
r_i = R_net_i * risk_per_trade_pct / 100
E_i = E_(i-1) * (1 + r_i)
```

| Trade | `R_net` | `r_i` | equity after the trade |
|---|---|---|---|
| — | — | — | `E_0 = 10000.0` |
| `sig-a` | 1.967 | 0.01967 | `E_1 = 10000.0 * 1.01967 = 10196.7` |
| `sig-b` | -1.0285 | -0.010285 | `E_2 = 10196.7 * 0.989715 = 10091.8269405` |
| `sig-c` | 0.9685 | 0.009685 | `E_3 = 10091.8269405 * 1.009685 = 10189.566284418743` |

```
total_return = 10189.566284418743 / 10000.0 - 1 = 0.01895662844187429
```

## Step 3 — the daily series

The report window runs from the UTC day of the first exit (`2026-10-01`) to
the UTC day of `as_of` (`2026-10-03`). Each trade closed on its own day, so
the daily series has three entries and no idle day:

```
R_d = [0.01967, -0.010285, 0.009685]
```

## Step 4 — the ratios

With `rf_d = performance_rf_annual / performance_periods_per_year = 0`:

```
mean(R_d)   = (0.01967 - 0.010285 + 0.009685) / 3 = 0.006356666666666667
spread      = stdev(R_d, ddof=1)
             = sqrt((0.0133133333^2 + (-0.0166416667)^2 + 0.0033283333^2) / 2)
             = sqrt(4.652664277777778e-04 / 2)
             = sqrt(2.326332138888889e-04)
             = 0.015252254065...
Sharpe      = 0.006356666666666667 / 0.015252254065... * sqrt(365)
            = 7.962315986966122
```

The Sortino downside deviation divides by the number of **all** days in the
window, not only the losing ones:

```
DD     = sqrt((min(0.01967, 0)^2 + min(-0.010285, 0)^2 + min(0.009685, 0)^2) / 3)
       = sqrt(1.05781225e-04 / 3)
       = sqrt(3.526040833333333e-05)
       = 0.00593805101...
Sortino = 0.006356666666666667 / 0.00593805101... * sqrt(365)
        = 20.451831307422246
```

With the committed default `performance_min_trades_for_ratios = 30` the
three trades are below the minimum, so the status is `insufficient_sample`
and **both ratios are `null`**. The values above are the `min_trades_for_ratios = 3`
variant of the same data.

## Step 5 — the maximum drawdown

The drawdown is computed on the trade-level equity curve
`[10000.0, 10196.7, 10091.8269405, 10189.566284418743]`:

| Index | Equity | Running peak | Depth |
|---|---|---|---|
| 0 | 10000.0 | 10000.0 | 0.0 |
| 1 | 10196.7 | 10196.7 (new peak) | 0.0 |
| 2 | 10091.8269405 | 10196.7 | `(10196.7 - 10091.8269405) / 10196.7 = 0.010284999999999973` |
| 3 | 10189.566284418743 | 10196.7 | 0.000698... |

The deepest trough is index 2, so:

```
depth          = 0.010284999999999973   (1.0285 %)
peak_index     = 1
trough_index   = 2
duration       = 1 trade
peak_time      = 2026-10-01T14:00:00.000000+00:00   (exit of sig-a)
trough_time    = 2026-10-02T14:00:00.000000+00:00   (exit of sig-b)
```

## Step 6 — the trade statistics

```
win_rate      = 2 / 3 = 0.6666666666666666
profit_factor = (1.967 + 0.9685) / 1.0285 = 2.9355 / 1.0285 = 2.8541565386485175
expectancy_R  = (1.967 - 1.0285 + 0.9685) / 3 = 1.907 / 3 = 0.6356666666666667
```

## Step 7 — the hashes

The `data_hash` covers the canonical JSON of the three included records and
does not depend on the configuration:

```
data_hash = 2a803a8d09eae9858d88e9fa9b82b2b5043c9cf79b3854c7939151308ec17dd6
```

The `config_hash` covers the effective parameters and therefore changes with
the minimum sample size:

```
config_hash (min_trades_for_ratios = 30) = a6ff27074d338465c91eee54b7501ef68c1c36e378b9a45f3a5e57b77c4c0c17
config_hash (min_trades_for_ratios = 3)  = 3b52ca2c086a3f140a15c8da7965b3ae4207b0064e96ad104da63c7f2a5428e7
```

## The resulting report

```json
{
  "as_of": "2026-10-03T23:59:59.000000+00:00",
  "config_hash": "a6ff27074d338465c91eee54b7501ef68c1c36e378b9a45f3a5e57b77c4c0c17",
  "data_hash": "2a803a8d09eae9858d88e9fa9b82b2b5043c9cf79b3854c7939151308ec17dd6",
  "exit_counts": {"expired": 1, "no_data": 0, "stop": 1, "target": 1},
  "expectancy_r": 0.6356666666666667,
  "final_equity": 10189.566284418743,
  "initial_equity": 10000.0,
  "max_drawdown": {
    "depth": 0.010284999999999973,
    "duration_trades": 1,
    "peak_index": 1,
    "peak_time": "2026-10-01T14:00:00.000000+00:00",
    "trough_index": 2,
    "trough_time": "2026-10-02T14:00:00.000000+00:00"
  },
  "mode": "paper",
  "parameters": {
    "fee_rate": 0.001,
    "initial_cash": 10000.0,
    "min_trades_for_ratios": 30,
    "periods_per_year": 365.0,
    "rf_annual": 0.0,
    "risk_per_trade_pct": 1.0,
    "slippage_rate": 0.0005
  },
  "period_end": "2026-10-03",
  "period_start": "2026-10-01",
  "profit_factor": 2.8541565386485175,
  "report_version": "performance-report-v1",
  "sharpe": null,
  "sortino": null,
  "status": "insufficient_sample",
  "total_resolved": 3,
  "total_return": 0.01895662844187429,
  "win_rate": 0.6666666666666666
}
```

## Report schema v2 note

Since `performance-report-v2` (P3) every record above carries no entry
quote volume, so each one is counted as a legacy full fill and the
`coverage` block reads
`{"legacy_resolutions_included": false, "legacy_full_fill_records": 3, "unfilled_trades": 0}`.
The cost profile is the legacy report profile (`legacy-report-v1`), so the
arithmetic of steps 1 to 6 above is unchanged. The `data_hash` now covers
the extra `entry_quote_volume` field and is
`94e5374204b61d1e43f8ded6e6cf29d1526d52b1c91fe303c02fb25caee82e9c`; the
`config_hash` now covers the effective cost profile. The cost-model-v2
variant with volume and partial fills is `docs/performance-worked-example-v2.md`.
