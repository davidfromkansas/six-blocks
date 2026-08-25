# Six Blocks — Global (Spectator) Protocol

Read-only WebSocket at `/global`. No authentication.

On connect, and whenever the state changes (at least once per second while active),
the game pushes a full snapshot:

```json
{
  "type": "state",
  "seed": 7,
  "day": 12,
  "total_days": 30,
  "finished": false,
  "done": false,
  "player_names": ["Neighborhood Manager"],
  "world": { ... static geometry (blocks, buildings, residents) ... },
  "dashboard": { ... same shape as the player dashboard ... },
  "frame": { ... latest daily replay frame (metrics, events, actions, blocks) ... }
}
```

Messages sent by the client are ignored. The browser spectator at `/client/global`
renders these snapshots with the same p5.js renderer used for live play and replay.

## Replay

`/replay` (WebSocket) is served when the container is started with
`COGAME_LOAD_REPLAY_URI`. On connect it sends the full saved replay:

```json
{"type": "replay", "format": "six_blocks_replay", "version": 1,
 "seed": 7, "world": {...}, "frames": [...30 daily frames...], "results": {...}}
```

The browser client at `/client/replay` scrubs and plays these frames.
