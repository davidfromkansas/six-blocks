"""Scripted policies.

A policy sees exactly what an AI player sees: the daily dashboard JSON. It returns an
ordered list of candidate interventions; the driver walks the list and funds the first
ones that are accepted, so a rejected candidate (precondition, budget) never wastes a day.

`balanced_baseline` is the certification baseline: always legal, deterministic, finishes
every episode, and sets a meaningful floor for AI players to beat.
"""

from __future__ import annotations

from ..simulation.rng import Rng, hash_string

Candidate = dict  # {"action": str, "target_id": str}

NEED_TO_ACTION = {
    "cleanliness": "increase_trash_pickup",
    "transit_access": "add_bus_service",
    "recreation_access": "build_small_park",
    "healthcare_access": "improve_clinic_capacity",
    "perceived_safety": "add_street_lighting",
    "food_access": "fund_small_business",
}


class Policy:
    name = "policy"

    def __init__(self, seed: int = 0) -> None:
        self.rng = Rng(hash_string(f"{self.name}:{seed}"))
        self.catalog: dict[str, dict] = {}
        self.history: dict[tuple[str, str], int] = {}

    def on_welcome(self, welcome: dict) -> None:
        self.catalog = {entry["action"]: entry for entry in welcome.get("actions", [])}

    def note_accepted(self, action: str, target_id: str) -> None:
        key = (action, target_id)
        self.history[key] = self.history.get(key, 0) + 1

    def cost(self, action: str) -> float:
        entry = self.catalog.get(action)
        return float(entry["cost"]) if entry else 0.0

    def affordable(self, action: str, dashboard: dict, reserve: float = 0.0) -> bool:
        return self.cost(action) <= dashboard["budget"] - reserve

    def plan(self, dashboard: dict) -> list[Candidate]:  # pragma: no cover - interface
        raise NotImplementedError


class DoNothing(Policy):
    name = "do_nothing"

    def plan(self, dashboard: dict) -> list[Candidate]:
        return []


class RandomLegal(Policy):
    name = "random_legal"

    def plan(self, dashboard: dict) -> list[Candidate]:
        actions = sorted(self.catalog)
        blocks = [row["block_id"] for row in dashboard["blocks"]]
        if not actions or not blocks:
            return []
        candidates = []
        for _ in range(9):
            action = self.rng.choice(actions)
            if not self.affordable(action, dashboard):
                continue
            candidates.append({"action": action, "target_id": self.rng.choice(blocks)})
        return candidates


class SpendEverythingImmediately(Policy):
    name = "spend_everything_immediately"

    def plan(self, dashboard: dict) -> list[Candidate]:
        if dashboard["day"] > 4:
            return []
        blocks = [row["block_id"] for row in dashboard["blocks"]]
        # Most expensive affordable interventions first, cycling through blocks.
        actions = sorted(self.catalog, key=lambda name: -self.cost(name))
        candidates: list[Candidate] = []
        for index, action in enumerate(actions):
            if not self.affordable(action, dashboard):
                continue
            candidates.append({"action": action, "target_id": blocks[index % len(blocks)]})
        return candidates


class SingleLever(Policy):
    """Spends only on one family of interventions, on whichever block looks worst for it."""

    actions: tuple[str, ...] = ()
    sort_key = "average_mood"

    def plan(self, dashboard: dict) -> list[Candidate]:
        rows = sorted(dashboard["blocks"], key=lambda row: (row.get(self.sort_key, 0.0), row["block_id"]))
        candidates: list[Candidate] = []
        for row in rows:
            for action in self.actions:
                if self.affordable(action, dashboard):
                    candidates.append({"action": action, "target_id": row["block_id"]})
        return candidates


class ParksOnly(SingleLever):
    name = "parks_only"
    actions = ("build_small_park", "repair_playground")
    sort_key = "recreation_access"


class RentReliefOnly(SingleLever):
    name = "rent_relief_only"
    actions = ("give_rent_relief",)
    sort_key = "average_rent_burden"

    def plan(self, dashboard: dict) -> list[Candidate]:
        rows = sorted(dashboard["blocks"], key=lambda row: (-row["average_rent_burden"], row["block_id"]))
        return [{"action": "give_rent_relief", "target_id": row["block_id"]} for row in rows
                if self.affordable("give_rent_relief", dashboard)]


