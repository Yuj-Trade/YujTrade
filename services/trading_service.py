import asyncio
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from application import performance_report
from application.gate_config import build_gate_config
from application.outcome_policy import NotificationPolicy
from application.performance_report import PerformanceConfig, PerformanceReport
from common import metrics
from common.constants import LONG_TERM_CONFIG, SIGNAL_EXPIRY_BY_TIMEFRAME, candle_duration
from common.core import TradingSignal
from common.exceptions import InvalidSymbolError
from common.rate_limit import configure_rate_limits
from config.logger import logger
from config.settings import ConfigManager
from data.data_provider import MarketDataProvider
from domain.gates import normalize_confidence, quality_gate_reason
from domain.outcome import (
    Resolution,
    event_from_resolution,
    observe_signal_barrier,
    resolve_signal_outcome,
)
from domain.performance import RESOLVER_VERSION, ResolutionRecord
from domain.types import SignalDraft
from modeling.learner import ModelLearner
from modeling.model_manager import ModelDataProvider, ModelManager
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from strategy.prediction_trace import PredictionTraceRecorder
from strategy.signal_generator import SignalGenerator
from strategy.signal_ranking import SignalRanking
from strategy.signal_tracker import OpenSignal, SignalTracker, make_signal_id
from trading.execution import ExchangeAdapter, ExecutionEngine
from trading.ledger import PaperLedger
from trading.paper_trading import PaperTradingEngine
from trading.portfolio import PortfolioManager
from trading.risk_manager import RiskManager, build_risk_config
from utils.resource_manager import ResourceManager

_LEDGER_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class WatchReport:
    detected: int
    groups: int
    failed_groups: int
    settled: int


async def build_performance_report_from_ledger(
    ledger: PaperLedger, config_manager: ConfigManager, as_of: datetime
) -> PerformanceReport:
    records = await ledger.load_resolutions(_LEDGER_EPOCH, as_of)
    return performance_report.build_performance_report(
        records, build_performance_config(config_manager), as_of
    )


def build_performance_config(config_manager: ConfigManager) -> PerformanceConfig:
    defaults = ConfigManager.DEFAULT_CONFIG
    return PerformanceConfig(
        initial_cash=float(config_manager.get("initial_cash", defaults["initial_cash"])),
        risk_per_trade_pct=float(
            config_manager.get("risk_per_trade_pct", defaults["risk_per_trade_pct"])
        ),
        fee_rate=float(config_manager.get("paper_fee_rate", defaults["paper_fee_rate"])),
        slippage_rate=float(
            config_manager.get("paper_slippage_rate", defaults["paper_slippage_rate"])
        ),
        rf_annual=float(
            config_manager.get("performance_rf_annual", defaults["performance_rf_annual"])
        ),
        periods_per_year=float(
            config_manager.get(
                "performance_periods_per_year", defaults["performance_periods_per_year"]
            )
        ),
        min_trades_for_ratios=int(
            config_manager.get(
                "performance_min_trades_for_ratios", defaults["performance_min_trades_for_ratios"]
            )
        ),
    )


