import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from analysis.portfolio_covariance import build_portfolio_risk_view
from common.exceptions import PortfolioRiskUnavailable
from config.logger import logger
from domain.portfolio_risk import (
    PortfolioRiskView,
    budget_factor,
    cluster_labels,
    correlation,
    cvar95,
    effective_bets,
    hrp_weights,
    leaf_order,
    portfolio_series,
    solve_scale,
)

MODES = ("off", "shadow", "enforce")


def _defaults() -> dict[str, Any]:
    from config.settings import ConfigManager

    config = ConfigManager.DEFAULT_CONFIG
    return {
        "portfolio_risk_mode": config["portfolio_risk_mode"],
        "portfolio_corr_lookback_days": config["portfolio_corr_lookback_days"],
        "portfolio_corr_min_overlap_days": config["portfolio_corr_min_overlap_days"],
        "portfolio_cluster_corr_threshold": config["portfolio_cluster_corr_threshold"],
        "max_cluster_exposure_pct": config["max_cluster_exposure_pct"],
        "max_daily_portfolio_vol_pct": config["max_daily_portfolio_vol_pct"],
        "max_portfolio_cvar95_pct": config["max_portfolio_cvar95_pct"],
        "min_effective_bets": config["min_effective_bets"],
        "correlation_penalty_weight": config["correlation_penalty_weight"],
        "risk_budget_bonus_weight": config["risk_budget_bonus_weight"],
        "min_portfolio_scale": config["min_portfolio_scale"],
    }


@dataclass(frozen=True)
class PortfolioRiskConfig:
    mode: str
    corr_lookback_days: int
    min_overlap_days: int
    cluster_corr_threshold: float
    max_cluster_exposure_pct: float
    max_daily_portfolio_vol_pct: float
    max_portfolio_cvar95_pct: float
    min_effective_bets: float
    correlation_penalty_weight: float
    risk_budget_bonus_weight: float
    min_portfolio_scale: float


def _bounded(value: Any, name: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} is not finite")
    if number < low or number > high:
        raise ValueError(f"{name} outside [{low}, {high}]")
    return number


def build_portfolio_risk_config(config_manager: Any) -> PortfolioRiskConfig:
    defaults = _defaults()
    mode = str(config_manager.get("portfolio_risk_mode", defaults["portfolio_risk_mode"]))
    mode = mode.strip().lower()
    if mode not in MODES:
        raise ValueError(f"portfolio_risk_mode must be one of {MODES}")
    lookback = int(
        _bounded(
            config_manager.get(
                "portfolio_corr_lookback_days", defaults["portfolio_corr_lookback_days"]
            ),
            "portfolio_corr_lookback_days",
            60,
            730,
        )
    )
    overlap = _bounded(
        config_manager.get(
            "portfolio_corr_min_overlap_days",
            defaults["portfolio_corr_min_overlap_days"],
        ),
        "portfolio_corr_min_overlap_days",
        30,
        float(lookback),
    )
    threshold = _bounded(
        config_manager.get(
            "portfolio_cluster_corr_threshold",
            defaults["portfolio_cluster_corr_threshold"],
        ),
        "portfolio_cluster_corr_threshold",
        0.3,
        0.95,
    )
    cluster_cap = _bounded(
        config_manager.get(
            "max_cluster_exposure_pct", defaults["max_cluster_exposure_pct"]
        ),
        "max_cluster_exposure_pct",
        1.0,
        100.0,
    )
    vol = _bounded(
        config_manager.get(
            "max_daily_portfolio_vol_pct", defaults["max_daily_portfolio_vol_pct"]
        ),
        "max_daily_portfolio_vol_pct",
        0.1,
        10.0,
    )
    cvar_cap = _bounded(
        config_manager.get(
            "max_portfolio_cvar95_pct", defaults["max_portfolio_cvar95_pct"]
        ),
        "max_portfolio_cvar95_pct",
        0.1,
        20.0,
    )
    min_bets = _bounded(
        config_manager.get("min_effective_bets", defaults["min_effective_bets"]),
        "min_effective_bets",
        1.0,
        10.0,
    )
    penalty = _bounded(
        config_manager.get(
            "correlation_penalty_weight", defaults["correlation_penalty_weight"]
        ),
        "correlation_penalty_weight",
        0.0,
        1.0,
    )
    bonus = _bounded(
        config_manager.get(
            "risk_budget_bonus_weight", defaults["risk_budget_bonus_weight"]
        ),
        "risk_budget_bonus_weight",
        0.0,
        0.5,
    )
    min_scale = _bounded(
        config_manager.get("min_portfolio_scale", defaults["min_portfolio_scale"]),
        "min_portfolio_scale",
        0.05,
        1.0,
    )
    return PortfolioRiskConfig(
        mode=mode,
        corr_lookback_days=lookback,
        min_overlap_days=int(overlap),
        cluster_corr_threshold=threshold,
        max_cluster_exposure_pct=cluster_cap,
        max_daily_portfolio_vol_pct=vol,
        max_portfolio_cvar95_pct=cvar_cap,
        min_effective_bets=min_bets,
        correlation_penalty_weight=penalty,
        risk_budget_bonus_weight=bonus,
        min_portfolio_scale=min_scale,
    )


