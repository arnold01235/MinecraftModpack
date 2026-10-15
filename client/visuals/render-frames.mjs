// Pre-renders the ascii.rest "snow train" piece (MIT, see LICENSE-ascii.rest) into
// console frames for client/sync-mods.cmd, so players need nothing but Windows.
//
//   node --experimental-strip-types client/visuals/render-frames.mjs
//
// Output: client/visuals/snow-train.frames.gz, a gzip of UTF-8 text: a header line
// "SNOWTRAIN1 <cols> <rows> <fps>" then frames separated by form feeds. Each frame
// positions every line itself (ESC[row;1H) and draws two pixels per cell with an
// upper half block in 24-bit colour.
import { gzipSync } from "node:zlib";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import snowTrain, { meta } from "./snow-train.ts";

const SRC_W = meta.cols, SRC_TOP = 8, SRC_ROWS = 68; // keep the moon, viaduct and river
const COLS = 120, ROWS = 20; // each console cell shows two pixels with a half block
const PX_W = SRC_W / COLS, PX_H = SRC_ROWS / (ROWS * 2);
const FPS = 8;
const SECONDS = (185 + 156 + 40) / 7; // the piece's PERIOD / SPEED: one full crossing
const DOTS = " ·•●";
const COVER = [0, 0.3, 0.6, 1];

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const P = meta.palette.map(hex);
const ground = hex(meta.ground);
// Light in a source cell: its colour scaled by the size of its dot, over the night ground.
const light = (k, cells, color) => {
  const c = COVER[Math.max(0, DOTS.indexOf(cells[k]))], p = P[color[k]];
  return [0, 1, 2].map((i) => ground[i] + (p[i] - ground[i]) * c);
};
// Area-average a pixel's rectangle of source cells.
const pixel = (px, py, cells, color) => {
  const x0 = px * PX_W, x1 = x0 + PX_W, y0 = SRC_TOP + py * PX_H, y1 = y0 + PX_H;
  const sum = [0, 0, 0];
  let area = 0;
  for (let y = Math.floor(y0); y < Math.ceil(y1); y++) {
    for (let x = Math.floor(x0); x < Math.ceil(x1); x++) {
      const w = (Math.min(x + 1, x1) - Math.max(x, x0)) * (Math.min(y + 1, y1) - Math.max(y, y0));
      const l = light(y * SRC_W + x, cells, color);
      for (let i = 0; i < 3; i++) sum[i] += l[i] * w;
      area += w;
    }
  }
  // Quantise lightly so neighbouring cells share colour escapes and the file stays small.
  return sum.map((v) => Math.min(255, Math.round(v / area / 10) * 10));
};

const frame = snowTrain();
const ESC = "\x1b";
const frames = [];
for (let i = 0; i < Math.round(SECONDS * FPS); i++) {
  const color = new Uint8Array(meta.cols * meta.rows);
  const cells = [...frame(i / FPS, { color }).replace(/\n/g, "")];
  let out = "";
  for (let r = 0; r < ROWS; r++) {
    out += `${ESC}[${r + 1};1H`;
    let fg = "", bg = "";
    for (let c = 0; c < COLS; c++) {
      const top = pixel(c, r * 2, cells, color).join(";"), bottom = pixel(c, r * 2 + 1, cells, color).join(";");
      if (top !== fg) out += `${ESC}[38;2;${top}m`, (fg = top);
      if (bottom !== bg) out += `${ESC}[48;2;${bottom}m`, (bg = bottom);
      out += "\u2580";
    }
    out += `${ESC}[0m`;
  }
  frames.push(out);
}

const data = gzipSync(Buffer.from(`SNOWTRAIN1 ${COLS} ${ROWS} ${FPS}\n` + frames.join("\f"), "utf8"), { level: 9 });
const target = fileURLToPath(new URL("./snow-train.frames.gz", import.meta.url));
writeFileSync(target, data);
console.log(`${frames.length} frames, ${COLS}x${ROWS} at ${FPS} fps, ${(data.length / 1024).toFixed(0)} KB -> ${target}`);
