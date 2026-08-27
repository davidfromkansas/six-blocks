# Writing a CitySim player

`agent_demo.py` is the smallest thing that plays a full episode — connect, read the
daily dashboard, send up to three `action` messages, send `end_day`, repeat. Replace
the body of `decide()` and you have your own agent. The packaged baseline in
`citysim/player/player.py` is the fuller reference; the protocol itself is
[docs/player_protocol.md](../docs/player_protocol.md).

## Run it against a local server

Start the game (see the root README for the config file), then:

```bash
COWORLD_PLAYER_WS_URL='ws://localhost:8080/player?slot=0&token=t' python examples/agent_demo.py
```

This is the fastest iteration loop — no Docker, no CLI, just two processes.

## Run it the way the platform does

```bash
coworld build --version 0.1.0 && coworld run-episode dist/coworld_manifest.json -o /tmp/ep
```

Point it at your own agent image by passing the image as a positional argument plus
`--run "python -m youragent"`. `coworld scrimmage` is the same against one target
policy. Note that `coworld build` must be re-run after any source change: the manifest
pins a content-addressed image tag, and a stale one fails with "image is not available
locally or reachable remotely".

## Things worth knowing before you write one

- **Read your rejections.** Interventions can fail a precondition — "this block already
  has a well-maintained park" — and the game answers with a structured `error`, not a
  crash. A failed precondition does not heal, so an agent that re-sends the move burns
  every remaining day on it. `decide()` tracks refused `(action, block)` pairs.
- **Upkeep is the real budget, and this is the big one.** Most interventions bill again
  every remaining day, so what matters is not whether today's cost fits but whether the
  commitment is still affordable on day 30. Capping each individual purchase is not
  enough: three a day for a week is how you go insolvent, and insolvency degrades
  services in every block, every day. An earlier draft of this example spent $459k in
  eight days, ended at **-$137,740** with `fiscal_sustainability` at **0.0**, and
  dragged mobility down to 31. Adding the solvency check below was worth about five
  points on its own.

## How well does it do?

Middling on purpose — it is a starting point, not a good policy:

| seed | this example | `balanced_baseline` |
| ---- | ------------ | ------------------- |
| 7    | 75.33        | 73.77               |
| 1000 | 67.96        | 72.05               |
| 1007 | 70.55        | 69.95               |
| 1014 | 66.99        | 66.72               |
| 1021 | 56.68        | 64.62               |

It wins on some seeds and loses on others, averaging a few points below the scripted
baseline. Seed 7 flatters it. If you tune a heuristic against one seed you will get a
number like that 75.33 and it will not survive contact with the rest of the ladder —
check several seeds before believing an improvement.
- **Inspections are free and unlimited.** `inspect` never costs an action point.
- **If your player calls an LLM in a hosted episode**, send every Bedrock call to
  `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` and use `InvokeModel`, not `Converse`. Hitting the
  real AWS host gets a 403 from the injected placeholder credentials and the episode
  silently falls back to a non-LLM baseline, with nothing visible in the score.
