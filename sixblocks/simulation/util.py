"""Small numeric helpers shared across the simulation."""

from __future__ import annotations


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def approach(value: float, target: float, rate: float) -> float:
    """Move ``value`` a ``rate`` fraction of the way toward ``target``."""
    return value + (target - value) * rate


def mean(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def median(values) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    middle = len(values) // 2
    if len(values) % 2 == 1:
        return float(values[middle])
    return (values[middle - 1] + values[middle]) / 2.0


def percentile(values, fraction: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    position = fraction * (len(values) - 1)
    low = int(position)
    high = min(low + 1, len(values) - 1)
    weight = position - low
    return values[low] * (1.0 - weight) + values[high] * weight


def round2(value: float) -> float:
    """Round for artifact output; keeps replays and results small and diff-friendly."""
    return round(value + 0.0, 2)


def gini(values) -> float:
    """Gini coefficient of a non-negative distribution (0 = equal, 1 = maximally unequal)."""
    values = sorted(max(0.0, float(value)) for value in values)
    count = len(values)
    total = sum(values)
    if count == 0 or total <= 0:
        return 0.0
    weighted = sum((index + 1) * value for index, value in enumerate(values))
    return (2.0 * weighted) / (count * total) - (count + 1.0) / count
