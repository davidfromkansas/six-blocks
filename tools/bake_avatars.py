"""Bake Pirate Nation voxel avatars into an isometric sprite atlas.

The residents used to be an ellipse and a circle. These are the real CC0 avatars
from proofofplay/piratenation-art, sampled from their ``04_Walk`` animation and
rendered at CitySim's exact 2:1 isometric angle, four headings each.

They cannot be drawn live: one avatar is ~1,300 triangles, and a hundred
residents would be ~130k CPU-filled polygons per frame in a 2D canvas. So they
are baked once, offline, into a single atlas the renderer blits.

    python tools/bake_avatars.py --variants 6 --frames 4

Writes citysim/game/client/assets/generated/avatars.png and avatars.json.

Notes for whoever runs this next:
  * The art repo is Git LFS. github.com serves 130-byte pointer files; the real
    bytes come from media.githubusercontent.com/media/... .
  * The meshes are skinned, so a walk frame needs linear blend skinning against
    the animated joint matrices, not just node transforms.
  * The source is CC0 1.0 (public domain), so no attribution is required.
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = "proofofplay/piratenation-art"
LFS = f"https://media.githubusercontent.com/media/{REPO}/main/Voxel%20Game%20Assets/Avatar"
OUT_DIR = Path(__file__).resolve().parents[1] / "citysim/game/client/assets/generated"
CACHE = Path(__file__).resolve().parents[1] / "tmp/avatar-src"

# The scene's projection: sx = (x - y) * 0.92, sy = (x + y) * 0.46 - z.
ISO_X, ISO_Y = 0.92, 0.46
# Matches the renderer's box() shading so sprites sit in the same light.
LIGHT = np.array([-0.40, 0.85, 0.35])
LIGHT /= np.linalg.norm(LIGHT)


def fetch(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    local = CACHE / name.replace("/", "_")
    if not local.exists():
        url = f"{LFS}/{name}"
        with urllib.request.urlopen(url) as response:
            local.write_bytes(response.read())
    return local


class Gltf:
    def __init__(self, path: Path) -> None:
        self.g = json.loads(path.read_text())
        uri = self.g["buffers"][0]["uri"]
        self.buf = base64.b64decode(uri.split(",", 1)[1])
        self._cache: dict[int, np.ndarray] = {}

    def accessor(self, index: int) -> np.ndarray:
        if index in self._cache:
            return self._cache[index]
        a = self.g["accessors"][index]
        view = self.g["bufferViews"][a["bufferView"]]
        offset = view.get("byteOffset", 0) + a.get("byteOffset", 0)
        ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
        ctype = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}[a["componentType"]]
        size = struct.calcsize(ctype)
        stride = view.get("byteStride") or size * ncomp
        out = np.empty((a["count"], ncomp), dtype=np.dtype(ctype))
        for k in range(a["count"]):
            out[k] = struct.unpack_from("<" + ctype * ncomp, self.buf, offset + k * stride)
        self._cache[index] = out
        return out


def quat_matrix(q: np.ndarray) -> np.ndarray:
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0.0],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0.0],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ])


def slerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    dot = float(np.dot(a, b))
    if dot < 0.0:
        b, dot = -b, -dot
    if dot > 0.9995:
        out = a + t * (b - a)
        return out / np.linalg.norm(out)
    theta = np.arccos(np.clip(dot, -1.0, 1.0))
    sin = np.sin(theta)
    return (np.sin((1 - t) * theta) / sin) * a + (np.sin(t * theta) / sin) * b


def local_matrix(node: dict, override: dict) -> np.ndarray:
    if "matrix" in node and not override:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    scale = override.get("scale", node.get("scale", [1.0, 1.0, 1.0]))
    rot = override.get("rotation", node.get("rotation", [0.0, 0.0, 0.0, 1.0]))
    trans = override.get("translation", node.get("translation", [0.0, 0.0, 0.0]))
    M = quat_matrix(np.array(rot, dtype=float)) @ np.diag([*scale, 1.0])
    M[:3, 3] = trans
    return M


def sample_animation(gl: Gltf, anim_name: str, t01: float) -> dict[int, dict]:
    """Node-local TRS overrides for every animated node at a phase of the clip."""
    anim = next((a for a in gl.g["animations"] if a.get("name") == anim_name), None)
    if anim is None:
        return {}
    duration = 0.0
    for ch in anim["channels"]:
        times = gl.accessor(anim["samplers"][ch["sampler"]]["input"]).ravel()
        duration = max(duration, float(times[-1]))
    time = t01 * duration
    out: dict[int, dict] = {}
    for ch in anim["channels"]:
        sampler = anim["samplers"][ch["sampler"]]
        times = gl.accessor(sampler["input"]).ravel()
        values = gl.accessor(sampler["output"]).astype(float)
        target = ch["target"]
        node, path = target.get("node"), target["path"]
        if node is None or path == "weights":
            continue
        k = int(np.searchsorted(times, time, side="right") - 1)
        k = max(0, min(k, len(times) - 2)) if len(times) > 1 else 0
        if len(times) == 1:
            value = values[0]
        else:
            span = max(1e-9, float(times[k + 1] - times[k]))
            u = float(np.clip((time - times[k]) / span, 0.0, 1.0))
            if path == "rotation":
                value = slerp(values[k], values[k + 1], u)
            else:
                value = values[k] * (1 - u) + values[k + 1] * u
        out.setdefault(node, {})[path] = value.tolist()
    return out


def world_transforms(gl: Gltf, overrides: dict[int, dict]) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}

    def walk(ni: int, parent: np.ndarray) -> None:
        M = parent @ local_matrix(gl.g["nodes"][ni], overrides.get(ni, {}))
        out[ni] = M
        for child in gl.g["nodes"][ni].get("children", []):
            walk(child, M)

    for ni in gl.g["scenes"][gl.g.get("scene", 0)]["nodes"]:
        walk(ni, np.eye(4))
    return out


def base_color(gl: Gltf, prim: dict) -> tuple[int, int, int]:
    mi = prim.get("material")
    if mi is None:
        return (190, 190, 190)
    pbr = gl.g["materials"][mi].get("pbrMetallicRoughness", {})
    factor = pbr.get("baseColorFactor", [0.8, 0.8, 0.8, 1.0])
    # glTF factors are linear; the scene paints in sRGB.
    return tuple(int(255 * max(0.0, min(1.0, c)) ** (1 / 2.2)) for c in factor[:3])


def posed_triangles(gl: Gltf, anim: str, t01: float) -> list[tuple]:
    """World-space triangles for one animation frame, with skinning applied."""
    overrides = sample_animation(gl, anim, t01)
    world = world_transforms(gl, overrides)

    skin_matrices: dict[int, np.ndarray] = {}
    for si, skin in enumerate(gl.g.get("skins", [])):
        ibm = gl.accessor(skin["inverseBindMatrices"]).reshape(-1, 4, 4)
        mats = np.stack([
            world[joint] @ ibm[j].T for j, joint in enumerate(skin["joints"])
        ])
        skin_matrices[si] = mats

    tris: list[tuple] = []
    for ni, node in enumerate(gl.g["nodes"]):
        if "mesh" not in node:
            continue
        M = world[ni]
        mats = skin_matrices.get(node.get("skin"))
        for prim in gl.g["meshes"][node["mesh"]]["primitives"]:
            attrs = prim["attributes"]
            if "POSITION" not in attrs:
                continue
            V = gl.accessor(attrs["POSITION"]).astype(float)
            if mats is not None and "JOINTS_0" in attrs and "WEIGHTS_0" in attrs:
                J = gl.accessor(attrs["JOINTS_0"]).astype(int)
                W = gl.accessor(attrs["WEIGHTS_0"]).astype(float)
                total = W.sum(axis=1, keepdims=True)
                W = np.divide(W, total, out=np.zeros_like(W), where=total > 1e-8)
                homo = np.c_[V, np.ones(len(V))]
                out = np.zeros((len(V), 4))
                for k in range(J.shape[1]):
                    out += W[:, k : k + 1] * np.einsum("nij,nj->ni", mats[J[:, k]], homo)
                V = out[:, :3]
            else:
                V = (M @ np.c_[V, np.ones(len(V))].T).T[:, :3]
            idx = gl.accessor(prim["indices"]).ravel() if "indices" in prim else np.arange(len(V))
            colour = base_color(gl, prim)
            for k in range(0, len(idx) - 2, 3):
                tris.append((V[idx[k]], V[idx[k + 1]], V[idx[k + 2]], colour))
    return tris


def _framing(heading: int, lo: np.ndarray, hi: np.ndarray):
    """The spin/project pair for one heading, independent of any fitting."""
    theta = np.radians(90.0 * heading)
    cos, sin = np.cos(theta), np.sin(theta)
    centre = np.array([(lo[0] + hi[0]) / 2, 0.0, (lo[2] + hi[2]) / 2])

    def spin(v: np.ndarray) -> np.ndarray:
        d = v - centre
        return np.array([d[0] * cos - d[2] * sin, v[1] - lo[1], d[0] * sin + d[2] * cos])

    def flat(s: np.ndarray) -> tuple[float, float]:
        return ((s[0] - s[2]) * ISO_X, (s[0] + s[2]) * ISO_Y - s[1])

    return spin, flat


def measure(tris: list[tuple], heading: int, lo, hi) -> np.ndarray:
    """Projected silhouette bounds of one posed frame, in model units."""
    spin, flat = _framing(heading, lo, hi)
    pts = np.array([flat(spin(v)) for t in tris for v in t[:3]])
    return np.array([pts.min(0), pts.max(0)])


def render_tile(tris: list[tuple], heading: int, tile: tuple[int, int], lo, hi,
                scale: float, anchor: np.ndarray, super_sample: int = 3) -> Image.Image:
    """Project one posed avatar at a shared scale, so it does not pulse mid-stride."""
    tw, th = tile
    W, H = tw * super_sample, th * super_sample
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    spin, flat = _framing(heading, lo, hi)
    s = scale * super_sample
    offx = W / 2 - (anchor[0] + anchor[2]) / 2 * s
    offy = H - 2.0 * super_sample - anchor[3] * s

    def proj(v: np.ndarray) -> tuple[float, float]:
        fx, fy = flat(spin(v))
        return (fx * s + offx, fy * s + offy)

    def depth(t: tuple) -> float:
        return sum(float(spin(v)[0] + spin(v)[2]) for v in t[:3])

    for a, b, c, colour in sorted(tris, key=depth):
        normal = np.cross(b - a, c - a)
        norm = np.linalg.norm(normal)
        if norm < 1e-12:
            continue
        shade = 0.58 + 0.42 * max(0.0, float(np.dot(normal / norm, LIGHT)))
        draw.polygon(
            [proj(a), proj(b), proj(c)],
            fill=(int(colour[0] * shade), int(colour[1] * shade), int(colour[2] * shade), 255),
        )
    return img.resize((tw, th), Image.LANCZOS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", type=int, default=6, help="how many hero avatars")
    parser.add_argument("--frames", type=int, default=4, help="walk-cycle frames per heading")
    parser.add_argument("--tile", type=int, nargs=2, default=(34, 46))
    parser.add_argument("--anim", default="04_Walk")
    args = parser.parse_args()

    headings = 4
    tw, th = args.tile

    # Pose every frame first, so one shared scale can be fitted across the whole
    # cast. Fitting per tile would make each figure breathe as its arms swing,
    # and fitting per variant would flatten their real height differences.
    posed: list[dict] = []
    for v in range(args.variants):
        name = f"heroes/hero_{v + 1:03d}.gltf"
        print(f"  posing {name}")
        gl = Gltf(fetch(name))
        rest = posed_triangles(gl, args.anim, 0.0)
        P = np.array([t[:3] for t in rest]).reshape(-1, 3)
        lo, hi = P.min(0), P.max(0)
        frames = [posed_triangles(gl, args.anim, f / args.frames) for f in range(args.frames)]
        bounds = np.array([measure(tris, h, lo, hi) for tris in frames for h in range(headings)])
        posed.append({
            "lo": lo, "hi": hi, "frames": frames,
            # x-extent and floor of this variant across every frame and heading
            "anchor": np.array([
                bounds[:, 0, 0].min(), 0.0, bounds[:, 1, 0].max(), bounds[:, 1, 1].max(),
            ]),
            "span": np.array([
                bounds[:, 1, 0].max() - bounds[:, 0, 0].min(),
                bounds[:, 1, 1].max() - bounds[:, 0, 1].min(),
            ]),
        })

    widest = max(a["span"][0] for a in posed)
    tallest = max(a["span"][1] for a in posed)
    scale = min(tw * 0.94 / widest, th * 0.94 / tallest)

    tiles: list[Image.Image] = []
    for a in posed:
        for tris in a["frames"]:
            for h in range(headings):
                tiles.append(render_tile(tris, h, (tw, th), a["lo"], a["hi"], scale, a["anchor"]))

    cols = headings * args.frames
    rows = args.variants
    atlas = Image.new("RGBA", (cols * tw, rows * th), (0, 0, 0, 0))
    for i, tile in enumerate(tiles):
        atlas.paste(tile, ((i % cols) * tw, (i // cols) * th))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    atlas.save(OUT_DIR / "avatars.png")
    (OUT_DIR / "avatars.json").write_text(json.dumps({
        "source": f"https://github.com/{REPO} (CC0 1.0)",
        "animation": args.anim,
        "tile": [tw, th],
        "variants": args.variants,
        "frames": args.frames,
        "headings": headings,
        "order": "row = variant, col = frame * headings + heading",
    }, indent=2) + "\n")
    size_kb = (OUT_DIR / "avatars.png").stat().st_size / 1024
    print(f"atlas {atlas.size[0]}x{atlas.size[1]}  {len(tiles)} tiles  {size_kb:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