def _utc_moment(value: Any) -> datetime | None:
    if isinstance(value, pd.Timestamp):
        moment = value.to_pydatetime()
    elif isinstance(value, datetime):
        moment = value
    else:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _frame_candles(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    candles: list[dict[str, Any]] = []
    has_timestamp_column = "timestamp" in frame.columns
    for index, row in frame.iterrows():
        moment = _utc_moment(index)
        if moment is None and has_timestamp_column:
            moment = _utc_moment(row["timestamp"])
        if moment is None:
            continue
        try:
            high = float(row["high"])
            low = float(row["low"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            close = float(row["close"])
        except (KeyError, TypeError, ValueError):
            close = None
        candles.append({"timestamp": moment, "high": high, "low": low, "close": close})
    return candles


def _build_exchange_service(config_manager: ConfigManager):
    try:
        from trading.exchanges.execution_service import ExchangeExecutionService
        from trading.exchanges.factory import build_gateway
        from trading.exchanges.gate_inputs import load_exchange_settings
        from trading.exchanges.permissions import verify_key_permissions
        from trading.live_ledger import LiveLedger
    except ImportError as exc:
        logger.error(f"Exchange service unavailable: {exc}")
        return None
    settings = load_exchange_settings(config_manager)
    if not settings.enabled:
        return None
    ledger = LiveLedger(settings.ledger_path)

    async def permission_check(spec):
        from trading.exchanges.credentials import load_exchange_credentials

        credentials = load_exchange_credentials(spec, settings.sandbox)
        gateway = build_gateway(spec, settings.sandbox, credentials)
        try:
            ok, reason = await verify_key_permissions(gateway, spec)
        finally:
            await gateway.close()
        if not ok:
            logger.warning(f"Key permissions not verified for {spec.exchange_id}: {reason}")
        return ok

    return ExchangeExecutionService(
        settings=settings,
        ledger=ledger,
        gateway_factory=build_gateway,
        execution_dry_run=bool(config_manager.get("execution_dry_run", True)),
        permission_check=permission_check,
    )


async def create_trading_stack(
    config_manager: ConfigManager | None = None,
    resource_manager: ResourceManager | None = None,
) -> tuple[ConfigManager, ResourceManager, MarketDataProvider, "TradingService"]:
    config_manager = config_manager or ConfigManager()
    resource_manager = resource_manager or ResourceManager()

    configure_rate_limits(config_manager.get_rate_limits())

    market_data_provider = MarketDataProvider(
        resource_manager=resource_manager, config_manager=config_manager
    )
    await market_data_provider.initialize()

    if config_manager.get("ohlcv_prewarm_enabled", False):
        from common.constants import SYMBOLS, TIME_FRAMES

        await market_data_provider.prewarm_ohlcv_store(
            SYMBOLS,
            TIME_FRAMES,
            limit=int(config_manager.get("ohlcv_prewarm_limit", 1000)),
        )

    trading_service = TradingService(
        market_data_provider=market_data_provider,
        config_manager=config_manager,
        resource_manager=resource_manager,
        exchange_service=_build_exchange_service(config_manager),
    )
    await trading_service.initialize()

    return config_manager, resource_manager, market_data_provider, trading_service


class TradingService(ModelDataProvider):
    performance_ledger: PaperLedger | None = None
    _performance_ledger_enabled: bool = False

    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        config_manager: ConfigManager,
        resource_manager: ResourceManager,
        exchange_service: Any | None = None,
    ):
        self.market_data_provider = market_data_provider
        self.config_manager = config_manager
        self.resource_manager = resource_manager
        self.exchange_service = exchange_service
        self.invalid_symbols: set[str] = set()
        self._initialized = False

        self.last_errors: int = 0

        self._redis_client = getattr(resource_manager, "_redis_client", None)

        self.model_manager = ModelManager(
            data_provider=self,
            redis_client=self._redis_client,
            model_path=self.config_manager.get("model_path", "models"),
            auto_train_on_predict=self.config_manager.get("model_auto_train_on_predict", False),
        )

        self.learner = ModelLearner(
            model_manager=self.model_manager,
            data_provider=self,
            config_manager=self.config_manager,
        )

        self.trace_recorder = PredictionTraceRecorder(
            directory=str(self.config_manager.get("prediction_trace_dir", "runs/feature_vectors")),
            enabled=bool(self.config_manager.get("prediction_trace_enabled", False)),
        )

        self.signal_generator = SignalGenerator(
            data_provider=self.market_data_provider,
            model_manager=self.model_manager,
            config_manager=self.config_manager,
            trace_recorder=self.trace_recorder,
        )

        self.multi_tf_analyzer = MultiTimeframeAnalyzer(
            market_data_provider=market_data_provider,
            config_manager=self.config_manager,
        )
        risk_cfg = build_risk_config(self.config_manager)
        self.risk_manager = RiskManager(risk_cfg)
        self.portfolio = PortfolioManager(float(self.config_manager.get("initial_cash", 10000.0)))
        self.paper_engine = PaperTradingEngine(
            portfolio=self.portfolio,
            risk_manager=self.risk_manager,
            fee_rate=float(
                self.config_manager.get(
                    "paper_fee_rate", ConfigManager.DEFAULT_CONFIG["paper_fee_rate"]
                )
            ),
            slippage_rate=float(
                self.config_manager.get(
                    "paper_slippage_rate", ConfigManager.DEFAULT_CONFIG["paper_slippage_rate"]
                )
            ),
        )
        self.execution_engine = ExecutionEngine(
            adapter=ExchangeAdapter(
                dry_run=bool(self.config_manager.get("execution_dry_run", True))
            )
        )
        self.signal_tracker = SignalTracker(
            ttl_days=int(self.config_manager.get("signal_history_ttl_days", 30)),
            max_entries=int(self.config_manager.get("signal_history_max_entries", 5000)),
        )
        self.performance_ledger = PaperLedger()
        self._performance_ledger_enabled = bool(
            self.config_manager.get("performance_ledger_enabled", False)
        )
        self._cycle_log = logger.bind(run_id=uuid.uuid4().hex[:12])

    def _log(self):
        return self._cycle_log

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            redis_client = await self.resource_manager.get_redis_client()
        except Exception as e:
            logger.opt(exception=True).debug(f"Redis unavailable, continuing without cache: {e}")
            redis_client = None
        self._redis_client = redis_client
        self.model_manager.redis_client = redis_client
        self.multi_tf_analyzer.redis = redis_client
        self._initialized = True

    async def get_data_for_model(
        self, symbol: str, timeframe: str, for_prediction: bool = False
    ) -> pd.DataFrame | None:
        limit_map = self.config_manager.get(
            "model_data_limits",
            {"1h": 2000, "4h": 1500, "1d": 1000, "1w": 500, "1M": 300},
        )
        limit = limit_map.get(timeframe, 2000)

        if for_prediction:
            limit = min(limit, self.config_manager.get("model_prediction_limit", 300))

        try:
            data = await self.market_data_provider.fetch_ohlcv_data(symbol, timeframe, limit=limit)
            if data is None or data.empty or len(data) < 200:
                logger.warning(f"Insufficient data for model operations for {symbol}-{timeframe}.")
                return None
            return data
        except Exception as e:
            logger.error(f"Failed to fetch data for model for {symbol}-{timeframe}: {e}")
            return None

    async def analyze_symbol(self, symbol: str, timeframe: str) -> TradingSignal | None:
        if symbol in self.invalid_symbols:
            self._log().debug(f"Skipping analysis for invalid symbol: {symbol}")
            return None

        self._log().info(f"Analyzing {symbol} on {timeframe} timeframe...")
        try:
            min_data_points = LONG_TERM_CONFIG.get("min_data_points", {})
            limit = min_data_points.get(timeframe, 600)
            ohlcv_data = await self.market_data_provider.fetch_ohlcv_data(
                symbol, timeframe, limit=limit
            )

            if ohlcv_data is None or ohlcv_data.empty:
                self._log().warning(f"No OHLCV data for {symbol}-{timeframe}")
                return None

            signal = await self.signal_generator.generate_signal(symbol, timeframe, ohlcv_data)

            if signal:
                metrics.record_candidate(signal.symbol, signal.timeframe)
                signal_id = make_signal_id(
                    signal.symbol,
                    signal.timeframe,
                    signal.timestamp,
                    signal.signal_type.value,
                )
                signal_log = self._log().bind(signal_id=signal_id)
                (
                    multi_tf_score,
                    _,
                    direction_conflict,
                ) = await self.multi_tf_analyzer.get_confirmation_score(
                    symbol, timeframe, signal.signal_type, ohlcv_data
                )
                if multi_tf_score < 0.3 or direction_conflict:
                    metrics.record_gate_rejection("multi_timeframe")
                    signal_log.info(
                        f"Signal for {symbol}-{timeframe} rejected due to multi-timeframe conflict."
                    )
                    return None

                if not self._passes_quality_gates(signal):
                    metrics.record_gate_rejection("quality_gates")
                    signal_log.info(f"Signal for {symbol}-{timeframe} rejected by quality gates.")
                    return None

                signal_log.info(
                    f"Generated signal for {symbol} on {timeframe}: "
                    f"{signal.signal_type.value} "
                    f"with confidence {signal.confidence_score:.2f}"
                )

                try:
                    await self.signal_tracker.record_if_absent(
                        signal_id,
                        {
                            "symbol": signal.symbol,
                            "timeframe": signal.timeframe,
                            "signal_type": signal.signal_type.value,
                            "confidence": signal.confidence_score,
                            "entry": signal.entry_price,
                            "stop": signal.stop_loss,
                            "target": signal.exit_price,
                            "created_at": datetime.now(UTC).isoformat(),
                            "candle_time": signal.timestamp.isoformat(),
                            "threshold_used": signal.threshold_used,
                            "threshold_regime": signal.threshold_regime,
                        },
                    )
                except Exception as e:
                    signal_log.debug(f"Signal tracking skipped: {e}")
                return signal

            return None
        except InvalidSymbolError:
            self._log().warning(f"Symbol {symbol} is invalid. Adding to ignore list.")
            self.invalid_symbols.add(symbol)
            return None
        except Exception as e:
            self._log().bind(symbol=symbol, timeframe=timeframe).opt(exception=e).error(
                f"Signal analysis failed for {symbol} on {timeframe}: {e}"
            )
            raise

    def _partition_results(self, results) -> list[TradingSignal]:
        signals = [res for res in results if isinstance(res, TradingSignal)]
        errors = [res for res in results if isinstance(res, Exception)]
        self.last_errors = len(errors)
        for err in errors:
            self._log().opt(exception=err).error(f"Signal generation failed: {err}")
        return signals

    def _passes_quality_gates(self, signal: TradingSignal) -> bool:
        gate_config = build_gate_config(LONG_TERM_CONFIG.get, signal.timeframe)
        strength = signal.market_context.get("trend_strength")
        strength_name = getattr(strength, "value", strength)
        strength_name = str(strength_name).upper() if strength_name else "WEAK"

        min_surge = LONG_TERM_CONFIG.get("min_volume_surge")
        ratio = (signal.volume_analysis or {}).get("volume_ratio")
        surge: float | None = None
        if min_surge is not None and ratio is not None:
            try:
                surge = float(ratio)
            except (TypeError, ValueError):
                surge = None

        draft = SignalDraft(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            side=signal.signal_type.value,
            timestamp=signal.timestamp,
            entry=signal.entry_price,
            stop=signal.stop_loss,
            target=signal.exit_price,
            confidence=signal.confidence_score,
        )
        reason = quality_gate_reason(draft, gate_config, strength_name, surge)
        if reason is not None:
            logger.debug(f"Gate {reason.value}: {signal.symbol}-{signal.timeframe} rejected.")
            return False

        min_ml_conf = LONG_TERM_CONFIG.get("min_ml_confidence", 0.0)
        ml_conf = getattr(signal, "ml_confidence", None)
        if ml_conf is not None and min_ml_conf:
            try:
                conf = float(ml_conf)
                if conf > 1.0:
                    conf /= 100.0
                if 0.0 < conf < float(min_ml_conf):
                    logger.debug(
                        f"Gate ml confidence: {conf:.3f} < {min_ml_conf} "
                        f"for {signal.symbol}-{signal.timeframe}"
                    )
                    return False
            except (TypeError, ValueError):
                pass

        return True

    async def run_analysis_for_all_symbols(self) -> list[TradingSignal]:
        self._cycle_log = logger.bind(run_id=uuid.uuid4().hex[:12])
        await self.signal_generator.begin_run_cycle()
        try:
            signals = await self._run_analysis_cycle_all()
        finally:
            await self.signal_generator.end_run_cycle()
        self._schedule_learning(self._analysis_timeframes())
        return signals

    def _analysis_timeframes(self) -> list[str]:
        focus_timeframes = LONG_TERM_CONFIG.get("focus_timeframes", ["1d", "1w", "1M"])
        all_timeframes = self.config_manager.get("timeframes", [])
        return [tf for tf in all_timeframes if tf in focus_timeframes] or all_timeframes

    def _schedule_learning(self, timeframes: list[str]) -> None:
        if self.learner is None:
            return
        for symbol in self.config_manager.get("symbols", []):
            for timeframe in timeframes:
                self.learner.request(symbol, timeframe)

    async def _run_analysis_cycle_all(self) -> list[TradingSignal]:
        try:
            await self.reconcile_pending_signals()
        except Exception as e:
            logger.debug(f"Pending-signal reconciliation skipped: {e}")

        symbols = self.config_manager.get("symbols", [])
        timeframes_to_use = self._analysis_timeframes()

        tasks = [self.analyze_symbol(s, tf) for s in symbols for tf in timeframes_to_use]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals = self._partition_results(results)

        if not signals:
            if self.last_errors:
                logger.warning(
                    f"No signals: {self.last_errors} analysis task(s) failed "
                    "in this cycle (distinct from 'no signal')."
                )
            else:
                logger.info("No signals generated in this analysis cycle")
            return []

        ranked_signals = SignalRanking.rank_signals(signals)

        per_tf_cap = self.config_manager.get("max_signals_per_timeframe", 1)
        try:
            per_tf_cap = max(1, int(per_tf_cap))
        except (TypeError, ValueError):
            per_tf_cap = 1
        seen_per_tf: dict = {}
        capped_signals = []
        for sig in ranked_signals:
            count = seen_per_tf.get(sig.timeframe, 0)
            if count < per_tf_cap:
                capped_signals.append(sig)
                seen_per_tf[sig.timeframe] = count + 1

        max_signals = LONG_TERM_CONFIG.get("max_signals_per_run", 3)
        final_signals = capped_signals[:max_signals]

        if final_signals:
            self._log().info(
                f"Selected {len(final_signals)} top quality long-term signals "
                f"from {len(signals)} candidates."
            )
            for i, sig in enumerate(final_signals, 1):
                metrics.record_signal(sig.symbol, sig.timeframe, sig.signal_type.value)
                self._log().info(
                    f"  #{i}: {sig.symbol} {sig.timeframe} {sig.signal_type.value.upper()} "
                    f"(Confidence: {sig.confidence_score:.1f}%, R/R: {sig.risk_reward_ratio:.2f}, "
                    f"Rank Score: {SignalRanking.calculate_signal_score(sig):.2f})"
                )
        else:
            self._log().info("No signals met the final quality criteria.")

        return final_signals

    async def run_quick_analysis(self, timeframes: list[str] | None = None) -> list[TradingSignal]:
        self._cycle_log = logger.bind(run_id=uuid.uuid4().hex[:12])
        await self.signal_generator.begin_run_cycle()
        try:
            signals = await self._run_quick_analysis_cycle(timeframes)
        finally:
            await self.signal_generator.end_run_cycle()
        self._schedule_learning(timeframes or ["1h"])
        return signals

    async def _run_quick_analysis_cycle(self, timeframes: list[str] | None) -> list[TradingSignal]:
        try:
            await self.reconcile_pending_signals()
        except Exception as e:
            logger.debug(f"Pending-signal reconciliation skipped: {e}")

        symbols = self.config_manager.get("symbols", [])
        timeframes_to_run = timeframes or ["1h"]

        tasks = [self.analyze_symbol(symbol, tf) for symbol in symbols for tf in timeframes_to_run]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return self._partition_results(results)

    async def reconcile_pending_signals(self) -> int:
        expired = await self.signal_tracker.get_pending_expired()
        if not expired:
            return 0

        resolved_count = 0
        for item in expired:
            try:
                if await self._settle_expired(item):
                    resolved_count += 1
            except ValueError as e:
                logger.error(f"Signal reconciliation failed: {e}")
            except Exception as e:
                logger.debug(f"Signal reconciliation skipped: {e}")

        if resolved_count:
            logger.info(f"Reconciled {resolved_count} expired pending signal(s).")
        return resolved_count

    async def _settle_expired(self, item: dict[str, Any]) -> bool:
        signal_id = item["signal_id"]
        signal_log = self._log().bind(signal_id=signal_id)
        details = item["details"]
        symbol = details.get("symbol")
        timeframe = details.get("timeframe")
        entry = details.get("entry")
        if not symbol or not timeframe or entry is None:
            signal_log.debug("Reconciliation skipped (missing fields).")
            return False
        created_at = SignalTracker._extract_created_at(signal_id, details)
        expiry_hours = SIGNAL_EXPIRY_BY_TIMEFRAME.get(timeframe)
        resolution = await self._resolve_signal_outcome(
            symbol, timeframe, details, created_at, expiry_hours
        )
        if resolution is None:
            signal_log.debug("Reconciliation skipped (incomplete levels).")
            return False
        if self._performance_ledger_enabled:
            stored = await self._store_resolution(
                signal_id, symbol, timeframe, details, created_at, resolution
            )
            if not stored:
                return False
        event = event_from_resolution(signal_id, resolution)
        if event is not None:
            await self.signal_tracker.set_outcome_event(signal_id, event)
        await self._sync_tracker(signal_id, symbol, timeframe, details, resolution)
        return True

    async def watch_outcomes(self, policy: NotificationPolicy, now: datetime) -> WatchReport:
        open_signals = await self.signal_tracker.open_signals(now, policy.since)
        groups: dict[tuple[str, str], list[OpenSignal]] = {}
        for signal in open_signals:
            if signal.timeframe in policy.timeframes:
                groups.setdefault((signal.symbol, signal.timeframe), []).append(signal)
        semaphore = asyncio.Semaphore(policy.concurrency)
        results = await asyncio.gather(
            *(
                self._watch_group(symbol, timeframe, items, now, semaphore)
                for (symbol, timeframe), items in groups.items()
            ),
            return_exceptions=True,
        )
        detected = sum(result for result in results if isinstance(result, int))
        failed = sum(1 for result in results if isinstance(result, BaseException))
        settled = await self.reconcile_pending_signals()
        return WatchReport(detected, len(groups), failed, settled)

    async def _watch_group(
        self,
        symbol: str,
        timeframe: str,
        items: list[OpenSignal],
        now: datetime,
        semaphore: asyncio.Semaphore,
    ) -> int:
        async with semaphore:
            duration = candle_duration(timeframe)
            oldest = min(item.created_at for item in items)
            count = int(math.ceil((now - oldest).total_seconds() / duration.total_seconds())) + 2
            try:
                frame = await self.market_data_provider.fetch_ohlcv_data(
                    symbol, timeframe, limit=count, bypass_cache=True
                )
            except Exception as e:
                logger.error(f"Outcome watch fetch failed for {symbol}-{timeframe}: {e}")
                raise
            candles = _frame_candles(frame)
            if not candles:
                logger.debug(f"Outcome watch found no candles for {symbol}-{timeframe}.")
                return 0
            detected = 0
            for signal in items:
                hit = observe_signal_barrier(
                    candles,
                    signal.side,
                    signal.stop,
                    signal.target,
                    signal.created_at,
                    now,
                    duration,
                )
                if hit is None:
                    continue
                event = event_from_resolution(signal.signal_id, hit)
                if event is not None and await self.signal_tracker.set_outcome_event(
                    signal.signal_id, event
                ):
                    metrics.record_outcome_event(event.kind)
                    detected += 1
            return detected

    async def _resolve_signal_outcome(
        self,
        symbol: str,
        timeframe: str,
        details: dict[str, Any],
        created_at: datetime | None,
        expiry_hours: float | None,
    ) -> Resolution | None:
        if created_at is None or not expiry_hours:
            return None
        try:
            entry = float(details.get("entry"))
            stop = float(details.get("stop"))
            target = float(details.get("target"))
        except (TypeError, ValueError):
            return None
        signal_type = str(details.get("signal_type", "")).lower()
        if signal_type not in ("buy", "sell"):
            return None

        duration = candle_duration(timeframe)
        candle_count = int(math.ceil(expiry_hours * 3600 / duration.total_seconds())) + 2
        try:
            frame = await self.market_data_provider.fetch_ohlcv_data(
                symbol, timeframe, limit=candle_count, bypass_cache=True
            )
        except Exception as e:
            logger.debug(f"Resolution candles fetch failed: {e}")
            frame = None
        candles = _frame_candles(frame)
        if not candles:
            return None
        return resolve_signal_outcome(
            candles,
            signal_type,
            entry,
            stop,
            target,
            created_at=created_at,
            expiry_hours=expiry_hours,
            candle_duration=duration,
        )

    async def _store_resolution(
        self,
        signal_id: str,
        symbol: str,
        timeframe: str,
        details: dict[str, Any],
        created_at: datetime,
        resolution: Resolution,
    ) -> bool:
        ledger = self.performance_ledger
        if ledger is None:
            logger.error(f"Performance ledger is unavailable for {signal_id}")
            return False
        if await ledger.has_resolution(signal_id):
            return True
        record = ResolutionRecord(
            signal_id=signal_id,
            symbol=symbol,
            timeframe=timeframe,
            side=str(details.get("signal_type", "")).lower(),
            entry=float(details.get("entry")),
            stop=float(details.get("stop")),
            target=float(details.get("target")),
            created_at=created_at,
            exit_at=resolution.exit_at,
            exit_price=resolution.exit_price,
            exit_reason=resolution.exit_reason,
            candles_used=resolution.candles_used,
            resolver_version=RESOLVER_VERSION,
        )
        try:
            return await ledger.record_resolution(record)
        except Exception as e:
            logger.error(f"Performance ledger write failed for {signal_id}: {e}")
            return False

    async def _sync_tracker(
        self,
        signal_id: str,
        symbol: str,
        timeframe: str,
        details: dict[str, Any],
        resolution: Resolution,
    ) -> None:
        resolved_at = datetime.now(UTC).isoformat()
        if resolution.exit_reason == "no_data":
            await self.signal_tracker.update_resolution_details(
                signal_id,
                {"resolution_status": "no_data", "resolved_at": resolved_at},
            )
            return
        success = self._tracker_outcome(details, resolution)
        await self.signal_tracker.resolve(
            signal_id,
            success,
            {
                "resolved_price": resolution.exit_price,
                "resolution_source": "live_reconciliation",
                "resolved_at": resolved_at,
                "resolution_status": resolution.exit_reason,
            },
        )
        metrics.record_resolution(success)
        await self._record_live_calibration(symbol, timeframe, details, success)

    @staticmethod
    def _tracker_outcome(details: dict[str, Any], resolution: Resolution) -> bool:
        if resolution.exit_reason == "target":
            return True
        if resolution.exit_reason == "stop":
            return False
        exit_price = float(resolution.exit_price or 0.0)
        entry = float(details.get("entry"))
        if str(details.get("signal_type", "")).lower() == "sell":
            return exit_price < entry
        return exit_price > entry

    @staticmethod
    def _normalize_confidence_0_100(confidence: Any) -> float:
        return normalize_confidence(confidence)

    async def _record_live_calibration(
        self, symbol: str, timeframe: str, details: dict[str, Any], success: bool
    ) -> None:
        try:
            confidence = self._normalize_confidence_0_100(details.get("confidence", 0.0))
            if confidence > 0:
                for model_type in ("lstm", "xgboost"):
                    try:
                        await self.model_manager.record_signal_performance(
                            model_type, symbol, timeframe, confidence, success
                        )
                    except Exception as e:
                        logger.debug(f"Calibration flush skipped: {e}")

            regime = str(details.get("threshold_regime") or "")
            vol_regime, _, hurst_range = regime.partition("|")
            threshold = float(details.get("threshold_used", 0.0) or 0.0)
            if vol_regime and hurst_range and threshold > 0:
                self.signal_generator.threshold_manager.record_performance(
                    vol_regime, hurst_range, threshold, success
                )
                await self.signal_generator.threshold_manager.flush()
        except (TypeError, ValueError, AttributeError) as e:
            logger.debug(f"Live calibration feedback skipped: {e}")

    async def build_performance_report(self, as_of: datetime) -> PerformanceReport:
        ledger = self.performance_ledger
        if ledger is None:
            return performance_report.build_performance_report(
                [], build_performance_config(self.config_manager), as_of
            )
        return await build_performance_report_from_ledger(ledger, self.config_manager, as_of)

    async def cleanup(self):
        logger.info("Cleaning up TradingService resources.")
        if self.learner:
            await self.learner.shutdown()
        if self.model_manager:
            await self.model_manager.shutdown()
