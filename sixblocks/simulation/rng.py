"""Deterministic pseudo-random number generation.

Every stochastic choice in Six Blocks flows through :class:`Rng`. The algorithm is
splitmix64, implemented in explicit 64-bit integer arithmetic so results are identical
on every platform and Python version. Never use :mod:`random` or wall-clock state in
simulation code.
"""

from __future__ import annotations

MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


def mix64(value: int) -> int:
    """Return a well-distributed 64-bit hash of ``value``."""
    z = value & MASK64
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9 & MASK64
    z = (z ^ (z >> 27)) * 0x94D049BB133111EB & MASK64
    return (z ^ (z >> 31)) & MASK64


def hash_string(text: str) -> int:
    """Stable 64-bit hash of a string (FNV-1a, then mixed)."""
    acc = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        acc = ((acc ^ byte) * 0x100000001B3) & MASK64
    return mix64(acc)


class Rng:
    """A splitmix64 generator with a small, explicit API."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & MASK64

    @property
    def state(self) -> int:
        return self._state

    def next_u64(self) -> int:
        self._state = (self._state + _GOLDEN) & MASK64
        return mix64(self._state)

    def derive(self, label: str) -> Rng:
        """A new independent generator, deterministically derived from this one's seed."""
        return Rng(mix64(self._state ^ hash_string(label)))

    def random(self) -> float:
        """Uniform float in ``[0, 1)`` with 53 bits of resolution."""
        return (self.next_u64() >> 11) * (1.0 / (1 << 53))

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.random()

    def randint(self, low: int, high: int) -> int:
        """Uniform integer in the inclusive range ``[low, high]``."""
        if high < low:
            raise ValueError("high must be >= low")
        span = high - low + 1
        return low + self.next_u64() % span

    def chance(self, probability: float) -> bool:
        return self.random() < probability

    def choice(self, items: list):
        if not items:
            raise ValueError("cannot choose from an empty sequence")
        return items[self.next_u64() % len(items)]

    def weighted_choice(self, items: list, weights: list[float]):
        if len(items) != len(weights):
            raise ValueError("items and weights must be the same length")
        total = sum(weights)
        if total <= 0:
            raise ValueError("weights must sum to a positive value")
        target = self.random() * total
        cumulative = 0.0
        for item, weight in zip(items, weights):
            cumulative += weight
            if target < cumulative:
                return item
        return items[-1]

    def shuffled(self, items: list) -> list:
        """Fisher-Yates on a copy, so the caller's list is untouched."""
        result = list(items)
        for index in range(len(result) - 1, 0, -1):
            swap = self.next_u64() % (index + 1)
            result[index], result[swap] = result[swap], result[index]
        return result

    def normal(self, mean: float, stdev: float) -> float:
        """Approximately normal deviate via the sum of twelve uniforms (Irwin-Hall)."""
        total = sum(self.random() for _ in range(12)) - 6.0
        return mean + stdev * total