class BusinessOnly(SingleLever):
    name = "business_only"
    actions = ("fund_small_business", "fund_community_event")
    sort_key = "food_access"


class BalancedBaseline(Policy):
    """Triage first, then invest in the worst block-level need. Never overcommits upkeep."""

    name = "balanced_baseline"

    def budget_ok(self, action: str, dashboard: dict) -> bool:
        """Can we afford this and still cover every upkeep commitment to day 30?"""
        days_left = max(1, dashboard["days_remaining"])
        entry = self.catalog.get(action)
        if entry is None:
            return False
        committed = dashboard.get("daily_upkeep", 0.0) * days_left
        new_upkeep = float(entry.get("daily_upkeep", 0.0)) * days_left
        buffer = 15_000.0 + dashboard.get("daily_upkeep", 0.0)
        return float(entry["cost"]) + new_upkeep + committed + buffer <= dashboard["budget"]

    def plan(self, dashboard: dict) -> list[Candidate]:
        blocks = dashboard["blocks"]
        candidates: list[Candidate] = []

        def add(action: str, block_id: str) -> None:
            if not self.budget_ok(action, dashboard):
                return
            if self.history.get((action, block_id), 0) >= 3:
                return
            candidate = {"action": action, "target_id": block_id}
            if candidate not in candidates:
                candidates.append(candidate)

        heat = any(event["kind"] == "heat_wave" for event in dashboard.get("events", []))
        if heat:
            uncovered = [row for row in blocks if "cooling_center_open" not in row.get("active_conditions", [])]
            for row in sorted(uncovered, key=lambda row: (row["average_mood"], row["block_id"]))[:2]:
                add("open_cooling_center", row["block_id"])

        # Per-block triage: fix whatever has fallen into the danger zone, worst first.
        for row in sorted(blocks, key=lambda row: (row["cleanliness"], row["block_id"])):
            if row["cleanliness"] < 55.0:
                add("increase_trash_pickup", row["block_id"])
        for row in sorted(blocks, key=lambda row: (row["transit_access"], row["block_id"])):
            if row["transit_access"] < 55.0:
                add("add_bus_service", row["block_id"])
        for row in sorted(blocks, key=lambda row: (row["perceived_safety"], row["block_id"])):
            if row["perceived_safety"] < 50.0:
                add("add_street_lighting", row["block_id"])
        if dashboard["average_rent_burden"] > 0.36:
            for row in sorted(blocks, key=lambda row: (-row["average_rent_burden"], row["block_id"]))[:2]:
                add("give_rent_relief", row["block_id"])
        if dashboard["business_health"] < 50.0:
            for row in sorted(blocks, key=lambda row: (row["food_access"], row["block_id"]))[:2]:
                add("fund_small_business", row["block_id"])

        # Then: the worst block-level need anywhere in the neighborhood.
        ranked: list[tuple[float, str, str]] = []
        for row in blocks:
            for need, action in NEED_TO_ACTION.items():
                value = row.get(need)
                if value is None:
                    continue
                penalty = 12.0 * self.history.get((action, row["block_id"]), 0)
                ranked.append((value + penalty, row["block_id"], action))
        ranked.sort()
        for _, block_id, action in ranked[:8]:
            if action == "build_small_park":
                # Repairing an existing playground is cheaper; if there is none the game
                # rejects it and the driver falls through to building a park.
                add("repair_playground", block_id)
            add(action, block_id)

        # Cheap, always-useful fillers late in the episode.
        for row in sorted(blocks, key=lambda row: (row["average_mood"], row["block_id"]))[:2]:
            add("fund_community_event", row["block_id"])
        for row in sorted(blocks, key=lambda row: (row["cleanliness"], row["block_id"]))[:2]:
            add("increase_trash_pickup", row["block_id"])
        return candidates


STRATEGIES: dict[str, type[Policy]] = {
    policy.name: policy
    for policy in [
        DoNothing,
        RandomLegal,
        SpendEverythingImmediately,
        ParksOnly,
        RentReliefOnly,
        BusinessOnly,
        BalancedBaseline,
    ]
}


def make_policy(name: str, seed: int = 0) -> Policy:
    if name not in STRATEGIES:
        raise KeyError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[name](seed=seed)
