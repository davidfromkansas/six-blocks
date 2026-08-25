---
name: testing-citysim
description: How to run and end-to-end test the CitySim Coworld game server, browser clients, scripted player, and replay mode locally.
---

# Testing CitySim locally

## Run the game server (no coworld CLI needed)
1. `python -m venv .venv && .venv/bin/pip install -e .` (fastapi/uvicorn/websockets)
2. Write a config, e.g. `/tmp/sbtest/config.json`:
   `{"tokens": ["testtoken"], "players": [{"name": "Manager"}], "seed": 7, "day_timeout_seconds": 300}`
3. Start (port defaults to 8080 via `COGAME_PORT`, not `PORT`):
   `COGAME_CONFIG_URI=file:///tmp/sbtest/config.json COGAME_RESULTS_URI=file:///tmp/sbtest/results.json COGAME_SAVE_REPLAY_URI=file:///tmp/sbtest/replay.json .venv/bin/python -m citysim.game.server`

## URLs
- Player: `http://localhost:8080/client/player?slot=0&token=testtoken`
- Spectator: `http://localhost:8080/client/global`
- Replay: restart server with `COGAME_LOAD_REPLAY_URI=file:///tmp/sbtest/replay.json` (plus COGAME_CONFIG_URI) and open `http://localhost:8080/client/replay`

## Gotchas
- The server EXITS ~0.5s after the episode finishes (writes results.json + replay.json first). Reloading pages after finish gives ERR_CONNECTION_REFUSED — expected; restart in replay mode to review.
- The scripted baseline player (`COWORLD_PLAYER_WS_URL='ws://localhost:8080/player?slot=0&token=testtoken' python -m citysim.player.player`) plays all 30 days in <1s, so you cannot watch it live in the spectator; use the replay to review the episode.
- Debug overlay: click the canvas first to give it focus, then press `d` (toggles FPS/IDs/bounds).
- Selecting from the block/action `<select>` dropdowns can leave a native popup open that swallows subsequent clicks; press Escape before clicking End Day repeatedly.
- Hovering the canvas over a block silently changes the block `<select>` (hover-inspect) — pick the block in the dropdown last, right before clicking Fund/Inspect.
- When restarting the server, run `pkill -f citysim.game.server` in its own exec call; chaining pkill with the new server start in one command can kill the whole shell before the new server launches.
- Window resize testing: use `wmctrl -r :ACTIVE: -b remove,maximized_vert,maximized_horz && wmctrl -r :ACTIVE: -e 0,50,50,700,600` to shrink, then re-add maximized flags to restore.
- Known display quirks to watch: live dashboards may show "Day X / undefined" if the dashboard payload lacks `total_days`; the spectator may miss the final-score snapshot because `_send_global_snapshots` exits its loop when `state.done` is set before sending the final state.
