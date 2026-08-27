"""Minimal CitySim agent — the smallest thing that plays a full episode.

Swap the body of `decide()` for an LLM call and you have an agent player.

    COWORLD_PLAYER_WS_URL='ws://localhost:8080/player?slot=0&token=t' \
    python agent_demo.py
"""

import asyncio
import json
import os

import websockets

# Levers that address each block-level need the dashboard can report.
NEED_TO_ACTION = {
    "cleanliness": "increase_trash_pickup",
    "transit_access": "add_bus_service",
    "recreation_access": "build_small_park",
    "healthcare_access": "improve_clinic_capacity",
    "safety": "add_street_lighting",
    "affordability": "give_rent_relief",
    "business": "fund_small_business",
}


def decide(dashboard, catalog, refused):
    """Return a list of {action, target_id} for today. Replace me with an LLM.

    ``refused`` is the set of (action, block) pairs the game has already rejected.
    Skipping them is most of what separates this from a wasted episode: once an
    intervention fails a precondition it will fail for the rest of the run, and an
    agent that keeps re-sending it spends its remaining days doing nothing.
    """
    blocks = dashboard.get("blocks", [])
    if not blocks:
        return []
    budget = dashboard.get("budget", 0)
    days_left = dashboard.get("days_remaining", 1) or 1
    upkeep = dashboard.get("daily_upkeep", 0)
    costs = {a["action"]: a for a in catalog}

    # Worst-off blocks first, and for each one fall back through its alternatives
    # rather than giving up when the obvious lever is unavailable.
    moves = []
    for block in sorted(blocks, key=lambda b: b.get("average_mood", 100)):
        if len(moves) >= dashboard.get("action_points_remaining", 0):
            break
        preferred = NEED_TO_ACTION.get(block.get("worst_need"))
        options = [preferred] if preferred else []
        options += ["increase_trash_pickup", "fund_community_event", "fund_small_business"]
        for action in options:
            entry = costs.get(action)
            if entry is None or (action, block["block_id"]) in refused:
                continue
            # Upkeep is the real budget. Every lever bills again each remaining
            # day, so what matters is not whether today's cost fits but whether
            # the commitment is still affordable on day 30. Capping each single
            # purchase is not enough -- three a day for a week is how you go
            # insolvent, and insolvency degrades services in every block.
            cost = entry["cost"]
            new_upkeep = upkeep + entry.get("daily_upkeep", 0)
            if cost > budget:
                continue
            if new_upkeep * days_left > (budget - cost) * 0.55:
                continue
            moves.append({"action": action, "target_id": block["block_id"]})
            budget -= cost
            upkeep = new_upkeep
            break
    return moves


async def main():
    url = os.environ["COWORLD_PLAYER_WS_URL"]
    async with websockets.connect(url, max_size=None) as ws:
        catalog, day, score = [], 0, None
        refused: set[tuple[str, str]] = set()   # (action, block) the game has refused
        sent: list[dict] = []                   # this day's moves, oldest first
        async for raw in ws:
            msg = json.loads(raw)
            kind = msg.get("type")

            if kind == "welcome":
                catalog = msg.get("actions", [])
                print(f"seed {msg['seed']}, {msg['total_days']} days, "
                      f"${msg['starting_budget']:,.0f}, {len(catalog)} interventions")

            elif kind == "dashboard":
                day = msg["day"]
                pending = decide(msg, catalog, refused)[: msg.get("action_points_remaining", 0)]
                sent.clear()
                sent.extend(pending)
                for move in pending:
                    await ws.send(json.dumps({"type": "action", **move}))
                await ws.send(json.dumps({"type": "end_day"}))

            elif kind == "action_result":
                if sent:
                    sent.pop(0)
                print(f"  day {day}: {msg['action']} @ {msg['target_id']} "
                      f"(-${msg['cost']:,.0f})")

            elif kind == "error":
                # Remember refusals: a failed precondition does not heal, so the
                # same move would be refused every remaining day.
                if msg.get("code") == "precondition_failed" and sent:
                    move = sent.pop(0)
                    refused.add((move["action"], move["target_id"]))
                print(f"  day {day}: rejected -- {msg['code']}: {msg['message']}")

            elif kind == "episode_finished":
                score = (msg.get("results") or {}).get("score")
                print(f"finished: score {score}")
                return


asyncio.run(main())
