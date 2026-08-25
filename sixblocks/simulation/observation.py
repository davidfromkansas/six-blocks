"""Player-facing observations: the daily dashboard and the six inspection views.

Observations expose *state* — what is happening in the neighborhood — but never the
formulas that turn interventions into outcomes. A player has to learn the causal structure
by managing the place, the way a real manager would.
"""

from __future__ import annotations

from .events import forecasts
from .metrics import block_metrics, welfare_index
from .state import City
from .util import mean, round2

CRITICAL = 35.0
LOW = 48.0


def qualitative(value: float) -> str:
    if value >= 78.0:
        return "strong"
    if value >= 62.0:
        return "good"
    if value >= LOW:
        return "fair"
    if value >= CRITICAL:
        return "weak"
    return "critical"


def build_alerts(city: City, metrics: dict) -> list[str]:
    alerts: list[str] = []
    if metrics["cleanliness"] < CRITICAL:
        alerts.append("Sanitation is critical neighborhood-wide")
    if metrics["mobility"] < CRITICAL:
        alerts.append("Mobility is critical: commutes are badly degraded")
    if metrics["average_rent_burden"] > 0.42:
        alerts.append("Rent burden is severe across the neighborhood")
    if metrics["business_health"] < CRITICAL:
        alerts.append("Local businesses are failing")
    if metrics["average_health"] < 55.0:
        alerts.append("Resident health is deteriorating")
    if metrics["displacements"] > 0:
        alerts.append(f"{metrics['displacements']} resident(s) have been displaced so far")

    for block in city.block_list:
        if block.cleanliness < CRITICAL:
            alerts.append(f"{block.name}: streets are filthy")
        if block.transit_access < CRITICAL:
            alerts.append(f"{block.name}: transit access is critical")
        if block.perceived_safety < CRITICAL:
            alerts.append(f"{block.name}: residents feel unsafe")
        if block.recreation_access < CRITICAL:
            alerts.append(f"{block.name}: nowhere to go outside")
        if block.healthcare_access < CRITICAL:
            alerts.append(f"{block.name}: healthcare is out of reach")

    heat = [event for event in city.active_events if event.kind == "heat_wave"]
    if heat:
        uncovered = [block.name for block in city.block_list if block.cooling_center_days == 0]
        if uncovered:
            alerts.append("Heat wave with no cooling center on: " + ", ".join(uncovered))

    budget_committed = city.upkeep_per_day * max(0, city.total_days - city.day)
    if budget_committed > city.budget:
        alerts.append("Committed upkeep now exceeds the remaining budget")

    alerts.extend(forecasts(city))
    return alerts


def block_summary(city: City) -> list[dict]:
    rows = []
    for row in block_metrics(city):
        block = city.blocks[row["block_id"]]
        rows.append(
            {
                "block_id": row["block_id"],
                "name": row["name"],
                "population": row["population"],
                "average_mood": row["average_mood"],
                "average_rent_burden": row["average_rent_burden"],
                "cleanliness": row["cleanliness"],
                "transit_access": row["transit_access"],
                "recreation_access": row["recreation_access"],
                "healthcare_access": row["healthcare_access"],
                "food_access": row["food_access"],
                "perceived_safety": row["perceived_safety"],
                "worst_need": worst_need(city, block.id)[0],
                "active_conditions": active_conditions(city, block.id),
            }
        )
    return rows


NEED_FIELDS = [
    ("cleanliness", "cleanliness"),
    ("transit_access", "transit_access"),
    ("recreation_access", "recreation_access"),
    ("healthcare_access", "healthcare_access"),
    ("perceived_safety", "perceived_safety"),
    ("food_access", "food_access"),
]


def worst_need(city: City, block_id: str) -> tuple[str, float]:
    block = city.blocks[block_id]
    scored = [(field, getattr(block, field)) for _, field in NEED_FIELDS]
    field, value = min(scored, key=lambda pair: (pair[1], pair[0]))
    return field, value


def active_conditions(city: City, block_id: str) -> list[str]:
    block = city.blocks[block_id]
    conditions = []
    if block.construction_days:
        conditions.append("street_construction")
    if block.flood_days:
        conditions.append("flooding")
    if block.outage_days:
        conditions.append("power_outage")
    if block.festival_days:
        conditions.append("festival")
    if block.cooling_center_days:
        conditions.append("cooling_center_open")
    if block.rent_relief_days:
        conditions.append("rent_relief_active")
    if block.business_grant_days:
        conditions.append("business_grants_active")
    if block.pedestrianized:
        conditions.append("pedestrianized")
    return conditions


