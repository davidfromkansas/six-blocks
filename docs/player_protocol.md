# Six Blocks — Player Protocol

One management seat, JSON over a WebSocket.

## Connecting

Connect to the URL in `COWORLD_PLAYER_WS_URL` (locally:
`ws://<host>:<port>/player?slot=0&token=<token>`). Slot must be `0`; the token must
match the game config. Invalid credentials close the socket with code 1008.

## Handshake

On connect the game sends a single `welcome` message:

```json
{
  "type": "welcome",
  "game": "six_blocks",
  "protocol_version": 1,
  "seed": 7,
  "total_days": 30,
  "actions_per_day": 3,
  "starting_budget": 500000.0,
  "blocks": [{"block_id": "block_a", "name": "Marcy Row", "col": 0, "row": 0}, ...],
  "actions": [{"action": "increase_trash_pickup", "cost": 9000, "daily_upkeep": 220,
               "description": "..."}, ...],
  "inspect_targets": ["city", "block", "resident", "business", "transit", "housing"],
  "message_types": ["inspect", "action", "end_day"],
  "score_dimensions": ["resident_welfare", "affordability", ...],
  "world": { ... static geometry for rendering ... }
}
```

followed by the day-1 `dashboard`.

## Daily dashboard

At the start of every day (and after `end_day`) the game sends:

```json
{
  "type": "dashboard",
  "day": 3, "total_days": 30, "days_remaining": 27,
  "budget": 447000.0, "daily_upkeep": 1000.0,
  "action_points_remaining": 3,
  "population": 100, "average_mood": 58.2, "median_rent": 2840.0,
  "average_rent_burden": 0.34, "mobility": 61.0, "cleanliness": 64.5,
  "business_health": 57.0, "health": 62.1,
  "events": [{"kind": "heat_wave", "headline": "...", "block_ids": [...],
              "citywide": true, "days_remaining": 2, "intensity": "severe"}],
  "alerts": ["..."], "recent_changes": ["..."],
  "blocks": [{"block_id": "block_a", "name": "...", "population": 18,
              "average_mood": 55.1, "cleanliness": 60.0, "transit_access": 52.0,
              "worst_need": "cleanliness", "active_conditions": ["trash_backlog"], ...}]
}
```

## Messages you can send

### Inspect (free, unlimited)

```json
{"type": "inspect", "target_type": "block", "target_id": "block_b"}
```

`target_type` ∈ `city | block | resident | business | transit | housing`.
`city`, `transit`, and `housing` need no `target_id`. Reply: `{"type": "inspection", ...}`
with detailed structured data. Inspections never consume action points.

### Action (up to `actions_per_day` per day)

```json
{"type": "action", "action": "increase_trash_pickup", "target_id": "block_b"}
```

Accepted reply:

```json
{"type": "action_result", "accepted": true, "day": 3,
 "action": "increase_trash_pickup", "target_id": "block_b",
 "cost": 9000, "daily_upkeep": 220, "budget": 438000.0,
 "action_points_remaining": 2, "note": "..."}
```

### End day

```json
{"type": "end_day"}
```

Reply: `{"type": "day_advanced", "day": 4, "notes": [...]}` followed by the next
day's `dashboard`. On the last day you receive
`{"type": "episode_finished", "results": {...}}` and then
`{"type": "final", "done": true, "results": {...}}` before the game exits.

## Errors

Invalid input never crashes the game; you get a structured error and can retry:

```json
{"type": "error", "code": "insufficient_budget", "message": "..."}
```

Codes include `bad_json`, `unknown_message_type`, `unknown_action`, `unknown_target`,
`unknown_target_type`, `no_action_points`, `insufficient_budget`,
`precondition_failed`, `day_timeout`, `seat_taken`.

## Timeouts and disconnects

- If no player connects within `player_connect_timeout_seconds`, or the player
  disconnects, the game finishes the episode with no further interventions.
- If a day exceeds `day_timeout_seconds`, the day ends automatically (a
  `day_timeout` error plus the new day's messages are sent).
- After ~25 protocol errors in one day the day is ended defensively.
