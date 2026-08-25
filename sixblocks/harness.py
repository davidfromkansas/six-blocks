"""Offline driver: run a full episode against a scripted policy, in-process.

The same decision loop the container player uses over the WebSocket, minus the transport.
Used by the tests, the benchmark comparison, and asset/replay generation.
"""

from __future__ import annotations

from .policies import make_policy
from .policies.strategies import Policy
from .simulation.engine import Episode


def drive_day(episode: Episode, policy: Policy) -> list[dict]:
    """Fund interventions until the day's action points run out or nothing is fundable.

    The policy re-plans after every accepted intervention, because the budget and the
    block it just changed both moved.
    """
    accepted: list[dict] = []
    while episode.city.action_points > 0:
        dashboard = episode.dashboard()
        funded = False
        for candidate in policy.plan(dashboard):
            result = episode.submit_action(candidate["action"], candidate["target_id"])
            if result.ok:
                policy.note_accepted(candidate["action"], candidate["target_id"])
                accepted.append(result.payload)
                funded = True
                break
        if not funded:
            break
    return accepted


def run_episode(seed: int, strategy: str = "balanced_baseline", total_days: int = 30,
                budget: float = 500_000.0) -> Episode:
    episode = Episode(seed=seed, total_days=total_days, budget=budget)
    policy = make_policy(strategy, seed=seed)
    policy.on_welcome(episode.handshake())
    while not episode.finished:
        drive_day(episode, policy)
        episode.end_day()
    return episode


def run_scored(seed: int, strategy: str = "balanced_baseline", total_days: int = 30) -> dict:
    episode = run_episode(seed, strategy=strategy, total_days=total_days)
    return episode.results()
