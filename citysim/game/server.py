"""CitySim game container.

Implements the Coworld game role contract (see coworld docs/roles/GAME.md):
  GET  /healthz             liveness
  GET  /client/player       browser player client
  GET  /client/global       spectator client
  GET  /client/replay       replay client
  GET  /client/assets/...   static js/css shared by the clients
  WS   /player              the single management seat (slot 0, token-checked)
  WS   /global              read-only spectator snapshots
  WS   /replay              replays a saved episode artifact

The game owns canonical state (the deterministic `Episode`), the authoritative results
artifact, and the replay artifact. One episode per container run.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import time
import zlib
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from citysim.simulation.engine import Episode

CLIENT_DIR = Path(__file__).parent / "client"
GAME_HOST = os.environ.get("COGAME_HOST", "0.0.0.0")
GAME_PORT = int(os.environ.get("COGAME_PORT", "8080"))
HTTP_USER_AGENT = "citysim-game/0.1"

# A stalled or hostile player can never hang the episode: after this many protocol
# errors in one day, or after the per-day timeout, the day ends with no intervention.
MAX_PROTOCOL_ERRORS_PER_DAY = 25


def read_data(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, headers={"User-Agent": HTTP_USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {uri}")


def artifact_method(env_var: str) -> Literal["POST", "PUT"]:
    method = os.environ.get(env_var, "PUT").upper()
    if method not in {"POST", "PUT"}:
        raise ValueError(f"{env_var} must be PUT or POST")
    return cast(Literal["POST", "PUT"], method)


def write_data(uri: str, data: bytes | str, *, content_type: str,
               http_method: Literal["POST", "PUT"]) -> None:
    if isinstance(data, str):
        data = data.encode()
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method=http_method)
        request.add_header("Content-Type", content_type)
        request.add_header("User-Agent", HTTP_USER_AGENT)
        with urlopen(request, timeout=60):
            return
    path = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(uri)
    if parsed.scheme in ("file", ""):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    raise ValueError(f"Unsupported URI for write_data: {uri}")


def load_replay_data(replay_uri: str) -> dict[str, Any]:
    replay_data = read_data(replay_uri)
    if replay_uri.endswith(".z"):
        replay_data = zlib.decompress(replay_data)
    elif replay_uri.endswith(".gz"):
        replay_data = gzip.decompress(replay_data)
    return json.loads(replay_data)


REPLAY_MODE = "COGAME_LOAD_REPLAY_URI" in os.environ
if REPLAY_MODE:
    REPLAY_LOAD_URI = os.environ["COGAME_LOAD_REPLAY_URI"]
    CONFIG: dict[str, Any] = {"tokens": [], "players": []}
    RESULTS_URI = ""
    REPLAY_URI = ""
else:
    REPLAY_LOAD_URI = ""
    CONFIG = json.loads(read_data(os.environ["COGAME_CONFIG_URI"]))
    RESULTS_URI = os.environ["COGAME_RESULTS_URI"]
    REPLAY_URI = os.environ["COGAME_SAVE_REPLAY_URI"]

TOKENS: list[str] = CONFIG.get("tokens", [])
PLAYER_NAMES = [player["name"] for player in CONFIG.get("players", [])]
SEED = CONFIG.get("seed")
TOTAL_DAYS = int(CONFIG.get("total_days", 30))
BUDGET = float(CONFIG.get("budget", 500_000.0))
ACTIONS_PER_DAY = int(CONFIG.get("actions_per_day", 3))
DAY_TIMEOUT_SECONDS = float(CONFIG.get("day_timeout_seconds", 120.0))
PLAYER_CONNECT_TIMEOUT_SECONDS = float(CONFIG.get("player_connect_timeout_seconds", 180.0))


class GameState:
    def __init__(self) -> None:
        self.episode = (
            Episode(seed=SEED, total_days=TOTAL_DAYS, budget=BUDGET, actions_per_day=ACTIONS_PER_DAY)
            if not REPLAY_MODE
            else None
        )
        self.player: WebSocket | None = None
        self.started = False
        self.done = False
        self.day_started_at = time.monotonic()
        self.protocol_errors_today = 0
        self.lock = asyncio.Lock()
        self.dirty = asyncio.Event()  # wakes global broadcasters


state = GameState()
server: uvicorn.Server


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = []
    if not REPLAY_MODE:
        tasks.append(asyncio.create_task(_connect_timeout_watchdog()))
        tasks.append(asyncio.create_task(_day_timeout_watchdog()))
    yield
    for task in tasks:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan)
app.mount("/client/assets", StaticFiles(directory=CLIENT_DIR / "assets"), name="assets")


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/client/player")
def player_client() -> HTMLResponse:
    return HTMLResponse((CLIENT_DIR / "player.html").read_text())


@app.get("/client/global")
def global_client() -> HTMLResponse:
    return HTMLResponse((CLIENT_DIR / "global.html").read_text())


@app.get("/client/replay")
def replay_client() -> HTMLResponse:
    return HTMLResponse((CLIENT_DIR / "replay.html").read_text())


@app.get("/client/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(CLIENT_DIR / "assets" / "favicon.png")


# ---------------------------------------------------------------------------
# Spectators and replay
# ---------------------------------------------------------------------------

def _global_snapshot() -> dict[str, Any]:
    episode = state.episode
    assert episode is not None
    return {**episode.snapshot(), "done": state.done, "player_names": PLAYER_NAMES}


@app.websocket("/global")
async def global_viewer(websocket: WebSocket) -> None:
    await websocket.accept()
    sender = asyncio.create_task(_send_global_snapshots(websocket))
    receiver = asyncio.create_task(_drain(websocket))
    _done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


async def _send_global_snapshots(websocket: WebSocket) -> None:
    if state.episode is None:
        return
    with suppress(WebSocketDisconnect, RuntimeError):
        await websocket.send_json(_global_snapshot())
        while not state.done:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(state.dirty.wait(), timeout=1.0)
            state.dirty.clear()
            await websocket.send_json(_global_snapshot())
        await websocket.send_json(_global_snapshot())


async def _drain(websocket: WebSocket) -> None:
    with suppress(WebSocketDisconnect):
        async for _ in websocket.iter_json():
            pass


@app.websocket("/replay")
async def replay_viewer(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "replay", **load_replay_data(REPLAY_LOAD_URI)})
    with suppress(WebSocketDisconnect):
        async for command in websocket.iter_json():
            await websocket.send_json({"type": "control", "command": command})


# ---------------------------------------------------------------------------
# The management seat
# ---------------------------------------------------------------------------

@app.websocket("/player")
async def player_socket(websocket: WebSocket) -> None:
    slot = int(websocket.query_params.get("slot", "0"))
    token = websocket.query_params.get("token", "")
    if slot != 0 or not TOKENS or TOKENS[0] != token:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    episode = state.episode
    assert episode is not None

    async with state.lock:
        if state.player is not None:
            await websocket.send_json({"type": "error", "code": "seat_taken",
                                       "message": "the management seat is already connected"})
            await websocket.close(code=1008)
            return
        state.player = websocket
        state.started = True
        state.day_started_at = time.monotonic()

    try:
        await websocket.send_json({**episode.handshake(), "world": episode.world()})
        await websocket.send_json(episode.dashboard())
        while not state.done:
            try:
                raw = await websocket.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                break
            for reply in await _handle_player_message(raw):
                await websocket.send_json(reply)
            if state.done:
                break
    finally:
        async with state.lock:
            if state.player is websocket:
                state.player = None
        if not state.done:
            # A disconnected player must never hang the episode: finish it with
            # no further interventions.
            asyncio.create_task(_finish_unattended())


async def _handle_player_message(raw: str) -> list[dict[str, Any]]:
    episode = state.episode
    assert episode is not None
    try:
        message = json.loads(raw)
        if not isinstance(message, dict):
            raise ValueError("message must be a JSON object")  # noqa: TRY004 - caught as protocol error below
    except ValueError:
        return await _protocol_error("bad_json", "message was not a JSON object")

    kind = message.get("type")
    async with state.lock:
        if kind == "inspect":
            result = episode.inspect(str(message.get("target_type", "")),
                                     _optional_str(message.get("target_id")))
            return [result.payload]
        if kind == "action":
            result = episode.submit_action(str(message.get("action", "")),
                                           _optional_str(message.get("target_id")))
            state.dirty.set()
            return [result.payload]
        if kind == "end_day":
            return await _advance_day("player")
    return await _protocol_error(
        "unknown_message_type",
        "expected one of: inspect, action, end_day",
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


async def _protocol_error(code: str, message: str) -> list[dict[str, Any]]:
    state.protocol_errors_today += 1
    if state.protocol_errors_today >= MAX_PROTOCOL_ERRORS_PER_DAY:
        async with state.lock:
            return await _advance_day("protocol_errors")
    return [{"type": "error", "code": code, "message": message}]


async def _advance_day(reason: str) -> list[dict[str, Any]]:
    """Caller must hold state.lock (or be single-threaded shutdown)."""
    episode = state.episode
    assert episode is not None
    payload = episode.end_day(reason=reason)
    state.day_started_at = time.monotonic()
    state.protocol_errors_today = 0
    state.dirty.set()
    if episode.finished and not state.done:
        await _finalize()
        return [payload]
    return [payload, episode.dashboard()]


async def _finalize() -> None:
    episode = state.episode
    assert episode is not None
    state.done = True
    results = episode.results()
    write_data(RESULTS_URI, json.dumps(results), content_type="application/json",
               http_method=artifact_method("COGAME_RESULTS_METHOD"))
    write_data(REPLAY_URI, json.dumps(episode.replay()), content_type="application/json",
               http_method=artifact_method("COGAME_SAVE_REPLAY_METHOD"))
    if state.player is not None:
        with suppress(Exception):
            await state.player.send_json({"type": "final", "done": True, "results": results})
    await asyncio.sleep(0.5)
    server.should_exit = True


async def _finish_unattended() -> None:
    async with state.lock:
        episode = state.episode
        assert episode is not None
        while not episode.finished and state.player is None and not state.done:
            await _advance_day("player_disconnected")


async def _connect_timeout_watchdog() -> None:
    await asyncio.sleep(PLAYER_CONNECT_TIMEOUT_SECONDS)
    if not state.started and not state.done:
        await _finish_unattended()


async def _day_timeout_watchdog() -> None:
    while not state.done:
        await asyncio.sleep(1.0)
        if not state.started or state.player is None or state.done:
            continue
        if time.monotonic() - state.day_started_at > DAY_TIMEOUT_SECONDS:
            async with state.lock:
                replies = await _advance_day("timeout")
            if state.player is not None:
                with suppress(Exception):
                    await state.player.send_json(
                        {"type": "error", "code": "day_timeout",
                         "message": "day ended automatically after the timeout"})
                    for reply in replies:
                        await state.player.send_json(reply)


if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config(app, host=GAME_HOST, port=GAME_PORT))
    server.run()
