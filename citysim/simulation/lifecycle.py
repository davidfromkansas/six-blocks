"""The daily lifecycle: decay, resident routines, mobility, businesses, housing.

Residents are the fundamental unit. Every aggregate the player sees is computed from
what actually happened to individual people today: how long their commute took, whether
they could reach food, whether they could pay rent, whether the park was usable.
"""

from __future__ import annotations

from .derive import FOOD_CATEGORIES, block_distance
from .rng import Rng
from .state import Business, City, Resident
from .util import approach, clamp

WORK_STATUSES = ("employed", "hourly", "self_employed")


# ---------------------------------------------------------------------------
# Decay: the neighborhood gets worse if nobody maintains it
# ---------------------------------------------------------------------------

def apply_decay(city: City) -> None:
    for block in city.block_list:
        # Sanitation: cleanliness drifts toward what the funded service level supports.
        load = 34.0 + len(block.resident_ids) * 0.55 + block.foot_traffic * 0.16
        supported = clamp(34.0 + block.trash_service * 1.35 - load * 0.5)
        block.cleanliness = clamp(approach(block.cleanliness, supported, 0.22))
        block.trash_service = clamp(block.trash_service - 0.45)

        block.bus_frequency = clamp(block.bus_frequency - 0.4)
        block.bike_capacity = clamp(block.bike_capacity - 0.25)
        block.lighting = clamp(block.lighting - 0.45)
        block.park_quality = clamp(block.park_quality - (0.6 if block.has_park else 0.2))
        block.playground_quality = clamp(block.playground_quality - (0.55 if block.has_playground else 0.2))
        block.greenery = clamp(block.greenery - 0.25)
        block.clinic_capacity = max(0.0, block.clinic_capacity - (0.5 if block.has_clinic else 0.0))

        for attribute in ("cooling_center_days", "rent_relief_days", "business_grant_days",
                          "festival_days", "construction_days", "outage_days", "flood_days"):
            setattr(block, attribute, max(0, getattr(block, attribute) - 1))

    city.subway_reliability = clamp(approach(city.subway_reliability, 92.0, 0.12))


def update_foot_traffic(city: City) -> None:
    for block in city.block_list:
        value = (
            block.desirability * 0.5
            + block.transit_access * 0.22
            + block.cleanliness * 0.12
            + len(block.resident_ids) * 0.35
        )
        if block.festival_days > 0:
            value += 22.0
        if block.pedestrianized:
            value += 9.0
        if block.flood_days > 0 or block.outage_days > 0:
            value -= 18.0
        block.foot_traffic = clamp(value)


# ---------------------------------------------------------------------------
# Mobility
# ---------------------------------------------------------------------------

def commute_factor(city: City, resident: Resident, heat: float, rng: Rng) -> float:
    block = city.blocks[resident.home_block_id]
    mode = resident.commute_mode
    factor = 1.0
    if mode == "subway":
        factor += (100.0 - city.subway_reliability) / 100.0 * 0.95
        factor += block.subway_distance * 0.04
    elif mode == "bus":
        factor += max(0.0, 58.0 - block.bus_frequency) / 58.0 * 0.7
        factor += block.construction_days > 0 and 0.12 or 0.0
    elif mode == "bike":
        factor += max(0.0, 45.0 - block.bike_capacity) / 45.0 * 0.4
        factor -= 0.06 if block.pedestrianized else 0.0
    elif mode == "walk":
        factor += max(0.0, 70.0 - block.walkability) / 70.0 * 0.32
    elif mode == "car":
        factor += 0.28 if block.construction_days > 0 else 0.0
        factor += 0.1 if block.pedestrianized else 0.0

    if block.flood_days > 0:
        factor += 0.22
    if block.construction_days > 0:
        factor += 0.1
    if heat > 0:
        factor += heat * 0.0015
    return factor * rng.uniform(0.97, 1.05)


