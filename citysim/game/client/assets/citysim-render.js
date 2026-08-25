/* CitySim p5.js world renderer — isometric diorama edition.
 *
 * Draws the whole neighborhood as a floating "tabletop diorama": an isometric
 * earth slab with a dirt cross-section, extruded buildings with lit/shaded
 * faces, streets, parks, props, residents, and vehicles. Everything is
 * procedural: no bitmap art, deterministic seeded variation (same seed ->
 * same city). Used unchanged by the live player, spectator, and replay clients.
 *
 * API (unchanged):
 *   const renderer = new CitySimRenderer(containerId, { onHover(id, kind) });
 *   renderer.setWorld(world);           // static geometry, once
 *   renderer.setFrame(frame);           // per-day simulation frame
 *   renderer.setDay(day);
 *   Debug overlay: press "d" or call renderer.toggleDebug().
 */
"use strict";

/* Deterministic PRNG (mulberry32) + string hash so visual jitter is seeded. */
function sbHash(str) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
function sbRng(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* Diorama palette: warm paper background, toy-like saturated props. */
const SB = {
  paper: [246, 243, 237],
  street: [178, 176, 172],
  streetLine: [236, 232, 220],
  sidewalk: [214, 210, 200],
  crosswalk: [244, 242, 234],
  bikeLane: [104, 156, 118],
  grass: [140, 186, 106],
  yard: [171, 166, 154],
  yardWarm: [186, 176, 156],
  grassDark: [112, 158, 88],
  parkGreen: [110, 168, 92],
  dirtTop: [148, 108, 76],
  dirtSide: [116, 82, 56],
  dirtDark: [92, 62, 42],
  water: [96, 148, 190],
  night: [30, 32, 52],
  shadow: [60, 60, 70],
};

const WALL_H = 13;      // world units of height per building floor
const SLAB_D = 46;      // dirt slab depth (screen units before scale)

function shade(rgb, f) {
  return [rgb[0] * f, rgb[1] * f, rgb[2] * f];
}

class CitySimRenderer {
  constructor(containerId, opts) {
    this.opts = opts || {};
    this.world = null;
    this.frame = null;
    this.day = 1;
    this.debug = false;
    this.time = 0;
    this.walkers = [];
    this.vehicles = [];
    this.blockRow = {};
    this.scale = 1;
    this.ox = 0;
    this.oy = 0;
    this.hovered = null;

    const self = this;
    this.p5 = new p5(function (p) {
      self.p = p;
      p.setup = function () {
        const el = document.getElementById(containerId);
        const c = p.createCanvas(el.clientWidth, el.clientHeight);
        c.parent(containerId);
        p.frameRate(30);
        p.textFont("Georgia");
      };
      p.windowResized = function () {
        const el = document.getElementById(containerId);
        p.resizeCanvas(el.clientWidth, el.clientHeight);
      };
      p.keyPressed = function () {
        if (p.key === "d" || p.key === "D") self.debug = !self.debug;
      };
      p.draw = function () { self.drawAll(); };
      p.mouseMoved = function () { self.pickHover(); };
    });
  }

  toggleDebug() { this.debug = !this.debug; }

  setWorld(world) {
    this.world = world;
    this.byId = {};
    world.blocks.forEach((b) => (this.byId[b.id] = b));
    world.buildings.forEach((b) => (this.byId[b.id] = b));
    this.seedWalkersAndVehicles();
  }

  setFrame(frame) {
    this.frame = frame;
    this.blockRow = {};
    if (frame && frame.blocks) frame.blocks.forEach((b) => (this.blockRow[b.block_id] = b));
  }

  setDay(day) { this.day = day; }

  /* ----- isometric projection ------------------------------------------- */
  /* World (x, y) on the ground plane, z up. Screen: 2:1 diamond iso. */

  iso(x, y, z) {
    const sx = (x - y) * 0.92;
    const sy = (x + y) * 0.46 - (z || 0);
    return [this.ox + sx * this.scale, this.oy + sy * this.scale];
  }

  unproject(mx, my) {
    const sx = (mx - this.ox) / this.scale;
    const sy = (my - this.oy) / this.scale;
    const a = sx / 0.92, b = sy / 0.46;
    return [(b + a) / 2, (b - a) / 2];
  }

  fitProjection() {
    const p = this.p, w = this.world;
    const maxZ = 108;
    const cxMin = (0 - w.height) * 0.92, cxMax = (w.width - 0) * 0.92;
    const cyMin = -maxZ, cyMax = (w.width + w.height) * 0.46 + SLAB_D + 26;
    const pad = 18;
    this.scale = Math.min(
      p.width / (cxMax - cxMin + pad * 2),
      p.height / (cyMax - cyMin + pad * 2)
    );
    this.ox = p.width / 2 - ((cxMin + cxMax) / 2) * this.scale;
    this.oy = p.height / 2 - ((cyMin + cyMax) / 2) * this.scale;
  }

  /* Fill a quad given four world-space [x,y,z] corners. */
  quad3(a, b, c, d) {
    const p = this.p;
    const A = this.iso(a[0], a[1], a[2]), B = this.iso(b[0], b[1], b[2]);
    const C = this.iso(c[0], c[1], c[2]), D = this.iso(d[0], d[1], d[2]);
    p.quad(A[0], A[1], B[0], B[1], C[0], C[1], D[0], D[1]);
  }

  /* Ground-plane rect (z = 0). */
  gRect(x, y, w, h, z) {
    this.quad3([x, y, z || 0], [x + w, y, z || 0], [x + w, y + h, z || 0], [x, y + h, z || 0]);
  }

  /* Extruded box with shaded faces. base rect (x,y,w,h), from z0 up to z1. */
  box(x, y, w, h, z0, z1, rgb, opts) {
    const p = this.p;
    const o = opts || {};
    p.noStroke();
    // Right face (x+w side) — darkest.
    p.fill(...shade(rgb, o.rightF || 0.62));
    this.quad3([x + w, y, z1], [x + w, y + h, z1], [x + w, y + h, z0], [x + w, y, z0]);
    // Left/front face (y+h side) — mid tone.
    p.fill(...shade(rgb, o.frontF || 0.8));
    this.quad3([x, y + h, z1], [x + w, y + h, z1], [x + w, y + h, z0], [x, y + h, z0]);
    // Top face — full color.
    p.fill(...shade(rgb, o.topF || 1.0));
    this.quad3([x, y, z1], [x + w, y, z1], [x + w, y + h, z1], [x, y + h, z1]);
  }

  /* ----- deterministic ambient population ------------------------------- */

  seedWalkersAndVehicles() {
    const w = this.world;
    const rng = sbRng(sbHash("walkers:" + w.seed));
    this.walkers = w.residents.map((r) => {
      const block = this.byId[r.home_block_id];
      return {
        id: r.id, block_id: r.home_block_id, mode: r.commute_mode,
        px: block.rect.x + rng() * block.rect.w,
        py: block.rect.y + block.rect.h + 6 + rng() * 10, // home sidewalk
        phase: rng() * Math.PI * 2, speed: 0.35 + rng() * 0.5,
        hue: Math.floor(rng() * 360), range: 40 + rng() * 140,
        bubble: rng() < 0.22, bubblePhase: rng() * 40,
      };
    });
    const vr = sbRng(sbHash("vehicles:" + w.seed));
    this.vehicles = [];
    for (let i = 0; i < 9; i++) {
      this.vehicles.push({
        kind: i < 2 ? "bus" : (vr() < 0.55 ? "cab" : "car"),
        horizontal: vr() < 0.5, lane: Math.floor(vr() * 3),
        offset: vr() * 2000, speed: 26 + vr() * 34, hue: Math.floor(vr() * 360),
      });
    }
  }

  /* ----- main draw ------------------------------------------------------ */

  drawAll() {
    const p = this.p;
    if (!this.world) { p.background(SB.paper[0], SB.paper[1], SB.paper[2]); return; }
    this.time = p.millis() / 1000;
    const w = this.world;
    this.fitProjection();

    p.background(SB.paper[0], SB.paper[1], SB.paper[2]);
    this.drawSlab();
    this.drawGround();
    this.drawStreets();
    w.blocks.forEach((b) => this.drawBlockGround(b));
    this.drawCrosswalks();
    this.drawGroundOverlays();

    // Depth-sorted solid objects (painter's algorithm on x + y at base).
    const items = [];
    w.buildings.forEach((b) => items.push({
      d: b.rect.x + b.rect.w + b.rect.y + b.rect.h, f: () => this.drawBuilding(b),
    }));
    w.blocks.forEach((b) => this.collectFurniture(b, items));
    this.collectVehicles(items);
    this.collectWalkers(items);
    items.sort((a, b) => a.d - b.d);
    items.forEach((it) => it.f());

    this.drawSkyTint();
    this.drawHover();
    w.blocks.forEach((b) => this.drawBlockLabel(b));
    if (this.debug) this.drawDebug();
  }

  /* Floating earth slab: grass rim + dirt cross-section under the city. */
  drawSlab() {
    const p = this.p, w = this.world;
    const m = 14; // grass apron beyond the street grid
    const x0 = -m, y0 = -m, x1 = w.width + m, y1 = w.height + m;
    p.noStroke();
    // Soft drop shadow under the floating slab.
    const S = this.iso((x0 + x1) / 2, (y0 + y1) / 2, -SLAB_D - 10);
    p.fill(SB.shadow[0], SB.shadow[1], SB.shadow[2], 26);
    p.ellipse(S[0], S[1] + 14 * this.scale, (x1 - x0) * 1.5 * this.scale, (y1 - y0) * 0.62 * this.scale);
    // Dirt sides with strata.
    p.fill(...SB.dirtSide);
    this.quad3([x0, y1, 0], [x1, y1, 0], [x1, y1, -SLAB_D], [x0, y1, -SLAB_D]);
    p.fill(...SB.dirtDark);
    this.quad3([x1, y0, 0], [x1, y1, 0], [x1, y1, -SLAB_D], [x1, y0, -SLAB_D]);
    // Strata lines + embedded rocks for the cross-section look.
    const rng = sbRng(sbHash("slab:" + w.seed));
    p.fill(SB.dirtDark[0], SB.dirtDark[1], SB.dirtDark[2], 120);
    for (let i = 1; i < 4; i++) {
      const z = -(SLAB_D / 4) * i;
      this.quad3([x0, y1, z], [x1, y1, z], [x1, y1, z - 2], [x0, y1, z - 2]);
    }
    p.fill(168, 148, 128, 200);
    for (let i = 0; i < 16; i++) {
      const rx = x0 + rng() * (x1 - x0), rz = -6 - rng() * (SLAB_D - 12);
      const R = this.iso(rx, y1, rz);
      p.ellipse(R[0], R[1], (3 + rng() * 5) * this.scale, (2 + rng() * 3) * this.scale);
    }
    // Grass rim on top.
    p.fill(...SB.grass);
    this.gRect(x0, y0, x1 - x0, y1 - y0, 0);
    // Grass tufts on the apron.
    p.fill(...SB.grassDark);
    for (let i = 0; i < 60; i++) {
      const gx = x0 + rng() * (x1 - x0), gy = y0 + rng() * (y1 - y0);
      if (gx > -3 && gx < w.width + 3 && gy > -3 && gy < w.height + 3) continue;
      const G = this.iso(gx, gy, 0);
      p.ellipse(G[0], G[1], 3.4 * this.scale, 1.8 * this.scale);
    }
  }

  drawGround() {
    // Street bed across the whole city rectangle; blocks are drawn on top.
    const p = this.p, w = this.world;
    p.noStroke();
    p.fill(...SB.street);
    this.gRect(0, 0, w.width, w.height, 0);
  }

  streetRects() {
    const w = this.world;
    const xs = [...new Set(w.blocks.map((b) => b.rect.x))].sort((a, b) => a - b);
    const ys = [...new Set(w.blocks.map((b) => b.rect.y))].sort((a, b) => a - b);
    const bw = w.blocks[0].rect.w, bh = w.blocks[0].rect.h;
    const v = [], h = [];
    for (let i = 0; i < xs.length - 1; i++) v.push([xs[i] + bw, xs[i + 1]]);
    for (let i = 0; i < ys.length - 1; i++) h.push([ys[i] + bh, ys[i + 1]]);
    return { v, h, xs, ys, bw, bh };
  }

  drawStreets() {
    const p = this.p, w = this.world;
    const { v, h } = this.streetRects();
    // Lane dashes.
    p.noStroke();
    p.fill(SB.streetLine[0], SB.streetLine[1], SB.streetLine[2], 210);
    v.forEach(([x0, x1]) => {
      const mid = (x0 + x1) / 2;
      for (let y = 4; y < w.height - 4; y += 30) this.gRect(mid - 1, y, 2, 14, 0.1);
    });
    h.forEach(([y0, y1]) => {
      const mid = (y0 + y1) / 2;
      for (let x = 4; x < w.width - 4; x += 30) this.gRect(x, mid - 1, 14, 2, 0.1);
    });
    // Bike lanes hug the block edges where capacity exists.
    w.blocks.forEach((b) => {
      const row = this.blockRow[b.id];
      if (!row || (row.bike_capacity || 0) < 25) return;
      p.fill(SB.bikeLane[0], SB.bikeLane[1], SB.bikeLane[2], 220);
      this.gRect(b.rect.x - 9, b.rect.y - 9, b.rect.w + 18, 3, 0.1);
    });
  }

  drawCrosswalks() {
    const p = this.p, w = this.world;
    p.noStroke();
    p.fill(SB.crosswalk[0], SB.crosswalk[1], SB.crosswalk[2], 220);
    w.blocks.forEach((b) => {
      const r = b.rect;
      for (let i = 0; i < 5; i++) {
        if (r.x + r.w + 30 < w.width) this.gRect(r.x + r.w + 9, r.y + 14 + i * 9, 18, 4, 0.15);
        if (r.y + r.h + 30 < w.height) this.gRect(r.x + 14 + i * 9, r.y + r.h + 9, 4, 18, 0.15);
      }
    });
  }

  drawBlockGround(b) {
    const p = this.p, r = b.rect;
    // Raised sidewalk curb: a very shallow box gives the diorama a tactile edge.
    this.box(r.x - 7, r.y - 7, r.w + 14, r.h + 14, 0, 1.6, SB.sidewalk);
    // Interior ground, tinted by cleanliness.
    const row = this.blockRow[b.id] || {};
    const clean = row.cleanliness == null ? 65 : row.cleanliness;
    const dirt = Math.max(0, 65 - clean) / 65;
    p.noStroke();
    p.fill(
      SB.yard[0] * (1 - dirt) + 142 * dirt,
      SB.yard[1] * (1 - dirt) + 122 * dirt,
      SB.yard[2] * (1 - dirt) + 94 * dirt
    );
    this.gRect(r.x, r.y, r.w, r.h, 1.6);
    // Back gardens: a seeded scatter of green behind the streetwall, so the block
    // interior is not a dead plane but never competes with a real park.
    const grng = sbRng(sbHash("yard:" + b.id));
    p.fill(SB.grassDark[0], SB.grassDark[1], SB.grassDark[2], 150 * (1 - dirt * 0.7));
    for (let i = 0; i < 7; i++) {
      const gx = r.x + 12 + grng() * (r.w - 40);
      const gy = r.y + r.h * 0.40 + grng() * (r.h * 0.20);
      this.gRect(gx, gy, 16 + grng() * 22, 7 + grng() * 6, 1.65);
    }
    // Litter specks when dirty.
    if (dirt > 0.25) {
      const rng = sbRng(sbHash("litter:" + b.id + ":" + this.day));
      p.fill(110, 96, 78, 200);
      const n = Math.floor(dirt * 26);
      for (let i = 0; i < n; i++) {
        const L = this.iso(r.x + rng() * r.w, r.y + rng() * r.h, 1.7);
        p.ellipse(L[0], L[1], 2.6 * this.scale, 1.5 * this.scale);
      }
    }
  }

  /* Flat overlays that belong to the ground plane (flood water, outage tint). */
  drawGroundOverlays() {
    const p = this.p;
    const events = (this.frame && this.frame.events) || [];
    this.world.blocks.forEach((b) => {
      const r = b.rect;
      events.forEach((ev) => {
        const hits = ev.citywide || (ev.block_ids || []).includes(b.id);
        if (!hits) return;
        if (ev.kind === "flash_flood") {
          p.noStroke();
          p.fill(SB.water[0], SB.water[1], SB.water[2], 150);
          this.gRect(r.x - 9, r.y + r.h * 0.5, r.w + 18, r.h * 0.5 + 9, 1.8);
          // ripples
          p.fill(255, 255, 255, 70);
          const t = Math.sin(this.time * 2) * 2;
          this.gRect(r.x + 6 + t, r.y + r.h * 0.66, r.w * 0.4, 1.4, 1.9);
        } else if (ev.kind === "power_outage") {
          p.noStroke();
          p.fill(SB.night[0], SB.night[1], SB.night[2], 90);
          this.gRect(r.x - 9, r.y - 9, r.w + 18, r.h + 18, 1.85);
        }
      });
    });
  }

  /* ----- buildings ------------------------------------------------------ */

  /* An "open_space" lot carries its real type in `service` (park | playground |
   * plaza). The kind field is always "open_space", so branch on the service. */
  openSpaceKind(b) {
    if (b.kind === "open_space") return b.service || "park";
    if (b.kind === "park" || b.kind === "playground" || b.kind === "plaza") return b.kind;
    return null;
  }

  /* Ground shadow cast east of a volume, so buildings sit on the street rather
   * than float above it. Two offset quads approximate a soft edge. */
  drawShadow(x, y, w, h, height) {
    const p = this.p;
    const k = height * 0.30;
    p.noStroke();
    p.fill(64, 58, 62, 34);
    this.quad3([x + k * 1.25, y - k * 1.25, 1.72], [x + w + k * 1.25, y - k * 1.25, 1.72],
               [x + w + k * 1.25, y + h - k * 1.25, 1.72], [x + k * 1.25, y + h - k * 1.25, 1.72]);
    p.fill(58, 52, 58, 46);
    this.quad3([x + k * 0.5, y - k * 0.5, 1.74], [x + w + k * 0.5, y - k * 0.5, 1.74],
               [x + w + k * 0.5, y + h - k * 0.5, 1.74], [x + k * 0.5, y + h - k * 0.5, 1.74]);
  }

  drawBuilding(b) {
    const r = b.rect;
    const rng = sbRng(sbHash("bld:" + b.id));
    const open = this.openSpaceKind(b);
    if (open) { this.drawOpenSpace(b, open, rng); return; }

    // Which elevation faces a street? The camera sees the +y face, so a lot on the
    // south frontage shows its storefront and cornice, while the north row shows a
    // plainer rear elevation across the block's shared yard.
    const block = this.byId[b.block_id];
    const facesStreet = !block || (r.y + r.h) >= block.rect.y + block.rect.h - 1.0;

    // The lot is a run of party-walled bays, not one monolithic volume: a wide
    // frontage becomes four narrow SoHo lofts sharing walls, each with its own
    // facade tone and cornice height.
    const bays = Math.max(1, Math.min(6, Math.round(r.w / 44)));
    // A business occupies one storefront, not the whole row of them.
    const shopBay = Math.floor(sbRng(sbHash("shop:" + b.id))() * Math.max(1, Math.min(6, Math.round(r.w / 44))));
    const bayW = r.w / bays;
    const isBrick = rng() < 0.58 && b.kind !== "civic";
    const baseFloors = Math.max(2, b.floors);
    const zBase = 1.6;
    const topOf = (fl) => zBase + fl * WALL_H * (0.8 + (b.quality / 100) * 0.2);
    this.drawShadow(r.x, r.y, r.w, r.h, topOf(baseFloors));

    for (let i = 0; i < bays; i++) {
      const brng = sbRng(sbHash("bay:" + b.id + ":" + i));
      // Neighbouring bays jog by a floor so the roofline steps like a real row.
      const jog = bays === 1 ? 0 : (i % 2 === 0 ? 0 : (brng() < 0.55 ? 1 : 0)) - (brng() < 0.2 ? 1 : 0);
      const floors = Math.max(2, baseFloors + jog);
      this.drawBay(b, r.x + i * bayW, r.y, bayW, r.h, floors, topOf(floors),
                   isBrick, facesStreet, i === bays - 1, i === shopBay, brng);
    }
  }

  /* One party-walled bay: massing, cornice, string courses, windows, and — on a
   * street elevation — the cast-iron storefront at grade. */
  drawBay(b, bx, by, bw, bh, floors, zTop, isBrick, facesStreet, isLast, isShopBay, rng) {
    const p = this.p;
    const brickTones = [[168, 92, 70], [154, 82, 64], [176, 104, 78], [140, 76, 62]];
    const ironTones = [
      [236, 226, 206], [226, 214, 190], [218, 200, 172], [210, 194, 162],
      [200, 186, 168], [190, 176, 144], [176, 182, 164], [208, 182, 148],
    ];
    const tones = isBrick ? brickTones : ironTones;
    const rgb = b.kind === "civic" ? [226, 220, 206] : tones[Math.floor(rng() * tones.length)];
    const zBase = 1.6;
    this.box(bx, by, bw, bh, zBase, zTop, rgb);

    const winLit = [255, 236, 170];
    const glass = isBrick ? [58, 62, 78] : [72, 84, 102];
    const winRight = shade(glass, 0.72);
    const trim = isBrick ? shade(rgb, 1.22) : [246, 240, 226];
    const zH = zTop - zBase;
    const fz = (t) => zBase + zH * t;
    const face = by + bh;                       // the elevation the camera sees
    const cols = Math.max(2, Math.min(4, Math.round(bw / 15)));
    const colsR = Math.max(2, Math.min(5, Math.round(bh / 17)));
    const lightShare = this.windowLightShare();
    p.noStroke();

    if (facesStreet) {
      // Cast-iron storefront: dark glazing between slender columns.
      p.fill(...shade(glass, 0.85));
      this.quad3([bx, face, fz(0.02)], [bx + bw, face, fz(0.02)],
                 [bx + bw, face, fz(0.82 / floors)], [bx, face, fz(0.82 / floors)]);
      p.fill(...shade(trim, 0.94));
      for (let j = 0; j <= cols; j++) {
        const cx = bx + j * (bw / cols);
        this.quad3([cx - 0.7, face, fz(0.02)], [cx + 0.7, face, fz(0.02)],
                   [cx + 0.7, face, fz(0.86 / floors)], [cx - 0.7, face, fz(0.86 / floors)]);
      }
    }

    for (let fl = 1; fl < floors; fl++) {
      const z0 = fz((fl + 0.18) / floors);
      const z1 = fz((fl + 0.78) / floors);
      const zArc = fz((fl + 0.9) / floors);
      for (let j = 0; j < cols; j++) {
        const wc = bx + (j + 0.5) * (bw / cols);
        const hw = (bw / cols) * 0.27;
        const lit = rng() < lightShare;
        p.fill(...(lit ? winLit : glass));
        this.quad3([wc - hw, face, z1], [wc + hw, face, z1], [wc + hw, face, z0], [wc - hw, face, z0]);
        this.quad3([wc - hw * 0.6, face, zArc], [wc + hw * 0.6, face, zArc],
                   [wc + hw, face, z1], [wc - hw, face, z1]);
        p.fill(...trim);
        this.quad3([wc - hw - 0.5, face, z0], [wc + hw + 0.5, face, z0],
                   [wc + hw + 0.5, face, fz((fl + 0.12) / floors)],
                   [wc - hw - 0.5, face, fz((fl + 0.12) / floors)]);
      }
      if (isLast) {
        for (let j = 0; j < colsR; j++) {
          const wc = by + (j + 0.5) * (bh / colsR);
          const hw = (bh / colsR) * 0.26;
          p.fill(...(rng() < lightShare * 0.7 ? winLit : winRight));
          this.quad3([bx + bw, wc - hw, z1], [bx + bw, wc + hw, z1],
                     [bx + bw, wc + hw, z0], [bx + bw, wc - hw, z0]);
          this.quad3([bx + bw, wc - hw * 0.6, zArc], [bx + bw, wc + hw * 0.6, zArc],
                     [bx + bw, wc + hw, z1], [bx + bw, wc - hw, z1]);
        }
      }
      p.fill(...shade(trim, 0.9));
      this.quad3([bx, face, fz(fl / floors)], [bx + bw, face, fz(fl / floors)],
                 [bx + bw, face, fz(fl / floors + 0.012)], [bx, face, fz(fl / floors + 0.012)]);
    }

    // Party-wall pilasters: a hairline strip at each bay edge reads as the seam
    // between two buildings that share a wall.
    p.fill(...shade(rgb, 0.86));
    this.quad3([bx, face, fz(0.02)], [bx + 1.0, face, fz(0.02)],
               [bx + 1.0, face, fz(1)], [bx, face, fz(1)]);

    // Tarred roof deck, then a cornice *ring* around it. Drawing the cornice as a
    // solid box would paint the whole roof in facade cream and flatten the massing
    // into a shed; a real roof is a dark surface inside a projecting cap.
    const over = facesStreet ? 1.6 : 0.9;
    const cornice = isBrick ? shade(rgb, 0.9) : trim;
    // Tar is a warm neutral grey; deriving it straight from the facade makes a
    // brick row read as a field of near-black roofs.
    const deck = [
      rgb[0] * 0.22 + 92 * 0.78, rgb[1] * 0.22 + 88 * 0.78, rgb[2] * 0.22 + 84 * 0.78,
    ];
    p.fill(deck[0], deck[1], deck[2]);
    this.gRect(bx - over, by - over, bw + over * 2, bh + over * 2, zTop + 2.05);
    // Roof seams: shallow banding so the deck is not a dead flat plane.
    p.fill(...shade(deck, 1.12));
    for (let sy = by - over + 5; sy < by + bh + over - 2; sy += 9) {
      this.gRect(bx - over, sy, bw + over * 2, 0.9, zTop + 2.07);
    }
    this.box(bx - over, by - over, bw + over * 2, 1.4, zTop, zTop + 2.1, cornice);
    this.box(bx - over, by - over, 1.4, bh + over * 2, zTop, zTop + 2.1, cornice);
    this.box(bx + bw + over - 1.4, by - over, 1.4, bh + over * 2, zTop, zTop + 2.1, cornice);
    this.box(bx - over, by + bh + over - 1.4, bw + over * 2, 1.4, zTop, zTop + 2.1, cornice);

    // Fire escape on brick street elevations.
    if (isBrick && floors >= 3 && facesStreet) {
      const ex0 = bx + bw * 0.28, ex1 = bx + bw * 0.66;
      p.stroke(46, 48, 52, 220);
      p.strokeWeight(Math.max(0.8, this.scale * 0.7));
      for (let fl = 1; fl < floors; fl++) {
        const zA = fz((fl + 0.2) / floors), zB = fz((fl + 1.0) / floors);
        const A = this.iso(ex0, face, zA), B = this.iso(ex1, face, zA);
        const C = this.iso(fl % 2 ? ex1 : ex0, face, zB);
        p.line(A[0], A[1], B[0], B[1]);
        const S = fl % 2 ? B : A;
        p.line(S[0], S[1], C[0], C[1]);
      }
      p.noStroke();
    }

    // Roof furniture: timber water tank on the taller bays, bulkhead otherwise.
    if (floors >= 5 && rng() < 0.55) {
      const tx = bx + bw * (0.3 + rng() * 0.3), ty = by + bh * (0.3 + rng() * 0.35);
      this.box(tx, ty, 7, 7, zTop + 2.1, zTop + 9.8, [122, 88, 60]);
      const T = this.iso(tx + 3.5, ty + 3.5, zTop + 10.6);
      p.noStroke(); p.fill(96, 66, 44);
      p.ellipse(T[0], T[1], 9 * this.scale, 4.8 * this.scale);
    } else if (rng() < 0.45) {
      this.box(bx + bw * 0.5, by + bh * 0.3, 5.5, 5.5, zTop + 2.1, zTop + 4.9, [176, 176, 182]);
    }

    // Storefront awning + a lit shop window when this lot carries a business.
    if (b.business_id && facesStreet && isShopBay) {
      const arng = sbRng(sbHash("awn:" + b.id));
      const shut = this.businessClosed(b.business_id);
      if (shut) {
        // A shuttered storefront reads as a closed business at a glance.
        p.noStroke(); p.fill(126, 122, 116);
        this.quad3([bx + 1, face, fz(0.03)], [bx + bw - 1, face, fz(0.03)],
                   [bx + bw - 1, face, fz(0.78 / floors)], [bx + 1, face, fz(0.78 / floors)]);
      } else {
        const aw = [170 + arng() * 60, 60 + arng() * 90, 60 + arng() * 40];
        p.noStroke(); p.fill(aw[0], aw[1], aw[2], 245);
        this.quad3([bx, face, 8.4], [bx + bw, face, 8.4],
                   [bx + bw, face + 4, 4.4], [bx, face + 4, 4.4]);
        p.fill(255, 246, 222, 250);
        for (let x = bx + 1.5; x < bx + bw - 3; x += 7) {
          this.quad3([x, face, 8.4], [x + 3.5, face, 8.4],
                     [x + 3.5, face + 4, 4.4], [x, face + 4, 4.4]);
        }
      }
    }

    if (b.kind === "civic" && isLast) {
      const F = this.iso(bx + bw - 4, by + 3, zTop + 2.1);
      const Ft = this.iso(bx + bw - 4, by + 3, zTop + 12);
      p.stroke(210); p.strokeWeight(Math.max(1, this.scale));
      p.line(F[0], F[1], Ft[0], Ft[1]);
      p.noStroke(); p.fill(90, 130, 190);
      p.triangle(Ft[0], Ft[1], Ft[0], Ft[1] + 4 * this.scale, Ft[0] + 7 * this.scale, Ft[1] + 2 * this.scale);
    }
  }

  /* Share of windows lit — low by day, high when the neighborhood is doing well,
   * and knocked out entirely by a power outage. Reads as occupancy at a glance. */
  windowLightShare() {
    const events = (this.frame && this.frame.events) || [];
    if (events.some((e) => e.kind === "power_outage" && e.citywide)) return 0.0;
    const m = (this.frame && this.frame.metrics) || {};
    const mood = m.average_mood == null ? 60 : m.average_mood;
    return 0.04 + (mood / 100) * 0.10;
  }

  businessClosed(businessId) {
    if (!this.frame || !this.frame.businesses) return false;
    const row = this.frame.businesses.find((x) => x.id === businessId);
    return row ? !row.open : false;
  }

  drawOpenSpace(b, kind, rng) {
    const p = this.p, r = b.rect;
    const row = this.blockRow[b.block_id] || {};
    const quality = kind === "playground" ? (row.playground_quality || 40) : (row.park_quality || 40);
    const g = Math.max(0.25, quality / 100);
    p.noStroke();
    p.fill(
      SB.parkGreen[0] * g + 150 * (1 - g),
      SB.parkGreen[1] * g + 140 * (1 - g),
      SB.parkGreen[2] * g + 104 * (1 - g)
    );
    this.gRect(r.x, r.y, r.w, r.h, 1.7);
    // Winding path.
    p.fill(216, 206, 184);
    this.gRect(r.x + r.w * 0.44, r.y, r.w * 0.12, r.h, 1.8);
    // Trees: trunk + two-tone canopy blobs.
    const n = Math.floor(3 + g * 7);
    for (let i = 0; i < n; i++) {
      const tx = r.x + 5 + rng() * (r.w - 10), ty = r.y + 5 + rng() * (r.h - 10);
      this.drawTree(tx, ty, 1.7, 0.8 + rng() * 0.7, rng);
    }
    if (kind === "playground") {
      this.box(r.x + r.w * 0.2, r.y + r.h * 0.32, r.w * 0.24, r.h * 0.26, 1.7, 4.6, [222, 166, 66]);
      const C = this.iso(r.x + r.w * 0.72, r.y + r.h * 0.5, 2);
      p.noStroke(); p.fill(198, 74, 74);
      p.ellipse(C[0], C[1], r.h * 0.22 * this.scale * 1.3, r.h * 0.22 * this.scale * 0.7);
    }
    if (kind === "plaza") {
      p.fill(210, 202, 188);
      this.gRect(r.x + 3, r.y + 3, r.w - 6, r.h - 6, 1.75);
      // Fountain: basin + animated jet.
      const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
      this.box(cx - 4, cy - 4, 8, 8, 1.75, 3.4, [150, 168, 190]);
      const J = this.iso(cx, cy, 3.4 + Math.abs(Math.sin(this.time * 2.4)) * 4);
      p.fill(SB.water[0], SB.water[1], SB.water[2], 220);
      p.ellipse(J[0], J[1], 3.2 * this.scale, 4.6 * this.scale);
    }
  }

  drawTree(x, y, z, s, rng) {
    const p = this.p;
    // trunk
    this.box(x - 1.1 * s, y - 1.1 * s, 2.2 * s, 2.2 * s, z, z + 5 * s, [124, 90, 60]);
    // canopy: stacked shaded blobs
    const C = this.iso(x, y, z + 9 * s);
    p.noStroke();
    p.fill(58, 112, 58);
    p.ellipse(C[0] + 1.6 * this.scale, C[1] + 1.6 * this.scale, 15 * s * this.scale, 12 * s * this.scale);
    p.fill(88, 148, 78);
    p.ellipse(C[0], C[1], 13.6 * s * this.scale, 10.8 * s * this.scale);
    p.fill(122, 176, 96, 235);
    p.ellipse(C[0] - 2 * this.scale, C[1] - 2 * this.scale, 7.4 * s * this.scale, 5.6 * s * this.scale);
  }

  /* ----- props / furniture ---------------------------------------------- */

  collectFurniture(b, items) {
    const r = b.rect;
    const rng = sbRng(sbHash("furn:" + b.id));
    // Street trees along the south sidewalk.
    for (let x = r.x + 12; x < r.x + r.w - 8; x += 40) {
      const tx = x + rng() * 6, ty = r.y + r.h + 3.4;
      items.push({ d: tx + ty, f: () => this.drawTree(tx, ty, 1.6, 0.62, sbRng(sbHash("st:" + b.id + x))) });
    }
    // Hydrant.
    items.push({
      d: r.x + r.w - 16 + r.y + r.h + 3, f: () => {
        this.box(r.x + r.w - 16, r.y + r.h + 2.4, 2.2, 2.2, 1.6, 4.4, [206, 78, 62]);
      },
    });
    const row = this.blockRow[b.id] || {};
    const lit = (row.lighting || 50) > 55;
    // Lamp posts on the north sidewalk corners.
    for (const lx of [r.x + 3, r.x + r.w - 5]) {
      items.push({
        d: lx + r.y - 4, f: () => {
          const p = this.p;
          this.box(lx, r.y - 5, 1.2, 1.2, 1.6, 11, [82, 84, 90]);
          const L = this.iso(lx + 0.6, r.y - 4.4, 11.8);
          p.noStroke();
          p.fill(lit ? p.color(255, 226, 120) : p.color(150), 245);
          p.circle(L[0], L[1], 4.4 * this.scale);
          if (lit) { p.fill(255, 226, 120, 46); p.circle(L[0], L[1], 10 * this.scale); }
        },
      });
    }
    // Bus stop on the east sidewalk when service exists.
    if ((row.bus_frequency || 30) > 20) {
      items.push({
        d: r.x + r.w + 4 + r.y + r.h * 0.45, f: () => {
          const p = this.p;
          this.box(r.x + r.w + 2, r.y + r.h * 0.4, 3, 8, 1.6, 8.4, [40, 100, 170]);
          p.noStroke(); p.fill(244);
          const S = this.iso(r.x + r.w + 3.5, r.y + r.h * 0.44 + 2, 6.6);
          p.rect(S[0] - 1.6 * this.scale, S[1] - 1.6 * this.scale, 3.2 * this.scale, 3.2 * this.scale);
        },
      });
    }
    // Subway entrance: green stair kiosk with an M globe.
    if (b.has_subway_entrance) {
      items.push({
        d: r.x - 4 + r.y + r.h * 0.42, f: () => {
          const p = this.p;
          this.box(r.x - 8, r.y + r.h * 0.35, 6, 11, 1.6, 6.4, [34, 108, 74]);
          const M = this.iso(r.x - 5, r.y + r.h * 0.35 + 5.5, 7.6);
          p.noStroke(); p.fill(255);
          p.circle(M[0], M[1], 4.6 * this.scale);
          p.fill(34, 108, 74); p.textSize(Math.max(6, 3.4 * this.scale)); p.textAlign(p.CENTER, p.CENTER);
          p.text("M", M[0], M[1]);
        },
      });
    }
    // Cooling center banner.
    if ((row.conditions || []).includes("cooling_center_open")) {
      items.push({
        d: r.x + r.w * 0.5 + r.y - 3, f: () => {
          const p = this.p;
          const A = this.iso(r.x + r.w * 0.32, r.y - 3, 10), B = this.iso(r.x + r.w * 0.68, r.y - 3, 10);
          p.noStroke(); p.fill(70, 150, 230, 240);
          p.rect(A[0], A[1] - 4 * this.scale, B[0] - A[0], 5 * this.scale, 2);
          p.fill(255); p.textSize(Math.max(6, 2.6 * this.scale)); p.textAlign(p.CENTER, p.CENTER);
          p.text("COOLING CENTER", (A[0] + B[0]) / 2, A[1] - 1.6 * this.scale);
        },
      });
    }
    // Event props that live above ground.
    const events = (this.frame && this.frame.events) || [];
    events.forEach((ev) => {
      const hits = ev.citywide || (ev.block_ids || []).includes(b.id);
      if (!hits) return;
      if (ev.kind === "street_construction") {
        for (let x = r.x; x < r.x + r.w; x += 20) {
          const cx = x;
          items.push({
            d: cx + r.y + r.h + 10, f: () => {
              this.box(cx, r.y + r.h + 9, 7, 2.4, 0.1, 3.4, [230, 152, 36]);
            },
          });
        }
      } else if (ev.kind === "street_festival") {
        const rng2 = sbRng(sbHash("fest:" + b.id));
        items.push({
          d: r.x + r.w / 2 + r.y - 2, f: () => {
            const p = this.p;
            for (let x = r.x + 5; x < r.x + r.w - 5; x += 9) {
              const F = this.iso(x, r.y - 2, 9 + Math.sin(this.time * 2 + x) * 0.6);
              p.colorMode(p.HSB, 360, 100, 100);
              p.noStroke(); p.fill(rng2() * 360, 74, 92);
              p.colorMode(p.RGB, 255);
              p.triangle(F[0], F[1], F[0] + 5 * this.scale, F[1], F[0] + 2.5 * this.scale, F[1] + 5 * this.scale);
            }
          },
        });
      } else if (ev.kind === "trash_backlog") {
        const rng3 = sbRng(sbHash("bags:" + b.id + this.day));
        for (let i = 0; i < 8; i++) {
          const bx = r.x + 6 + rng3() * (r.w - 12), by = r.y + r.h + 4 + rng3() * 5;
          items.push({
            d: bx + by, f: () => {
              const p = this.p;
              const T = this.iso(bx, by, 1.4);
              p.noStroke(); p.fill(46, 50, 46, 240);
              p.ellipse(T[0], T[1] - 1.4 * this.scale, 5 * this.scale, 4.4 * this.scale);
            },
          });
        }
      }
    });
  }

  /* ----- agents ---------------------------------------------------------- */

  collectWalkers(items) {
    if (!this.frame) return;
    this.walkers.forEach((wk) => {
      const t = this.time * wk.speed + wk.phase;
      const x = wk.px + Math.sin(t) * wk.range * 0.5;
      const y = wk.py + Math.sin(t * 0.63) * 2;
      items.push({ d: x + y, f: () => this.drawWalker(wk, x, y) });
    });
  }

  drawWalker(wk, x, y) {
    const p = this.p;
    const row = this.blockRow[wk.block_id] || {};
    const mood = row.average_mood == null ? 60 : row.average_mood;
    const bob = Math.abs(Math.sin(this.time * 4 * wk.speed + wk.phase)) * 0.8;
    const B = this.iso(x, y, 1.6 + bob);
    p.noStroke();
    // tiny contact shadow
    const S = this.iso(x, y, 1.55);
    p.fill(40, 40, 50, 60);
    p.ellipse(S[0], S[1], 3.6 * this.scale, 1.8 * this.scale);
    p.colorMode(p.HSB, 360, 100, 100);
    p.fill(wk.hue, 52, 82);
    p.ellipse(B[0], B[1] - 1.6 * this.scale, 3 * this.scale, 3.8 * this.scale); // body
    p.fill(36, 34, 90);
    p.circle(B[0], B[1] - 4.2 * this.scale, 2.2 * this.scale); // head
    p.colorMode(p.RGB, 255);
    if (wk.mode === "bike") {
      p.fill(40);
      p.circle(B[0] - 1.4 * this.scale, B[1], 1.6 * this.scale);
      p.circle(B[0] + 1.4 * this.scale, B[1], 1.6 * this.scale);
    }
    // Occasional thought bubbles: sad cloud when unhappy, coin when thriving.
    const cycle = (this.time + wk.bubblePhase) % 14;
    if (wk.bubble && cycle < 2.4) {
      const bx = B[0] + 3 * this.scale, by = B[1] - 8.5 * this.scale;
      p.fill(255, 255, 255, 235);
      p.ellipse(bx, by, 6.4 * this.scale, 5.2 * this.scale);
      p.circle(bx - 2.4 * this.scale, by + 3.2 * this.scale, 1.4 * this.scale);
      if (mood < 42) {
        p.fill(120, 124, 136);
        p.ellipse(bx, by, 3.4 * this.scale, 2.2 * this.scale);
      } else if (mood > 68) {
        p.fill(238, 190, 60);
        p.circle(bx, by, 3 * this.scale);
        p.fill(180, 130, 30);
        p.textSize(Math.max(5, 2 * this.scale)); p.textAlign(p.CENTER, p.CENTER);
        p.text("$", bx, by);
      } else {
        p.fill(200, 90, 90);
        p.circle(bx, by, 2.6 * this.scale);
      }
    } else if (mood < 42 && !wk.bubble) {
      p.fill(120, 120, 132, 170);
      p.ellipse(B[0] + 1.6 * this.scale, B[1] - 7 * this.scale, 3.2 * this.scale, 2.2 * this.scale);
    }
  }

  collectVehicles(items) {
    const w = this.world;
    const { v, h } = this.streetRects();
    this.vehicles.forEach((veh) => {
      const t = (this.time * veh.speed + veh.offset);
      let x, y;
      if (veh.horizontal && h.length) {
        const band = h[veh.lane % h.length];
        y = (band[0] + band[1]) / 2 + (veh.lane % 2 ? -7 : 7);
        x = (t % (w.width + 60)) - 30;
      } else if (v.length) {
        const band = v[veh.lane % v.length];
        x = (band[0] + band[1]) / 2 + (veh.lane % 2 ? -7 : 7);
        y = (t % (w.height + 60)) - 30;
      } else return;
      if (x < -14 || x > w.width + 14 || y < -14 || y > w.height + 14) return;
      items.push({ d: x + y, f: () => this.drawVehicle(veh, x, y) });
    });
  }

  drawVehicle(veh, x, y) {
    const p = this.p;
    const len = veh.kind === "bus" ? 16 : 9;
    const wid = veh.kind === "bus" ? 5.4 : 4.6;
    const hgt = veh.kind === "bus" ? 5.2 : 3.4;
    let rgb;
    if (veh.kind === "bus") rgb = [56, 118, 188];
    else if (veh.kind === "cab") rgb = [240, 190, 40];
    else {
      p.colorMode(p.HSB, 360, 100, 100);
      const c = p.color(veh.hue, 36, 70);
      rgb = [p.red(c), p.green(c), p.blue(c)];
      p.colorMode(p.RGB, 255);
    }
    const bx = veh.horizontal ? x : x - wid / 2;
    const by = veh.horizontal ? y - wid / 2 : y;
    const bw = veh.horizontal ? len : wid;
    const bh = veh.horizontal ? wid : len;
    // contact shadow
    const S = this.iso(bx + bw / 2, by + bh / 2, 0.05);
    p.noStroke(); p.fill(40, 40, 50, 70);
    p.ellipse(S[0], S[1], (bw + 3) * this.scale, (bh * 0.62) * this.scale);
    this.box(bx, by, bw, bh, 0.2, 0.2 + hgt, rgb);
    // cabin
    this.box(bx + bw * 0.22, by + bh * 0.18, bw * 0.56, bh * 0.64, 0.2 + hgt, 0.2 + hgt + 2, [212, 228, 240]);
  }

  /* ----- atmosphere / labels / debug ------------------------------------ */

  drawSkyTint() {
    const p = this.p;
    const events = (this.frame && this.frame.events) || [];
    const heat = events.find((e) => e.kind === "heat_wave");
    if (heat) {
      p.noStroke();
      p.fill(255, 140, 46, 30 + Math.sin(this.time * 2) * 10);
      p.rect(0, 0, p.width, p.height);
      // shimmering sun
      p.fill(255, 214, 120, 220);
      p.circle(p.width - 52, 46, 40 + Math.sin(this.time * 3) * 3);
    }
  }

  drawBlockLabel(b) {
    const p = this.p, r = b.rect;
    // Floating sign above the block's front-left corner.
    const A = this.iso(r.x + 2, r.y + r.h + 2, 0);
    const wpx = Math.min(r.w * this.scale * 1.6, b.name.length * 6.4 + 12);
    p.noStroke();
    p.fill(52, 46, 40, 215);
    p.rect(A[0], A[1] + 6, wpx, 14, 4);
    p.fill(246, 240, 224);
    p.textSize(9); p.textAlign(p.LEFT, p.CENTER);
    p.text(b.name, A[0] + 6, A[1] + 13);
    const row = this.blockRow[b.id];
    if (row && row.average_mood != null) {
      const mood = row.average_mood;
      p.fill(mood > 60 ? p.color(96, 180, 90) : mood > 45 ? p.color(230, 190, 70) : p.color(210, 80, 70));
      p.circle(A[0] + wpx - 2, A[1] + 12, 6);
    }
  }

  drawDebug() {
    const p = this.p, w = this.world;
    p.push();
    p.textSize(8); p.textAlign(p.LEFT, p.TOP);
    p.stroke(255, 60, 60, 220); p.strokeWeight(1); p.noFill();
    w.blocks.forEach((b) => {
      const r = b.rect;
      const A = this.iso(r.x, r.y, 0), B = this.iso(r.x + r.w, r.y, 0);
      const C = this.iso(r.x + r.w, r.y + r.h, 0), D = this.iso(r.x, r.y + r.h, 0);
      p.quad(A[0], A[1], B[0], B[1], C[0], C[1], D[0], D[1]);
      p.noStroke(); p.fill(255, 90, 90);
      p.text(b.id + " (" + Math.round(r.x) + "," + Math.round(r.y) + ")", A[0], A[1] - 10);
      p.stroke(255, 60, 60, 220); p.noFill();
    });
    p.stroke(80, 170, 255, 200);
    w.buildings.forEach((b) => {
      const r = b.rect;
      const A = this.iso(r.x, r.y, 0), B = this.iso(r.x + r.w, r.y, 0);
      const C = this.iso(r.x + r.w, r.y + r.h, 0), D = this.iso(r.x, r.y + r.h, 0);
      p.quad(A[0], A[1], B[0], B[1], C[0], C[1], D[0], D[1]);
      p.noStroke(); p.fill(140, 200, 255);
      p.text(b.id, A[0] + 1, A[1] + 1);
      p.stroke(80, 170, 255, 200); p.noFill();
    });
    // Walker paths.
    p.stroke(120, 255, 120, 130);
    this.walkers.forEach((wk) => {
      const A = this.iso(wk.px - wk.range * 0.5, wk.py, 0);
      const B = this.iso(wk.px + wk.range * 0.5, wk.py, 0);
      p.line(A[0], A[1], B[0], B[1]);
    });
    p.noStroke(); p.fill(60, 50, 40);
    p.textSize(11);
    p.text("FPS " + Math.round(p.frameRate()) + "  day " + this.day + "  scale " + this.scale.toFixed(2), 6, 4);
    p.pop();
  }

  /* Glowing footprint outline + name tag for the hovered block/building. */
  drawHover() {
    if (!this.hovered) return;
    const p = this.p;
    const r = this.hovered.obj.rect;
    const pulse = 170 + Math.sin(this.time * 4) * 60;
    const A = this.iso(r.x, r.y, 1.2), B = this.iso(r.x + r.w, r.y, 1.2);
    const C = this.iso(r.x + r.w, r.y + r.h, 1.2), D = this.iso(r.x, r.y + r.h, 1.2);
    p.noFill();
    p.stroke(255, 214, 90, pulse);
    p.strokeWeight(Math.max(1.5, this.scale * 1.6));
    p.quad(A[0], A[1], B[0], B[1], C[0], C[1], D[0], D[1]);
    p.noStroke();
    const name = this.hovered.obj.name || this.hovered.obj.id;
    const T = this.iso(r.x + r.w / 2, r.y, 0);
    p.textSize(Math.max(10, 5 * this.scale));
    p.textAlign(p.CENTER, p.BOTTOM);
    const tw = p.textWidth(name) + 10;
    p.fill(34, 32, 30, 225);
    p.rect(T[0] - tw / 2, T[1] - 20 - Math.max(12, 6 * this.scale), tw, Math.max(14, 7 * this.scale), 4);
    p.fill(255, 240, 210);
    p.text(name, T[0], T[1] - 18);
  }

  pickHover() {
    if (!this.world) return;
    const p = this.p;
    const [mx, my] = this.unproject(p.mouseX, p.mouseY);
    let hit = null;
    this.world.buildings.forEach((b) => {
      const r = b.rect;
      if (mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) hit = { kind: "building", obj: b };
    });
    if (!hit) {
      this.world.blocks.forEach((b) => {
        const r = b.rect;
        if (mx >= r.x - 8 && mx <= r.x + r.w + 8 && my >= r.y - 8 && my <= r.y + r.h + 8) {
          hit = { kind: "block", obj: b };
        }
      });
    }
    if ((hit && hit.obj.id) !== (this.hovered && this.hovered.obj.id)) {
      this.hovered = hit;
      if (this.opts.onHover) this.opts.onHover(hit);
    }
  }
}

window.CitySimRenderer = CitySimRenderer;
