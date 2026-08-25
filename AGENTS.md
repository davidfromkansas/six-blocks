# AGENTS.md — CitySim

Onboarding guide for coding agents working on this repo with zero prior context.
Read this file, then `README.md`, then the docs relevant to your change (see the
doc map below) before editing.

## What this is

CitySim is a **Coworld**: a containerized benchmark game for AI agents, run on the
Softmax platform (see https://github.com/Metta-AI/coworld). The player manages a
fictional NYC-inspired six-block neighborhood (~100 residents) for 30 simulated days
with a $500,000 budget, up to 3 block-targeted interventions per day, free
inspections, and seeded random events. After day 30 a 0–100 score is computed from
weighted components (welfare, affordability, mobility, health, cleanliness, economy,
equity, fiscal sustainability, resilience).

Naming note: the product/package is **CitySim** (`citysim` Python package,
`CITYSIM_*` env vars, `citysim_replay` format), but the GitHub repo slug is still
`six-blocks`. Do not rename either without being asked.

## Repository layout

```
citysim/
  simulation/        # deterministic simulation core (pure Python, no I/O)
    world.py         #   world generation (blocks, buildings, residents, businesses)
    engine.py        #   day advancement, results artifact, replay frames
    interventions.py #   the 12 interventions (costs, upkeep, effects)
    events.py        #   the 10 seeded event types
    scoring.py       #   score components and WEIGHTS
    rng.py           #   seeded PRNG helpers — ALL randomness flows through this
    state.py, lifecycle.py, derive.py, metrics.py, observation.py, names.py, util.py
  game/
    server.py        # FastAPI/uvicorn game container: WebSocket protocol, routes
    client/          # browser UIs: player.html, global.html (spectator), replay.html
      assets/citysim-render.js  # the p5.js isometric diorama renderer
      assets/{player,global,replay,dashboard}.js, style.css, p5.min.js
  player/player.py   # baseline WebSocket player (the packaged player role)
  policies/          # baseline strategies used by the player and benchmark
  harness.py         # local orchestration helpers
tests/               # pytest: determinism, rules/protocol, simulation behavior
tools/
  benchmark.py       # multi-seed strategy comparison
  generate_assets.mjs # procedural favicon/palette generation (node)
docs/                # player_protocol, global_protocol, simulation, scoring, references
Dockerfile, compose.yaml, coworld_manifest_template.json  # Coworld packaging
```

## Hard invariants (do not break)

1. **Determinism by seed.** Same seed → identical world, trajectory, score, results,
   and replay. Never use wall-clock time, `random` module state, dict-order
   dependence, or floats derived from iteration over unordered collections in
   simulation code. All randomness must come from the seeded RNGs in
   `citysim/simulation/rng.py`. `tests/test_determinism.py` enforces this.
2. **Rendering never mutates simulation state.** The browser renderer is display
   only; ambient walkers/vehicles are seeded deterministically client-side.
3. **Results contract.** The results artifact written by `engine.py` must keep
   `game`, `seed`, `score`, `scores` (1-element array, required by the hosted
   platform), `components`, `days_simulated`, `total_days` — and match the results
   schema in `coworld_manifest_template.json`.
4. **Protocol shape.** JSON over WebSocket at `/player`; message types are `inspect`,
   `action`, `end_day`. Bad input must return structured errors, never crash or hang.
   Disconnect/timeout falls back to `end_day` with no intervention. See
   `docs/player_protocol.md` for the exact shapes.
5. **Renderer public API** (used by player, spectator, and replay clients):
   `new CitySimRenderer(containerId, {onHover})`, `setWorld(world)`,
   `setFrame(frame)`, `setDay(day)`, `toggleDebug()`. Keep it stable.

## Setup, test, lint, run

Python 3.12+. From the repo root:

```bash
python -m venv .venv
.venv/bin/pip install -e . pytest ruff mypy httpx

.venv/bin/ruff check .          # lint (must pass before any PR)
.venv/bin/python -m pytest -q   # tests (must pass before any PR)
```

Run the game server locally (it needs a config file and artifact URIs):

```bash
mkdir -p /tmp/cs
echo '{"tokens":["t"],"players":[{"name":"me"}],"seed":7}' > /tmp/cs/config.json
COGAME_CONFIG_URI=file:///tmp/cs/config.json \
COGAME_RESULTS_URI=file:///tmp/cs/results.json \
COGAME_SAVE_REPLAY_URI=file:///tmp/cs/replay.json \
.venv/bin/python -m citysim.game.server
```

Then open:

- `http://localhost:8080/client/player?slot=0&token=t` — interactive player UI
- `http://localhost:8080/global` — live spectator view
- `http://localhost:8080/client/replay` — replay viewer (load the saved replay JSON)
- `http://localhost:8080/healthz` — health check

Gotchas learned from testing (also in `.agents/skills/testing-sixblocks/SKILL.md`):

- Reloading the player page closes the WebSocket; the server then fast-forwards the
  abandoned episode to day 30 and **exits**. Restart the server between browser runs.
- Browsers cache `citysim-render.js`; hard-reload after editing client assets.
- Run the baseline player headlessly with `.venv/bin/python -m citysim.player.player`
  (env `CITYSIM_WS_URL`, `CITYSIM_TOKEN`).

## Coworld packaging (build / certify / upload)

The Coworld CLI lives in a separate checkout of https://github.com/Metta-AI/coworld
(read its `AGENTS.md` before touching packaging). Typical flow, from this repo root
with a coworld-enabled venv:

```bash
coworld build      # builds the Docker image from compose.yaml and hydrates
                   # coworld_manifest_template.json into a manifest
coworld certify <manifest.json>   # local smoke certification (must pass)
coworld upload-coworld <manifest.json>  # requires `softmax login` auth
```

- `compose.yaml` pins `linux/amd64`; keep it that way.
- The manifest declares `game` and `player` roles only (no commissioner —
  platform-ladder Coworlds omit it).
- If you change the results artifact shape, update the results schema in
  `coworld_manifest_template.json` in the same PR, and re-run `coworld certify`.
  Hosted certification additionally validates against the platform's
  `CoworldEpisodeResults` model (this is what requires `scores`).

## Renderer notes (citysim/game/client/assets/citysim-render.js)

- Isometric 2:1 diamond projection: `iso(x,y,z)` / `unproject(mx,my)`; world-space
  quads via `quad3`, extruded shaded volumes via `box(x,y,w,h,z0,z1,rgb)`.
- Draw order: slab → ground/streets → depth-sorted item list (buildings, props,
  vehicles, walkers, sorted by `x+y` footprint depth) → sky tint → hover → labels →
  debug. Anything with height must go through the sorted item list or it will
  z-fight.
- Buildings are styled after SoHo cast-iron lofts (cream painted-iron and brick
  facades, arched window bays, storefront band, cornice, water tanks, fire escapes).
- All per-building/per-block variation must be seeded via `sbHash`/`sbRng` with a
  stable key (e.g. `"bld:" + b.id`) so every client renders the same scene.
- Camera: scroll to zoom (1x fits the neighborhood, 8x max), drag to pan, `f`/`0` to
  reset, `+`/`-` to step. Zoom anchors on the cursor and panning is clamped to the
  ground slab, so the city can never be pushed off screen. Picking shares the
  projection via `unproject`, so hover keeps working at any zoom.
- Press `d` in any view for the debug overlay (FPS, footprints, walker paths).
- Verify with `node -c citysim/game/client/assets/citysim-render.js` plus a browser
  check of all three views before opening a PR.

## Doc map

- `docs/player_protocol.md` — player WebSocket contract (source of truth).
- `docs/global_protocol.md` — spectator broadcast contract.
- `docs/simulation.md` — simulation model: residents, businesses, housing, mobility,
  events, interventions.
- `docs/scoring.md` — score components, weights, final-day share.
- `docs/VISUAL_REFERENCES.md`, `docs/SIMULATION_REFERENCES.md` — research notes.

## Workflow conventions

- Work on a `devin/<timestamp>-<slug>` branch; PR into `main`. Never push to `main`.
- Before any PR: `ruff check .` and `pytest -q` must pass; if you touched client JS,
  syntax-check it and exercise the affected views in a browser.
- If you touched simulation behavior, also run `tools/benchmark.py` across a few
  seeds to check the baseline still performs sensibly.
- Keep changes minimal and scoped; do not reformat unrelated code.
