# Proposal: add-asset-reference-store

## Why

Static per-asset reference data (provider identifiers, genesis dates,
supply caps, categories) is re-fetched on every analysis run for every
symbol/timeframe combination. With Redis unavailable there is no cache at
all, so identifiers such as the CoinGecko coin list are downloaded
repeatedly, and identifier guessing (`symbol.lower()`) risks wrong-asset
responses for tickers whose slug differs from the ticker.

## What

1. A tracked, expiry-free seed file mapping each base ticker in
   `symbols.txt` to its verified CoinGecko id and Messari slug.
2. A small async store (`AssetReferenceStore`) that serves identifiers from
   memory and persists slowly-changing profiles (genesis date, max supply,
   categories) in SQLite with a 7-day TTL.
3. Wiring through `MarketDataProvider` so `CoinGeckoFetcher` and
   `MessariFetcher` resolve identifiers from the seed instead of guessing.

## Non-goals

OHLCV history archiving, exchange filter storage, new fields on
`FundamentalAnalysis`/`OnChainAnalysis`, any scoring, gate, threshold,
model, artifact or backtest change.

## Identifier verification status

Verified against live provider data on 2026-10-14: CoinGecko ids
`chainlink`, `litecoin`, `polkadot` (live markets API) and `astar`
(CoinGecko coin page shows API ID `astar` for the Astar Network token).
Canonical ids `bitcoin`, `ethereum`, `solana`, `binancecoin`, `ripple`,
`sui` are high-confidence but still require the pre-commit check below.
Messari slugs are candidates only (docs confirm the slug convention, e.g.
`bitcoin`); `bnb` is the highest-risk candidate. Any value that cannot be
verified before the implementation commit is stored as `null`, and `null`
always selects the existing fallback path.

## Corrections to the originating directive found during verification

- `MessariFetcher` and `MarketIndicesFetcher` declare explicit constructor
  parameters (no `**kwargs`), so passing `asset_reference` through the
  shared `common_args` dict would raise `TypeError`. Both gain an explicit
  keyword; all other fetchers already forward `**kwargs` to `BaseFetcher`,
  which gains the keyword too. A compatibility test constructs every
  fetcher with the new keyword.
- `aiosqlite` is declared in `requirements.txt` but is neither pinned in
  `requirements.lock` nor installed in the current environment, and no
  production file imports it today. Implementation must verify availability
  (or pin it via the `lock-refresh` workflow) before relying on it; sync
  `sqlite3` must not be called from async code.

## Out of scope for later phases (recorded, not proposed)

OHLCV history archive and exchange filter storage need their own proposals:
candles touch the model/backtest data contract, and exchange filters have
no consumer yet.
