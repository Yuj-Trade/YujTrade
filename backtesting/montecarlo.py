import random
from collections.abc import Iterable
from statistics import mean

MONTE_CARLO_SCHEMA_VERSION = 1
DEFAULT_SIMULATIONS = 1000
DEFAULT_SEED = 42
DEFAULT_CONFIDENCE = 0.95


def simulate_r_multiples(
    r_multiples: Iterable[float], simulations: int = 1000, seed: int = 42
) -> list[float]:
    values = list(float(value) for value in r_multiples)
    if not values or simulations < 1:
        return []
    rng = random.Random(seed)
    results = []
    for _ in range(simulations):
        equity = 0.0
        for _ in values:
            equity += rng.choice(values)
        results.append(equity)
    return results


def expected_r(r_multiples: Iterable[float]) -> float:
    values = list(r_multiples)
    return mean(values) if values else 0.0


def bootstrap_confidence_interval(
    r_multiples: Iterable[float],
    confidence: float = DEFAULT_CONFIDENCE,
    simulations: int = DEFAULT_SIMULATIONS,
    seed: int = DEFAULT_SEED,
) -> dict[str, float | int | str]:
    simulated = simulate_r_multiples(r_multiples, simulations=simulations, seed=seed)
    if not simulated:
        return {
            "schema_version": MONTE_CARLO_SCHEMA_VERSION,
            "confidence": float(confidence),
            "simulations": int(simulations),
            "seed": int(seed),
            "samples": 0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "mean": 0.0,
        }
    ordered = sorted(simulated)
    tail = (1.0 - float(confidence)) / 2.0
    low_index = max(0, min(len(ordered) - 1, int(tail * len(ordered))))
    high_index = max(0, min(len(ordered) - 1, int((1.0 - tail) * len(ordered)) - 1))
    return {
        "schema_version": MONTE_CARLO_SCHEMA_VERSION,
        "confidence": float(confidence),
        "simulations": int(simulations),
        "seed": int(seed),
        "samples": len(ordered),
        "ci_low": float(ordered[low_index]),
        "ci_high": float(ordered[high_index]),
        "mean": float(mean(ordered)),
    }
