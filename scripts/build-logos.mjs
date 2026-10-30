#!/usr/bin/env node
/**
 * Clipper Factory — icon generator.
 *
 * Draws the mark geometrically (gear ring + film-strip "C" + scissors), writes the
 * master vector to assets/logos/icon.svg and rasterises every size with sharp.
 *
 *   node scripts/build-logos.mjs
 */
import sharp from 'sharp';
import { copyFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const OUT = path.join(process.cwd(), 'assets', 'logos');
const PUBLIC = path.join(process.cwd(), 'public');
const PUBLIC_LOGOS = path.join(PUBLIC, 'assets', 'logos');
const BRAND_LIGHT = '#C98A4A';
const BRAND_DARK = '#7A4A26';
const NAVY = '#241712';

const BLUE_LIGHT = BRAND_LIGHT;
const BLUE_DARK = BRAND_DARK;

const CX = 512;
const CY = 512;
const DEG = Math.PI / 180;

const n = (v) => Math.round(v * 100) / 100;
const polar = (r, a) => ({ x: n(CX + r * Math.cos(a * DEG)), y: n(CY + r * Math.sin(a * DEG)) });

/* ------------------------------------------------------------------ geometry */

const G = {
  gearIn: 366,
  gearRoot: 416,
  gearTip: 470,
  gearStart: -40,
  gearEnd: 282,
  teeth: 14,

  stripIn: 226,
  stripOut: 336,
  stripStart: -38,
  stripEnd: 282,

  holes: 12,
  holeStart: -20,
  holeEnd: 262,
  holeW: 32,
  holeH: 22,
  holeRows: [252, 310],

  scissors: { angle: -27, radius: 352 },
};

function gearPath() {
  const { gearIn: ri, gearRoot: rr, gearTip: rt, gearStart: s, gearEnd: e, teeth } = G;
  const pitch = (e - s) / teeth;
  const tip = pitch * 0.3;
  const flank = pitch * 0.22;
  const root = pitch - tip - 2 * flank;

  const start = polar(rr, s);
  const seg = [`M${start.x} ${start.y}`];

  for (let i = 0; i < teeth; i++) {
    const a0 = s + i * pitch;
    const rootEnd = a0 + root / 2;
    const tipStart = rootEnd + flank;
    const tipEnd = tipStart + tip;
    const flankEnd = tipEnd + flank;

    const pRoot = polar(rr, rootEnd);
    const pTipA = polar(rt, tipStart);
    const pTipB = polar(rt, tipEnd);
    const pFlank = polar(rr, flankEnd);

    seg.push(`A${rr} ${rr} 0 0 1 ${pRoot.x} ${pRoot.y}`);
    seg.push(`L${pTipA.x} ${pTipA.y}`);
    seg.push(`A${rt} ${rt} 0 0 1 ${pTipB.x} ${pTipB.y}`);
    seg.push(`L${pFlank.x} ${pFlank.y}`);
  }

  const innerEnd = polar(ri, e);
  const innerStart = polar(ri, s);
  const gearEndPoint = polar(rr, e);
  seg.push(`A${rr} ${rr} 0 0 1 ${gearEndPoint.x} ${gearEndPoint.y}`);
  seg.push(`L${innerEnd.x} ${innerEnd.y}`);
  seg.push(`A${ri} ${ri} 0 1 0 ${innerStart.x} ${innerStart.y}`);
  seg.push('Z');
  return seg.join('\n        ');
}

function stripPath(outer = G.stripOut) {
  const { stripIn: ri, stripStart: s, stripEnd: e } = G;
  const ro = outer;
  const a = polar(ro, s);
  const b = polar(ro, e);
  const c = polar(ri, e);
  const d = polar(ri, s);
  return `M${a.x} ${a.y}A${ro} ${ro} 0 1 1 ${b.x} ${b.y}L${c.x} ${c.y}A${ri} ${ri} 0 1 0 ${d.x} ${d.y}Z`;
}

function holeRects() {
  const { holes, holeStart, holeEnd, holeW, holeH, holeRows } = G;
  const step = (holeEnd - holeStart) / (holes - 1);
  const out = [];
  for (let i = 0; i < holes; i++) {
    const a = holeStart + i * step;
    for (const r of holeRows) {
      const { x, y } = polar(r, a);
      out.push(
        `<rect x="${n(-holeW / 2)}" y="${n(-holeH / 2)}" width="${holeW}" height="${holeH}" rx="6"` +
          ` transform="translate(${x} ${y}) rotate(${n(a + 90)})"/>`
      );
    }
  }
  return out.join('\n        ');
}

/* ------------------------------------------------------------------ scissors */

/** One scissor half: blade (minus x), shank + eyelet ring (plus x). Sharp, flat, geometric. */
const SCISSOR_HALF = `
      <g transform="rotate(-18)">
        <path d="M-88 0L8 -11L8 11Z"/>
      </g>
      <g transform="rotate(39)">
        <path d="M-2 -13L26 -11L30 0L26 11L-2 13Z"/>
      </g>
      <path fill-rule="evenodd" d="M58 29a22 22 0 1 0-44 0a22 22 0 1 0 44 0Zm-11 0a11 11 0 1 0-22 0a11 11 0 1 0 22 0Z"/>`;

// Blades splay ±18°; the eyelets sit at local (42, ±29) so both rings stay inside the gear band.
const scissorTransform = () => {
  const p = polar(G.scissors.radius, G.scissors.angle);
  return `translate(${p.x} ${p.y}) rotate(${G.scissors.angle})`;
};

/* ------------------------------------------------------------------ document */

function svgDoc({ mono = false, opacity = 1, holes = true, solid = false } = {}) {
  const paint = mono ? '#FFFFFF' : 'url(#cf-blue)';
  const outer = solid ? G.gearIn : G.stripOut;
  const geo =
    `<path d="${gearPath()}" fill="${paint}"/>` +
    `<path d="${stripPath(outer)}" fill="${paint}"/>`;

  const paintLayer = holes ? `<g mask="url(#cf-holes)">${geo}</g>` : geo;

  // The 1-colour watermark drops the scissors: at 100 px its cut lines only smear the silhouette.
  const top = mono
    ? ''
    : `<g transform="${scissorTransform()}">
      <g fill="#FFFFFF">
        <use href="#cf-scissor-half"/>
        <use href="#cf-scissor-half" transform="scale(1,-1)"/>
      </g>
      <circle r="10" fill="${BLUE_DARK}"/>
    </g>`;

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024"${opacity < 1 ? ` opacity="${opacity}"` : ''} fill="none">
  <defs>
    <linearGradient id="cf-blue" x1="200" y1="120" x2="830" y2="900" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="${BLUE_LIGHT}"/>
      <stop offset="1" stop-color="${BLUE_DARK}"/>
    </linearGradient>

    <!-- sprocket holes punched out of the film strip -->
    <mask id="cf-holes" maskUnits="userSpaceOnUse" x="0" y="0" width="1024" height="1024">
      <rect width="1024" height="1024" fill="#FFFFFF"/>
      <g fill="#000000">
        ${holeRects()}
      </g>
    </mask>

    <!-- one scissor half, mirrored below into a full pair -->
    <g id="cf-scissor-half">${SCISSOR_HALF}
    </g>
  </defs>

  ${paintLayer}
  ${top}
</svg>
`;
}

/* ------------------------------------------------------------------ raster */

async function png(svg, size, file) {
  await sharp(Buffer.from(svg), { density: (72 * size) / 1024 })
    .resize(size, size)
    .png({ compressionLevel: 9 })
    .toFile(path.join(OUT, file));
}

async function appIcon(svg, size, bg, file) {
  const radius = Math.round(size * 0.2246);
  const plate = Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">` +
      `<rect width="${size}" height="${size}" rx="${radius}" ry="${radius}" fill="${bg}"/></svg>`
  );
  const inner = Math.round(size * 0.762);
  const icon = await sharp(Buffer.from(svg), { density: (72 * inner) / 1024 })
    .resize(inner, inner)
    .png()
    .toBuffer();
  const off = Math.round((size - inner) / 2);
  await sharp(plate)
    .composite([{ input: icon, left: off, top: off }])
    .png({ compressionLevel: 9 })
    .toFile(path.join(OUT, file));
}

