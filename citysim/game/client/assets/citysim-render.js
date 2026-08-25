/* CitySim p5.js world renderer.
 *
 * Draws the whole neighborhood procedurally: no bitmap art, every visual is generated
 * from the world payload plus deterministic seeded variation (same seed -> same city).
 * Used unchanged by the live player client, the spectator client, and the replay client.
 *
 * API:
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

const SB = {
  street: [56, 58, 64],
  streetLine: [212, 190, 92],
  sidewalk: [168, 164, 156],
  crosswalk: [230, 228, 220],
  bikeLane: [66, 120, 84],
  blockGround: [188, 182, 170],
  parkGreen: [96, 148, 84],
  water: [70, 110, 150],
  night: [24, 26, 44],
};

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

  /* ----- deterministic ambient population ------------------------------- */

  seedWalkersAndVehicles() {
    const w = this.world;
    const rng = sbRng(sbHash("walkers:" + w.seed));
    this.walkers = w.residents.map((r) => {
      const block = this.byId[r.home_block_id];
      return {
        id: r.id, block_id: r.home_block_id, mode: r.commute_mode,
        px: block.rect.x + rng() * block.rect.w,
        py: block.rect.y + block.rect.h + 10 + rng() * 14, // home sidewalk
        phase: rng() * Math.PI * 2, speed: 0.35 + rng() * 0.5,
        hue: Math.floor(rng() * 360), range: 40 + rng() * 140,
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
    if (!this.world) { p.background(30); return; }
    this.time = p.millis() / 1000;
    const w = this.world;
    this.scale = Math.min(p.width / w.width, p.height / w.height);
    p.push();
    p.scale(this.scale);

    p.background(SB.street[0], SB.street[1], SB.street[2]);
    this.drawStreets();
    w.blocks.forEach((b) => this.drawBlock(b));
    this.drawCrosswalks();
    this.drawVehicles();
    w.buildings.forEach((b) => this.drawBuilding(b));
    w.blocks.forEach((b) => this.drawBlockFurniture(b));
    this.drawWalkers();
    w.blocks.forEach((b) => this.drawEventOverlays(b));
    this.drawSkyTint();
    w.blocks.forEach((b) => this.drawBlockLabel(b));
    if (this.debug) this.drawDebug();
    p.pop();
  }

  streetRects() {
    // Streets are the gaps between block rects; recompute simple bands.
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
    p.noStroke();
    // Lane markings
    p.stroke(SB.streetLine[0], SB.streetLine[1], SB.streetLine[2], 130);
    p.strokeWeight(2);
    v.forEach(([x0, x1]) => {
      const mid = (x0 + x1) / 2;
      for (let y = 0; y < w.height; y += 34) p.line(mid, y, mid, y + 16);
    });
    h.forEach(([y0, y1]) => {
      const mid = (y0 + y1) / 2;
      for (let x = 0; x < w.width; x += 34) p.line(x, mid, x + 16, mid);
    });
    // Bike lanes hug the block edges where capacity exists
    p.strokeWeight(4);
    w.blocks.forEach((b) => {
      const row = this.blockRow[b.id];
      if (!row || (row.bike_capacity || 0) < 25) return;
      p.stroke(SB.bikeLane[0], SB.bikeLane[1], SB.bikeLane[2], 200);
      p.line(b.rect.x - 8, b.rect.y - 8, b.rect.x + b.rect.w + 8, b.rect.y - 8);
    });
    p.noStroke();
  }

  drawCrosswalks() {
    const p = this.p, w = this.world;
    p.fill(SB.crosswalk[0], SB.crosswalk[1], SB.crosswalk[2], 180);
    w.blocks.forEach((b) => {
      const r = b.rect;
      for (let i = 0; i < 5; i++) {
        p.rect(r.x + r.w + 12, r.y + 16 + i * 10, 26, 5, 1);       // east crossing
        p.rect(r.x + 16 + i * 10, r.y + r.h + 12, 5, 26, 1);       // south crossing
      }
    });
  }

  drawBlock(b) {
    const p = this.p;
    const r = b.rect;
    // Sidewalk apron
    p.noStroke();
    p.fill(SB.sidewalk[0], SB.sidewalk[1], SB.sidewalk[2]);
    p.rect(r.x - 10, r.y - 10, r.w + 20, r.h + 20, 4);
    // Interior ground, tinted by cleanliness
    const row = this.blockRow[b.id] || {};
    const clean = row.cleanliness == null ? 65 : row.cleanliness;
    const dirt = Math.max(0, 65 - clean) / 65;
    p.fill(
      SB.blockGround[0] - dirt * 26,
      SB.blockGround[1] - dirt * 32,
      SB.blockGround[2] - dirt * 34
    );
    p.rect(r.x, r.y, r.w, r.h, 3);
    // Litter specks when dirty
    if (dirt > 0.25) {
      const rng = sbRng(sbHash("litter:" + b.id + ":" + this.day));
      p.fill(120, 104, 84, 190);
      const n = Math.floor(dirt * 26);
      for (let i = 0; i < n; i++) p.rect(r.x + rng() * r.w, r.y + rng() * r.h, 3, 2);
    }
  }

  drawBuilding(b) {
    const p = this.p;
    const r = b.rect;
    const rng = sbRng(sbHash("bld:" + b.id));
    if (b.kind === "park" || b.kind === "playground" || b.kind === "plaza" || b.kind === "community_garden") {
      this.drawOpenSpace(b, rng);
      return;
    }
    // Facade
    p.noStroke();
    p.colorMode(p.HSB, 360, 100, 100);
    const sat = b.kind === "civic" ? 8 : 26 + rng() * 22;
    const bright = 46 + (b.quality / 100) * 22 + rng() * 8;
    p.fill(b.facade_hue, sat, bright);
    p.rect(r.x, r.y, r.w, r.h, 2);
    // Roof detailing: parapet + water tank on taller buildings
    p.fill(b.facade_hue, sat, bright - 14);
    p.rect(r.x, r.y, r.w, 5);
    if (b.floors >= 5) {
      p.fill(28, 42, 38);
      p.circle(r.x + r.w * (0.25 + rng() * 0.5), r.y + r.h * (0.3 + rng() * 0.3), 9);
    }
    // Window grid (roof view keeps it abstract: skylight rows per floor strip)
    p.fill(b.facade_hue, Math.min(60, sat + 12), bright - 22);
    const rows = Math.max(2, Math.min(6, Math.floor(b.floors / 1.5)));
    const cols = Math.max(2, Math.floor(r.w / 14));
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        if (rng() < 0.18) continue;
        p.rect(r.x + 4 + j * ((r.w - 8) / cols), r.y + 8 + i * ((r.h - 12) / rows), 5, 4, 1);
      }
    }
    p.colorMode(p.RGB, 255);
    // Storefront awning strip for mixed-use / commercial ground floors
    if (b.business_id) {
      const arng = sbRng(sbHash("awn:" + b.id));
      p.fill(170 + arng() * 60, 60 + arng() * 90, 60 + arng() * 40, 235);
      p.rect(r.x + 2, r.y + r.h - 7, r.w - 4, 7, 2);
      p.fill(255, 244, 214, 240);
      for (let x = r.x + 4; x < r.x + r.w - 6; x += 8) p.rect(x, r.y + r.h - 7, 4, 7);
    }
    // Civic buildings get a tiny flag
    if (b.kind === "civic") {
      p.stroke(200); p.strokeWeight(1);
      p.line(r.x + r.w - 8, r.y + 2, r.x + r.w - 8, r.y - 8);
      p.noStroke(); p.fill(90, 130, 190);
      p.triangle(r.x + r.w - 8, r.y - 8, r.x + r.w - 8, r.y - 3, r.x + r.w, r.y - 5.5);
    }
  }

  drawOpenSpace(b, rng) {
    const p = this.p, r = b.rect;
    const row = this.blockRow[b.block_id] || {};
    const quality = b.kind === "playground" ? (row.playground_quality || 40) : (row.park_quality || 40);
    const g = Math.max(0.25, quality / 100);
    p.noStroke();
    p.fill(SB.parkGreen[0] * g + 120 * (1 - g), SB.parkGreen[1] * g + 110 * (1 - g), SB.parkGreen[2] * g + 90 * (1 - g));
    p.rect(r.x, r.y, r.w, r.h, 6);
    // Paths
    p.fill(206, 196, 176);
    p.rect(r.x + r.w * 0.45, r.y, r.w * 0.12, r.h, 3);
    // Trees
    const n = Math.floor(3 + g * 7);
    for (let i = 0; i < n; i++) {
      const tx = r.x + 6 + rng() * (r.w - 12), ty = r.y + 6 + rng() * (r.h - 12);
      p.fill(40, 84, 46, 240);
      p.circle(tx, ty, 10 + rng() * 8);
      p.fill(66, 116, 62, 200);
      p.circle(tx - 2, ty - 2, 6 + rng() * 4);
    }
    if (b.kind === "playground") {
      p.fill(214, 158, 60);
      p.rect(r.x + r.w * 0.2, r.y + r.h * 0.3, r.w * 0.25, r.h * 0.3, 3);
      p.fill(190, 70, 70);
      p.circle(r.x + r.w * 0.7, r.y + r.h * 0.5, r.h * 0.24);
    }
    if (b.kind === "plaza") {
      p.fill(204, 196, 182);
      p.rect(r.x + 4, r.y + 4, r.w - 8, r.h - 8, 4);
      p.fill(120, 140, 170);
      p.circle(r.x + r.w / 2, r.y + r.h / 2, 12); // fountain
    }
  }

  drawBlockFurniture(b) {
    const p = this.p, r = b.rect;
    const rng = sbRng(sbHash("furn:" + b.id));
    // Street trees along the south sidewalk
    for (let x = r.x + 14; x < r.x + r.w - 8; x += 44) {
      p.noStroke(); p.fill(52, 96, 54);
      p.circle(x + rng() * 6, r.y + r.h + 15, 9);
    }
    // Hydrant + lamp posts
    p.fill(196, 74, 60);
    p.rect(r.x + r.w - 18, r.y + r.h + 12, 4, 6, 1);
    const row = this.blockRow[b.id] || {};
    const lit = (row.lighting || 50) > 55;
    for (const lx of [r.x + 4, r.x + r.w - 6]) {
      p.fill(90); p.rect(lx, r.y - 16, 2, 10);
      p.fill(lit ? p.color(255, 226, 130) : p.color(140), 240);
      p.circle(lx + 1, r.y - 17, 5);
    }
    // Bus stop on the east sidewalk when service exists
    if ((row.bus_frequency || 30) > 20) {
      p.fill(30, 90, 160); p.rect(r.x + r.w + 2, r.y + r.h * 0.4, 6, 14, 2);
      p.fill(240); p.rect(r.x + r.w + 3.5, r.y + r.h * 0.4 + 2, 3, 4);
    }
    // Subway entrance
    if (b.has_subway_entrance) {
      p.fill(24, 94, 66); p.rect(r.x - 9, r.y + r.h * 0.35, 14, 22, 3);
      p.fill(255); p.textSize(10); p.textAlign(p.CENTER, p.CENTER);
      p.text("M", r.x - 2, r.y + r.h * 0.35 + 11);
    }
    // Cooling center banner
    if ((row.conditions || []).includes("cooling_center_open")) {
      p.fill(70, 150, 230, 235); p.rect(r.x + r.w * 0.35, r.y - 9, r.w * 0.3, 8, 2);
      p.fill(255); p.textSize(6); p.textAlign(p.CENTER, p.CENTER);
      p.text("COOLING CENTER", r.x + r.w * 0.5, r.y - 5);
    }
  }

  drawWalkers() {
    const p = this.p;
    if (!this.frame) return;
    p.noStroke();
    this.walkers.forEach((wk) => {
      const row = this.blockRow[wk.block_id] || {};
      const mood = row.average_mood == null ? 60 : row.average_mood;
      const t = this.time * wk.speed + wk.phase;
      const x = wk.px + Math.sin(t) * wk.range * 0.5;
      const y = wk.py + Math.sin(t * 0.63) * 3;
      p.colorMode(p.HSB, 360, 100, 100);
      p.fill(wk.hue, 42, 78);
      p.circle(x, y, 5);
      p.fill(36, 30, 88);
      p.circle(x, y - 3, 3); // head
      p.colorMode(p.RGB, 255);
      // Sad residents droop: tiny gray cloud
      if (mood < 42) { p.fill(120, 120, 130, 160); p.circle(x + 2, y - 7, 4); }
      if (wk.mode === "bike" && Math.sin(t * 1.7) > 0.4) {
        p.fill(40); p.circle(x - 2, y + 2, 2.6); p.circle(x + 2, y + 2, 2.6);
      }
    });
  }

  drawVehicles() {
    const p = this.p, w = this.world;
    const { v, h } = this.streetRects();
    this.vehicles.forEach((veh) => {
      const t = (this.time * veh.speed + veh.offset);
      p.noStroke();
      let x, y;
      if (veh.horizontal && h.length) {
        const band = h[veh.lane % h.length];
        y = (band[0] + band[1]) / 2 + (veh.lane % 2 ? -12 : 12);
        x = (t % (w.width + 60)) - 30;
      } else if (v.length) {
        const band = v[veh.lane % v.length];
        x = (band[0] + band[1]) / 2 + (veh.lane % 2 ? -12 : 12);
        y = (t % (w.height + 60)) - 30;
      } else return;
      const len = veh.kind === "bus" ? 30 : 15;
      const wid = veh.kind === "bus" ? 10 : 8;
      if (veh.kind === "bus") p.fill(46, 110, 180);
      else if (veh.kind === "cab") p.fill(238, 188, 32);
      else { p.colorMode(p.HSB, 360, 100, 100); p.fill(veh.hue, 30, 62); p.colorMode(p.RGB, 255); }
      if (veh.horizontal) p.rect(x, y - wid / 2, len, wid, 3);
      else p.rect(x - wid / 2, y, wid, len, 3);
      p.fill(20, 24, 30, 200);
      if (veh.horizontal) p.rect(x + 3, y - wid / 2 + 2, 4, wid - 4, 1);
      else p.rect(x - wid / 2 + 2, y + 3, wid - 4, 4, 1);
    });
  }

  drawEventOverlays(b) {
    const p = this.p, r = b.rect;
    const events = (this.frame && this.frame.events) || [];
    events.forEach((ev) => {
      const hits = ev.citywide || (ev.block_ids || []).includes(b.id);
      if (!hits) return;
      if (ev.kind === "flash_flood") {
        p.fill(SB.water[0], SB.water[1], SB.water[2], 110);
        p.rect(r.x - 10, r.y + r.h * 0.55, r.w + 20, r.h * 0.45 + 10, 4);
      } else if (ev.kind === "power_outage") {
        p.fill(SB.night[0], SB.night[1], SB.night[2], 120);
        p.rect(r.x - 10, r.y - 10, r.w + 20, r.h + 20, 4);
      } else if (ev.kind === "street_construction") {
        p.fill(226, 150, 32, 220);
        for (let x = r.x; x < r.x + r.w; x += 22) p.rect(x, r.y + r.h + 16, 12, 6, 1);
      } else if (ev.kind === "street_festival") {
        const rng = sbRng(sbHash("fest:" + b.id));
        for (let x = r.x + 6; x < r.x + r.w - 6; x += 12) {
          p.colorMode(p.HSB, 360, 100, 100);
          p.fill(rng() * 360, 70, 90);
          p.colorMode(p.RGB, 255);
          p.triangle(x, r.y - 12, x + 8, r.y - 12, x + 4, r.y - 5);
        }
      } else if (ev.kind === "trash_backlog") {
        const rng = sbRng(sbHash("bags:" + b.id + this.day));
        p.fill(40, 44, 40, 235);
        for (let i = 0; i < 8; i++) p.circle(r.x + 8 + rng() * (r.w - 16), r.y + r.h + 14 + rng() * 8, 7);
      }
    });
  }

  drawSkyTint() {
    const p = this.p, w = this.world;
    const events = (this.frame && this.frame.events) || [];
    const heat = events.find((e) => e.kind === "heat_wave");
    if (heat) {
      p.fill(255, 130, 40, 26 + Math.sin(this.time * 2) * 10);
      p.rect(0, 0, w.width, w.height);
    }
  }

  drawBlockLabel(b) {
    const p = this.p, r = b.rect;
    p.fill(30, 30, 30, 200);
    p.rect(r.x + 4, r.y + 4, Math.min(r.w - 8, b.name.length * 6.4 + 10), 13, 3);
    p.fill(244, 238, 220);
    p.textSize(9); p.textAlign(p.LEFT, p.CENTER);
    p.text(b.name, r.x + 9, r.y + 11);
    const row = this.blockRow[b.id];
    if (row && row.average_mood != null) {
      const mood = row.average_mood;
      p.fill(mood > 60 ? p.color(96, 180, 90) : mood > 45 ? p.color(230, 190, 70) : p.color(210, 80, 70));
      p.circle(r.x + Math.min(r.w - 8, b.name.length * 6.4 + 10) - 2, r.y + 10.5, 6);
    }
  }

  drawDebug() {
    const p = this.p, w = this.world;
    p.push();
    p.textSize(8); p.textAlign(p.LEFT, p.TOP);
    p.noFill(); p.stroke(255, 60, 60, 220); p.strokeWeight(1);
    w.blocks.forEach((b) => {
      p.rect(b.rect.x, b.rect.y, b.rect.w, b.rect.h);
      p.noStroke(); p.fill(255, 90, 90);
      p.text(b.id + " (" + Math.round(b.rect.x) + "," + Math.round(b.rect.y) + ")", b.rect.x, b.rect.y - 10);
      p.stroke(255, 60, 60, 220); p.noFill();
    });
    p.stroke(80, 170, 255, 200);
    w.buildings.forEach((b) => {
      p.rect(b.rect.x, b.rect.y, b.rect.w, b.rect.h);
      p.noStroke(); p.fill(140, 200, 255);
      p.text(b.id, b.rect.x + 1, b.rect.y + 1);
      p.stroke(80, 170, 255, 200); p.noFill();
    });
    // Walker paths and destinations
    p.stroke(120, 255, 120, 130);
    this.walkers.forEach((wk) => p.line(wk.px - wk.range * 0.5, wk.py, wk.px + wk.range * 0.5, wk.py));
    p.noStroke(); p.fill(255, 255, 120);
    p.textSize(11);
    p.text("FPS " + Math.round(p.frameRate()) + "  day " + this.day + "  scale " + this.scale.toFixed(2), 6, 4);
    p.pop();
  }

  pickHover() {
    if (!this.world || !this.opts.onHover) return;
    const p = this.p;
    const mx = p.mouseX / this.scale, my = p.mouseY / this.scale;
    let hit = null;
    this.world.buildings.forEach((b) => {
      const r = b.rect;
      if (mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) hit = { kind: "building", obj: b };
    });
    if (!hit) {
      this.world.blocks.forEach((b) => {
        const r = b.rect;
        if (mx >= r.x - 10 && mx <= r.x + r.w + 10 && my >= r.y - 10 && my <= r.y + r.h + 10) {
          hit = { kind: "block", obj: b };
        }
      });
    }
    if ((hit && hit.obj.id) !== (this.hovered && this.hovered.obj.id)) {
      this.hovered = hit;
      this.opts.onHover(hit);
    }
  }
}

window.CitySimRenderer = CitySimRenderer;
