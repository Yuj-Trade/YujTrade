import math
from dataclasses import asdict, dataclass
from typing import Any

PROMOTION_SCHEMA_VERSION = 1
REASON_ELIGIBLE = "eligible"
REASON_NO_BASELINE = "no_baseline"
REASON_METRICS_UNAVAILABLE = "candidate_metrics_unavailable"
REASON_ACCURACY_DEGRADED = "directional_accuracy_degraded"
REASON_RMSE_DEGRADED = "rmse_degraded"
METRIC_ACCURACY = "directional_accuracy"
METRIC_RMSE = "rmse"


@dataclass(frozen=True)
class PromotionPolicy:
    max_directional_accuracy_drop: float = 0.10
    max_rmse_increase_ratio: float = 1.25

    @classmethod
    def from_config(cls, config_manager: Any) -> "PromotionPolicy":
        return cls(
            max_directional_accuracy_drop=float(
                config_manager.get("promotion_max_directional_accuracy_drop", 0.10)
            ),
            max_rmse_increase_ratio=float(
                config_manager.get("promotion_max_rmse_increase_ratio", 1.25)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reasons: tuple[str, ...]
    baseline_metrics: dict[str, float]
    candidate_metrics: dict[str, float]
    deltas: dict[str, float]
    schema_version: int = PROMOTION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


def _numeric_metrics(metrics: Any) -> dict[str, float]:
    if not isinstance(metrics, dict):
        return {}
    collected: dict[str, float] = {}
    for key, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            continue
        collected[str(key)] = number
    return collected


def _metric(metrics: dict[str, float], key: str) -> float | None:
    value = metrics.get(key)
    if value is None:
        return None
    return float(value)


def evaluate_promotion(
    baseline_metrics: Any, candidate_metrics: Any, policy: PromotionPolicy
) -> PromotionDecision:
    baseline = _numeric_metrics(baseline_metrics)
    candidate = _numeric_metrics(candidate_metrics)
    if not baseline:
        return PromotionDecision(
            promote=True,
            reasons=(REASON_NO_BASELINE,),
            baseline_metrics=baseline,
            candidate_metrics=candidate,
            deltas={},
        )
    if not candidate:
        return PromotionDecision(
            promote=False,
            reasons=(REASON_METRICS_UNAVAILABLE,),
            baseline_metrics=baseline,
            candidate_metrics=candidate,
            deltas={},
        )

    reasons: list[str] = []
    deltas: dict[str, float] = {}

    baseline_accuracy = _metric(baseline, METRIC_ACCURACY)
    candidate_accuracy = _metric(candidate, METRIC_ACCURACY)
    if baseline_accuracy is not None and candidate_accuracy is not None:
        drop = baseline_accuracy - candidate_accuracy
        deltas["directional_accuracy_drop"] = drop
        if drop > policy.max_directional_accuracy_drop:
            reasons.append(REASON_ACCURACY_DEGRADED)

    baseline_rmse = _metric(baseline, METRIC_RMSE)
    candidate_rmse = _metric(candidate, METRIC_RMSE)
    if baseline_rmse is not None and candidate_rmse is not None and baseline_rmse > 0:
        ratio = candidate_rmse / baseline_rmse
        deltas["rmse_ratio"] = ratio
        if ratio > policy.max_rmse_increase_ratio:
            reasons.append(REASON_RMSE_DEGRADED)

    if reasons:
        return PromotionDecision(
            promote=False,
            reasons=tuple(reasons),
            baseline_metrics=baseline,
            candidate_metrics=candidate,
            deltas=deltas,
        )
    return PromotionDecision(
        promote=True,
        reasons=(REASON_ELIGIBLE,),
        baseline_metrics=baseline,
        candidate_metrics=candidate,
        deltas=deltas,
    )
