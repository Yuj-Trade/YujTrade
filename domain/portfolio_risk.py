import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PortfolioRiskView:
    symbols: tuple[str, ...]
    last_close: tuple[float, ...]
    returns: tuple[tuple[float, ...], ...]
    covariance: tuple[tuple[float, ...], ...]


def _check_finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite value for {name}")
    return number


def _check_vector(values: Sequence[float], name: str) -> tuple[float, ...]:
    checked: list[float] = []
    for index, value in enumerate(values):
        checked.append(_check_finite(value, f"{name}[{index}]"))
    return tuple(checked)


def _check_matrix(
    matrix: Sequence[Sequence[float]], name: str
) -> tuple[tuple[float, ...], ...]:
    checked: list[tuple[float, ...]] = []
    for row_index, row in enumerate(matrix):
        checked.append(_check_vector(row, f"{name}[{row_index}]"))
    size = len(checked)
    if size == 0:
        raise ValueError(f"{name} is empty")
    for row in checked:
        if len(row) != size:
            raise ValueError(f"{name} is not square")
    return tuple(checked)


def correlation(cov: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    matrix = _check_matrix(cov, "covariance")
    size = len(matrix)
    result: list[list[float]] = []
    for i in range(size):
        row = [0.0] * size
        for j in range(size):
            denominator = math.sqrt(matrix[i][i] * matrix[j][j])
            if denominator <= 0.0:
                raise ValueError("covariance diagonal is not positive")
            row[j] = matrix[i][j] / denominator
            if not math.isfinite(row[j]):
                raise ValueError("correlation is not finite")
        result.append(row)
    return tuple(tuple(row) for row in result)


def distance_matrix(corr: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    matrix = _check_matrix(corr, "correlation")
    size = len(matrix)
    result: list[list[float]] = []
    for i in range(size):
        row = [0.0] * size
        for j in range(size):
            value = corr[i][j]
            if value < -1.0:
                value = -1.0
            if value > 1.0:
                value = 1.0
            row[j] = math.sqrt(0.5 * (1.0 - value))
            if not math.isfinite(row[j]):
                raise ValueError("distance is not finite")
        result.append(row)
    return tuple(tuple(row) for row in result)


def _average_linkage(
    distances: Sequence[Sequence[float]], first: Sequence[int], second: Sequence[int]
) -> float:
    total = 0.0
    for i in first:
        for j in second:
            total += distances[i][j]
    count = len(first) * len(second)
    if count == 0:
        raise ValueError("empty cluster pair")
    return total / count


def _merge_tree(
    distances: Sequence[Sequence[float]],
) -> list[tuple[float, frozenset[int], frozenset[int], frozenset[int]]]:
    size = len(distances)
    clusters: list[tuple[frozenset[int], tuple[int, ...]]] = [
        (frozenset({index}), (index,)) for index in range(size)
    ]
    merges: list[tuple[float, frozenset[int], frozenset[int], frozenset[int]]] = []
    while len(clusters) > 1:
        best_cost: float | None = None
        best_pair: tuple[int, int, tuple[int, ...], tuple[int, ...]] | None = None
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                members_a, _ = clusters[a]
                members_b, _ = clusters[b]
                cost = _average_linkage(distances, sorted(members_a), sorted(members_b))
                if best_cost is None or cost < best_cost:
                    best_cost = cost
                    best_pair = (a, b, clusters[a][1], clusters[b][1])
        if best_pair is None or best_cost is None:
            break
        a, b, order_a, order_b = best_pair
        members_a, _ = clusters[a]
        members_b, _ = clusters[b]
        merged_members = members_a | members_b
        merged_order = order_a + order_b
        merges.append((best_cost, members_a, members_b, merged_members))
        del clusters[b]
        del clusters[a]
        clusters.append((merged_members, merged_order))
    return merges


def cluster_labels(corr: Sequence[Sequence[float]], threshold: float) -> tuple[int, ...]:
    matrix = _check_matrix(corr, "correlation")
    limit = _check_finite(threshold, "threshold")
    size = len(matrix)
    distances = distance_matrix(matrix)
    merges = _merge_tree(distances)

    cut = math.sqrt(0.5 * (1.0 - limit))
    parent = list(range(size))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(first: int, second: int) -> None:
        root_a = find(first)
        root_b = find(second)
        if root_a == root_b:
            return
        if root_a < root_b:
            parent[root_b] = root_a
        else:
            parent[root_a] = root_b

    for cost, members_a, members_b, _ in merges:
        if cost > cut:
            continue
        roots_a = sorted({find(index) for index in members_a})
        roots_b = sorted({find(index) for index in members_b})
        for index in roots_a[1:]:
            union(roots_a[0], index)
        for index in roots_b[1:]:
            union(roots_b[0], index)
        union(roots_a[0], roots_b[0])

    roots = [find(index) for index in range(size)]
    unique_roots = sorted(set(roots))
    root_to_label = {root: label for label, root in enumerate(unique_roots)}
    return tuple(root_to_label[root] for root in roots)


def _leaf_sequence(
    size: int,
    merges: list[tuple[float, frozenset[int], frozenset[int], frozenset[int]]],
) -> tuple[int, ...]:
    orders: dict[frozenset[int], tuple[int, ...]] = {
        frozenset({index}): (index,) for index in range(size)
    }
    for _, members_a, members_b, merged in merges:
        orders[merged] = orders[members_a] + orders[members_b]
    return orders[merges[-1][3]]


def leaf_order(corr: Sequence[Sequence[float]]) -> tuple[int, ...]:
    matrix = _check_matrix(corr, "correlation")
    size = len(matrix)
    distances = distance_matrix(matrix)
    merges = _merge_tree(distances)
    if not merges:
        return tuple(range(size))
    return _leaf_sequence(size, merges)


def hrp_weights(cov: Sequence[Sequence[float]], order: Sequence[int]) -> tuple[float, ...]:
    matrix = _check_matrix(cov, "covariance")
    size = len(matrix)
    leaf = [int(index) for index in order]
    if len(leaf) != size or sorted(leaf) != list(range(size)):
        raise ValueError("order is not a permutation of the covariance indices")
    weights = [0.0] * size
    _bisect_cluster(matrix, leaf, weights)
    total = sum(weights)
    if total <= 0.0 or not math.isfinite(total):
        raise ValueError("hrp weights are not positive")
    result = tuple(_check_finite(value / total, "hrp weight") for value in weights)
    if abs(sum(result) - 1.0) > 1e-9:
        raise ValueError("hrp weights do not sum to one")
    return result


def _bisect_cluster(
    cov: Sequence[Sequence[float]], cluster: Sequence[int], weights: list[float]
) -> None:
    if len(cluster) <= 1:
        if cluster:
            weights[cluster[0]] = 1.0
        return
    half = len(cluster) // 2
    left = list(cluster[:half])
    right = list(cluster[half:])
    left_inverse = _inverse_variance_weights(cov, left)
    right_inverse = _inverse_variance_weights(cov, right)
    variance_left = _sub_variance(cov, left, left_inverse)
    variance_right = _sub_variance(cov, right, right_inverse)
    total = variance_left + variance_right
    if total <= 0.0 or not math.isfinite(total):
        alpha = 0.5
    else:
        alpha = _clamp(1.0 - variance_left / total, 0.0, 1.0)
    _bisect_cluster(cov, left, weights)
    _bisect_cluster(cov, right, weights)
    left_total = sum(weights[index] for index in left)
    right_total = sum(weights[index] for index in right)
    if left_total <= 0.0 and right_total <= 0.0:
        raise ValueError("cluster variance is not positive")
    if left_total > 0.0:
        for index in left:
            weights[index] = weights[index] / left_total * alpha
    if right_total > 0.0:
        for index in right:
            weights[index] = weights[index] / right_total * (1.0 - alpha)


def _inverse_variance_weights(
    cov: Sequence[Sequence[float]], indices: Sequence[int]
) -> list[float]:
    weights: list[float] = []
    for index in indices:
        variance = cov[index][index]
        if variance <= 0.0 or not math.isfinite(variance):
            raise ValueError("covariance diagonal is not positive")
        weights.append(1.0 / variance)
    total = sum(weights)
    if total <= 0.0:
        raise ValueError("inverse variance sum is not positive")
    return [value / total for value in weights]


def _sub_variance(
    cov: Sequence[Sequence[float]], indices: Sequence[int], weights: Sequence[float]
) -> float:
    total = 0.0
    for position, i in enumerate(indices):
        for other, j in enumerate(indices):
            total += weights[position] * cov[i][j] * weights[other]
    return total


def portfolio_series(w: Sequence[float], returns: Sequence[Sequence[float]]) -> tuple[float, ...]:
    weights = _check_vector(w, "weights")
    if len(returns) != len(weights):
        raise ValueError("weights and returns length mismatch")
    length = len(returns[0]) if returns else 0
    for row in returns:
        if len(row) != length:
            raise ValueError("return rows are not aligned")
    result: list[float] = []
    for t in range(length):
        total = 0.0
        for i in range(len(weights)):
            total += weights[i] * returns[i][t]
        result.append(total)
    return tuple(result)


def cvar95(series: Sequence[float]) -> float:
    values = sorted(_check_vector(series, "series"))
    if not values:
        return 0.0
    tail_size = max(1, math.ceil(0.05 * len(values)))
    tail_size = min(tail_size, len(values))
    return -sum(values[:tail_size]) / tail_size


def _sigma_vector(cov: Sequence[Sequence[float]], weights: Sequence[float]) -> list[float]:
    result: list[float] = []
    for i in range(len(weights)):
        total = 0.0
        for j in range(len(weights)):
            total += cov[i][j] * weights[j]
        result.append(total)
    return result


def effective_bets(w: Sequence[float], cov: Sequence[Sequence[float]]) -> float:
    weights = _check_vector(w, "weights")
    matrix = _check_matrix(cov, "covariance")
    if len(matrix) != len(weights):
        raise ValueError("weights and covariance size mismatch")
    non_zero = sum(1 for weight in weights if weight != 0.0)
    if len(weights) <= 1 or non_zero <= 1:
        return 1.0
    sigma_w = _sigma_vector(matrix, weights)
    sigma_sq = 0.0
    for i in range(len(weights)):
        sigma_sq += weights[i] * sigma_w[i]
    if sigma_sq <= 0.0 or not math.isfinite(sigma_sq):
        return 1.0
    contributions = [weights[i] * sigma_w[i] / sigma_sq for i in range(len(weights))]
    total_abs = sum(abs(value) for value in contributions)
    if total_abs <= 0.0:
        return 1.0
    shares = [abs(value) / total_abs for value in contributions]
    denominator = sum(value * value for value in shares)
    if denominator <= 0.0:
        return 1.0
    value = 1.0 / denominator
    if not math.isfinite(value):
        raise ValueError("effective bets is not finite")
    return value


def _cvar_bisect(
    book_series: tuple[float, ...], cand_series: tuple[float, ...], cvar_cap: float
) -> float:
    if len(book_series) != len(cand_series):
        raise ValueError("return series are not aligned")
    if not book_series:
        return 1.0
    mixed = tuple(book_series[t] + cand_series[t] for t in range(len(book_series)))
    if cvar95(mixed) <= cvar_cap:
        return 1.0
    low = 0.0
    high = 1.0
    for _ in range(60):
        middle = (low + high) / 2.0
        candidate = tuple(
            book_series[t] + middle * cand_series[t] for t in range(len(book_series))
        )
        if cvar95(candidate) <= cvar_cap:
            low = middle
        else:
            high = middle
    return low


def solve_scale(
    w_book: Sequence[float],
    w_cand: Sequence[float],
    cluster_members: Sequence[int],
    cluster_cap: float,
    budget: float,
    cvar_cap: float,
    cov: Sequence[Sequence[float]],
    book_series: Sequence[float],
    cand_series: Sequence[float],
) -> tuple[float, str]:
    book = _check_vector(w_book, "w_book")
    candidate = _check_vector(w_cand, "w_cand")
    matrix = _check_matrix(cov, "covariance")
    cap = _check_finite(cluster_cap, "cluster_cap")
    limit = _check_finite(budget, "budget")
    cvar_limit = _check_finite(cvar_cap, "cvar_cap")
    if len(matrix) != len(book) or len(candidate) != len(book):
        raise ValueError("weights and covariance size mismatch")
    book_returns = _check_vector(book_series, "book_series")
    cand_returns = _check_vector(cand_series, "cand_series")
    members = [int(index) for index in cluster_members]

    entry_index = -1
    magnitude = 0.0
    for index in range(len(candidate)):
        if candidate[index] != 0.0:
            entry_index = index
            magnitude = abs(candidate[index])
            break
    if entry_index < 0 or magnitude <= 0.0:
        return 1.0, "none"
    if entry_index not in members:
        members = members + [entry_index]

    cluster_exposure = 0.0
    for index in members:
        cluster_exposure += abs(book[index])
    k_cluster = _clamp((cap - cluster_exposure) / magnitude, 0.0, 1.0)

    book_variance = _sub_variance(matrix, list(range(len(book))), book)
    cross = 0.0
    for i in range(len(book)):
        for j in range(len(candidate)):
            cross += book[i] * matrix[i][j] * candidate[j]
    cand_variance = _sub_variance(matrix, list(range(len(candidate))), candidate)
    budget_sq = limit * limit
    if book_variance > budget_sq:
        k_vol = 0.0
    elif cand_variance > 1e-18:
        discriminant = cross * cross - cand_variance * (book_variance - budget_sq)
        if discriminant < 0.0:
            k_vol = 0.0
        else:
            k_vol = _clamp((-cross + math.sqrt(discriminant)) / cand_variance, 0.0, 1.0)
    elif cross > 0.0:
        k_vol = _clamp((budget_sq - book_variance) / (2.0 * cross), 0.0, 1.0)
    else:
        k_vol = 1.0

    if cvar95(book_returns) > cvar_limit:
        k_cvar = 0.0
    else:
        k_cvar = _cvar_bisect(tuple(book_returns), tuple(cand_returns), cvar_limit)

    checks = (("cluster", k_cluster), ("vol", k_vol), ("cvar", k_cvar))
    scale = min(value for _, value in checks)
    binding = "none"
    if scale < 1.0:
        for name, value in checks:
            if value == scale:
                binding = name
                break
    return scale, binding


def correlation_penalty(
    cand: int, refs: Sequence[tuple[int, int]], corr: Sequence[Sequence[float]]
) -> float:
    matrix = _check_matrix(corr, "correlation")
    index = int(cand)
    if index < 0 or index >= len(matrix):
        raise ValueError("candidate index out of range")
    best = 0.0
    for reference_index, _sign in refs:
        reference = int(reference_index)
        if reference < 0 or reference >= len(matrix):
            raise ValueError("reference index out of range")
        value = matrix[index][reference]
        if not math.isfinite(value):
            raise ValueError("correlation value is not finite")
        if value > best:
            best = value
    return best if best > 0.0 else 0.0


def budget_factor(h: float, cs: float, beta: float) -> float:
    target = _check_finite(h, "h")
    share = _check_finite(cs, "cs")
    weight = _check_finite(beta, "beta")
    denominator = target if abs(target) > 1e-9 else 1e-9
    adjusted = 1.0 + weight * (target - share) / denominator
    return _clamp(adjusted, 0.8, 1.2)


def _clamp(value: float, low: float, high: float) -> float:
    if not math.isfinite(value):
        raise ValueError("value is not finite")
    if value < low:
        return low
    if value > high:
        return high
    return value
