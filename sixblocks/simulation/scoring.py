"""Multidimensional scoring.

Nine dimensions, each normalized to 0-100, then weighted into a single 0-100 score. Each
dimension blends the *final* day with the *trajectory* across the episode, so a manager
who lets the neighborhood suffer for three weeks and then buys a good final day does not
score like one who kept people well the whole time.
"""

from __future__ import annotations

from .state import City
from .util import clamp, mean, round2

WEIGHTS = {
    "resident_welfare": 0.20,
    "affordability": 0.13,
    "mobility": 0.12,
    "health": 0.12,
    "cleanliness": 0.07,
    "economic_health": 0.12,
    "equity": 0.12,
    "fiscal_sustainability": 0.06,
    "resilience": 0.06,
}

FINAL_SHARE = 0.55  # the rest is the episode trajectory


def _blend(final_value: float, series: list[float]) -> float:
    return clamp(FINAL_SHARE * final_value + (1.0 - FINAL_SHARE) * mean(series))


def _affordability(row: dict) -> float:
    return clamp(
        100.0
        - row["share_severely_burdened"] * 0.75
        - max(0.0, row["average_rent_burden"] - 0.30) * 120.0
    )


def _economic(row: dict) -> float:
    open_share = 100.0 * row["businesses_open"] / max(1, row["businesses_total"])
    return clamp(0.55 * row["business_health"] + 0.25 * row["employment_rate"] + 0.20 * open_share)


def _equity(row: dict, population_start: int) -> float:
    displacement_penalty = min(35.0, 100.0 * row["displacements"] / max(1, population_start) * 2.2)
    return clamp(
        0.55 * row["welfare_bottom_quintile"]
        + 0.45 * clamp(100.0 - row["welfare_gini"] * 2.2)
        - displacement_penalty
    )


def _fiscal(city: City) -> float:
    ratio = city.budget / max(1.0, city.starting_budget)
    if city.budget < 0:
        score = clamp(28.0 + ratio * 120.0, 0.0, 28.0)
    elif ratio <= 0.18:
        score = 100.0
    else:
        score = clamp(100.0 - (ratio - 0.18) * 165.0)
    score -= min(30.0, city.insolvent_days * 4.0)
    committed = city.upkeep_per_day * max(0, city.total_days - city.day)
    if committed > max(0.0, city.budget):
        score -= 12.0
    return clamp(score)


def _resilience(series: list[float]) -> float:
    if not series:
        return 0.0
    average = mean(series)
    if average <= 0:
        return 0.0
    worst = min(series)
    late = mean(series[-5:])
    early = mean(series[:5])
    recovery = clamp(100.0 + (late - early) * 3.0, 0.0, 100.0)
    return clamp(0.5 * (worst / average) * 100.0 + 0.3 * recovery + 0.2 * clamp(average))


def score_episode(city: City) -> dict:
    history = city.daily_metrics
    if not history:
        raise ValueError("cannot score an episode with no recorded days")
    final = history[-1]
    population_start = history[0]["population"]

    welfare_series = [row["average_welfare"] for row in history]
    components = {
        "resident_welfare": _blend(final["average_welfare"], welfare_series),
        "affordability": _blend(_affordability(final), [_affordability(row) for row in history]),
        "mobility": _blend(final["mobility"], [row["mobility"] for row in history]),
        "health": _blend(final["average_health"], [row["average_health"] for row in history]),
        "cleanliness": _blend(final["cleanliness"], [row["cleanliness"] for row in history]),
        "economic_health": _blend(_economic(final), [_economic(row) for row in history]),
        "equity": _blend(
            _equity(final, population_start),
            [_equity(row, population_start) for row in history],
        ),
        "fiscal_sustainability": _fiscal(city),
        "resilience": _resilience(welfare_series),
    }

    total = sum(WEIGHTS[key] * value for key, value in components.items())
    final_score = clamp(total)

    return {
        "final_score": round2(final_score),
        "components": {key: round2(value) for key, value in components.items()},
        "weights": dict(WEIGHTS),
        "headline": {
            "population_start": population_start,
            "population_end": final["population"],
            "displacements": final["displacements"],
            "business_closures": final["business_closures"],
            "businesses_open": final["businesses_open"],
            "businesses_total": final["businesses_total"],
            "average_mood_end": final["average_mood"],
            "average_welfare_end": final["average_welfare"],
            "median_rent_end": final["median_rent"],
            "average_rent_burden_end": final["average_rent_burden"],
            "budget_remaining": round2(city.budget),
            "total_spent": round2(city.total_spent),
            "interventions_funded": sum(1 for record in city.action_log if record.accepted),
        },
    }
