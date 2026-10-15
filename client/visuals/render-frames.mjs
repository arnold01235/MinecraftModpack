// Pre-renders the ascii.rest "snow train" piece (MIT, see LICENSE-ascii.rest) into
// console frames for client/sync-mods.cmd, so players need nothing but Windows.
//
//   node --experimental-strip-types client/visuals/render-frames.mjs
//
// Writes two gzip files of UTF-8 text: a header line "SNOWTRAIN1 <cols> <rows> <fps>"
// then frames separated by form feeds. Each frame positions its own lines (ESC[row;colH)
// and uses 24-bit colour.
//   snow-train.frames.gz         Braille: every cell of the piece is one dot, unscaled.
//                                Needs a font with Braille (Windows Terminal has one).
//   snow-train-blocks.frames.gz  Upper half blocks, two area-averaged pixels per
//                                character. Softer, but works in the classic console.
import { gzipSync } from "node:zlib";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import snowTrain, { meta } from "./snow-train.ts";

const FPS = 8;
const SECONDS = (185 + 156 + 40) / 7; // the piece's PERIOD / SPEED: one full crossing
const DOTS = " ·•●";
const COVER = [0, 0.3, 0.6, 1];
const SRC_W = meta.cols;
const ESC = "\x1b";

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const P = meta.palette.map(hex);
const ground = hex(meta.ground);
const step = (cells, k) => Math.max(0, DOTS.indexOf(cells[k]));

// --- Braille: 200x80 cells fill 100x20 characters, keeping the square aspect --------
const braille = {
  file: "snow-train.frames.gz",
  cols: 100,
  rows: 20,
  top: 10, // first source row: keeps the moon, viaduct and river
  left: 11, // centred in a 120 column window
  bit: [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]], // [row][column]
  // A 2x4 ordered-dither matrix, scaled to the brightness range of the night scene.
  threshold: [[0, 4], [6, 2], [1, 5], [7, 3]].map((row) => row.map((v) => 0.04 + ((v + 0.5) / 8) * 0.42)),
  render(cells, color) {
    let out = "";
    for (let r = 0; r < this.rows; r++) {
      out += `${ESC}[${r + 1};${this.left}H${ESC}[48;2;${ground.join(";")}m`;
      let last = "";
      for (let c = 0; c < this.cols; c++) {
        // Each cell's light (its colour's brightness times its dot size) decides through
        // the dither whether its dot shows, so dark areas thin out like a halftone.
        let bits = 0, n = 0;
        const sum = [0, 0, 0];
        for (let y = 0; y < 4; y++) {
          for (let x = 0; x < 2; x++) {
            const k = (this.top + r * 4 + y) * SRC_W + c * 2 + x;
            const s = step(cells, k);
            if (!s) continue;
            const p = P[color[k]];
            const lum = ((0.3 * p[0] + 0.55 * p[1] + 0.15 * p[2]) / 255) * COVER[s];
            if (lum <= this.threshold[y][x]) continue;
            bits |= this.bit[y][x], n++;
            for (let j = 0; j < 3; j++) sum[j] += p[j];
          }
        }
        if (!bits) {
          out += " ";
          continue;
        }
        const rgb = sum.map((v) => Math.min(255, Math.round(v / n / 8) * 8)).join(";");
        if (rgb !== last) out += `${ESC}[38;2;${rgb}m`, (last = rgb);
        out += String.fromCharCode(0x2800 + bits);
      }
      out += `${ESC}[0m`;
    }
    return out;
  },
};

// --- Half blocks: 200x68 cells averaged into 120x40 pixels ---------------------------
const blocks = {
  file: "snow-train-blocks.frames.gz",
  cols: 120,
  rows: 20,
  top: 8,
  height: 68,
  // Light in a source cell: its colour scaled by its dot size, over the night ground.
  light(cells, color, k) {
    const c = COVER[step(cells, k)], p = P[color[k]];
    return [0, 1, 2].map((i) => ground[i] + (p[i] - ground[i]) * c);
  },
  // Area-average a pixel's rectangle of source cells.
  pixel(px, py, cells, color) {
    const w = SRC_W / this.cols, h = this.height / (this.rows * 2);
    const x0 = px * w, x1 = x0 + w, y0 = this.top + py * h, y1 = y0 + h;
    const sum = [0, 0, 0];
    let area = 0;
    for (let y = Math.floor(y0); y < Math.ceil(y1); y++) {
      for (let x = Math.floor(x0); x < Math.ceil(x1); x++) {
        const a = (Math.min(x + 1, x1) - Math.max(x, x0)) * (Math.min(y + 1, y1) - Math.max(y, y0));
        const l = this.light(cells, color, y * SRC_W + x);
        for (let i = 0; i < 3; i++) sum[i] += l[i] * a;
        area += a;
      }
    }
    // Quantise lightly so neighbouring cells share colour escapes and the file stays small.
    return sum.map((v) => Math.min(255, Math.round(v / area / 10) * 10)).join(";");
  },
  render(cells, color) {
    let out = "";
    for (let r = 0; r < this.rows; r++) {
      out += `${ESC}[${r + 1};1H`;
      let fg = "", bg = "";
      for (let c = 0; c < this.cols; c++) {
        const top = this.pixel(c, r * 2, cells, color), bottom = this.pixel(c, r * 2 + 1, cells, color);
        if (top !== fg) out += `${ESC}[38;2;${top}m`, (fg = top);
        if (bottom !== bg) out += `${ESC}[48;2;${bottom}m`, (bg = bottom);
        out += "▀";
      }
      out += `${ESC}[0m`;
    }
    return out;
  },
};

const frame = snowTrain();
const outputs = [braille, blocks].map((style) => ({ style, frames: [] }));
for (let i = 0; i < Math.round(SECONDS * FPS); i++) {
  const color = new Uint8Array(meta.cols * meta.rows);
  const cells = [...frame(i / FPS, { color }).replace(/\n/g, "")];
  for (const o of outputs) o.frames.push(o.style.render(cells, color));
}
for (const { style, frames } of outputs) {
  const text = `SNOWTRAIN1 ${style.cols} ${style.rows} ${FPS}\n` + frames.join("\f");
  const data = gzipSync(Buffer.from(text, "utf8"), { level: 9 });
  const target = fileURLToPath(new URL(`./${style.file}`, import.meta.url));
  writeFileSync(target, data);
  console.log(`${style.file}: ${frames.length} frames, ${style.cols}x${style.rows} at ${FPS} fps, ${(data.length / 1024).toFixed(0)} KB`);
}