def dashboard(city: City, metrics: dict) -> dict:
    """The daily observation the player receives at the start of each day."""
    return {
        "type": "dashboard",
        "day": city.day,
        "days_remaining": max(0, city.total_days - city.day),
        "budget": round2(city.budget),
        "daily_upkeep": round2(city.upkeep_per_day),
        "action_points_remaining": city.action_points,
        "population": metrics["population"],
        "average_mood": metrics["average_mood"],
        "median_rent": metrics["median_rent"],
        "average_rent_burden": metrics["average_rent_burden"],
        "mobility": metrics["mobility"],
        "cleanliness": metrics["cleanliness"],
        "business_health": metrics["business_health"],
        "health": metrics["average_health"],
        "events": [
            {
                "kind": event.kind,
                "headline": event.headline,
                "block_ids": event.block_ids,
                "citywide": event.citywide,
                "days_remaining": event.days_remaining,
                "intensity": qualitative(100.0 - event.severity),
            }
            for event in city.active_events
        ],
        "alerts": build_alerts(city, metrics),
        "recent_changes": list(city.recent_changes),
        "blocks": block_summary(city),
    }


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

def inspect_city(city: City, metrics: dict) -> dict:
    return {
        "target_type": "city",
        "target_id": "city",
        "day": city.day,
        "metrics": metrics,
        "blocks": block_summary(city),
        "subway_reliability": round2(city.subway_reliability),
        "spent_by_block": {block.id: round2(block.investment_total) for block in city.block_list},
    }


def inspect_block(city: City, block_id: str) -> dict:
    block = city.blocks[block_id]
    residents = [city.residents[rid] for rid in block.resident_ids if not city.residents[rid].displaced]
    buildings = [city.buildings[bid] for bid in block.building_ids]
    field, value = worst_need(city, block_id)
    return {
        "target_type": "block",
        "target_id": block_id,
        "name": block.name,
        "population": len(residents),
        "households": sum(1 for h in city.households.values()
                          if h.block_id == block_id and h.displaced_on_day is None),
        "service_levels": {
            "cleanliness": round2(block.cleanliness),
            "sanitation_service": qualitative(block.trash_service),
            "bus_service": qualitative(block.bus_frequency),
            "bike_capacity": qualitative(block.bike_capacity),
            "walkability": round2(block.walkability),
            "street_lighting": qualitative(block.lighting),
            "park_quality": round2(block.park_quality),
            "playground_quality": round2(block.playground_quality),
            "clinic_capacity": round2(block.clinic_capacity),
            "greenery": round2(block.greenery),
        },
        "access": {
            "transit_access": round2(block.transit_access),
            "recreation_access": round2(block.recreation_access),
            "healthcare_access": round2(block.healthcare_access),
            "food_access": round2(block.food_access),
            "perceived_safety": round2(block.perceived_safety),
            "desirability": round2(block.desirability),
            "foot_traffic": round2(block.foot_traffic),
            "noise": round2(block.noise),
        },
        "housing": {
            "median_rent": round2(mean(h.monthly_rent for h in city.households.values()
                                       if h.block_id == block_id and h.displaced_on_day is None)),
            "average_rent_burden": round2(mean(r.rent_burden for r in residents)) if residents else 0.0,
            "rent_index": round2(block.rent_index * 100.0) / 100.0,
            "vacant_units": sum(b.vacant_units for b in buildings),
        },
        "residents_sample": [
            {
                "id": resident.id,
                "name": resident.name,
                "age": resident.age,
                "occupation": resident.occupation,
                "mood": round2(resident.mood),
                "rent_burden": resident.rent_burden,
                "commute_minutes": resident.current_commute_minutes,
            }
            for resident in sorted(residents, key=lambda r: r.id)[:8]
        ],
        "features": {
            "has_subway_entrance": block.has_subway_entrance,
            "has_clinic": block.has_clinic,
            "has_school": block.has_school,
            "has_library": block.has_library,
            "has_park": block.has_park,
            "has_playground": block.has_playground,
            "has_plaza": block.has_plaza,
            "pedestrianized": block.pedestrianized,
        },
        "active_conditions": active_conditions(city, block_id),
        "worst_need": {"field": field, "value": round2(value)},
        "interventions_funded": list(block.interventions),
        "investment_total": round2(block.investment_total),
        "buildings": [
            {"id": b.id, "label": b.label, "kind": b.kind, "business_id": b.business_id, "service": b.service}
            for b in buildings
        ],
    }


