"""Causal behavior, event targeting, numeric sanity, and stress runs."""

from __future__ import annotations

import math

from citysim.harness import run_episode
from citysim.policies import STRATEGIES
from citysim.simulation.engine import Episode
from citysim.simulation.events import EVENT_KINDS
from citysim.simulation.metrics import compute_metrics


def walk(payload: object, path: str = "$") -> None:
    if isinstance(payload, float):
        assert math.isfinite(payload), f"non-finite number at {path}"
    elif isinstance(payload, dict):
        for key, value in payload.items():
            walk(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            walk(value, f"{path}[{index}]")


def test_world_shape() -> None:
    episode = Episode(seed=8)
    city = episode.city
    assert len(city.blocks) == 6
    assert 92 <= len(city.residents) <= 110
    assert 25 <= len(city.buildings) <= 40
    assert len(city.businesses) >= 6
    assert any(block.has_subway_entrance for block in city.block_list)
    assert any(block.has_clinic for block in city.block_list)
    for resident in city.residents.values():
        assert resident.home_block_id in city.blocks
        assert resident.household_id in city.households


def test_every_event_kind_is_scheduled() -> None:
    episode = Episode(seed=8)
    kinds = {
        spec["kind"]
        for specs in episode.city.event_schedule.values()
        for spec in specs
    }
    assert kinds == set(EVENT_KINDS)


def test_events_touch_their_targets() -> None:
    episode = Episode(seed=8)
    city = episode.city
    # Find the scheduled trash_backlog and check the targeted blocks degrade that day.
    day, spec = next(
        (day, spec)
        for day, specs in sorted(city.event_schedule.items())
        for spec in specs
        if spec["kind"] == "trash_backlog"
    )
    while city.day < day - 1:
        episode.end_day()
    before = {bid: city.blocks[bid].trash_service for bid in spec["block_ids"]}
    episode.end_day()
    assert any(city.blocks[bid].trash_service < before[bid] for bid in spec["block_ids"])


def test_trash_pickup_improves_target_block_cleanliness() -> None:
    treated = Episode(seed=21)
    control = Episode(seed=21)
    for _ in range(8):
        treated.submit_action("increase_trash_pickup", "block_c")
        treated.end_day()
        control.end_day()
    assert treated.city.blocks["block_c"].cleanliness > control.city.blocks["block_c"].cleanliness + 5


def test_bus_service_helps_bus_commuters_on_block() -> None:
    treated = Episode(seed=21)
    control = Episode(seed=21)
    for _ in range(8):
        treated.submit_action("add_bus_service", "block_d")
        treated.end_day()
        control.end_day()
    riders = [r.id for r in control.city.residents.values()
              if r.home_block_id == "block_d" and r.commute_mode == "bus"]
    assert riders
    for rid in riders:
        assert (treated.city.residents[rid].current_commute_minutes
                <= control.city.residents[rid].current_commute_minutes)


def test_metrics_and_results_are_finite_and_bounded() -> None:
    for strategy in ("do_nothing", "balanced_baseline", "spend_everything_immediately"):
        episode = run_episode(3, strategy)
        results = episode.results()
        walk(results)
        walk(episode.replay())
        walk(compute_metrics(episode.city))
        assert 0.0 <= results["score"] <= 100.0
        for value in results["components"].values():
            assert 0.0 <= value <= 100.0


def test_random_legal_policy_never_crashes_many_seeds() -> None:
    for seed in range(50, 66):
        episode = run_episode(seed, "random_legal")
        assert episode.finished
        assert 0.0 <= episode.results()["score"] <= 100.0


def test_all_strategies_complete() -> None:
    for name in STRATEGIES:
        episode = run_episode(9, name, total_days=10)
        assert episode.finished


def test_baseline_beats_naive_strategies_on_average() -> None:
    seeds = [1000, 1007, 1014]
    def avg(strategy: str) -> float:
        return sum(run_episode(s, strategy).results()["score"] for s in seeds) / len(seeds)
    baseline = avg("balanced_baseline")
    assert baseline > avg("do_nothing")
    assert baseline > avg("random_legal")