/** Multi-size .ico with PNG payloads (Vista+ / all modern browsers). */
function ico(entries) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(entries.length, 4);

  const dir = [];
  let offset = 6 + 16 * entries.length;
  for (const { size, data } of entries) {
    const e = Buffer.alloc(16);
    e.writeUInt8(size >= 256 ? 0 : size, 0);
    e.writeUInt8(size >= 256 ? 0 : size, 1);
    e.writeUInt8(0, 2);
    e.writeUInt8(0, 3);
    e.writeUInt16LE(1, 4);
    e.writeUInt16LE(32, 6);
    e.writeUInt32LE(data.length, 8);
    e.writeUInt32LE(offset, 12);
    offset += data.length;
    dir.push(e);
  }
  return Buffer.concat([header, ...dir, ...entries.map((e) => e.data)]);
}

/* ------------------------------------------------------------------ main */

await mkdir(OUT, { recursive: true });

const svg = svgDoc();
const mono = svgDoc({ mono: true, opacity: 0.5 });
await writeFile(path.join(OUT, 'icon.svg'), svg);

await png(svg, 1024, 'icon-1024.png');
await png(svg, 512, 'icon-512.png');
await png(svg, 256, 'icon-256.png');
await appIcon(svg, 1024, NAVY, 'icon-dark-bg.png');
await appIcon(svg, 1024, '#FFFFFF', 'icon-light-bg.png');
await png(mono, 100, 'watermark-100.png');

// At 32 px the sprocket holes and the 30 px gap collapse into grey noise, so the tiny favicon
// uses one solid ring with the gear teeth on the outside.
const small = svgDoc({ holes: false, solid: true });
const fav32 = await sharp(Buffer.from(small), { density: (72 * 32) / 1024 }).resize(32, 32).png().toBuffer();
const fav64 = await sharp(Buffer.from(svg), { density: (72 * 64) / 1024 }).resize(64, 64).png().toBuffer();
await writeFile(path.join(OUT, 'favicon.ico'), ico([{ size: 32, data: fav32 }, { size: 64, data: fav64 }]));

// The dashboard needs web-served copies; keep public/ in sync with the pack.
await mkdir(PUBLIC, { recursive: true });
await mkdir(PUBLIC_LOGOS, { recursive: true });
for (const [from, to] of [
  ['favicon.ico', 'favicon.ico'],
  ['icon-1024.png', path.join('assets', 'logos', 'icon-1024.png')],
  ['icon.svg', path.join('assets', 'logos', 'icon.svg')],
]) {
  await copyFile(path.join(OUT, from), path.join(PUBLIC, to));
}

console.log(`logo pack written to ${path.relative(process.cwd(), OUT)} (copied to public/)`);
