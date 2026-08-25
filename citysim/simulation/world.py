"""Deterministic world generation: geometry, buildings, businesses, households, residents.

The neighborhood is a fictional six-block grid. No real parcel geometry, addresses or
resident records are used; every building and person here is invented by this generator
from the episode seed.
"""

from __future__ import annotations

from .names import BLOCK_NAMES, business_name, full_name
from .rng import Rng
from .state import Block, Building, Business, City, Household, Rect, Resident
from .util import clamp

# ---------------------------------------------------------------------------
# Geometry (world units; the renderer maps these 1:1 to canvas pixels at zoom 1)
# ---------------------------------------------------------------------------

BLOCK_W = 360.0
BLOCK_H = 260.0
STREET_W = 64.0
MARGIN_X = 48.0
MARGIN_Y = 120.0
WORLD_W = MARGIN_X * 2 + BLOCK_W * 3 + STREET_W * 2
WORLD_H = MARGIN_Y + BLOCK_H * 2 + STREET_W + 96.0

LOT_COLS = 4
LOT_ROWS = 2

# Lots are packed edge to edge along each street frontage: a block is a
# continuous streetwall of party-walled buildings around a shared rear yard,
# the way a real one is, not detached volumes sitting on lawn. Frontage is
# divided between the row's buildings by kind; depth is fixed per row.
LOT_DEPTH = 108.0
REAR_YARD = BLOCK_H - LOT_DEPTH * 2  # light well / back gardens between the rows
FRONTAGE_WEIGHT = {
    "tower": 1.15,
    "walkup": 1.0,
    "brownstone": 0.82,
    "mixed_use": 1.05,
    "civic": 1.45,
    "open_space": 1.0,
}

BLOCK_ORDER = ["block_a", "block_b", "block_c", "block_d", "block_e", "block_f"]
BLOCK_GRID = {
    "block_a": (0, 0),
    "block_b": (1, 0),
    "block_c": (2, 0),
    "block_d": (0, 1),
    "block_e": (1, 1),
    "block_f": (2, 1),
}

# Units of housing by building kind.
UNITS_BY_KIND = {"tower": 6, "walkup": 3, "brownstone": 2, "mixed_use": 2, "civic": 0, "open_space": 0}
FLOORS_BY_KIND = {"tower": 11, "walkup": 5, "brownstone": 4, "mixed_use": 4, "civic": 2, "open_space": 0}
BASE_RENT_BY_KIND = {"tower": 2650.0, "walkup": 1850.0, "brownstone": 2200.0, "mixed_use": 1750.0}

# lot index -> (kind, label, service, business_category)
BLOCK_PLAN: dict[str, list[tuple[int, str, str, str | None, str | None]]] = {
    "block_a": [
        (0, "walkup", "Marlow Walk-up A", None, None),
        (1, "walkup", "Marlow Walk-up B", None, None),
        (2, "brownstone", "Marlow Brownstone", None, None),
        (4, "mixed_use", "Marlow Corner", None, "bodega"),
        (5, "mixed_use", "Marlow Storefront", None, "restaurant"),
    ],
    "block_b": [
        (0, "civic", "Halden Public School", "school", None),
        (1, "tower", "Halden Tower", None, None),
        (2, "mixed_use", "Halden Storefront", None, "cafe"),
        (5, "open_space", "Halden Playground", "playground", None),
    ],
    "block_c": [
        (0, "tower", "Kestrel Tower", None, None),
        (1, "walkup", "Kestrel Walk-up", None, None),
        (2, "mixed_use", "Kestrel Corner", None, "pharmacy"),
        (4, "mixed_use", "Kestrel Storefront", None, "bakery"),
    ],
    "block_d": [
        (0, "brownstone", "Ashgrove Brownstone A", None, None),
        (1, "brownstone", "Ashgrove Brownstone B", None, None),
        (2, "walkup", "Ashgrove Walk-up", None, None),
        (4, "mixed_use", "Ashgrove Market Building", None, "grocery"),
        (5, "open_space", "Ashgrove Community Garden", "park", None),
    ],
    "block_e": [
        (0, "civic", "Fenner Community Clinic", "clinic", None),
        (1, "civic", "Fenner Branch Library", "library", None),
        (2, "walkup", "Fenner Walk-up", None, None),
        (4, "mixed_use", "Fenner Storefront", None, "laundromat"),
    ],
    "block_f": [
        (0, "tower", "Sable Tower", None, None),
        (1, "walkup", "Sable Walk-up A", None, None),
        (2, "walkup", "Sable Walk-up B", None, None),
        (4, "mixed_use", "Sable Corner", None, "bodega"),
        (5, "open_space", "Sable Plaza", "plaza", None),
    ],
}

