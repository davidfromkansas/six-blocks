# CitySim

**30 days. Six blocks. One neighborhood to keep alive.**

CitySim is a Coworld benchmark for AI agents. You are the manager of a fictional,
NYC-inspired six-block neighborhood of about 100 residents. You have thirty simulated
days, a $500,000 budget, and up to three interventions per day. Residents commute, pay
rent, get sick, open and lose businesses, and react to everything you do — and to the
seeded events (heat waves, floods, rent spikes, festivals) that hit the neighborhood
while you manage it.

The question the benchmark asks: **given limited money, incomplete information,
heterogeneous residents, and changing city conditions, can an AI make decisions that
create a thriving neighborhood?**

## How an episode works

Each simulated day:

1. The game sends you a **dashboard**: budget, mood, rents, mobility, cleanliness,
   business health, active events, alerts, and per-block summaries.
2. You may **inspect** anything (`city`, `block`, `resident`, `business`, `transit`,
   `housing`) — inspections are free and unlimited.
3. You may fund up to **three interventions** (each costs money now, and most add
   daily upkeep).
4. You send `end_day`. The simulation advances: residents run their routines,
   businesses respond, housing and events resolve, and a replay frame is recorded.

After day 30 the episode ends and a multidimensional score (0–100) is computed.

## Action space

Twelve interventions, all block-targeted:

`increase_trash_pickup`, `add_bus_service`, `add_bike_capacity`, `repair_playground`,
`build_small_park`, `open_cooling_center`, `fund_small_business`, `give_rent_relief`,
`add_street_lighting`, `fund_community_event`, `improve_clinic_capacity`,
`pedestrianize_street`.

Costs, upkeep, and plain-language effects are sent in the welcome message; see
[docs/player_protocol.md](docs/player_protocol.md).

## Scoring

The score blends resident welfare, affordability, mobility, health, cleanliness,
economic health, equity/displacement, fiscal sustainability, and resilience — final
state plus trajectory, normalized to 0–100. Philosophy in [docs/scoring.md](docs/scoring.md).

The simulation is **deterministic by seed**: same seed + same actions ⇒ identical
trajectory, score, and replay.

## Repository layout

- `citysim/simulation/` — deterministic simulation core (pure Python, no I/O)
- `citysim/game/` — Coworld game container (FastAPI + WebSockets + p5.js clients)
- `citysim/player/` — baseline scripted player container
- `citysim/policies/` — scripted strategies incl. `balanced_baseline`
- `tools/benchmark.py` — strategy comparison over many seeds
- `tools/generate_assets.mjs` — deterministic procedural asset generation

## Running locally

```bash
# tests (25 deterministic tests)
uv venv .venv -p 3.12 && uv pip install -p .venv -e '.[dev]'
.venv/bin/pytest

# regenerate procedural assets
npm run generate-assets

# headless local episode: server + baseline player
COGAME_CONFIG_URI=file:///tmp/sb/config.json \
COGAME_RESULTS_URI=file:///tmp/sb/results.json \
COGAME_SAVE_REPLAY_URI=file:///tmp/sb/replay.json \
python -m citysim.game.server &
COWORLD_PLAYER_WS_URL='ws://localhost:8080/player?slot=0&token=<token>' \
python -m citysim.player.player
```

Browser play: open `http://localhost:8080/client/player?slot=0&token=<token>`
(spectator: `/client/global`, replay: `/client/replay`). Press `d` in the world view
for the visual debug overlay.

## Coworld build / certify / upload

The `coworld` CLI is not a dependency of this project — it lives in a separate
checkout of https://github.com/Metta-AI/coworld, so run it from there (`uv run
coworld ...` from *this* repo has nothing to run). Docker must be running, and on
Apple Silicon export `DOCKER_DEFAULT_PLATFORM=linux/amd64`.

```bash
coworld build --version 0.4.0            # builds the image, writes dist/coworld_manifest.json
coworld certify dist/coworld_manifest.json
coworld upload-coworld dist/coworld_manifest.json   # needs `softmax login`
coworld run-episode dist/coworld_manifest.json -o /tmp/ep
```

`--version` is required and must be higher than the highest already uploaded —
check with `coworld list` first, because the platform keeps every version and the
canonical one is not necessarily the newest. Re-run `coworld build` after any
source change: the manifest pins a content-addressed image tag, and a stale one
fails with "image is not available locally or reachable remotely".

## Writing your own player

Connect a WebSocket to `COWORLD_PLAYER_WS_URL`, read the `welcome` and daily
`dashboard` messages, send `inspect` / `action` / `end_day` JSON messages. Full
protocol with examples: [docs/player_protocol.md](docs/player_protocol.md). The
baseline in `citysim/player/player.py` is a complete working example.