# ---------------------------------------------------------------------------
# Shopping
# ---------------------------------------------------------------------------

def choose_business(city: City, resident: Resident, rng: Rng) -> Business | None:
    home = city.blocks[resident.home_block_id]
    price_sensitivity = resident.preferences.get("price_sensitivity", 0.5)
    best: Business | None = None
    best_score = -1e9
    for business in sorted(city.businesses.values(), key=lambda b: b.id):
        if not business.open or business.category not in FOOD_CATEGORIES:
            continue
        if business.customers_today >= business.capacity:
            continue
        other = city.blocks[business.block_id]
        distance = block_distance(home, other)
        score = (
            business.quality * 0.5
            - business.price_level * 34.0 * price_sensitivity
            - distance * (16.0 + 8.0 * (1.0 - resident.preferences.get("local_shopping", 0.5)))
            + other.walkability * 0.06
            + (5.0 if other.pedestrianized else 0.0)
            - (9.0 if other.flood_days > 0 or other.outage_days > 0 else 0.0)
            + rng.uniform(-6.0, 6.0)
        )
        if "mobility_limited" in resident.vulnerabilities:
            score -= distance * 14.0
        if score > best_score:
            best_score = score
            best = business
    return best


# ---------------------------------------------------------------------------
# Resident day
# ---------------------------------------------------------------------------

