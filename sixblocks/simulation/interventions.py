"""The twelve interventions a manager can fund.

Each intervention has an up-front cost, an optional daily upkeep, preconditions, and a
deterministic effect on primitive block state. Repeating the same intervention on the same
block has diminishing returns, so no single lever can be spammed to victory.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .state import Block, City
from .util import clamp


@dataclass(frozen=True)
class Intervention:
    name: str
    cost: float
    upkeep: float
    summary: str
    apply: Callable[[City, Block, float], str]
    precondition: Callable[[City, Block], str | None] | None = None


def _diminish(city: City, block: Block, name: str) -> float:
    """0.35^n-style falloff on the n-th repeat of ``name`` on this block."""
    previous = sum(1 for record in city.action_log
                   if record.accepted and record.action == name and record.target_id == block.id)
    return 1.0 / (1.0 + 0.7 * previous)


# --- effects ---------------------------------------------------------------

def _increase_trash_pickup(city: City, block: Block, scale: float) -> str:
    block.trash_service = clamp(block.trash_service + 26.0 * scale)
    block.cleanliness = clamp(block.cleanliness + 9.0 * scale)
    return f"Sanitation crews added on {block.name}"


def _add_bus_service(city: City, block: Block, scale: float) -> str:
    block.bus_frequency = clamp(block.bus_frequency + 24.0 * scale)
    return f"Bus service increased on {block.name}"


def _add_bike_capacity(city: City, block: Block, scale: float) -> str:
    block.bike_capacity = clamp(block.bike_capacity + 26.0 * scale)
    block.walkability = clamp(block.walkability + 3.0 * scale)
    return f"Bike lanes and racks added on {block.name}"


def _repair_playground(city: City, block: Block, scale: float) -> str:
    block.playground_quality = clamp(block.playground_quality + 34.0 * scale)
    block.greenery = clamp(block.greenery + 4.0 * scale)
    return f"Playground repaired on {block.name}"


def _build_small_park(city: City, block: Block, scale: float) -> str:
    block.has_park = True
    block.park_quality = clamp(max(block.park_quality, 30.0) + 36.0 * scale)
    block.greenery = clamp(block.greenery + 22.0 * scale)
    block.walkability = clamp(block.walkability + 4.0 * scale)
    return f"A small park opened on {block.name}"


def _open_cooling_center(city: City, block: Block, scale: float) -> str:
    block.cooling_center_days = max(block.cooling_center_days, 5)
    return f"Cooling center open on {block.name}"


def _fund_small_business(city: City, block: Block, scale: float) -> str:
    block.business_grant_days = max(block.business_grant_days, 12)
    touched = 0
    for business in sorted(city.businesses.values(), key=lambda b: b.id):
        if business.block_id != block.id or not business.open:
            continue
        business.cash += 5200.0 * scale
        business.quality = clamp(business.quality + 5.0 * scale)
        business.grant_days = max(business.grant_days, 12)
        touched += 1
    return f"Grants paid to {touched} business(es) on {block.name}"


def _give_rent_relief(city: City, block: Block, scale: float) -> str:
    block.rent_relief_days = max(block.rent_relief_days, 12)
    helped = 0
    for household in sorted(city.households.values(), key=lambda h: h.id):
        if household.block_id != block.id or household.displaced_on_day is not None:
            continue
        household.rent_relief_days = max(household.rent_relief_days, 12)
        household.months_behind = max(0.0, household.months_behind - 0.5 * scale)
        for resident_id in household.resident_ids:
            city.residents[resident_id].cash += 260.0 * scale
        helped += 1
    return f"Rent relief reached {helped} household(s) on {block.name}"


def _add_street_lighting(city: City, block: Block, scale: float) -> str:
    block.lighting = clamp(block.lighting + 30.0 * scale)
    return f"Street lighting improved on {block.name}"


def _fund_community_event(city: City, block: Block, scale: float) -> str:
    block.festival_days = max(block.festival_days, 3)
    for resident_id in block.resident_ids:
        resident = city.residents[resident_id]
        resident.social_connection = clamp(resident.social_connection + 9.0 * scale)
        resident.mood = clamp(resident.mood + 4.0 * scale)
    return f"Community event running on {block.name}"


def _improve_clinic_capacity(city: City, block: Block, scale: float) -> str:
    block.clinic_capacity = clamp(block.clinic_capacity + 26.0 * scale)
    if not block.has_clinic:
        block.has_clinic = True
        return f"A clinic annex opened on {block.name}"
    return f"Clinic capacity increased on {block.name}"


def _pedestrianize_street(city: City, block: Block, scale: float) -> str:
    block.pedestrianized = True
    block.walkability = clamp(block.walkability + 18.0 * scale)
    block.greenery = clamp(block.greenery + 6.0 * scale)
    return f"A street was pedestrianized on {block.name}"


# --- preconditions ---------------------------------------------------------

def _needs_playground(city: City, block: Block) -> str | None:
    if not block.has_playground:
        return f"{block.id} has no playground to repair"
    return None


def _needs_no_park(city: City, block: Block) -> str | None:
    if block.has_park and block.park_quality > 78.0:
        return f"{block.id} already has a well-maintained park"
    return None


def _needs_open_business(city: City, block: Block) -> str | None:
    if not any(b.block_id == block.id and b.open for b in city.businesses.values()):
        return f"{block.id} has no open businesses to fund"
    return None


def _needs_household(city: City, block: Block) -> str | None:
    if not any(h.block_id == block.id and h.displaced_on_day is None for h in city.households.values()):
        return f"{block.id} has no resident households"
    return None


def _needs_no_pedestrianization(city: City, block: Block) -> str | None:
    if block.pedestrianized:
        return f"{block.id} already has a pedestrianized street"
    return None


INTERVENTIONS: dict[str, Intervention] = {
    intervention.name: intervention
    for intervention in [
        Intervention("increase_trash_pickup", 9_000, 220,
                     "Add sanitation pickups. Raises cleanliness, which feeds safety and business traffic.",
                     _increase_trash_pickup),
        Intervention("add_bus_service", 26_000, 780,
                     "Increase bus frequency on a block. Helps bus-dependent commuters most.",
                     _add_bus_service),
        Intervention("add_bike_capacity", 14_000, 180,
                     "Add protected bike capacity and racks. Helps cyclists and walkability.",
                     _add_bike_capacity),
        Intervention("repair_playground", 22_000, 120,
                     "Repair an existing playground. Recreation for families with children.",
                     _repair_playground, _needs_playground),
        Intervention("build_small_park", 48_000, 320,
                     "Convert a lot into a small park. Recreation, shade and heat resilience.",
                     _build_small_park, _needs_no_park),
        Intervention("open_cooling_center", 11_000, 900,
                     "Open a temporary cooling center for several days. Protects heat-vulnerable residents.",
                     _open_cooling_center),
        Intervention("fund_small_business", 18_000, 0,
                     "Grants and rent offsets for local businesses. Keeps storefronts open.",
                     _fund_small_business, _needs_open_business),
        Intervention("give_rent_relief", 24_000, 0,
                     "Temporary rent relief for households on a block. Reduces displacement risk.",
                     _give_rent_relief, _needs_household),
        Intervention("add_street_lighting", 16_000, 210,
                     "Install street lighting. Raises perceived safety and evening foot traffic.",
                     _add_street_lighting),
        Intervention("fund_community_event", 8_000, 0,
                     "Fund a short street event. Builds social connection and business traffic.",
                     _fund_community_event),
        Intervention("improve_clinic_capacity", 34_000, 640,
                     "Expand clinic capacity. Improves healthcare access nearby, strongest on this block.",
                     _improve_clinic_capacity),
        Intervention("pedestrianize_street", 30_000, 260,
                     "Pedestrianize a street. Walkability, safety and local spending; slower for drivers.",
                     _pedestrianize_street, _needs_no_pedestrianization),
    ]
}

INTERVENTION_NAMES = sorted(INTERVENTIONS)


def action_catalog() -> list[dict]:
    """Player-facing catalog: names, costs and plain-language effects (never formulas)."""
    return [
        {
            "action": intervention.name,
            "cost": intervention.cost,
            "daily_upkeep": intervention.upkeep,
            "target": "block",
            "summary": intervention.summary,
        }
        for intervention in (INTERVENTIONS[name] for name in INTERVENTION_NAMES)
    ]


def check_precondition(city: City, name: str, block: Block) -> str | None:
    intervention = INTERVENTIONS[name]
    if intervention.precondition is None:
        return None
    return intervention.precondition(city, block)


def apply_intervention(city: City, name: str, block: Block) -> str:
    intervention = INTERVENTIONS[name]
    scale = _diminish(city, block, name)
    note = intervention.apply(city, block, scale)
    block.investment_total += intervention.cost
    block.upkeep_per_day += intervention.upkeep
    city.upkeep_per_day += intervention.upkeep
    if name not in block.interventions:
        block.interventions.append(name)
    return note