def inspect_resident(city: City, resident_id: str) -> dict:
    resident = city.residents[resident_id]
    return {
        "target_type": "resident",
        "target_id": resident_id,
        "name": resident.name,
        "age": resident.age,
        "household_id": resident.household_id,
        "home_building_id": resident.home_building_id,
        "home_block_id": resident.home_block_id,
        "occupation": resident.occupation,
        "employment_status": resident.employment_status,
        "annual_income": round2(resident.annual_income),
        "cash": round2(resident.cash),
        "monthly_rent": round2(resident.monthly_rent),
        "rent_burden": resident.rent_burden,
        "work_location": resident.work_location,
        "commute_mode": resident.commute_mode,
        "baseline_commute_minutes": resident.baseline_commute_minutes,
        "current_commute_minutes": resident.current_commute_minutes,
        "health": round2(resident.health),
        "energy": round2(resident.energy),
        "mood": round2(resident.mood),
        "stress": round2(resident.stress),
        "food_access": round2(resident.food_access),
        "transit_access": round2(resident.transit_access),
        "recreation_access": round2(resident.recreation_access),
        "healthcare_access": round2(resident.healthcare_access),
        "social_connection": round2(resident.social_connection),
        "perceived_safety": round2(resident.perceived_safety),
        "welfare": round2(welfare_index(resident)),
        "preferences": resident.preferences,
        "vulnerabilities": resident.vulnerabilities,
        "displaced": resident.displaced,
        "notes": resident.last_day_notes,
    }


def inspect_business(city: City, business_id: str) -> dict:
    business = city.businesses[business_id]
    return {
        "target_type": "business",
        "target_id": business_id,
        "name": business.name,
        "category": business.category,
        "block_id": business.block_id,
        "building_id": business.building_id,
        "open": business.open,
        "closed_on_day": business.closed_on_day,
        "health": round2(business.health),
        "cash": round2(business.cash),
        "customers_yesterday": business.customers_today,
        "revenue_recent": business.revenue_history[-5:],
        "capacity": business.capacity,
        "price_level": round2(business.price_level * 100.0) / 100.0,
        "quality": round2(business.quality),
        "employees": len(business.employee_ids),
        "grant_active": business.grant_days > 0,
    }


def inspect_transit(city: City) -> dict:
    modes: dict[str, int] = {}
    for resident in city.active_residents:
        modes[resident.commute_mode] = modes.get(resident.commute_mode, 0) + 1
    return {
        "target_type": "transit",
        "target_id": "transit",
        "subway_reliability": round2(city.subway_reliability),
        "subway_entrance_block": next(
            (block.id for block in city.block_list if block.has_subway_entrance), None
        ),
        "mode_split": modes,
        "average_commute_minutes": round2(mean(r.current_commute_minutes for r in city.active_residents)),
        "average_delay_minutes": round2(
            mean(r.current_commute_minutes - r.baseline_commute_minutes for r in city.active_residents)
        ),
        "blocks": [
            {
                "block_id": block.id,
                "name": block.name,
                "bus_service": qualitative(block.bus_frequency),
                "bike_capacity": qualitative(block.bike_capacity),
                "subway_distance_blocks": round2(block.subway_distance),
                "walkability": round2(block.walkability),
                "transit_access": round2(block.transit_access),
                "pedestrianized": block.pedestrianized,
            }
            for block in city.block_list
        ],
    }


def inspect_housing(city: City) -> dict:
    households = [h for h in city.households.values() if h.displaced_on_day is None]
    burdened = [h for h in households
                if any(city.residents[rid].rent_burden > 0.5 for rid in h.resident_ids)]
    return {
        "target_type": "housing",
        "target_id": "housing",
        "households": len(households),
        "severely_burdened_households": len(burdened),
        "displacements": city.displacements,
        "vacant_units": sum(b.vacant_units for b in city.buildings.values()),
        "blocks": [
            {
                "block_id": block.id,
                "name": block.name,
                "rent_index": round2(block.rent_index * 100.0) / 100.0,
                "median_rent": round2(mean(h.monthly_rent for h in households if h.block_id == block.id)),
                "average_rent_burden": round2(
                    mean(city.residents[rid].rent_burden
                         for h in households if h.block_id == block.id
                         for rid in h.resident_ids)
                ),
                "rent_relief_active": block.rent_relief_days > 0,
                "at_risk_households": sum(
                    1 for h in households
                    if h.block_id == block.id and h.months_behind > 0.3
                    and any(city.residents[rid].rent_burden > 0.5 for rid in h.resident_ids)
                ),
            }
            for block in city.block_list
        ],
    }
