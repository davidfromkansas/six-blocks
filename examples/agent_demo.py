"""Minimal CitySim agent — the smallest thing that plays a full episode.

Swap the body of `decide()` for an LLM call and you have an agent player.

    COWORLD_PLAYER_WS_URL='ws://localhost:8080/player?slot=0&token=t' \
    python agent_demo.py
"""

import asyncio
import json
import os

import websockets


def decide(dashboard, catalog):
    """Return a list of {action, target_id} for today. Replace me with an LLM."""
    blocks = dashboard.get("blocks", [])
    if not blocks:
        return []
    budget = dashboard.get("budget", 0)
    # Cheapest lever that addresses the worst-off block's stated worst_need.
    need_to_action = {
        "cleanliness": "increase_trash_pickup",
        "transit_access": "add_bus_service",
        "recreation_access": "build_small_park",
        "healthcare_access": "improve_clinic_capacity",
        "safety": "add_street_lighting",
        "affordability": "give_rent_relief",
        "business": "fund_small_business",
    }
    worst = min(blocks, key=lambda b: b.get("average_mood", 100))
    action = need_to_action.get(worst.get("worst_need"), "fund_community_event")
    cost = next((a["cost"] for a in catalog if a["action"] == action), 1e9)
    if cost > budget:
        return []
    return [{"action": action, "target_id": worst["block_id"]}]


async def main():
    url = os.environ["COWORLD_PLAYER_WS_URL"]
    async with websockets.connect(url, max_size=None) as ws:
        catalog, day, score = [], 0, None
        async for raw in ws:
            msg = json.loads(raw)
            kind = msg.get("type")

            if kind == "welcome":
                catalog = msg.get("actions", [])
                print(f"seed {msg['seed']}, {msg['total_days']} days, "
                      f"${msg['starting_budget']:,.0f}, {len(catalog)} interventions")

            elif kind == "dashboard":
                day = msg["day"]
                for move in decide(msg, catalog)[: msg.get("action_points_remaining", 0)]:
                    await ws.send(json.dumps({"type": "action", **move}))
                await ws.send(json.dumps({"type": "end_day"}))

            elif kind == "action_result":
                print(f"  day {day}: {msg['action']} @ {msg['target_id']} "
                      f"(-${msg['cost']:,.0f})")

            elif kind == "error":
                print(f"  day {day}: rejected -- {msg['code']}: {msg['message']}")

            elif kind == "episode_finished":
                score = (msg.get("results") or {}).get("score")
                print(f"finished: score {score}")
                return


asyncio.run(main())