# Starting service levels that differ per block. Everything else uses the Block defaults.
BLOCK_START = {
    "block_a": {"cleanliness": 66.0, "trash_service": 48.0, "bus_frequency": 42.0, "lighting": 52.0,
                "subway_distance": 1.0, "walkability": 62.0, "rent_index": 0.98},
    "block_b": {"cleanliness": 72.0, "trash_service": 55.0, "bus_frequency": 55.0, "lighting": 62.0,
                "subway_distance": 0.6, "walkability": 68.0, "rent_index": 1.05},
    "block_c": {"cleanliness": 74.0, "trash_service": 58.0, "bus_frequency": 60.0, "lighting": 66.0,
                "subway_distance": 0.1, "walkability": 72.0, "rent_index": 1.16},
    "block_d": {"cleanliness": 60.0, "trash_service": 42.0, "bus_frequency": 30.0, "lighting": 44.0,
                "subway_distance": 1.8, "walkability": 54.0, "rent_index": 0.9},
    "block_e": {"cleanliness": 64.0, "trash_service": 46.0, "bus_frequency": 36.0, "lighting": 50.0,
                "subway_distance": 1.4, "walkability": 58.0, "rent_index": 0.94},
    "block_f": {"cleanliness": 55.0, "trash_service": 38.0, "bus_frequency": 24.0, "lighting": 38.0,
                "subway_distance": 2.2, "walkability": 48.0, "rent_index": 0.85},
}

# occupation -> (income_low, income_high, status_weights)
OCCUPATIONS: list[tuple[str, float, float, str]] = [
    ("home health aide", 34000, 46000, "hourly"),
    ("nurse", 78000, 104000, "employed"),
    ("teacher", 58000, 82000, "employed"),
    ("line cook", 32000, 44000, "hourly"),
    ("barista", 28000, 38000, "hourly"),
    ("retail clerk", 30000, 42000, "hourly"),
    ("delivery cyclist", 26000, 40000, "hourly"),
    ("bus operator", 60000, 78000, "employed"),
    ("warehouse worker", 36000, 50000, "hourly"),
    ("custodian", 34000, 46000, "hourly"),
    ("security guard", 36000, 48000, "hourly"),
    ("hairdresser", 33000, 52000, "self_employed"),
    ("tailor", 32000, 48000, "self_employed"),
    ("shop owner", 38000, 72000, "self_employed"),
    ("musician", 22000, 46000, "self_employed"),
    ("graphic designer", 52000, 82000, "self_employed"),
    ("software developer", 105000, 165000, "employed"),
    ("accountant", 72000, 96000, "employed"),
    ("paralegal", 54000, 70000, "employed"),
    ("social worker", 48000, 64000, "employed"),
    ("EMT", 46000, 62000, "employed"),
    ("dental hygienist", 62000, 80000, "employed"),
    ("mechanic", 44000, 62000, "employed"),
    ("librarian", 52000, 68000, "employed"),
    ("chef", 48000, 72000, "employed"),
    ("building super", 42000, 58000, "employed"),
]

OCCUPATION_WEIGHTS = [
    3.0, 2.2, 2.0, 2.6, 2.4, 2.8, 2.2, 1.4, 2.2, 2.0, 1.8, 1.4, 1.0, 1.6, 1.2,
    1.4, 1.0, 1.0, 1.2, 1.4, 1.0, 0.9, 1.2, 0.8, 1.0, 1.0,
]

CATEGORY_PROFILE = {
    # category -> (price_level, capacity, base_cash, quality_range)
    "bodega": (0.9, 70, 12000.0, (55.0, 72.0)),
    "grocery": (1.0, 110, 26000.0, (58.0, 76.0)),
    "cafe": (1.15, 55, 14000.0, (60.0, 80.0)),
    "bakery": (1.0, 60, 12000.0, (58.0, 78.0)),
    "restaurant": (1.2, 65, 20000.0, (58.0, 80.0)),
    "pharmacy": (1.05, 60, 22000.0, (60.0, 78.0)),
    "laundromat": (0.95, 45, 10000.0, (50.0, 70.0)),
}


