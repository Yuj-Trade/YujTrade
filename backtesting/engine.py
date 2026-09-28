import asyncio

import backtrader as bt
import pandas as pd
from typing import Dict, List, Optional

from config.logger import logger
from common.core import TradingSignal
from strategy.signal_tracker import make_signal_id


class BacktraderStrategy(bt.Strategy):
    params = (
        ("symbol", None),
        ("timeframe", None),
        ("signals_df", None),
        ("owner_engine", None),
    )

    def __init__(self):
        self.symbol = self.p.symbol
        self.timeframe = self.p.timeframe
        self.signals_df = self.p.signals_df
        self.owner_engine = self.p.owner_engine
        self.order = None
        self._open_trade = None

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.date(0)
        logger.debug(f"{dt.isoformat()} - {txt}")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    f"BUY EXECUTED, Price: {order.executed.price:.2f}, Cost: {order.executed.value:.2f}"
                )
            elif order.issell():
                self.log(
                    f"SELL EXECUTED, Price: {order.executed.price:.2f}, Cost: {order.executed.value:.2f}"
                )
            self.bar_executed = len(self)
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("Order Canceled/Margin/Rejected")
            self._open_trade = None
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f"OPERATION PROFIT, GROSS {trade.pnl:.2f}, NET {trade.pnlcomm:.2f}")
        # نتیجه واقعی معامله → چرخه رهگیری (شکاف ۱۲/۱۳/۱۴). resolve و
        # فراخوانی‌های کالیبراتور بعد از پایان cerebro.run به‌صورت همگام
        # flush می‌شوند تا callback همگام backtrader با lifecycle async
        # تولید تداخل نکند.
        if self._open_trade and self.owner_engine is not None:
            try:
                # شکاف ۳۷: فراخوانی بدون await، coroutine را دور می‌ریزد و
                # هیچ سیگنالی resolve نمی‌شود؛ resolve در _flush_calibration
                # انجام می‌شود (تنها نقطه قابل await در بک‌تست).
                self.owner_engine.pending_outcomes.append(
                    {
                        "signal_id": self._open_trade["signal_id"],
                        "success": trade.pnl > 0,
                        "confidence": self._open_trade.get("confidence", 0.0),
                        "pnl": trade.pnl,
                        "pnlcomm": trade.pnlcomm,
                    }
                )
            except Exception as e:
                logger.debug(f"Trade outcome tracking skipped: {e}")
        self._open_trade = None

    def next(self):
        if self.order:
            return

        current_dt = pd.to_datetime(self.datas[0].datetime.datetime(0)).tz_localize(
            "UTC"
        )

        # Check if the current datetime from backtrader exists in our pre-calculated signals
        if self.signals_df is None or self.signals_df.empty or current_dt not in self.signals_df.index:
            return

        signal_row = self.signals_df.loc[current_dt]
        signal_type = signal_row.get("signal_type")

        if not signal_type:
            return

        if not self.position:
            if signal_type == "buy":
                self.log(f"BUY CREATE, {self.datas[0].close[0]:.2f}")
                self._open_trade = self._capture_signal(current_dt, signal_row)
                self.order = self.buy()
            elif signal_type == "sell":
                self.log(f"SELL CREATE, {self.datas[0].close[0]:.2f}")
                self._open_trade = self._capture_signal(current_dt, signal_row)
                self.order = self.sell()
        else:
            # Simple logic: close position if the signal reverses
            if self.position.size > 0 and signal_type == "sell":
                self.log(f"CLOSE (SELL) CREATE, {self.datas[0].close[0]:.2f}")
                self.order = self.close()
            elif self.position.size < 0 and signal_type == "buy":
                self.log(f"CLOSE (BUY) CREATE, {self.datas[0].close[0]:.2f}")
                self.order = self.close()

    def _capture_signal(self, current_dt, signal_row) -> Dict:
        try:
            confidence = float(signal_row.get("confidence_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        try:
            threshold = float(signal_row.get("threshold_used", 0.0) or 0.0)
        except (TypeError, ValueError):
            threshold = 0.0
        return {
            "signal_id": make_signal_id(
                self.symbol, self.timeframe, current_dt, signal_row.get("signal_type")
            ),
            "confidence": confidence,
            "threshold": threshold,
            "threshold_regime": signal_row.get("threshold_regime"),
        }


class BacktestingEngine:
    """موتور بک‌تست هم‌مسیر با Production (شکاف ۱۵): کاملاً async و بدون
    run_until_complete؛ از همان lifecycle سیستم استفاده می‌کند.
    سیگنال‌های تاریخی در حالت خالص محاسبه می‌شوند (شکاف ۱۴):
    بدون external لحظه‌ای و بدون ML زنده."""

    def __init__(self, trading_service):
        self.trading_service = trading_service
        self.signal_tracker = trading_service.signal_tracker
        self.full_data = None
        self.pending_outcomes: List[Dict] = []
        self.symbol = None
        self.timeframe = None

    def get_historical_data(self, current_len):
        """
        Provides historical data up to the current point in the backtest.
        This is useful for indicators that need a consistent history.
        """
        if self.full_data is not None and not self.full_data.empty:
            if current_len > len(self.full_data):
                return self.full_data.copy()
            return self.full_data.iloc[:current_len]
        return pd.DataFrame()

    async def pre_calculate_signals(self) -> pd.DataFrame:
        """
        Generates signals for the entire dataset at once to speed up backtesting.
        حالت تاریخی خالص: include_external=False و include_ml=False تا داده
        لحظه‌ای Production وارد تحلیل گذشته نشود (شکاف ۱۴).
        """
        if self.full_data is None:
            return pd.DataFrame()

        tasks = []
        # Generate a signal for each data point in the dataset
        for i in range(100, len(self.full_data)):  # Start after a warmup period
            data_slice = self.full_data.iloc[:i]
            tasks.append(
                self.trading_service.signal_generator.generate_signal(
                    self.symbol,
                    self.timeframe,
                    data_slice,
                    include_external=False,
                    include_ml=False,
                )
            )

        signals = await asyncio.gather(*tasks, return_exceptions=True)
        # قرارداد شکاف ۳۰: None یعنی «سیگنالی نیست» (رد می‌شود)، Exception
        # یعنی «تحلیل شکست خورد» (لاگ می‌شود) — فقط سیگنال‌های واقعی می‌مانند.
        genuine = []
        for s in signals:
            if isinstance(s, TradingSignal):
                genuine.append(s)
            elif isinstance(s, Exception):
                logger.debug(f"Historical signal skipped: {s}")
        signals = genuine

        if not signals:
            return pd.DataFrame()

        signal_data = [
            {
                "timestamp": s.timestamp,
                "signal_type": s.signal_type.value,
                "confidence_score": s.confidence_score,
                "threshold_used": s.threshold_used,
                "threshold_regime": s.threshold_regime,
            }
            for s in signals
        ]
        signals_df = pd.DataFrame(signal_data)
        signals_df["timestamp"] = pd.to_datetime(signals_df["timestamp"])
        signals_df = signals_df.set_index("timestamp")
        return signals_df

    async def _flush_calibration(self):
        """حلقه بازخورد کالیبراسیون (شکاف ۱۲) + lifecycle رهگیری (شکاف ۱۳):
        هر نتیجه pending اول resolve می‌شود (record → resolved؛ record/resolve
        async‌اند و callback همگام backtrader قابل await نیست، پس این تنها
        نقطه صحیح resolve در بک‌تست است) و سپس نتیجه واقعی به calibrator
        مدل‌ها و threshold_manager برمی‌گردد. چون تفکیک confidence به‌ازای
        هر مدل در قرارداد فعلی plumbing نشده، از confidence ترکیبی سیگنال
        به‌عنوان proxy استفاده می‌شود (بدون مکانیزم جدید)."""
        threshold_manager = (
            self.trading_service.signal_generator.threshold_manager
        )
        for outcome in self.pending_outcomes:
            success = bool(outcome.get("success", False))
            confidence = outcome.get("confidence", 0.0) or 0.0
            signal_id = outcome.get("signal_id")
            if signal_id:
                try:
                    await self.signal_tracker.resolve(
                        signal_id,
                        success,
                        {
                            "pnl": outcome.get("pnl"),
                            "pnlcomm": outcome.get("pnlcomm"),
                            "resolution_source": "backtest_flush",
                        },
                    )
                except Exception as e:
                    logger.debug(f"Trade outcome resolve skipped: {e}")
            if confidence > 0:
                for model_type in ("lstm", "xgboost"):
                    try:
                        await self.trading_service.model_manager.record_signal_performance(
                            model_type,
                            self.symbol,
                            self.timeframe,
                            float(confidence),
                            success,
                        )
                    except Exception as e:
                        logger.debug(f"Calibration flush skipped: {e}")
            # مسیر نوشتن آستانه تطبیقی: فقط با هر سه جزء (رژیم/آستانه/نتیجه).
            try:
                regime = outcome.get("threshold_regime") or ""
                vol_regime, _, hurst_range = regime.partition("|")
                threshold = float(outcome.get("threshold", 0.0) or 0.0)
                if vol_regime and hurst_range and threshold > 0:
                    threshold_manager.record_performance(
                        vol_regime, hurst_range, threshold, success
                    )
            except (TypeError, ValueError, AttributeError) as e:
                logger.debug(f"Threshold feedback skipped: {e}")

    async def run_backtest(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        initial_capital: float = 10000,
        commission_rate: float = 0.001,
    ):
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(initial_capital)
        cerebro.broker.setcommission(commission=commission_rate)

        self.symbol = symbol
        self.timeframe = timeframe
        self.pending_outcomes = []

        # Fetch the complete data for the backtest period
        self.full_data = (
            await self.trading_service.market_data_provider.fetch_ohlcv_data(
                symbol, timeframe, limit=5000
            )  # Fetch ample data
        )
        if self.full_data is None or self.full_data.empty:
            logger.error(f"No data for {symbol} on {timeframe}")
            return {}

        if not isinstance(self.full_data.index, pd.DatetimeIndex):
            self.full_data = self.full_data.set_index("timestamp")

        signals_df = await self.pre_calculate_signals()

        # Create a data feed for cerebro with the specified date range
        data_feed = bt.feeds.PandasData(
            dataname=self.full_data[start:end],
        )
        cerebro.adddata(data_feed)

        cerebro.addstrategy(
            BacktraderStrategy,
            symbol=symbol,
            timeframe=timeframe,
            signals_df=signals_df,
            owner_engine=self,
        )
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

        logger.info(f"Running backtest for {symbol} from {start} to {end}...")
        results = cerebro.run()
        strat = results[0]
        logger.info("Backtest finished.")

        await self._flush_calibration()

        trade_analysis = strat.analyzers.trades.get_analysis()

        return {
            "initial_capital": initial_capital,
            "final_capital": cerebro.broker.getvalue(),
            "total_return_pct": (cerebro.broker.getvalue() / initial_capital - 1) * 100,
            "sharpe_ratio": strat.analyzers.sharpe.get_analysis().get("sharperatio", 0),
            "max_drawdown_pct": strat.analyzers.drawdown.get_analysis().max.drawdown,
            "total_trades": trade_analysis.get("total", {}).get("total", 0),
            "winning_trades": trade_analysis.get("won", {}).get("total", 0),
            "losing_trades": trade_analysis.get("lost", {}).get("total", 0),
            "win_rate_pct": (
                (
                    trade_analysis.get("won", {}).get("total", 0)
                    / trade_analysis.get("total", {}).get("total", 0)
                    * 100
                )
                if trade_analysis.get("total", {}).get("total", 0) > 0
                else 0
            ),
            "tracked_outcomes": len(self.pending_outcomes),
            "tracker_summary": self.signal_tracker.get_performance_summary(),
        }
