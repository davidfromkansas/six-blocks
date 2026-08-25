"""Determinism is the load-bearing property of the benchmark."""

from __future__ import annotations

import json

from citysim.harness import run_episode
from citysim.simulation.engine import Episode


def canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, default=str)


def test_same_seed_same_initial_state() -> None:
    a = Episode(seed=4242)
    b = Episode(seed=4242)
    assert canonical(a.snapshot()) == canonical(b.snapshot())
    assert canonical(a.world()) == canonical(b.world())
    assert canonical(a.handshake()) == canonical(b.handshake())


def test_different_seeds_differ() -> None:
    assert canonical(Episode(seed=1).snapshot()) != canonical(Episode(seed=2).snapshot())


def test_same_seed_same_event_schedule() -> None:
    assert Episode(seed=99).city.event_schedule == Episode(seed=99).city.event_schedule


def test_same_seed_and_actions_same_trajectory() -> None:
    first = run_episode(31337, "balanced_baseline")
    second = run_episode(31337, "balanced_baseline")
    assert canonical(first.city.daily_metrics) == canonical(second.city.daily_metrics)
    assert canonical(first.snapshot()) == canonical(second.snapshot())
    assert canonical(first.results()) == canonical(second.results())
    assert canonical(first.replay()) == canonical(second.replay())


def test_manual_action_sequence_is_reproducible() -> None:
    plan = [
        ("increase_trash_pickup", "block_a"),
        ("add_bus_service", "block_c"),
        ("build_small_park", "block_f"),
    ]

    def play() -> dict:
        episode = Episode(seed=777)
        while not episode.finished:
            for action, target in plan:
                if episode.city.action_points <= 0:
                    break
                episode.submit_action(action, target)
            episode.end_day()
        return episode.results()

    assert canonical(play()) == canonical(play())


def test_replay_frames_cover_every_day() -> None:
    episode = run_episode(11, "balanced_baseline", total_days=12)
    frames = episode.replay()["frames"]
    assert [frame["day"] for frame in frames] == list(range(1, 13))