@dataclass(frozen=True)
class PortfolioRiskDerived:
    corr: tuple[tuple[float, ...], ...]
    labels: tuple[int, ...]
    order: tuple[int, ...]
    hrp: tuple[float, ...]
    index: dict[str, int]


class PortfolioRiskService:
    def __init__(self, config_manager: Any, provider: Any):
        self.symbols = [str(symbol) for symbol in (config_manager.get("symbols") or [])]
        self.provider = provider
        self._key: str | None = None
        self._view: PortfolioRiskView | None = None
        self._derived: PortfolioRiskDerived | None = None
        self.config = build_portfolio_risk_config(config_manager)

    def set_config(self, config: PortfolioRiskConfig) -> None:
        self.config = config
        self._key = None
        self._view = None
        self._derived = None

    def execution_key(self) -> str:
        return "exec-" + datetime.now(UTC).date().isoformat()

    def cached(
        self, cycle_key: str | None
    ) -> tuple[PortfolioRiskView, PortfolioRiskDerived] | None:
        if cycle_key is None:
            return None
        if self._key != cycle_key or self._view is None or self._derived is None:
            return None
        return self._view, self._derived

    async def resolve(
        self, cycle_key: str | None
    ) -> tuple[PortfolioRiskView, PortfolioRiskDerived] | None:
        if cycle_key is None:
            return None
        cached = self.cached(cycle_key)
        if cached is not None:
            return cached
        view = await self._build(cycle_key)
        if view is None:
            return None
        self._view = view
        self._derived = self._derive(view)
        self._key = cycle_key
        return self._view, self._derived

    async def view(self, cycle_key: str | None) -> PortfolioRiskView | None:
        resolved = await self.resolve(cycle_key)
        return None if resolved is None else resolved[0]

    async def derived(self, cycle_key: str | None) -> PortfolioRiskDerived | None:
        resolved = await self.resolve(cycle_key)
        return None if resolved is None else resolved[1]

    async def _build(self, cycle_key: str) -> PortfolioRiskView | None:
        try:
            view = await build_portfolio_risk_view(
                self.provider,
                self.symbols,
                self.config.corr_lookback_days,
                self.config.min_overlap_days,
            )
        except PortfolioRiskUnavailable as exc:
            logger.warning(f"portfolio_view_unavailable: {exc}")
            self._invalidate(cycle_key)
            return None
        except Exception as exc:
            logger.warning(f"portfolio_view_unavailable: {exc}")
            self._invalidate(cycle_key)
            return None
        try:
            derived = self._derive(view)
        except ValueError as exc:
            logger.warning(f"portfolio_view_unavailable: {exc}")
            self._invalidate(cycle_key)
            return None
        self._view = view
        self._derived = derived
        self._key = cycle_key
        return view

    def _invalidate(self, cycle_key: str | None) -> None:
        self._key = cycle_key
        self._view = None
        self._derived = None

    def _derive(self, view: PortfolioRiskView) -> PortfolioRiskDerived:
        corr = correlation(view.covariance)
        order = leaf_order(corr)
        hrp = hrp_weights(view.covariance, order)
        labels = cluster_labels(corr, self.config.cluster_corr_threshold)
        index = {symbol: position for position, symbol in enumerate(view.symbols)}
        return PortfolioRiskDerived(corr=corr, labels=labels, order=order, hrp=hrp, index=index)

    def book_weights(
        self, portfolio: Any, view: PortfolioRiskView, equity: float
    ) -> dict[str, float]:
        prices = dict(zip(view.symbols, view.last_close))
        return portfolio.signed_weights(prices, equity)

    def budget_factors(
        self, book_weights: dict[str, float], derived: PortfolioRiskDerived
    ) -> dict[str, float]:
        total = sum(abs(value) for value in book_weights.values())
        factors: dict[str, float] = {}
        for symbol, position in derived.index.items():
            share = abs(book_weights.get(symbol, 0.0)) / total if total > 0 else 0.0
            target = derived.hrp[position]
            factors[symbol] = budget_factor(
                target, share, self.config.risk_budget_bonus_weight
            )
        return factors

    def _vectors(
        self,
        book_weights: dict[str, float],
        symbol: str,
        size: float,
        side_sign: float,
        entry_price: float,
        equity: float,
        view: PortfolioRiskView,
        derived: PortfolioRiskDerived,
    ) -> tuple[list[float], list[float]] | None:
        position = derived.index.get(symbol)
        if position is None:
            return None
        if equity <= 0.0 or size <= 0.0 or entry_price <= 0.0:
            return None
        weights = [0.0] * len(view.symbols)
        for held, weight in book_weights.items():
            index = derived.index.get(held)
            if index is not None:
                weights[index] = weight
        candidate = [0.0] * len(view.symbols)
        candidate[position] = side_sign * size * entry_price / equity
        return weights, candidate

    def check_entry_with_view(
        self,
        symbol: str,
        side_sign: float,
        size: float,
        entry_price: float,
        portfolio: Any,
        equity: float,
        view: PortfolioRiskView,
        derived: PortfolioRiskDerived,
    ) -> tuple[float, str]:
        book_weights = self.book_weights(portfolio, view, equity)
        return self._check_entry(
            symbol,
            side_sign,
            size,
            entry_price,
            book_weights,
            equity,
            view,
            derived,
        )

    def _check_entry(
        self,
        symbol: str,
        side_sign: float,
        size: float,
        entry_price: float,
        book_weights: dict[str, float],
        equity: float,
        view: PortfolioRiskView,
        derived: PortfolioRiskDerived,
    ) -> tuple[float, str]:
        position = derived.index.get(symbol)
        if position is None:
            return 0.0, "corr_unavailable"
        vectors = self._vectors(
            book_weights,
            symbol,
            size,
            side_sign,
            entry_price,
            equity,
            view,
            derived,
        )
        if vectors is None:
            return 0.0, "corr_unavailable"
        weights, candidate = vectors
        book_series = portfolio_series(weights, view.returns)
        cand_series = portfolio_series(candidate, view.returns)
        book_variance = 0.0
        for i in range(len(weights)):
            for j in range(len(weights)):
                book_variance += weights[i] * view.covariance[i][j] * weights[j]
        budget = self.config.max_daily_portfolio_vol_pct / 100.0
        cvar_cap = self.config.max_portfolio_cvar95_pct / 100.0
        if cvar95(book_series) > cvar_cap or book_variance > budget * budget:
            return 0.0, "halt"
        cluster = [
            index
            for index in range(len(view.symbols))
            if derived.labels[index] == derived.labels[position]
        ]
        scale, binding = solve_scale(
            weights,
            candidate,
            cluster,
            self.config.max_cluster_exposure_pct / 100.0,
            budget,
            cvar_cap,
            view.covariance,
            book_series,
            cand_series,
        )
        combined = list(weights)
        combined[position] += candidate[position]
        held = {name for name, weight in book_weights.items() if weight != 0.0}
        symbols_after = len(held | {symbol})
        if symbols_after >= 2:
            bets = effective_bets(combined, view.covariance)
            floor = min(self.config.min_effective_bets, float(symbols_after))
            if bets < floor:
                return 0.0, "effective_bets"
        if scale < self.config.min_portfolio_scale:
            return 0.0, binding
        return scale, "none"

    async def check_entry(
        self,
        symbol: str,
        side_sign: float,
        size: float,
        entry_price: float,
        portfolio: Any,
        equity: float,
        cycle_key: str | None,
    ) -> tuple[float, str]:
        resolved = await self.resolve(cycle_key)
        if resolved is None:
            return 0.0, "corr_unavailable"
        view, derived = resolved
        return self.check_entry_with_view(
            symbol, side_sign, size, entry_price, portfolio, equity, view, derived
        )
