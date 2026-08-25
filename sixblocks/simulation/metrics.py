"""Daily aggregates.

Everything here is computed from resident, business and block state. Aggregates are for
reading (dashboard, score, replay); they are never inputs to the simulation itself.
"""

from __future__ import annotations

from .state import City, Resident
from .util import clamp, gini, mean, median, percentile, round2


def welfare_index(resident: Resident) -> float:
    """A single 0-100 summary of how this person is actually doing."""
    return clamp(
        resident.mood * 0.3
        + resident.health * 0.24
        + resident.energy * 0.12
        + (100.0 - resident.stress) * 0.16
        + resident.social_connection * 0.08
        + resident.food_access * 0.06
        + resident.perceived_safety * 0.04
    )


def commute_penalty(city: City) -> float:
    residents = [r for r in city.active_residents if r.baseline_commute_minutes > 1.0]
    if not residents:
        return 0.0
    ratios = [r.current_commute_minutes / r.baseline_commute_minutes for r in residents]
    return clamp((mean(ratios) - 1.0) * 100.0, 0.0, 60.0)


def compute_metrics(city: City) -> dict:
    residents = city.active_residents
    open_businesses = [b for b in city.businesses.values() if b.open]
    all_businesses = list(city.businesses.values())
    workers = [r for r in residents if r.employment_status in ("employed", "hourly", "self_employed")]
    working_age = [r for r in residents if 19 <= r.age < 67]
    welfare = [welfare_index(r) for r in residents]
    burdens = [r.rent_burden for r in residents]
    rents = [h.monthly_rent for h in city.households.values() if h.displaced_on_day is None]

    mobility = clamp(mean(r.transit_access for r in residents) - commute_penalty(city) * 0.5)
    cleanliness = mean(block.cleanliness for block in city.block_list)
    business_health = clamp(
        (mean(b.health for b in open_businesses) if open_businesses else 0.0)
        * (len(open_businesses) / max(1, len(all_businesses)))
    )
    employment_rate = len(workers) / max(1, len(working_age))

    metrics = {
        "day": city.day,
        "population": len(residents),
        "budget": round2(city.budget),
        "upkeep_per_day": round2(city.upkeep_per_day),
        "total_spent": round2(city.total_spent),
        "average_mood": round2(mean(r.mood for r in residents)),
        "average_health": round2(mean(r.health for r in residents)),
        "average_stress": round2(mean(r.stress for r in residents)),
        "average_energy": round2(mean(r.energy for r in residents)),
        "average_welfare": round2(mean(welfare)),
        "welfare_bottom_quintile": round2(percentile(welfare, 0.2)),
        "welfare_gini": round2(gini(welfare) * 100.0),
        "median_rent": round2(median(rents)),
        "average_rent_burden": round2(mean(burdens)),
        "share_rent_burdened": round2(
            100.0 * sum(1 for value in burdens if value > 0.3) / max(1, len(burdens))
        ),
        "share_severely_burdened": round2(
            100.0 * sum(1 for value in burdens if value > 0.5) / max(1, len(burdens))
        ),
        "mobility": round2(mobility),
        "average_commute_minutes": round2(mean(r.current_commute_minutes for r in residents)),
        "cleanliness": round2(cleanliness),
        "business_health": round2(business_health),
        "businesses_open": len(open_businesses),
        "businesses_total": len(all_businesses),
        "employment_rate": round2(employment_rate * 100.0),
        "food_access": round2(mean(r.food_access for r in residents)),
        "recreation_access": round2(mean(r.recreation_access for r in residents)),
        "healthcare_access": round2(mean(r.healthcare_access for r in residents)),
        "perceived_safety": round2(mean(r.perceived_safety for r in residents)),
        "social_connection": round2(mean(r.social_connection for r in residents)),
        "displacements": city.displacements,
        "business_closures": city.business_closures,
        "subway_reliability": round2(city.subway_reliability),
        "event_day": bool(city.active_events),
        "active_events": [event.kind for event in city.active_events],
    }
    return metrics


def block_metrics(city: City) -> list[dict]:
    rows = []
    for block in city.block_list:
        residents = [city.residents[rid] for rid in block.resident_ids if not city.residents[rid].displaced]
        rows.append(
            {
                "block_id": block.id,
                "name": block.name,
                "population": len(residents),
                "average_mood": round2(mean(r.mood for r in residents)) if residents else 0.0,
                "average_welfare": round2(mean(welfare_index(r) for r in residents)) if residents else 0.0,
                "average_rent_burden": round2(mean(r.rent_burden for r in residents)) if residents else 0.0,
                "cleanliness": round2(block.cleanliness),
                "transit_access": round2(block.transit_access),
                "recreation_access": round2(block.recreation_access),
                "healthcare_access": round2(block.healthcare_access),
                "food_access": round2(block.food_access),
                "perceived_safety": round2(block.perceived_safety),
                "desirability": round2(block.desirability),
                "rent_index": round2(block.rent_index * 100.0) / 100.0,
                "foot_traffic": round2(block.foot_traffic),
                "investment_total": round2(block.investment_total),
            }
        )
    return rows
