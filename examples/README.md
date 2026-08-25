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
  crash. `agent_demo.py` deliberately ignores them, which is why it re-sends the same
  refused move for twenty days and scores 66.35 against the baseline's 73.77. Handling
  that is most of the gap.
- **Upkeep is the real budget.** Most interventions bill every remaining day, so the
  cost of a lever depends on which day you pull it. Spending everything early scores
  worse than doing nothing.
- **Inspections are free and unlimited.** `inspect` never costs an action point.
- **If your player calls an LLM in a hosted episode**, send every Bedrock call to
  `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` and use `InvokeModel`, not `Converse`. Hitting the
  real AWS host gets a 403 from the injected placeholder credentials and the episode
  silently falls back to a non-LLM baseline, with nothing visible in the score.