def run_resident_day(city: City, resident: Resident, rng: Rng, heat: float) -> None:
    block = city.blocks[resident.home_block_id]
    building = city.buildings[resident.home_building_id]
    household = city.households[resident.household_id]
    resident.last_day_notes = []

    # --- mobility -------------------------------------------------------
    factor = commute_factor(city, resident, heat, rng)
    resident.current_commute_minutes = round(resident.baseline_commute_minutes * factor, 1)
    delay = resident.current_commute_minutes - resident.baseline_commute_minutes
    transit_target = clamp(block.transit_access - delay * 0.8)
    resident.transit_access = clamp(approach(resident.transit_access, transit_target, 0.45))

    # --- income ---------------------------------------------------------
    daily_income = resident.annual_income / 365.0
    lost = 0.0
    if resident.employment_status == "hourly" and delay > 22.0:
        lost = daily_income * min(0.6, delay / 90.0)
        resident.days_missed_work += 1
        resident.last_day_notes.append("lost hours to a delayed commute")
    if resident.employment_status in WORK_STATUSES and resident.health < 35.0:
        lost += daily_income * 0.5
        resident.last_day_notes.append("too unwell to work a full day")
    resident.income_lost += lost
    resident.cash += daily_income - lost

    # --- food and errands ----------------------------------------------
    monthly_income = resident.annual_income / 12.0
    business = choose_business(city, resident, rng)
    if business is not None:
        spend = clamp(monthly_income * 0.075 / 30.0 * business.price_level, 5.0, 70.0)
        if resident.cash < spend * 2:
            spend *= 0.55
        resident.cash -= spend
        business.customers_today += 1
        business.revenue_today += spend
        resident.food_access = clamp(approach(resident.food_access, block.food_access + 8.0, 0.3))
        resident.days_food_insecure = max(0, resident.days_food_insecure - 1)
    else:
        resident.food_access = clamp(resident.food_access - 9.0)
        resident.days_food_insecure += 1
        resident.stress = clamp(resident.stress + 4.0)
        resident.last_day_notes.append("could not reach an open food store")

    # --- recreation and community --------------------------------------
    green_pref = resident.preferences.get("green_space", 0.5)
    resident.recreation_access = clamp(approach(resident.recreation_access, block.recreation_access, 0.3))
    social_target = (
        block.recreation_access * 0.35
        + block.foot_traffic * 0.14
        + (18.0 if block.festival_days > 0 else 0.0)
        + (8.0 if block.has_library else 0.0)
        + 26.0
    )
    resident.social_connection = clamp(approach(resident.social_connection, social_target, 0.16))

    # --- housing costs --------------------------------------------------
    daily_rent = resident.monthly_rent / 30.0
    if household.rent_relief_days > 0:
        daily_rent *= 0.55
    resident.cash -= daily_rent

    # --- environment and health ----------------------------------------
    heat_exposure = 0.0
    if heat > 0:
        cooling = 22.0 if block.cooling_center_days > 0 else 0.0
        shade = block.greenery * 0.18 + block.park_quality * 0.08
        heat_exposure = max(0.0, heat - cooling - shade)
        if "older_adult" in resident.vulnerabilities or "chronic_condition" in resident.vulnerabilities:
            heat_exposure *= 1.6
        if "young_child" in resident.vulnerabilities:
            heat_exposure *= 1.3

    resident.healthcare_access = clamp(approach(resident.healthcare_access, block.healthcare_access, 0.3))
    resident.perceived_safety = clamp(approach(resident.perceived_safety, block.perceived_safety, 0.3))

    stress_target = (
        22.0
        + max(0.0, resident.rent_burden - 0.3) * 95.0
        + delay * 0.55
        + max(0.0, 55.0 - block.cleanliness) * 0.22
        + max(0.0, 55.0 - resident.perceived_safety) * 0.2
        + max(0.0, 60.0 - resident.food_access) * 0.16
        + block.noise * 0.12 * resident.preferences.get("quiet", 0.5)
        + heat_exposure * 0.5
        - resident.social_connection * 0.16
        - resident.recreation_access * 0.1 * (0.5 + green_pref)
    )
    if resident.cash < 0:
        stress_target += 12.0
    resident.stress = clamp(approach(resident.stress, clamp(stress_target), 0.3))

    energy_target = (
        86.0
        - delay * 0.35
        - resident.stress * 0.3
        - heat_exposure * 0.5
        - max(0.0, 60.0 - building.quality) * 0.12
        + (4.0 if block.outage_days == 0 else -12.0)
    )
    resident.energy = clamp(approach(resident.energy, clamp(energy_target), 0.35))

    health_delta = (
        (resident.energy - 62.0) * 0.022
        - (resident.stress - 40.0) * 0.02
        - heat_exposure * 0.06
        + (resident.healthcare_access - 45.0) * 0.012
        + (resident.food_access - 55.0) * 0.01
    )
    if resident.days_food_insecure > 2:
        health_delta -= 0.35
    if resident.age >= 70 or "chronic_condition" in resident.vulnerabilities:
        health_delta -= 0.05
    resident.health = clamp(resident.health + health_delta, 5.0, 100.0)

    mood_target = (
        30.0
        + resident.social_connection * 0.2
        + resident.recreation_access * 0.16
        + resident.food_access * 0.1
        + resident.perceived_safety * 0.12
        + block.cleanliness * 0.12
        + resident.health * 0.12
        - resident.stress * 0.4
        - max(0.0, delay) * 0.3
        - max(0.0, resident.rent_burden - 0.35) * 55.0
    )
    if block.festival_days > 0:
        mood_target += 6.0
    resident.mood = clamp(approach(resident.mood, clamp(mood_target), 0.28))


# ---------------------------------------------------------------------------
# Businesses
# ---------------------------------------------------------------------------

