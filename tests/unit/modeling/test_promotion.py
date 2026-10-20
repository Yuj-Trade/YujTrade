"""Promotion and rollback policy for retrained models.

The contract: a retrained model is promoted only when it is not measurably
worse than the model it would replace. Unknown quality is not quality.
"""

import pytest

from modeling.promotion import (
    PROMOTION_SCHEMA_VERSION,
    REASON_ACCURACY_DEGRADED,
    REASON_ELIGIBLE,
    REASON_METRICS_UNAVAILABLE,
    REASON_NO_BASELINE,
    REASON_RMSE_DEGRADED,
    PromotionPolicy,
    evaluate_promotion,
)


class _Config:
    def __init__(self, values: dict):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class TestPolicyConstruction:
    def test_defaults_are_conservative(self):
        policy = PromotionPolicy()
        assert policy.max_directional_accuracy_drop == pytest.approx(0.10)
        assert policy.max_rmse_increase_ratio == pytest.approx(1.25)

    def test_policy_reads_bounds_from_configuration(self):
        policy = PromotionPolicy.from_config(
            _Config(
                {
                    "promotion_max_directional_accuracy_drop": 0.25,
                    "promotion_max_rmse_increase_ratio": 2.0,
                }
            )
        )
        assert policy.max_directional_accuracy_drop == pytest.approx(0.25)
        assert policy.max_rmse_increase_ratio == pytest.approx(2.0)

    def test_policy_falls_back_to_defaults_for_missing_configuration(self):
        policy = PromotionPolicy.from_config(_Config({}))
        assert policy.max_directional_accuracy_drop == pytest.approx(0.10)
        assert policy.max_rmse_increase_ratio == pytest.approx(1.25)


class TestPromotionDecision:
    def test_first_training_without_baseline_is_promoted(self):
        decision = evaluate_promotion(
            {}, {"rmse": 12.0, "directional_accuracy": 0.6}, PromotionPolicy()
        )
        assert decision.promote is True
        assert decision.reasons == (REASON_NO_BASELINE,)

    def test_healthy_candidate_is_promoted(self):
        decision = evaluate_promotion(
            {"rmse": 10.0, "directional_accuracy": 0.60},
            {"rmse": 9.0, "directional_accuracy": 0.62},
            PromotionPolicy(),
        )
        assert decision.promote is True
        assert decision.reasons == (REASON_ELIGIBLE,)
        assert decision.deltas["rmse_ratio"] == pytest.approx(0.9)
        assert decision.deltas["directional_accuracy_drop"] == pytest.approx(-0.02)

    def test_poisoned_accuracy_never_promotes(self):
        decision = evaluate_promotion(
            {"rmse": 10.0, "directional_accuracy": 0.80},
            {"rmse": 9.0, "directional_accuracy": 0.40},
            PromotionPolicy(),
        )
        assert decision.promote is False
        assert REASON_ACCURACY_DEGRADED in decision.reasons

    def test_poisoned_rmse_never_promotes(self):
        decision = evaluate_promotion(
            {"rmse": 10.0, "directional_accuracy": 0.60},
            {"rmse": 40.0, "directional_accuracy": 0.62},
            PromotionPolicy(),
        )
        assert decision.promote is False
        assert REASON_RMSE_DEGRADED in decision.reasons

    def test_candidate_without_metrics_never_promotes(self):
        decision = evaluate_promotion(
            {"rmse": 10.0, "directional_accuracy": 0.60},
            {},
            PromotionPolicy(),
        )
        assert decision.promote is False
        assert decision.reasons == (REASON_METRICS_UNAVAILABLE,)

    def test_nan_metrics_are_treated_as_missing(self):
        decision = evaluate_promotion(
            {"rmse": 10.0, "directional_accuracy": 0.60},
            {"rmse": float("nan"), "directional_accuracy": float("nan")},
            PromotionPolicy(),
        )
        assert decision.promote is False
        assert decision.reasons == (REASON_METRICS_UNAVAILABLE,)

    def test_degradation_within_bounds_is_tolerated(self):
        decision = evaluate_promotion(
            {"rmse": 10.0, "directional_accuracy": 0.60},
            {"rmse": 12.0, "directional_accuracy": 0.52},
            PromotionPolicy(),
        )
        assert decision.promote is True
        assert decision.reasons == (REASON_ELIGIBLE,)

    def test_bounds_come_from_the_policy(self):
        policy = PromotionPolicy(max_directional_accuracy_drop=0.50, max_rmse_increase_ratio=5.0)
        decision = evaluate_promotion(
            {"rmse": 10.0, "directional_accuracy": 0.80},
            {"rmse": 45.0, "directional_accuracy": 0.35},
            policy,
        )
        assert decision.promote is True

    def test_non_numeric_baseline_is_ignored(self):
        decision = evaluate_promotion(
            {"rmse": "unknown", "directional_accuracy": None},
            {"rmse": 9.0, "directional_accuracy": 0.55},
            PromotionPolicy(),
        )
        assert decision.promote is True
        assert decision.reasons == (REASON_NO_BASELINE,)

    def test_decision_payload_is_json_serializable(self):
        decision = evaluate_promotion(
            {"rmse": 10.0, "directional_accuracy": 0.60},
            {"rmse": 9.0, "directional_accuracy": 0.62},
            PromotionPolicy(),
        )
        payload = decision.to_dict()
        assert payload["schema_version"] == PROMOTION_SCHEMA_VERSION
        assert isinstance(payload["reasons"], list)
        assert payload["promote"] is True
