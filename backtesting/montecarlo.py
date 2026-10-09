import random
from statistics import mean
from typing import Iterable


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