def run_business_day(city: City, rng: Rng) -> list[str]:
    notes: list[str] = []
    for business in sorted(city.businesses.values(), key=lambda b: b.id):
        if not business.open:
            continue
        block = city.blocks[business.block_id]

        # Passers-by, on top of the residents who actually shopped here today.
        passers = max(0, int(block.foot_traffic * 0.22 + business.quality * 0.1 - 12.0))
        if block.festival_days > 0:
            passers = int(passers * 1.6)
        if block.outage_days > 0 or block.flood_days > 0:
            passers = int(passers * 0.35)
        passers = min(passers, max(0, business.capacity - business.customers_today))
        outside_spend = passers * clamp(14.0 * business.price_level, 6.0, 40.0) * rng.uniform(0.85, 1.15)
        business.customers_today += passers
        business.revenue_today += outside_spend

        expenses = 90.0 + business.capacity * 1.9 + len(business.employee_ids) * 105.0
        expenses *= 0.85 + block.rent_index * 0.35
        if business.grant_days > 0 or block.business_grant_days > 0:
            expenses *= 0.72
        margin = business.revenue_today - expenses
        business.cash += margin
        business.revenue_history.append(round(business.revenue_today, 2))
        if len(business.revenue_history) > 10:
            business.revenue_history.pop(0)

        utilization = business.customers_today / max(1, business.capacity)
        health_target = clamp(
            42.0
            + margin * 0.045
            + utilization * 34.0
            + (business.cash / 1200.0)
            + block.desirability * 0.12
            - 18.0
        )
        business.health = clamp(approach(business.health, health_target, 0.22))
        business.grant_days = max(0, business.grant_days - 1)

        if business.cash < -4500.0 or (business.health < 14.0 and business.cash < 500.0):
            business.open = False
            business.closed_on_day = city.day
            city.business_closures += 1
            notes.append(f"{business.name} closed on {block.name}")
            for employee_id in business.employee_ids:
                resident = city.residents.get(employee_id)
                if resident and resident.employment_status in WORK_STATUSES:
                    resident.employment_status = "unemployed"
                    resident.annual_income *= 0.35
                    resident.work_location = "none"
    return notes


# ---------------------------------------------------------------------------
# Housing and household finances
# ---------------------------------------------------------------------------

def run_housing_day(city: City, rng: Rng) -> list[str]:
    notes: list[str] = []
    for household in sorted(city.households.values(), key=lambda h: h.id):
        members = [city.residents[rid] for rid in household.resident_ids if not city.residents[rid].displaced]
        if not members:
            continue
        block = city.blocks[household.block_id]
        building = city.buildings[household.building_id]

        # Rents re-price slowly toward the block's rent index.
        target_rent = building.base_rent * block.rent_index * (1.0 + 0.16 * (len(members) - 1))
        household.monthly_rent = round(approach(household.monthly_rent, target_rent, 0.05), 2)
        household.rent_relief_days = max(household.rent_relief_days, block.rent_relief_days)
        household.rent_relief_days = max(0, household.rent_relief_days - 1)

        monthly_income = sum(member.annual_income for member in members) / 12.0
        effective_rent = household.monthly_rent * (0.55 if household.rent_relief_days > 0 else 1.0)
        burden = effective_rent / monthly_income if monthly_income > 0 else 1.6
        household.cash = round(sum(member.cash for member in members), 2)
        for member in members:
            member.monthly_rent = round(household.monthly_rent / len(members), 2)
            member.rent_burden = round(min(2.5, burden), 4)

        if household.cash < 0:
            household.months_behind += 1.0 / 30.0
        else:
            household.months_behind = max(0.0, household.months_behind - 1.0 / 45.0)

        at_risk = burden > 0.45 and household.months_behind > 0.3
        if at_risk and household.rent_relief_days == 0:
            risk = min(0.3, (burden - 0.45) * 0.4 + household.months_behind * 0.14)
            if rng.chance(risk):
                household.displaced_on_day = city.day
                for member in members:
                    member.displaced = True
                    member.displaced_on_day = city.day
                    if member.id in block.resident_ids:
                        block.resident_ids.remove(member.id)
                    city.displacements += 1
                building.vacant_units += 1
                if household.id in building.household_ids:
                    building.household_ids.remove(household.id)
                notes.append(f"A household was displaced from {block.name}")
    return notes


def reset_daily_counters(city: City) -> None:
    for business in city.businesses.values():
        business.customers_today = 0
        business.revenue_today = 0.0
