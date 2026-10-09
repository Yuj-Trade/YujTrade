import asyncio
import math
import uuid
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from backtesting.walk_forward import WalkForwardValidator
from config.logger import logger
from modeling.artifacts import ArtifactRegistry
from modeling.models import LSTMModel, XGBoostModel


class HyperparameterOptimizer:
    def __init__(
        self,
        symbol: str,
        timeframe: str,
        data: pd.DataFrame,
        model_type="lstm",
        n_trials=50,
        folds: int = 3,
        artifact_root: str | Path = "artifacts",
        validation_runner: Callable[[object, pd.DataFrame], float] | None = None,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.data = data
        self.model_type = model_type.lower()
        self.n_trials = n_trials
        self.folds = folds
        self.artifact_root = Path(artifact_root)
        self.validation_runner = validation_runner
        self.loop = asyncio.get_running_loop()

        # Check if optuna is available
        try:
            import optuna

            self.optuna = optuna
        except ImportError:
            self.optuna = None
            logger.error(
                "Optuna is not installed. Install it to use HyperparameterOptimizer."
            )

    def _define_lstm_search_space(self, trial):
        return {
            "units": trial.suggest_int("units", 32, 256, step=32),
            "lr": trial.suggest_float("lr", 1e-5, 1e-2, log=True),
            "sequence_length": trial.suggest_int("sequence_length", 20, 120, step=10),
        }

    def _define_xgboost_search_space(self, trial):
        return {
            "n_estimators": trial.suggest_int("n_estimators", 50, 500, step=50),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        }

    async def _objective(self, trial):
        if not self.optuna:
            raise ImportError("Optuna is not installed.")

        try:
            if self.model_type == "lstm":
                params = self._define_lstm_search_space(trial)
                sequence_length = params.pop("sequence_length")
                model_class = LSTMModel
            elif self.model_type == "xgboost":
                params = self._define_xgboost_search_space(trial)
                sequence_length = 0
                model_class = XGBoostModel
            else:
                raise ValueError("Unsupported model type")
            validator = WalkForwardValidator(
                folds=self.folds,
                min_train_fraction=0.6,
                sequence_length=sequence_length,
            )
            run_id = f"trial-{trial.number}-{uuid.uuid4().hex[:8]}"
            registry = ArtifactRegistry(self.artifact_root)
            sharpes: list[float] = []
            for fold in validator.split(self.data):
                fold_dir = self.artifact_root / "fold-runs" / run_id / f"fold-{fold.index}"
                model = model_class(
                    symbol=self.symbol, timeframe=self.timeframe,
                    model_path=str(fold_dir), **params
                )
                if sequence_length and hasattr(model, "sequence_length"):
                    model.sequence_length = sequence_length
                is_trained = await self.loop.run_in_executor(None, model.fit, fold.train)
                if not is_trained:
                    raise self.optuna.exceptions.TrialPruned()
                score = (
                    self.validation_runner(model, fold.test)
                    if self.validation_runner
                    else self._default_validation_score(model, fold.train, fold.test)
                )
                score = float(score) if math.isfinite(float(score)) else -1.0
                sharpes.append(score)
                source_files = list(fold_dir.glob("*"))
                registry.create_version(
                    self.model_type, self.symbol, self.timeframe, source_files,
                    metadata={"run_id": run_id, "fold": fold.index, "params": params,
                              "oos_metrics": {"sharpe": score}},
                    version=f"{run_id}-fold-{fold.index}", update_current=False,
                )
                model.cleanup()
                trial.report(purged_objective_score(sharpes), step=fold.index)
                if trial.should_prune():
                    raise self.optuna.exceptions.TrialPruned()
            return purged_objective_score(sharpes)
        except Exception as e:
            logger.error(f"Trial {trial.number} failed: {e}", exc_info=True)
            return -2.0

    @staticmethod
    def _default_validation_score(model, train: pd.DataFrame, test: pd.DataFrame) -> float:
        if test.empty or "close" not in test:
            return -1.0
        history = pd.concat([train.tail(500), test])
        predictions = []
        for index in range(len(test)):
            result = model.predict(history.iloc[: len(train.tail(500)) + index + 1])
            predictions.append(float(result[0].ravel()[0]) if result else float("nan"))
        actual = test["close"].to_numpy()
        previous = pd.Series(actual).shift(1).fillna(float(train["close"].iloc[-1])).to_numpy()
        returns = (actual - previous) / previous
        directions = pd.Series(predictions).sub(previous).apply(
            lambda value: 1 if value > 0 else -1
        )
        strategy_returns = returns * directions.to_numpy()
        std = float(strategy_returns.std())
        return (
            float(strategy_returns.mean() / std * (len(strategy_returns) ** 0.5))
            if std
            else -1.0
        )

    async def run(self):
        if not self.optuna:
            return {}, -1.0

        study = self.optuna.create_study(
            direction="maximize", pruner=self.optuna.pruners.MedianPruner()
        )

        # Use run_in_executor to run the sync objective function in the event loop
        def sync_objective_wrapper(trial):
            future = asyncio.run_coroutine_threadsafe(self._objective(trial), self.loop)
            return future.result()

        # Run optimize in a separate thread to avoid blocking the event loop
        await self.loop.run_in_executor(
            None,
            lambda: study.optimize(
                sync_objective_wrapper, n_trials=self.n_trials, n_jobs=1
            ),
        )

        pruned_trials = study.get_trials(
            deepcopy=False, states=[self.optuna.trial.TrialState.PRUNED]
        )
        complete_trials = study.get_trials(
            deepcopy=False, states=[self.optuna.trial.TrialState.COMPLETE]
        )

        logger.info("Study statistics: ")
        logger.info(f"  Number of finished trials: {len(study.trials)}")
        logger.info(f"  Number of pruned trials: {len(pruned_trials)}")
        logger.info(f"  Number of complete trials: {len(complete_trials)}")

        if not complete_trials:
            logger.error("No trials were completed successfully.")
            return {}, -1.0

        logger.info("Best trial:")
        trial = study.best_trial

        logger.info(f"  Value (Sharpe Ratio): {trial.value}")
        logger.info("  Params: ")
        for key, value in trial.params.items():
            logger.info(f"    {key}: {value}")

        return trial.params, trial.value


def purged_objective_score(sharpes: list[float]) -> float:
    if not sharpes:
        return -1.0
    series = pd.Series(sharpes, dtype=float)
    return float(series.median() - 0.5 * series.std(ddof=0))
