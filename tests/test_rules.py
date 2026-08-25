"""Action legality: budget, action points, targets, preconditions, protocol errors."""

from __future__ import annotations

import pytest

from citysim.simulation.engine import Episode
from citysim.simulation.interventions import INTERVENTIONS, action_catalog


def test_catalog_matches_spec() -> None:
    expected = {
        "increase_trash_pickup", "add_bus_service", "add_bike_capacity", "repair_playground",
        "build_small_park", "open_cooling_center", "fund_small_business", "give_rent_relief",
        "add_street_lighting", "fund_community_event", "improve_clinic_capacity",
        "pedestrianize_street",
    }
    assert set(INTERVENTIONS) == expected
    assert {entry["action"] for entry in action_catalog()} == expected
    assert all(entry["cost"] > 0 for entry in action_catalog())


def test_action_points_are_capped_per_day() -> None:
    episode = Episode(seed=5)
    for _ in range(3):
        assert episode.submit_action("increase_trash_pickup", "block_a").ok
    result = episode.submit_action("increase_trash_pickup", "block_a")
    assert not result.ok
    assert result.payload["code"] == "no_action_points"
    assert episode.city.action_points == 0


def test_action_points_reset_each_day() -> None:
    episode = Episode(seed=5)
    episode.submit_action("increase_trash_pickup", "block_a")
    episode.end_day()
    assert episode.city.action_points == episode.city.actions_per_day


def test_unknown_action_and_target_are_rejected() -> None:
    episode = Episode(seed=5)
    assert episode.submit_action("nuke_the_block", "block_a").payload["code"] == "unknown_action"
    assert episode.submit_action("add_bus_service", "block_z").payload["code"] == "unknown_target"
    assert episode.submit_action("add_bus_service", None).payload["code"] == "unknown_target"


def test_budget_is_enforced_and_never_silently_overdrawn_by_actions() -> None:
    episode = Episode(seed=5, budget=1_000.0)
    result = episode.submit_action("build_small_park", "block_a")
    assert not result.ok
    assert result.payload["code"] == "insufficient_budget"
    assert episode.city.budget == 1_000.0
    assert episode.city.action_points == episode.city.actions_per_day


def test_spending_debits_the_budget_exactly_once() -> None:
    episode = Episode(seed=5)
    cost = INTERVENTIONS["add_street_lighting"].cost
    before = episode.city.budget
    assert episode.submit_action("add_street_lighting", "block_b").ok
    assert episode.city.budget == pytest.approx(before - cost)


def test_precondition_failure_is_reported() -> None:
    episode = Episode(seed=5)
    without_playground = [b for b in episode.city.block_list if not b.has_playground]
    assert without_playground, "seed should produce at least one block with no playground"
    result = episode.submit_action("repair_playground", without_playground[0].id)
    assert not result.ok
    assert result.payload["code"] == "precondition_failed"


def test_inspection_targets_and_errors() -> None:
    episode = Episode(seed=5)
    assert episode.inspect("city", None).ok
    assert episode.inspect("transit", None).ok
    assert episode.inspect("housing", None).ok
    assert episode.inspect("block", "block_a").ok
    resident_id = min(episode.city.residents)
    assert episode.inspect("resident", resident_id).ok
    business_id = min(episode.city.businesses)
    assert episode.inspect("business", business_id).ok
    assert episode.inspect("banana", None).payload["code"] == "unknown_target_type"
    assert episode.inspect("resident", "res_nope").payload["code"] == "unknown_target"


def test_inspection_never_costs_action_points() -> None:
    episode = Episode(seed=5)
    for _ in range(10):
        episode.inspect("city", None)
    assert episode.city.action_points == episode.city.actions_per_day


def test_episode_terminates_and_rejects_late_actions() -> None:
    episode = Episode(seed=5, total_days=6)
    for _ in range(6):
        episode.end_day()
    assert episode.finished
    assert episode.city.day == 6
    assert episode.submit_action("add_bus_service", "block_a").payload["code"] == "episode_finished"
    assert episode.end_day()["type"] == "episode_finished"
