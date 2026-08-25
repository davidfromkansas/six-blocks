/* Deterministic procedural asset generation for Six Blocks.
 *
 * Everything in the world view is drawn procedurally at runtime by
 * sixblocks-render.js (p5.js) from seeded PRNGs, so there is no bitmap sprite
 * pipeline. This script (re)generates the few static assets that must exist as
 * files: the favicon (a tiny procedural six-block grid) and the shared palette
 * JSON that keeps the p5 renderer and the CSS dashboard in the same family.
 *
 * Usage: npm run generate-assets   (deterministic: same output every run)
 */
import { deflateSync } from "node:zlib";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const assets = join(here, "..", "sixblocks", "game", "client", "assets");

/* -- seeded prng (mulberry32) -------------------------------------------- */
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* -- minimal PNG encoder --------------------------------------------------- */
function crc32(buf) {
  let c, table = [];
  for (let n = 0; n < 256; n++) {
    c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const b of buf) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}
function png(width, height, pixels /* RGBA rows */) {
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 4 + 1)] = 0;
    pixels.copy(raw, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; ihdr[9] = 6; // 8-bit RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/* -- favicon: 32x32 procedural six-block grid ------------------------------ */
const SIZE = 32;
const px = Buffer.alloc(SIZE * SIZE * 4);
const r = rng(0x51bb10c5); // "six blocks"
function put(x, y, [rr, gg, bb]) {
  const i = (y * SIZE + x) * 4;
  px[i] = rr; px[i + 1] = gg; px[i + 2] = bb; px[i + 3] = 255;
}
const street = [56, 58, 64];
const blockColors = [];
for (let i = 0; i < 6; i++) {
  blockColors.push([150 + Math.floor(r() * 70), 120 + Math.floor(r() * 60), 80 + Math.floor(r() * 50)]);
}
blockColors[4] = [96, 148, 84]; // one park block
for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) put(x, y, street);
const bw = 9, bh = 13, gap = 2;
let bi = 0;
for (let row = 0; row < 2; row++) {
  for (let col = 0; col < 3; col++) {
    const ox = 1 + col * (bw + gap), oy = 2 + row * (bh + gap);
    for (let y = 0; y < bh; y++) for (let x = 0; x < bw; x++) put(ox + x, oy + y, blockColors[bi]);
    // window specks
    const wr = rng(0xbeef + bi);
    for (let k = 0; k < 8; k++) {
      put(ox + 1 + Math.floor(wr() * (bw - 2)), oy + 1 + Math.floor(wr() * (bh - 2)), [244, 226, 160]);
    }
    bi++;
  }
}
writeFileSync(join(assets, "favicon.png"), png(SIZE, SIZE, px));

/* -- shared palette --------------------------------------------------------- */
const palette = {
  street: [56, 58, 64],
  streetLine: [212, 190, 92],
  sidewalk: [168, 164, 156],
  crosswalk: [230, 228, 220],
  bikeLane: [66, 120, 84],
  blockGround: [188, 182, 170],
  parkGreen: [96, 148, 84],
  water: [70, 110, 150],
  night: [24, 26, 44],
  accent: "#e8b84b",
};
mkdirSync(join(assets, "generated"), { recursive: true });
writeFileSync(join(assets, "generated", "palette.json"), JSON.stringify(palette, null, 2) + "\n");

console.log("generated favicon.png and generated/palette.json (deterministic)");
