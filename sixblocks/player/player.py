"""Scripted baseline player (Coworld player role).

Connects to the game's /player WebSocket, plays every day with the balanced-baseline
policy, and always finishes the episode. Strategy and seed can be overridden through
SIXBLOCKS_STRATEGY / SIXBLOCKS_POLICY_SEED for benchmark runs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import websockets

from sixblocks.policies import make_policy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("sixblocks.player")

MAX_REJECTED_PER_DAY = 24


async def main() -> None:
    url = os.environ["COWORLD_PLAYER_WS_URL"]
    strategy = os.environ.get("SIXBLOCKS_STRATEGY", "balanced_baseline")
    policy_seed = int(os.environ.get("SIXBLOCKS_POLICY_SEED", "0"))
    policy = make_policy(strategy, seed=policy_seed)
    logger.info("connecting to %s as %s", url, strategy)

    async with websockets.connect(url, ping_timeout=None, max_size=64 * 1024 * 1024) as websocket:
        dashboard: dict[str, Any] | None = None
        candidates: list[dict[str, str]] = []
        rejected_today = 0

        async for raw in websocket:
            message = json.loads(raw)
            kind = message.get("type")

            if kind == "welcome":
                policy.on_welcome(message)
                continue
            if kind == "final":
                logger.info("episode finished: score=%s", message.get("results", {}).get("score"))
                return
            if kind == "episode_finished":
                logger.info("episode already finished")
                return

            if kind == "dashboard":
                dashboard = message
                rejected_today = 0
                candidates = policy.plan(dashboard)
            elif kind == "action_result" and message.get("accepted"):
                policy.note_accepted(message["action"], message["target_id"])
                if dashboard is not None:
                    dashboard["budget"] = message["budget"]
                    dashboard["daily_upkeep"] = dashboard.get("daily_upkeep", 0.0) + message.get("daily_upkeep", 0.0)
                    dashboard["action_points_remaining"] = message["action_points_remaining"]
                    candidates = policy.plan(dashboard)
            elif kind == "error":
                rejected_today += 1
                logger.info("rejected: %s", message.get("code"))
            else:
                continue

            # Decide the next message for the current day.
            if message.get("action_points_remaining", 0) > 0 and rejected_today < MAX_REJECTED_PER_DAY:
                if not candidates and dashboard is not None:
                    candidates = policy.plan(dashboard)
                if candidates:
                    candidate = candidates.pop(0)
                    await websocket.send(json.dumps({
                        "type": "action",
                        "action": candidate["action"],
                        "target_id": candidate["target_id"],
                    }))
                    continue
            await websocket.send(json.dumps({"type": "end_day"}))


if __name__ == "__main__":
    asyncio.run(main())
