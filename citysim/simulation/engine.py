"""The episode engine: the only object that advances canonical state.

Determinism contract:
  * same seed                        -> identical initial state
  * same seed + same action sequence -> identical trajectory, results and replay

All randomness is drawn from generators derived from the seed and the day number, so the
number of times a caller inspects state can never change the simulation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import events as events_module
from . import lifecycle, observation
from .derive import update_derived, update_rent_index
from .interventions import INTERVENTIONS, action_catalog, apply_intervention, check_precondition
from .metrics import block_metrics, compute_metrics, welfare_index
from .rng import Rng, mix64
from .scoring import WEIGHTS, score_episode
from .state import ActionRecord, City
from .util import round2
from .world import BLOCK_ORDER, WORLD_H, WORLD_W, generate_city

INSPECT_TARGETS = ("city", "block", "resident", "business", "transit", "housing")


@dataclass
class ActionResult:
    ok: bool
    payload: dict


def new_seed() -> int:
    """A fresh episode seed when the caller did not supply one."""
    return mix64(int(time.time_ns())) & 0xFFFFFFFF


class Episode:
    def __init__(
        self,
        seed: int | None = None,
        total_days: int = 30,
        budget: float = 500_000.0,
        actions_per_day: int = 3,
        target_population: int = 100,
    ) -> None:
        self.seed = int(seed) if seed is not None else new_seed()
        self.city: City = generate_city(
            self.seed,
            total_days=total_days,
            budget=budget,
            actions_per_day=actions_per_day,
            target_population=target_population,
        )
        self.city.event_schedule = events_module.build_schedule(self.seed, total_days, BLOCK_ORDER)
        update_derived(self.city)
        lifecycle.update_foot_traffic(self.city)
        update_derived(self.city)
        self.frames: list[dict] = []
        self.day_notes: list[str] = []
        self.log: list[dict] = []
        self.city.recent_changes = ["Day 1: you have taken over management of the neighborhood."]
        started = events_module.start_events_for_day(self.city)
        self.city.recent_changes.extend(started)

    # -- read-only views ---------------------------------------------------

    @property
    def finished(self) -> bool:
        return self.city.finished

    def metrics(self) -> dict:
        return compute_metrics(self.city)

    def dashboard(self) -> dict:
        return observation.dashboard(self.city, self.metrics())

    def handshake(self) -> dict:
        city = self.city
        return {
            "type": "welcome",
            "game": "citysim",
            "protocol_version": 1,
            "seed": self.seed,
            "total_days": city.total_days,
            "actions_per_day": city.actions_per_day,
            "starting_budget": round2(city.starting_budget),
            "blocks": [
                {"block_id": block.id, "name": block.name, "col": block.col, "row": block.row}
                for block in city.block_list
            ],
            "actions": action_catalog(),
            "inspect_targets": list(INSPECT_TARGETS),
            "message_types": ["inspect", "action", "end_day"],
            "score_dimensions": list(WEIGHTS),
        }

    def inspect(self, target_type: str, target_id: str | None) -> ActionResult:
        if target_type not in INSPECT_TARGETS:
            return ActionResult(False, self._error("unknown_target_type",
                                                   f"target_type must be one of {list(INSPECT_TARGETS)}"))
        try:
            if target_type == "city":
                payload = observation.inspect_city(self.city, self.metrics())
            elif target_type == "transit":
                payload = observation.inspect_transit(self.city)
            elif target_type == "housing":
                payload = observation.inspect_housing(self.city)
            elif target_type == "block":
                if target_id not in self.city.blocks:
                    return ActionResult(False, self._error("unknown_target", f"no block {target_id!r}"))
                payload = observation.inspect_block(self.city, target_id)
            elif target_type == "resident":
                if target_id not in self.city.residents:
                    return ActionResult(False, self._error("unknown_target", f"no resident {target_id!r}"))
                payload = observation.inspect_resident(self.city, target_id)
            else:  # business
                if target_id not in self.city.businesses:
                    return ActionResult(False, self._error("unknown_target", f"no business {target_id!r}"))
                payload = observation.inspect_business(self.city, target_id)
        except KeyError as error:  # defensive: never let an inspection kill the episode
            return ActionResult(False, self._error("unknown_target", str(error)))
        payload = dict(payload)
        payload["type"] = "inspection"
        payload["day"] = self.city.day
        return ActionResult(True, payload)

    # -- actions -----------------------------------------------------------

    def submit_action(self, action: str, target_id: str | None) -> ActionResult:
        city = self.city
        if city.finished:
            return ActionResult(False, self._error("episode_finished", "the episode is over"))
        if action not in INTERVENTIONS:
            return ActionResult(False, self._error("unknown_action", f"no intervention named {action!r}"))
        if target_id not in city.blocks:
            return ActionResult(False, self._error("unknown_target",
                                                   f"target_id must be a block id, got {target_id!r}"))
        intervention = INTERVENTIONS[action]
        block = city.blocks[target_id]

        if city.action_points <= 0:
            return ActionResult(False, self._error("no_action_points",
                                                   "no action points left today; send end_day"))
        if intervention.cost > city.budget:
            return ActionResult(False, self._error(
                "insufficient_budget",
                f"{action} costs {intervention.cost:.0f} but only {city.budget:.0f} remains",
            ))
        failure = check_precondition(city, action, block)
        if failure:
            return ActionResult(False, self._error("precondition_failed", failure))

        note = apply_intervention(city, action, block)
        city.budget -= intervention.cost
        city.total_spent += intervention.cost
        city.action_points -= 1
        city.action_log.append(ActionRecord(city.day, action, target_id, intervention.cost, True, note))
        self.day_notes.append(note)
        return ActionResult(True, {
            "type": "action_result",
            "accepted": True,
            "day": city.day,
            "action": action,
            "target_id": target_id,
            "cost": intervention.cost,
            "daily_upkeep": intervention.upkeep,
            "budget": round2(city.budget),
            "action_points_remaining": city.action_points,
            "note": note,
        })

    def _error(self, code: str, message: str) -> dict:
        return {
            "type": "error",
            "code": code,
            "message": message,
            "day": self.city.day,
            "budget": round2(self.city.budget),
            "action_points_remaining": self.city.action_points,
        }

    # -- day advance -------------------------------------------------------

    def end_day(self, reason: str = "player") -> dict:
        if self.city.finished:
            return {"type": "episode_finished", "day": self.city.day}
        city = self.city
        day = city.day
        rng = Rng(mix64(self.seed ^ (day * 0x9E3779B1))).derive(f"day:{day}")
        notes: list[str] = list(self.day_notes)
        self.day_notes = []

        # 1. Upkeep is charged before anything else; unfunded upkeep degrades services.
        city.budget -= city.upkeep_per_day
        if city.budget < 0:
            city.insolvent_days += 1
            notes.append("Budget is overdrawn: service levels are slipping")
            for block in city.block_list:
                block.trash_service = max(0.0, block.trash_service - 1.2)
                block.bus_frequency = max(0.0, block.bus_frequency - 1.0)
                block.lighting = max(0.0, block.lighting - 0.8)

        # 2. Today's funded interventions are already in primitive state; refresh derived
        #    values so residents experience them today.
        update_derived(city)
        lifecycle.update_foot_traffic(city)

        # 3. Events act, then people live their day.
        events_module.apply_active_events(city)
        update_derived(city)
        heat = events_module.current_heat(city)
        lifecycle.reset_daily_counters(city)
        for resident in sorted(city.active_residents, key=lambda r: r.id):
            lifecycle.run_resident_day(city, resident, rng.derive(f"res:{resident.id}"), heat)

        notes.extend(lifecycle.run_business_day(city, rng.derive("business")))
        notes.extend(lifecycle.run_housing_day(city, rng.derive("housing")))

        # 4. End-of-day physical decay, then events age out.
        lifecycle.apply_decay(city)
        notes.extend(events_module.expire_events(city))

        # 5. Recompute everything the player and the score read.
        update_derived(city)
        update_rent_index(city)
        lifecycle.update_foot_traffic(city)
        update_derived(city)

        metrics = compute_metrics(city)
        city.daily_metrics.append(metrics)
        self.frames.append(self.frame(metrics, notes, reason))
        self.log.append({
            "seed": self.seed,
            "day": day,
            "end_day_reason": reason,
            "actions": [
                {"action": record.action, "target_id": record.target_id, "cost": record.cost}
                for record in city.action_log if record.day == day and record.accepted
            ],
            "events": [event.kind for event in city.active_events],
            "budget": round2(city.budget),
            "average_mood": metrics["average_mood"],
            "average_health": metrics["average_health"],
            "mobility": metrics["mobility"],
            "cleanliness": metrics["cleanliness"],
            "business_health": metrics["business_health"],
            "displacements": metrics["displacements"],
        })

        # 6. Roll the calendar.
        city.recent_changes = notes[-12:]
        if day >= city.total_days:
            city.finished = True
            return {"type": "episode_finished", "day": day, "results": self.results()}

        city.day = day + 1
        city.action_points = city.actions_per_day
        started = events_module.start_events_for_day(city)
        if started:
            city.recent_changes.extend(started)
        return {"type": "day_advanced", "day": city.day, "notes": city.recent_changes}

    # -- artifacts ---------------------------------------------------------

    def frame(self, metrics: dict, notes: list[str], reason: str = "player") -> dict:
        city = self.city
        return {
            "day": metrics["day"],
            "end_day_reason": reason,
            "budget": round2(city.budget),
            "upkeep_per_day": round2(city.upkeep_per_day),
            "metrics": metrics,
            "notes": notes[-12:],
            "actions": [
                {"action": record.action, "target_id": record.target_id, "cost": record.cost}
                for record in city.action_log
                if record.accepted and record.day == metrics["day"]
            ],
            "events": [
                {
                    "kind": event.kind,
                    "block_ids": event.block_ids,
                    "citywide": event.citywide,
                    "severity": round2(event.severity),
                    "headline": event.headline,
                }
                for event in city.active_events
            ],
            "blocks": [
                {
                    **row,
                    "conditions": observation.active_conditions(city, row["block_id"]),
                    "greenery": round2(city.blocks[row["block_id"]].greenery),
                    "lighting": round2(city.blocks[row["block_id"]].lighting),
                    "park_quality": round2(city.blocks[row["block_id"]].park_quality),
                    "playground_quality": round2(city.blocks[row["block_id"]].playground_quality),
                    "pedestrianized": city.blocks[row["block_id"]].pedestrianized,
                    "bus_frequency": round2(city.blocks[row["block_id"]].bus_frequency),
                    "bike_capacity": round2(city.blocks[row["block_id"]].bike_capacity),
                    "noise": round2(city.blocks[row["block_id"]].noise),
                }
                for row in block_metrics(city)
            ],
            "businesses": [
                {
                    "id": business.id,
                    "block_id": business.block_id,
                    "building_id": business.building_id,
                    "open": business.open,
                    "health": round2(business.health),
                    "customers": business.customers_today,
                    "revenue": round2(business.revenue_today),
                }
                for business in sorted(city.businesses.values(), key=lambda b: b.id)
            ],
            "residents": [
                {
                    "id": resident.id,
                    "block_id": resident.home_block_id,
                    "building_id": resident.home_building_id,
                    "mood": round2(resident.mood),
                    "health": round2(resident.health),
                    "stress": round2(resident.stress),
                    "welfare": round2(welfare_index(resident)),
                    "commute": resident.current_commute_minutes,
                    "mode": resident.commute_mode,
                    "displaced": resident.displaced,
                }
                for resident in sorted(city.residents.values(), key=lambda r: r.id)
            ],
        }

    def snapshot(self) -> dict:
        """Live view payload: the last simulated frame plus the current dashboard."""
        return {
            "type": "state",
            "seed": self.seed,
            "day": self.city.day,
            "total_days": self.city.total_days,
            "finished": self.city.finished,
            "world": self.world(),
            "dashboard": self.dashboard(),
            "frame": self.frames[-1] if self.frames else self.frame(self.metrics(), [], "initial"),
            "results": self.results() if self.city.finished else None,
        }

    def world(self) -> dict:
        """Static geometry and labels the renderer needs once."""
        city = self.city
        return {
            "width": WORLD_W,
            "height": WORLD_H,
            "seed": self.seed,
            "blocks": [
                {
                    "id": block.id,
                    "name": block.name,
                    "col": block.col,
                    "row": block.row,
                    "rect": block.rect.to_dict(),
                    "has_subway_entrance": block.has_subway_entrance,
                }
                for block in city.block_list
            ],
            "buildings": [
                {
                    "id": building.id,
                    "block_id": building.block_id,
                    "kind": building.kind,
                    "label": building.label,
                    "rect": building.rect.to_dict(),
                    "floors": building.floors,
                    "units": building.units,
                    "quality": round2(building.quality),
                    "facade_hue": building.facade_hue,
                    "business_id": building.business_id,
                    "service": building.service,
                }
                for building in sorted(city.buildings.values(), key=lambda b: b.id)
            ],
            "businesses": [
                {
                    "id": business.id,
                    "name": business.name,
                    "category": business.category,
                    "block_id": business.block_id,
                    "building_id": business.building_id,
                }
                for business in sorted(city.businesses.values(), key=lambda b: b.id)
            ],
            "residents": [
                {
                    "id": resident.id,
                    "name": resident.name,
                    "age": resident.age,
                    "occupation": resident.occupation,
                    "home_building_id": resident.home_building_id,
                    "home_block_id": resident.home_block_id,
                    "commute_mode": resident.commute_mode,
                    "work_location": resident.work_location,
                }
                for resident in sorted(city.residents.values(), key=lambda r: r.id)
            ],
        }

    def results(self) -> dict:
        score = score_episode(self.city)
        city = self.city
        return {
            "game": "citysim",
            "seed": self.seed,
            "days_simulated": len(city.daily_metrics),
            "total_days": city.total_days,
            "score": score["final_score"],
            "scores": [score["final_score"]],
            "components": score["components"],
            "weights": score["weights"],
            "headline": score["headline"],
            "daily_metrics": city.daily_metrics,
            "actions": [
                {
                    "day": record.day,
                    "action": record.action,
                    "target_id": record.target_id,
                    "cost": record.cost,
                    "note": record.note,
                }
                for record in city.action_log if record.accepted
            ],
            "events": [
                {"day": day, "events": [entry["kind"] for entry in entries]}
                for day, entries in sorted(city.event_schedule.items())
            ],
            "blocks_final": block_metrics(city),
        }

    def replay(self) -> dict:
        return {
            "format": "citysim_replay",
            "version": 1,
            "seed": self.seed,
            "world": self.world(),
            "frames": self.frames,
            "results": self.results() if self.city.daily_metrics else None,
        }
