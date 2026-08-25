"""Seeded city events.

The whole schedule is drawn from the episode seed before day 1, so an episode is
reproducible and events are never a function of what the player did. Every event kind
appears at least once per episode; extra draws add variety. Events propagate through
primitive state (reliability, sanitation capacity, rents, businesses), never by nudging an
aggregate metric directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .rng import Rng
from .state import ActiveEvent, City
from .util import clamp

EVENT_KINDS = [
    "heat_wave",
    "subway_disruption",
    "trash_backlog",
    "flash_flood",
    "street_construction",
    "rent_spike",
    "business_closure",
    "street_festival",
    "power_outage",
    "new_development",
]


@dataclass(frozen=True)
class EventSpec:
    kind: str
    citywide: bool
    min_days: int
    max_days: int
    min_severity: float
    max_severity: float
    blocks_affected: tuple[int, int]
    headline: str
    forecast: str | None
    on_start: Callable[[City, ActiveEvent], None] | None = None
    per_day: Callable[[City, ActiveEvent], None] | None = None


# --- effects ---------------------------------------------------------------

def _subway_start(city: City, event: ActiveEvent) -> None:
    city.subway_reliability = clamp(city.subway_reliability - event.severity)


def _subway_day(city: City, event: ActiveEvent) -> None:
    city.subway_reliability = clamp(min(city.subway_reliability, 100.0 - event.severity * 1.1))


def _trash_start(city: City, event: ActiveEvent) -> None:
    for block_id in event.block_ids:
        block = city.blocks[block_id]
        block.trash_service = clamp(block.trash_service - event.severity * 0.6)


def _trash_day(city: City, event: ActiveEvent) -> None:
    for block_id in event.block_ids:
        block = city.blocks[block_id]
        block.cleanliness = clamp(block.cleanliness - event.severity * 0.35)


def _flood_start(city: City, event: ActiveEvent) -> None:
    for block_id in event.block_ids:
        block = city.blocks[block_id]
        block.flood_days = max(block.flood_days, event.days_remaining)
        block.cleanliness = clamp(block.cleanliness - event.severity * 0.5)
        block.walkability = clamp(block.walkability - event.severity * 0.12)
        for business in city.businesses.values():
            if business.block_id == block_id and business.open:
                business.cash -= 900.0 + event.severity * 22.0


def _construction_start(city: City, event: ActiveEvent) -> None:
    for block_id in event.block_ids:
        block = city.blocks[block_id]
        block.construction_days = max(block.construction_days, event.days_remaining)


def _rent_spike_start(city: City, event: ActiveEvent) -> None:
    for block_id in event.block_ids:
        block = city.blocks[block_id]
        block.rent_index = round(block.rent_index * (1.0 + event.severity / 220.0), 5)
    for household in city.households.values():
        if household.block_id in event.block_ids:
            household.monthly_rent = round(household.monthly_rent * (1.0 + event.severity / 260.0), 2)


def _business_closure_start(city: City, event: ActiveEvent) -> None:
    candidates = [b for b in sorted(city.businesses.values(), key=lambda b: b.id)
                  if b.open and b.block_id in event.block_ids]
    if not candidates:
        return
    weakest = min(candidates, key=lambda b: (b.health, b.id))
    weakest.cash -= 3200.0 + event.severity * 40.0
    weakest.health = clamp(weakest.health - event.severity * 0.8)
    event.headline = f"A storefront on {city.blocks[weakest.block_id].name} is close to closing"


def _festival_start(city: City, event: ActiveEvent) -> None:
    for block_id in event.block_ids:
        block = city.blocks[block_id]
        block.festival_days = max(block.festival_days, event.days_remaining)


def _development_start(city: City, event: ActiveEvent) -> None:
    for block_id in event.block_ids:
        block = city.blocks[block_id]
        block.construction_days = max(block.construction_days, event.days_remaining)
        block.rent_index = round(block.rent_index * (1.0 + event.severity / 300.0), 5)
        block.greenery = clamp(block.greenery - event.severity * 0.15)


def _outage_start(city: City, event: ActiveEvent) -> None:
    for block_id in event.block_ids:
        block = city.blocks[block_id]
        block.outage_days = max(block.outage_days, event.days_remaining)


def _outage_day(city: City, event: ActiveEvent) -> None:
    for block_id in event.block_ids:
        for business in city.businesses.values():
            if business.block_id == block_id and business.open:
                business.cash -= 420.0


EVENT_SPECS: dict[str, EventSpec] = {
    spec.kind: spec
    for spec in [
        EventSpec("heat_wave", True, 2, 5, 26.0, 58.0, (6, 6),
                  "A heat wave is settling over the neighborhood",
                  "Forecast: dangerous heat expected tomorrow"),
        EventSpec("subway_disruption", True, 1, 3, 18.0, 42.0, (6, 6),
                  "Subway service is disrupted", None, _subway_start, _subway_day),
        EventSpec("trash_backlog", False, 2, 4, 22.0, 48.0, (1, 3),
                  "Sanitation pickups are backed up", None, _trash_start, _trash_day),
        EventSpec("flash_flood", False, 1, 2, 24.0, 52.0, (1, 2),
                  "A flash flood hit low-lying streets", None, _flood_start),
        EventSpec("street_construction", False, 3, 6, 20.0, 40.0, (1, 1),
                  "Street reconstruction has started", "Notice: street work begins tomorrow",
                  _construction_start),
        EventSpec("rent_spike", False, 1, 1, 18.0, 46.0, (1, 3),
                  "Rents jumped after new listings hit the market", None, _rent_spike_start),
        EventSpec("business_closure", False, 1, 1, 20.0, 45.0, (1, 1),
                  "A local business is in trouble", None, _business_closure_start),
        EventSpec("street_festival", False, 2, 3, 20.0, 40.0, (1, 1),
                  "A street festival is happening", "Notice: a street festival starts tomorrow",
                  _festival_start),
        EventSpec("power_outage", False, 1, 2, 22.0, 45.0, (1, 2),
                  "A power outage is affecting the block", None, _outage_start, _outage_day),
        EventSpec("new_development", False, 3, 5, 20.0, 45.0, (1, 1),
                  "A new development broke ground", "Notice: a new development breaks ground tomorrow",
                  _development_start),
    ]
}


def build_schedule(seed: int, total_days: int, block_ids: list[str]) -> dict[int, list[dict]]:
    """Draw the event schedule for the whole episode from the seed."""
    rng = Rng(seed).derive("events")
    # Every kind appears once; then a few extra draws for texture.
    draws = list(EVENT_KINDS) + [rng.choice(EVENT_KINDS) for _ in range(rng.randint(2, 5))]
    draws = rng.shuffled(draws)

    # Spread the events across days 2..total_days-1 (day 1 is a clean read of the city).
    usable_days = list(range(2, max(3, total_days)))
    schedule: dict[int, list[dict]] = {}
    for kind in draws:
        spec = EVENT_SPECS[kind]
        day = rng.choice(usable_days)
        count = rng.randint(*spec.blocks_affected)
        if spec.citywide:
            targets = list(block_ids)
        else:
            targets = sorted(rng.shuffled(list(block_ids))[:count])
        schedule.setdefault(day, []).append(
            {
                "kind": kind,
                "days": rng.randint(spec.min_days, spec.max_days),
                "severity": round(rng.uniform(spec.min_severity, spec.max_severity), 2),
                "block_ids": targets,
            }
        )
    return schedule


def start_events_for_day(city: City) -> list[str]:
    """Activate everything scheduled for ``city.day`` and return log lines."""
    notes: list[str] = []
    for index, entry in enumerate(city.event_schedule.get(city.day, [])):
        spec = EVENT_SPECS[entry["kind"]]
        event = ActiveEvent(
            id=f"evt_d{city.day:02d}_{index}",
            kind=entry["kind"],
            day_started=city.day,
            days_remaining=entry["days"],
            severity=entry["severity"],
            block_ids=list(entry["block_ids"]),
            headline=spec.headline,
            citywide=spec.citywide,
        )
        if spec.on_start:
            spec.on_start(city, event)
        city.active_events.append(event)
        scope = "neighborhood-wide" if spec.citywide else ", ".join(
            city.blocks[block_id].name for block_id in event.block_ids
        )
        notes.append(f"{event.headline} ({scope})")
    return notes


def apply_active_events(city: City) -> None:
    for event in city.active_events:
        spec = EVENT_SPECS[event.kind]
        if spec.per_day:
            spec.per_day(city, event)


def expire_events(city: City) -> list[str]:
    notes: list[str] = []
    remaining: list[ActiveEvent] = []
    for event in city.active_events:
        event.days_remaining -= 1
        if event.days_remaining > 0:
            remaining.append(event)
        else:
            notes.append(f"Ended: {event.headline}")
    city.active_events = remaining
    return notes


def current_heat(city: City) -> float:
    """Effective heat stress today (0 when there is no heat wave)."""
    return max((event.severity for event in city.active_events if event.kind == "heat_wave"), default=0.0)


def forecasts(city: City) -> list[str]:
    """Player-visible warnings for tomorrow, where a real city would have advance notice."""
    lines: list[str] = []
    for entry in city.event_schedule.get(city.day + 1, []):
        spec = EVENT_SPECS[entry["kind"]]
        if not spec.forecast:
            continue
        if spec.citywide:
            lines.append(spec.forecast)
        else:
            names = ", ".join(city.blocks[block_id].name for block_id in entry["block_ids"])
            lines.append(f"{spec.forecast} ({names})")
    return lines
