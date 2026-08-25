"""Canonical simulation state.

These dataclasses *are* the neighborhood. The renderer, the observation builder and the
scorer all read from them; nothing outside :mod:`sixblocks.simulation` may mutate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class Block:
    """One of the six city blocks and every service level attached to it."""

    id: str
    name: str
    col: int
    row: int
    rect: Rect

    # Physical / service state, all 0-100 unless noted.
    cleanliness: float = 70.0
    trash_service: float = 50.0  # sanitation capacity; decays without funding
    bus_frequency: float = 40.0  # 0 = no service, 100 = very frequent
    bike_capacity: float = 20.0
    subway_distance: float = 1.0  # in blocks, from the neighborhood's subway entrance
    walkability: float = 60.0
    lighting: float = 55.0
    park_quality: float = 30.0
    playground_quality: float = 30.0
    clinic_capacity: float = 0.0  # only blocks with a clinic start above zero
    greenery: float = 25.0

    pedestrianized: bool = False
    has_subway_entrance: bool = False
    has_clinic: bool = False
    has_library: bool = False
    has_school: bool = False
    has_playground: bool = False
    has_park: bool = False
    has_plaza: bool = False

    # Temporary states, measured in remaining days.
    cooling_center_days: int = 0
    rent_relief_days: int = 0
    business_grant_days: int = 0
    festival_days: int = 0
    construction_days: int = 0
    outage_days: int = 0
    flood_days: int = 0

    # Derived each day.
    desirability: float = 50.0
    rent_index: float = 1.0
    foot_traffic: float = 50.0
    transit_access: float = 50.0
    recreation_access: float = 40.0
    healthcare_access: float = 40.0
    food_access: float = 60.0
    perceived_safety: float = 55.0
    noise: float = 30.0

    resident_ids: list[str] = field(default_factory=list)
    building_ids: list[str] = field(default_factory=list)

    # Bookkeeping for the dashboard and the score.
    investment_total: float = 0.0
    upkeep_per_day: float = 0.0
    interventions: list[str] = field(default_factory=list)


@dataclass
class Building:
    id: str
    block_id: str
    kind: str  # walkup | brownstone | tower | mixed_use | civic | open_space
    label: str
    rect: Rect
    floors: int
    units: int
    quality: float
    base_rent: float
    facade_hue: int
    business_id: str | None = None
    service: str | None = None  # clinic | school | library | park | playground | plaza
    household_ids: list[str] = field(default_factory=list)
    vacant_units: int = 0


@dataclass
class Business:
    id: str
    name: str
    category: str  # bodega | grocery | cafe | restaurant | pharmacy | laundromat | hardware
    building_id: str
    block_id: str
    price_level: float  # 0.7 cheap .. 1.4 expensive
    quality: float
    capacity: int
    cash: float
    health: float = 65.0
    open: bool = True
    closed_on_day: int | None = None
    customers_today: int = 0
    revenue_today: float = 0.0
    revenue_history: list[float] = field(default_factory=list)
    employee_ids: list[str] = field(default_factory=list)
    grant_days: int = 0


@dataclass
class Household:
    id: str
    building_id: str
    block_id: str
    resident_ids: list[str]
    monthly_rent: float
    cash: float
    rent_relief_days: int = 0
    months_behind: float = 0.0
    displaced_on_day: int | None = None


@dataclass
class Resident:
    id: str
    name: str
    age: int
    household_id: str
    home_building_id: str
    home_block_id: str

    occupation: str
    employment_status: str  # employed | hourly | self_employed | unemployed | retired | student
    annual_income: float
    cash: float
    monthly_rent: float
    rent_burden: float

    work_location: str  # block id, business id, or "outside_neighborhood"
    commute_mode: str  # subway | bus | bike | walk | car
    baseline_commute_minutes: float
    current_commute_minutes: float

    health: float
    energy: float
    mood: float
    stress: float

    food_access: float
    transit_access: float
    recreation_access: float
    healthcare_access: float
    social_connection: float
    perceived_safety: float

    preferences: dict = field(default_factory=dict)
    vulnerabilities: list[str] = field(default_factory=list)

    # Per-day scratch state, reset at the start of each day.
    days_food_insecure: int = 0
    days_missed_work: int = 0
    income_lost: float = 0.0
    displaced: bool = False
    displaced_on_day: int | None = None
    last_day_notes: list[str] = field(default_factory=list)


@dataclass
class ActiveEvent:
    id: str
    kind: str
    day_started: int
    days_remaining: int
    severity: float
    block_ids: list[str]
    headline: str
    citywide: bool = False


@dataclass
class ActionRecord:
    day: int
    action: str
    target_id: str
    cost: float
    accepted: bool
    note: str = ""


@dataclass
class City:
    """Root of the canonical state."""

    seed: int
    day: int
    total_days: int
    budget: float
    starting_budget: float
    action_points: int
    actions_per_day: int

    blocks: dict[str, Block]
    buildings: dict[str, Building]
    businesses: dict[str, Business]
    households: dict[str, Household]
    residents: dict[str, Resident]

    subway_reliability: float = 92.0
    active_events: list[ActiveEvent] = field(default_factory=list)
    event_schedule: dict[int, list[dict]] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)
    recent_changes: list[str] = field(default_factory=list)
    action_log: list[ActionRecord] = field(default_factory=list)
    daily_metrics: list[dict] = field(default_factory=list)
    upkeep_per_day: float = 0.0
    total_spent: float = 0.0
    displacements: int = 0
    business_closures: int = 0
    insolvent_days: int = 0
    finished: bool = False

    @property
    def block_list(self) -> list[Block]:
        return [self.blocks[key] for key in sorted(self.blocks)]

    @property
    def active_residents(self) -> list[Resident]:
        return [r for r in self.residents.values() if not r.displaced]