def block_lot_rects(block_rect: Rect, plan: list[tuple]) -> dict[int, Rect]:
    """Pack a block's plan into two party-walled street frontages.

    Lot indices below ``LOT_COLS`` face the north street, the rest face the south
    street. Within a row the block width is divided between the buildings by
    :data:`FRONTAGE_WEIGHT`, with no side gaps, so neighbours share party walls and
    the row runs corner to corner. Purely visual: nothing in the simulation reads
    these rectangles.
    """
    rects: dict[int, Rect] = {}
    for row in range(LOT_ROWS):
        entries = [entry for entry in plan if entry[0] // LOT_COLS == row]
        if not entries:
            continue
        weights = [FRONTAGE_WEIGHT.get(entry[1], 1.0) for entry in entries]
        total = sum(weights)
        y = block_rect.y if row == 0 else block_rect.y + block_rect.h - LOT_DEPTH
        cursor = block_rect.x
        for entry, weight in zip(entries, weights, strict=True):
            width = block_rect.w * weight / total
            rects[entry[0]] = Rect(cursor, y, width, LOT_DEPTH)
            cursor += width
    return rects


def _make_blocks() -> dict[str, Block]:
    blocks: dict[str, Block] = {}
    for block_id in BLOCK_ORDER:
        col, row = BLOCK_GRID[block_id]
        rect = Rect(
            MARGIN_X + col * (BLOCK_W + STREET_W),
            MARGIN_Y + row * (BLOCK_H + STREET_W),
            BLOCK_W,
            BLOCK_H,
        )
        block = Block(id=block_id, name=BLOCK_NAMES[block_id], col=col, row=row, rect=rect)
        for key, value in BLOCK_START[block_id].items():
            setattr(block, key, value)
        blocks[block_id] = block
    blocks["block_c"].has_subway_entrance = True
    return blocks


def _make_buildings(city_rng: Rng, blocks: dict[str, Block]) -> tuple[dict[str, Building], dict[str, Business]]:
    buildings: dict[str, Building] = {}
    businesses: dict[str, Business] = {}
    building_seq = 0
    business_seq = 0

    for block_id in BLOCK_ORDER:
        block = blocks[block_id]
        rng = city_rng.derive(f"buildings:{block_id}")
        rects = block_lot_rects(block.rect, BLOCK_PLAN[block_id])
        for lot_index, kind, label, service, category in BLOCK_PLAN[block_id]:
            building_seq += 1
            building_id = f"bld_{building_seq:02d}"
            rect = rects[lot_index]
            quality = clamp(rng.normal(62.0, 9.0), 30.0, 92.0)
            floors = FLOORS_BY_KIND[kind]
            if kind in ("walkup", "brownstone", "mixed_use"):
                floors = max(3, floors + rng.randint(-1, 1))
            elif kind == "tower":
                floors = floors + rng.randint(-2, 4)
            units = UNITS_BY_KIND[kind]
            base_rent = BASE_RENT_BY_KIND.get(kind, 0.0)
            building = Building(
                id=building_id,
                block_id=block_id,
                kind=kind,
                label=label,
                rect=rect,
                floors=floors,
                units=units,
                quality=quality,
                base_rent=base_rent * (0.9 + quality / 500.0),
                facade_hue=rng.randint(0, 359),
                service=service,
                vacant_units=units,
            )
            buildings[building_id] = building
            block.building_ids.append(building_id)

            if service == "clinic":
                block.has_clinic = True
                block.clinic_capacity = 45.0
            elif service == "library":
                block.has_library = True
            elif service == "school":
                block.has_school = True
            elif service == "playground":
                block.has_playground = True
                block.playground_quality = 42.0
            elif service == "park":
                block.has_park = True
                block.park_quality = 40.0
                block.greenery = 55.0
            elif service == "plaza":
                block.has_plaza = True
                block.recreation_access = 45.0

            if category:
                business_seq += 1
                business_id = f"biz_{business_seq:02d}"
                price_level, capacity, base_cash, quality_range = CATEGORY_PROFILE[category]
                businesses[business_id] = Business(
                    id=business_id,
                    name=business_name(rng, category),
                    category=category,
                    building_id=building_id,
                    block_id=block_id,
                    price_level=price_level * rng.uniform(0.94, 1.07),
                    quality=rng.uniform(*quality_range),
                    capacity=capacity + rng.randint(-8, 10),
                    cash=base_cash * rng.uniform(0.75, 1.2),
                    health=rng.uniform(55.0, 72.0),
                )
                building.business_id = business_id
    return buildings, businesses


def _household_size(rng: Rng) -> int:
    return rng.weighted_choice([1, 2, 3, 4, 5], [0.30, 0.30, 0.20, 0.13, 0.07])


def _pick_occupation(rng: Rng) -> tuple[str, float, str]:
    index = rng.weighted_choice(list(range(len(OCCUPATIONS))), OCCUPATION_WEIGHTS)
    name, low, high, status = OCCUPATIONS[index]
    income = rng.uniform(low, high)
    return name, income, status


def _commute_mode(rng: Rng, block: Block, works_locally: bool, prefers_bike: bool) -> str:
    if works_locally:
        return rng.weighted_choice(["walk", "bike", "bus"], [0.7, 0.2, 0.1])
    weights = {
        "subway": max(0.1, 2.4 - block.subway_distance * 0.7),
        "bus": 0.5 + block.bus_frequency / 90.0,
        "bike": 0.9 if prefers_bike else 0.25,
        "walk": 0.18,
        "car": 0.3,
    }
    modes = list(weights)
    return rng.weighted_choice(modes, [weights[mode] for mode in modes])


def _populate(city_rng: Rng, blocks: dict[str, Block], buildings: dict[str, Building],
              businesses: dict[str, Business], target_population: int
              ) -> tuple[dict[str, Household], dict[str, Resident]]:
    rng = city_rng.derive("population")
    households: dict[str, Household] = {}
    residents: dict[str, Resident] = {}

    residential = [b for b in buildings.values() if b.units > 0]
    # Deterministic unit list: building order, then unit index.
    unit_slots: list[Building] = []
    for building in sorted(residential, key=lambda b: b.id):
        unit_slots.extend([building] * building.units)
    unit_slots = rng.shuffled(unit_slots)

    household_seq = 0
    resident_seq = 0
    population = 0
    for building in unit_slots:
        if population >= target_population:
            break
        size = _household_size(rng)
        household_seq += 1  # noqa: SIM113 - counter only advances for funded households
        household_id = f"hh_{household_seq:03d}"
        block = blocks[building.block_id]
        rent = building.base_rent * block.rent_index * (1.0 + 0.16 * (size - 1)) * rng.uniform(0.92, 1.1)
        household = Household(
            id=household_id,
            building_id=building.id,
            block_id=building.block_id,
            resident_ids=[],
            monthly_rent=round(rent, 2),
            cash=0.0,
        )

        adults = max(1, size - (1 if size >= 3 and rng.chance(0.7) else 0) - (1 if size >= 4 and rng.chance(0.5) else 0))
        for member in range(size):
            resident_seq += 1
            resident_id = f"res_{resident_seq:03d}"
            is_adult = member < adults
            if is_adult:
                age = rng.randint(19, 78)
            else:
                age = rng.randint(2, 18)

            occupation, income, status = _pick_occupation(rng)
            if age >= 67 and rng.chance(0.75):
                occupation, status = "retired", "retired"
                income = rng.uniform(19000, 34000)
            elif age < 19:
                occupation, status = "student", "student"
                income = 0.0
            elif rng.chance(0.07):
                status = "unemployed"
                income = income * rng.uniform(0.18, 0.35)

            works_locally = False
            work_location = "outside_neighborhood"
            if status in ("employed", "hourly", "self_employed") and rng.chance(0.34):
                open_businesses = sorted(businesses.values(), key=lambda b: b.id)
                target = rng.choice(open_businesses)
                if len(target.employee_ids) < 5:
                    target.employee_ids.append(resident_id)
                    work_location = target.id
                    works_locally = True
            elif status in ("retired", "unemployed", "student"):
                work_location = "none" if status != "student" else block.id

            prefers_bike = rng.chance(0.3)
            mode = "walk" if status in ("retired", "unemployed", "student") else _commute_mode(
                rng, block, works_locally, prefers_bike
            )
            base_commute = {
                "subway": rng.uniform(28, 52) + block.subway_distance * 6,
                "bus": rng.uniform(26, 46) + max(0.0, (60 - block.bus_frequency)) * 0.25,
                "bike": rng.uniform(16, 34),
                "walk": rng.uniform(8, 26),
                "car": rng.uniform(22, 44),
                "none": 0.0,
            }[mode if mode in ("subway", "bus", "bike", "walk", "car") else "walk"]
            if works_locally:
                base_commute = rng.uniform(5, 14)
            if status in ("retired", "unemployed"):
                base_commute = rng.uniform(0, 8)

            share = income / max(1.0, sum(1 for _ in range(size)))
            resident = Resident(
                id=resident_id,
                name=full_name(rng),
                age=age,
                household_id=household_id,
                home_building_id=building.id,
                home_block_id=building.block_id,
                occupation=occupation,
                employment_status=status,
                annual_income=round(income, 2),
                cash=round(max(120.0, rng.normal(1400.0, 900.0) + income * 0.012), 2),
                monthly_rent=0.0,  # filled in after the household total is known
                rent_burden=0.0,
                work_location=work_location,
                commute_mode=mode,
                baseline_commute_minutes=round(base_commute, 1),
                current_commute_minutes=round(base_commute, 1),
                health=clamp(rng.normal(76.0, 10.0) - max(0, age - 60) * 0.25, 25.0, 99.0),
                energy=clamp(rng.normal(72.0, 9.0), 25.0, 99.0),
                mood=clamp(rng.normal(66.0, 11.0), 15.0, 96.0),
                stress=clamp(rng.normal(36.0, 12.0), 2.0, 92.0),
                food_access=clamp(rng.normal(62.0, 10.0), 10.0, 95.0),
                transit_access=50.0,
                recreation_access=40.0,
                healthcare_access=45.0,
                social_connection=clamp(rng.normal(58.0, 13.0), 10.0, 95.0),
                perceived_safety=clamp(rng.normal(58.0, 12.0), 10.0, 95.0),
                preferences={
                    "green_space": round(rng.uniform(0.2, 1.0), 3),
                    "quiet": round(rng.uniform(0.1, 1.0), 3),
                    "transit": round(rng.uniform(0.3, 1.0), 3),
                    "local_shopping": round(rng.uniform(0.2, 1.0), 3),
                    "price_sensitivity": round(rng.uniform(0.2, 1.0), 3),
                    "cycling": round(1.0 if prefers_bike else rng.uniform(0.0, 0.4), 3),
                },
                vulnerabilities=[],
            )
            del share

            if age >= 70:
                resident.vulnerabilities.append("older_adult")
            if age <= 12:
                resident.vulnerabilities.append("young_child")
            if rng.chance(0.11):
                resident.vulnerabilities.append("chronic_condition")
            if rng.chance(0.08):
                resident.vulnerabilities.append("mobility_limited")
            if mode in ("subway", "bus") and not works_locally:
                resident.vulnerabilities.append("transit_dependent")
            if status in ("hourly",):
                resident.vulnerabilities.append("hourly_wage")

            residents[resident_id] = resident
            household.resident_ids.append(resident_id)
            blocks[building.block_id].resident_ids.append(resident_id)
            population += 1

        households[household_id] = household
        building.household_ids.append(household_id)
        building.vacant_units = max(0, building.vacant_units - 1)

        household_income = sum(residents[rid].annual_income for rid in household.resident_ids)
        household.cash = round(max(300.0, household_income * rng.uniform(0.02, 0.09)), 2)
        for rid in household.resident_ids:
            resident = residents[rid]
            resident.monthly_rent = round(household.monthly_rent / len(household.resident_ids), 2)
            monthly_income = household_income / 12.0
            resident.rent_burden = round(household.monthly_rent / monthly_income, 4) if monthly_income > 0 else 1.5

    return households, residents


def generate_city(seed: int, total_days: int = 30, budget: float = 500_000.0,
                  actions_per_day: int = 3, target_population: int = 100) -> City:
    """Build the day-0 neighborhood for ``seed``. Identical seeds give identical cities."""
    city_rng = Rng(seed)
    blocks = _make_blocks()
    buildings, businesses = _make_buildings(city_rng, blocks)
    households, residents = _populate(city_rng, blocks, buildings, businesses, target_population)

    city = City(
        seed=seed,
        day=1,
        total_days=total_days,
        budget=budget,
        starting_budget=budget,
        action_points=actions_per_day,
        actions_per_day=actions_per_day,
        blocks=blocks,
        buildings=buildings,
        businesses=businesses,
        households=households,
        residents=residents,
    )
    return city
