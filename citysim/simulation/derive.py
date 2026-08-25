"""Derived block-level state.

Nothing here is a score: these are the intermediate "how good is this block at X today"
values that resident outcomes, business outcomes and rents all read from. They are
recomputed from primitive state every day, so an intervention on Monday is visible in
resident experience on Tuesday.
"""

from __future__ import annotations

from .state import Block, City
from .util import approach, clamp, mean

FOOD_CATEGORIES = {"bodega", "grocery", "bakery", "cafe", "restaurant"}


def block_distance(a: Block, b: Block) -> int:
    return abs(a.col - b.col) + abs(a.row - b.row)


def _transit_access(city: City, block: Block) -> float:
    subway = max(0.0, 100.0 - block.subway_distance * 18.0) * (0.55 + 0.45 * city.subway_reliability / 100.0)
    bus = clamp(block.bus_frequency * 1.2)
    bike = clamp(30.0 + block.bike_capacity * 0.7 + (8.0 if block.pedestrianized else 0.0))
    walk = block.walkability
    value = 0.38 * subway + 0.3 * bus + 0.14 * bike + 0.18 * walk
    if block.construction_days > 0:
        value -= 12.0
    if block.flood_days > 0:
        value -= 9.0
    return clamp(value)


def _recreation_access(block: Block) -> float:
    value = (
        block.park_quality * 0.36
        + block.playground_quality * 0.24
        + block.greenery * 0.16
        + (14.0 if block.has_plaza else 0.0)
        + (10.0 if block.has_library else 0.0)
        + (8.0 if block.pedestrianized else 0.0)
    )
    if block.festival_days > 0:
        value += 12.0
    return clamp(value)


def _healthcare_access(city: City, block: Block) -> float:
    total = 0.0
    for other in city.block_list:
        if other.clinic_capacity <= 0:
            continue
        distance = block_distance(block, other)
        total += other.clinic_capacity / (1.0 + 0.85 * distance)
    baseline = 26.0  # hospitals outside the neighborhood
    return clamp(baseline + total * 0.95)


def _food_access(city: City, block: Block) -> float:
    total = 0.0
    for business in city.businesses.values():
        if not business.open or business.category not in FOOD_CATEGORIES:
            continue
        other = city.blocks[business.block_id]
        distance = block_distance(block, other)
        weight = 1.0 / (1.0 + 0.9 * distance)
        grocery_bonus = 1.5 if business.category in ("grocery", "bodega") else 1.0
        total += weight * grocery_bonus * (0.6 + business.quality / 160.0)
    walk_bonus = block.walkability * 0.12
    return clamp(18.0 + total * 15.0 + walk_bonus)


def _perceived_safety(block: Block) -> float:
    value = (
        block.lighting * 0.44
        + block.cleanliness * 0.2
        + min(70.0, block.foot_traffic) * 0.22
        + (8.0 if block.pedestrianized else 0.0)
        + block.greenery * 0.08
    )
    if block.outage_days > 0:
        value -= 22.0
    return clamp(value)


def _desirability(block: Block) -> float:
    value = (
        block.cleanliness * 0.17
        + block.transit_access * 0.22
        + block.recreation_access * 0.14
        + block.perceived_safety * 0.15
        + block.food_access * 0.14
        + block.walkability * 0.1
        + block.healthcare_access * 0.08
    )
    value -= block.noise * 0.08
    if block.construction_days > 0:
        value -= 5.0
    return clamp(value)


def _noise(block: Block) -> float:
    value = 22.0 + (100.0 - block.walkability) * 0.08
    if block.construction_days > 0:
        value += 34.0
    if block.festival_days > 0:
        value += 16.0
    if block.pedestrianized:
        value -= 10.0
    value += max(0.0, block.bus_frequency - 60.0) * 0.15
    return clamp(value)


def update_derived(city: City) -> None:
    """Recompute every derived block field from primitive state."""
    for block in city.block_list:
        block.noise = _noise(block)
        block.transit_access = _transit_access(city, block)
        block.recreation_access = _recreation_access(block)
        block.healthcare_access = _healthcare_access(city, block)
        block.food_access = _food_access(city, block)
        block.perceived_safety = _perceived_safety(block)
        block.desirability = _desirability(block)


def update_rent_index(city: City) -> None:
    """Rents chase desirability slowly; that lag is what makes displacement a real risk."""
    for block in city.block_list:
        target = 0.72 + block.desirability / 145.0
        if block.rent_relief_days > 0:
            target -= 0.05
        block.rent_index = round(approach(block.rent_index, target, 0.06), 5)


def city_average(city: City, attribute: str) -> float:
    return mean(getattr(block, attribute) for block in city.block_list)
