#!/usr/bin/env python3
"""Build "Where in the State" (Oregon edition) as one self-contained HTML file.

Reads the real data files (cities, outline, landmarks) and embeds them
verbatim as JSON inside the page. No coordinates, geometry or city names
are invented here.
"""
import json, os

BASE = os.path.expanduser("~/workspace/game-project")
OUT = os.path.join(BASE, "oregon-geography-game.html")

cities = json.load(open(os.path.join(BASE, "oregon-cities-with-coords.json")))
outline = json.load(open(os.path.join(BASE, "data/oregon/outline.geojson")))
landmarks = json.load(open(os.path.join(BASE, "data/oregon/landmarks.geojson")))
counties = json.load(open(os.path.join(BASE, "data/oregon/counties.geojson")))
assert len(cities) == 241, len(cities)
assert len(outline["features"]) == 1
assert len(landmarks["features"]) == 224, len(landmarks["features"])
assert len(counties["features"]) == 36, len(counties["features"])

CITIES_JSON = json.dumps(cities, separators=(",", ":"))
OUTLINE_JSON = json.dumps(outline, separators=(",", ":"))
LANDMARKS_JSON = json.dumps(landmarks, separators=(",", ":"))
COUNTIES_JSON = json.dumps(counties, separators=(",", ":"))

PURE_JS = r"""
/* ============ Projection — the single source of truth ============
   Equirectangular with cos(44 deg) correction. The SAME function draws
   every path and (via its inverse) reads every click, so drawing and
   clicking can never disagree. Bounds lon -124.716 to -116.314,
   lat 41.843 to 46.421, viewBox 0 0 1000 757.4. */
var LON_MIN = -124.716, LON_MAX = -116.314;
var LAT_MIN = 41.843,  LAT_MAX = 46.421;
var W = 1000;
var COS = Math.cos(44 * Math.PI / 180);
var X_RANGE = (LON_MAX - LON_MIN) * COS;
var Y_RANGE = LAT_MAX - LAT_MIN;
var H = W * Y_RANGE / X_RANGE;                 /* ~757.4 */

function project(lon, lat) {
  return [(lon - LON_MIN) * COS / X_RANGE * W, (LAT_MAX - lat) / Y_RANGE * H];
}
function unproject(x, y) {
  return [LON_MIN + x / W * X_RANGE / COS, LAT_MAX - y / H * Y_RANGE];
}

/* ============ Distance (Haversine, miles, R = 3959) ============ */
function haversineMiles(lat1, lon1, lat2, lon2) {
  var R = 3959;
  var dLat = (lat2 - lat1) * Math.PI / 180;
  var dLon = (lon2 - lon1) * Math.PI / 180;
  var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
          Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
          Math.sin(dLon / 2) * Math.sin(dLon / 2);
  /* Clamp: rounding can push a a hair above 1, and asin(sqrt(a)) is NaN then. */
  a = Math.min(1, Math.max(0, a));
  return 2 * R * Math.asin(Math.sqrt(a));
}

/* ============ Scoring ============
   100 points if rounded distance <= 5 miles, else
   max(0, 100 - (rounded miles - 5)). Floored at 0. */
function scoreForDistance(distMiles) {
  if (!isFinite(distMiles)) return 0;
  var r = Math.round(distMiles);
  return r <= 5 ? 100 : Math.max(0, 100 - (r - 5));
}

/* ============ Overlap scoring (Counties mode) ============
   Port of the Blazor OverlapService: the placed piece is the true
   county translated by (dx, dy) in SVG viewBox units, so the overlap
   is the fraction of the true county's area the piece covers, sampled
   on a grid of cell centres (4 SVG units apart). The projection is
   linear, so area ratios in SVG space equal area ratios on the ground.
   Only cells inside the true county's bounding box are tested. */
var OVERLAP_GRID_STEP = 4;
function isInsideRing(x, y, ring) {
  var inside = false;
  var n = ring.length;
  for (var i = 0; i < n; i++) {
    var x1 = ring[i][0], y1 = ring[i][1];
    var x2 = ring[(i + 1) % n][0], y2 = ring[(i + 1) % n][1];
    if ((y1 > y) !== (y2 > y)) {
      var xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1;
      if (x < xin) inside = !inside;
    }
  }
  return inside;
}
function isInsideAnyRing(x, y, rings) {
  for (var i = 0; i < rings.length; i++) {
    if (isInsideRing(x, y, rings[i])) return true;
  }
  return false;
}
function overlapFraction(ringsSvg, dx, dy) {
  if (!ringsSvg || ringsSvg.length === 0) return 0;
  var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  ringsSvg.forEach(function (ring) {
    ring.forEach(function (pt) {
      if (pt[0] < minX) minX = pt[0]; if (pt[0] > maxX) maxX = pt[0];
      if (pt[1] < minY) minY = pt[1]; if (pt[1] > maxY) maxY = pt[1];
    });
  });
  var insideTrue = 0, insideBoth = 0;
  /* Cell centres, so a cell on the boundary counts half the time —
     the error this introduces is far below a point at this grid size. */
  for (var y = minY + OVERLAP_GRID_STEP / 2; y <= maxY; y += OVERLAP_GRID_STEP) {
    for (var x = minX + OVERLAP_GRID_STEP / 2; x <= maxX; x += OVERLAP_GRID_STEP) {
      if (!isInsideAnyRing(x, y, ringsSvg)) continue;
      insideTrue++;
      /* The placed piece is the true county translated by (dx, dy), so a
         point is inside the placed piece exactly when the point shifted
         back by (dx, dy) is inside the true county. */
      if (isInsideAnyRing(x - dx, y - dy, ringsSvg)) insideBoth++;
    }
  }
  return insideTrue === 0 ? 0 : insideBoth / insideTrue;
}
/* Points for an overlap fraction: 100 for a perfect placement, scaled
   linearly, floored at 0. Mirrors the city game's 100 per round so the
   two modes share a /1000 game total. ("Name the county" scores 100 for
   the right county, 50 for a neighboring one — see revealNameTheCounty.) */
function scoreForOverlap(overlap) {
  if (!isFinite(overlap)) return 0;
  return Math.round(Math.min(1, Math.max(0, overlap)) * 100);
}

/* ============ Seeded randomization ============
   SHA-256 of the seed string (SubtleCrypto), first 4 bytes as a signed
   32-bit int (little-endian, matching C# BitConverter.ToInt32), then
   mulberry32 driving a Fisher-Yates shuffle. Same seed -> same 10
   items in the same order, in any browser. */
function mulberry32(a) {
  return function () {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    var t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
async function seedIntFromString(seed) {
  var bytes = new TextEncoder().encode(seed);
  if (window.crypto && window.crypto.subtle && window.crypto.subtle.digest) {
    var hash = await window.crypto.subtle.digest("SHA-256", bytes);
    return new DataView(hash).getInt32(0, true);
  }
  /* Fallback for non-secure contexts: FNV-1a (still deterministic). */
  var h = 0x811c9dc5;
  for (var i = 0; i < bytes.length; i++) { h ^= bytes[i]; h = Math.imul(h, 0x01000193); }
  return h | 0;
}
/* Seeded Fisher-Yates shuffle of any pool (cities or counties):
   same seed -> same 10 items in the same order. */
function selectItems(seedInt, pool, count) {
  var rng = mulberry32(seedInt);
  var arr = pool.slice();
  for (var i = arr.length - 1; i > 0; i--) {
    var j = Math.floor(rng() * (i + 1));
    var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
  }
  return arr.slice(0, count);
}
/* Seeded Fisher-Yates shuffle of a copy of any array (used to interleave
   the 7 city + 3 county rounds of City County Mode): same seed -> same
   order. The C# version uses System.Random, so the interleaving order
   may differ between the two versions — the 7 cities and 3 counties
   themselves are the same. */
function shuffleItems(seedInt, arr) {
  var rng = mulberry32(seedInt);
  var shuffled = arr.slice();
  for (var i = shuffled.length - 1; i > 0; i--) {
    var j = Math.floor(rng() * (i + 1));
    var t = shuffled[i]; shuffled[i] = shuffled[j]; shuffled[j] = t;
  }
  return shuffled;
}
function dailySeed() {
  var d = new Date();
  function p(n) { return String(n).padStart(2, "0"); }
  return "OR-" + d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}
function randomSeed() {
  var chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  var out = "OR-";
  var buf = new Uint8Array(6);
  if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(buf);
  else for (var i = 0; i < 6; i++) buf[i] = Math.floor(Math.random() * 256);
  for (var k = 0; k < 6; k++) out += chars[buf[k] % chars.length];
  return out;
}
/* __PURE_END__ */
"""

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light" />
<link rel="icon" href="data:," />
<title>Where in the State — Oregon</title>
<style>
  :root {
    color-scheme: light;
    --bg: #f2efe4; --panel: #fffdf6; --panel-soft: #f6f2e7;
    --ink: #1e2a24; --muted: #5c6b60; --faint: #8a978d; --line: #ddd5bf;
    --state-fill: #e7edda; --state-stroke: #4a6b52;
    --interstate: #c0563a; --highway: #a5873f; --river: #4d7fa8;
    --lake-fill: #bfd9ea; --lake-stroke: #4d7fa8;
    --guess-blue: #4d7fa8; --guess-red: #c0563a; --truth: #177245;
    --accent: #205c46; --accent-btn: #205c46;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 16px; line-height: 1.5; -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 28px 20px 40px; }
  h1 { font-family: Georgia, serif; font-weight: 600; font-size: 30px; line-height: 1.15; margin: 0 0 8px; letter-spacing: -0.01em; }
  /* Header logo: a solid green pin with a white "?!" inside, next to the
     title. The title text lives in #game-title-text so showScreen can
     retitle the game without wiping out the logo. */
  .wordmark-logo { display: inline-block; width: 1.35em; height: 1.35em; vertical-align: -0.22em; margin-right: 0.35rem; }
  .wordmark-logo .pin-fill { fill: var(--accent); }
  .wordmark-logo .mark-fill { fill: #fff; }
  header p { margin: 0 0 20px; color: var(--muted); font-size: 15.5px; max-width: 760px; }
  header p strong { color: var(--ink); }
  h2 { font-size: 20px; margin: 0 0 6px; }
  .screen[hidden] { display: none; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 20px 22px; margin-bottom: 18px; }
  .card h2 { font-size: 11px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; color: var(--faint); margin: 0 0 12px; }
  .card p { margin: 0 0 12px; }
  .muted { color: var(--muted); }
  .small { font-size: 13.5px; }

  .field-label { display: block; font-weight: 600; margin-bottom: 6px; }
  input[type="text"], textarea {
    font: inherit; width: 100%; padding: 12px 14px; min-height: 48px;
    border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--ink);
  }
  input[type="text"]:focus, textarea:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
  .seed-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: stretch; }
  /* The seed box is short (20 chars max) and sits below Start, out of the
     normal player's path — keep it narrow so it reads as a secondary control. */
  .seed-row input { flex: 0 1 240px; max-width: 240px; }
  .btn-row { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }

  button, .btn {
    font: inherit; font-size: 15px; font-weight: 600;
    min-height: 48px; padding: 10px 18px; border-radius: 8px; cursor: pointer;
    border: 1px solid var(--line); background: var(--panel); color: var(--ink);
  }
  button:hover:not(:disabled) { background: var(--panel-soft); }
  button:disabled { opacity: .45; cursor: default; }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .btn-primary { background: var(--accent-btn); border-color: var(--accent-btn); color: #fff; }
  .btn-primary:hover:not(:disabled) { background: #184636; }
  .btn-big { font-size: 17px; padding: 12px 26px; }

  .state-badge {
    display: inline-block; font-weight: 700; font-size: 18px;
    border: 1px solid var(--line); background: var(--panel-soft);
    border-radius: 8px; padding: 10px 16px; margin-bottom: 4px;
  }
  .toggle-row { display: flex; gap: 8px; flex-wrap: wrap; }
  .toggle {
    font: inherit; font-size: 13.5px; font-weight: 600; min-height: 44px;
    display: inline-flex; align-items: center; gap: 7px;
    padding: 6px 14px 6px 10px; border-radius: 999px;
    border: 1px solid var(--line); background: var(--panel); color: var(--muted); cursor: pointer;
  }
  .toggle .swatch { width: 16px; height: 0; border-top: 3px solid currentColor; border-radius: 2px; flex: none; }
  .toggle .swatch.fill { height: 10px; border-top: none; border-radius: 3px; background: currentColor; opacity: .55; }
  .toggle[aria-pressed="true"] { color: var(--ink); border-color: #aebbbd; background: var(--panel-soft); }
  .toggle[aria-pressed="false"] { opacity: .55; }
  .toggle[data-layer="interstate"] { --c: var(--interstate); }
  .toggle[data-layer="highway"]    { --c: var(--highway); }
  .toggle[data-layer="river"]      { --c: var(--river); }
  .toggle[data-layer="lake"]       { --c: var(--river); }
  .toggle .swatch { color: var(--c, var(--muted)); }
  /* Game-mode buttons: large buttons in a 3-column grid, each with a small
     map preview of how that mode plays. Matches the Blazor start screen:
     selected button gets a green border and a soft green fill. */
  .mode-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .mode-button {
    display: flex; flex-direction: column; align-items: stretch; text-align: left;
    background: var(--panel); border: 2px solid var(--line); border-radius: 14px;
    padding: 12px; cursor: pointer; font: inherit; color: var(--ink);
  }
  .mode-button:hover:not(:disabled) { border-color: var(--accent); box-shadow: 0 1px 2px rgba(30, 42, 36, 0.06), 0 6px 18px rgba(30, 42, 36, 0.07); }
  .mode-button[aria-pressed="true"] { border-color: var(--accent); background: #e3ede6; box-shadow: 0 1px 2px rgba(30, 42, 36, 0.06), 0 6px 18px rgba(30, 42, 36, 0.07); }
  .mode-button:disabled { opacity: 0.45; cursor: not-allowed; }
  .mode-button-title { font-weight: 700; font-size: 17px; margin-top: 10px; }
  .mode-button-desc { font-size: 14px; color: var(--muted); margin-top: 2px; }
  @media (max-width: 700px) { .mode-grid { grid-template-columns: 1fr; } }
  .mode-preview { width: 100%; height: auto; display: block; border-radius: 8px; background: var(--bg); }
  .preview-state { fill: var(--state-fill); stroke: var(--state-stroke); stroke-width: 2; stroke-linejoin: round; }
  .preview-grid { fill: none; stroke: #6b8a6f; stroke-width: 1.5; }
  .preview-line { stroke: var(--ink); stroke-width: 4; stroke-dasharray: 2 8; stroke-linecap: round; }
  .preview-guess { fill: #3b82c4; stroke: #fff; stroke-width: 3; }
  .preview-guess-dot { fill: #fff; }
  .preview-target { fill: #fff; stroke: var(--accent); stroke-width: 3; }
  .preview-target-dot { fill: var(--accent); }
  .preview-ghost { fill: rgba(32, 92, 70, 0.08); stroke: var(--accent); stroke-width: 2.5; stroke-dasharray: 7 5; }
  .preview-piece { fill: var(--interstate); stroke: #8f3d26; stroke-width: 2; opacity: 0.95; }
  .preview-arrow { fill: none; stroke: var(--ink); stroke-width: 3; }
  .preview-arrowhead { fill: var(--ink); }
  .preview-selected { fill: #3b82c4; fill-opacity: 0.45; stroke: #1d4ed8; stroke-width: 2.5; }
  .lede { margin: 0 0 20px; color: var(--muted); font-size: 15.5px; max-width: 760px; }
  .lede strong { color: var(--ink); }
  /* Mode instructions (lede + steps under the picker) and the Game card's
     game lines: all three variants are rendered in one grid cell and only
     the selected mode's is visible, so the block is always as tall as the
     tallest variant and switching modes never moves anything below it.
     Hidden variants are visibility:hidden, not display:none, so they still
     size the grid; aria-hidden keeps them out of screen readers. */
  .mode-instructions { display: grid; margin-top: 12px; }
  .mode-instructions > * { grid-area: 1 / 1; }
  .mode-instructions > :not(.is-active) { visibility: hidden; }
  .mode-lines { display: grid; }
  .mode-lines > * { grid-area: 1 / 1; }
  .mode-lines > :not(.is-active) { visibility: hidden; }
  .how-it-works { margin: 0 0 12px; padding-left: 0; list-style: none; }
  .how-it-works li { margin-bottom: 6px; }
  .how-it-works .step-num {
    display: inline-block; width: 22px; height: 22px; border-radius: 50%;
    background: var(--accent); color: #fff; font-size: 12px; font-weight: 700;
    line-height: 22px; text-align: center; margin-right: 8px;
  }

  .score-line { font-size: 16px; font-weight: 600; margin: 0 0 10px; font-variant-numeric: tabular-nums; }
  /* Round bar: fills by total score (out of the mode's maximum), with a terracotta tick
     marking the best total possible once the question on screen is scored
     ((question number) x 100). The wrapper carries the sizing so the tick,
     taller than the track, is not clipped by the track's overflow. */
  .round-status { display: flex; align-items: center; gap: 12px; margin: 0 0 10px; }
  .round-status .score-line { margin: 0; white-space: nowrap; }
  .progress-wrap { position: relative; flex: 1; }
  .progress-track { height: 10px; background: #e2ddc9; border-radius: 999px; overflow: hidden; }
  .progress-fill { height: 100%; background: var(--accent); border-radius: 999px; transition: width 0.3s ease; }
  .progress-max { position: absolute; top: 50%; width: 3px; height: 16px; transform: translate(-50%, -50%); background: #c0563a; border-radius: 999px; transition: left 0.3s ease; }
  #round-heading { font-size: 22px; margin: 0 0 6px; }
  .map-card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px; margin-bottom: 14px; }
  /* One row at the top of the map card holds the round's controls:
     Confirm/Pass while placing, then the distance and the Next button
     after the reveal. Landmark toggles live on the start screen only,
     so nothing below the map needs a scroll to reach. */
  .game-controls { padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid var(--line); }
  /* The controls row is a single line in both states: the hint sits to the
     right of the buttons while placing, and the reveal line takes the same
     spot after confirming. If the row wrapped, its height would change
     between states and the map below would bounce up and down. */
  .game-controls .btn-row { margin-top: 0; flex-wrap: nowrap; }
  .game-controls .btn-row button { flex-shrink: 0; }
  .controls-hint { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--muted); font-size: 13.5px; align-self: center; }
  .reveal-line { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 700; font-size: 16px; color: var(--accent); font-variant-numeric: tabular-nums; align-self: center; }
  .map-frame { position: relative; width: min(100%, calc(min(56vh, 620px) * 1.3203)); margin: 0 auto; background: #f8f5ea; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
  /* Sized by viewport height so the whole round fits on one screen;
     the width follows from the viewBox aspect ratio (1000 / 757.4).
     Clicks use getScreenCTM, so they stay exact at any size. */
  svg#map { display: block; width: 100%; height: auto; cursor: crosshair; touch-action: none; }
  /* Small Confirm bubble next to the pin while placing, so the player
     doesn't have to travel back to the controls row. The tail points
     at the pin; near the right edge the bubble flips to the pin's left. */
  .pin-confirm {
    position: absolute; z-index: 2; transform: translate(14px, -50%);
    min-height: 36px; padding: 6px 14px; font-size: 13.5px; white-space: nowrap;
    background: var(--accent-btn); border-color: var(--accent-btn); color: #fff; border-radius: 999px;
  }
  .pin-confirm.flipped { transform: translate(calc(-100% - 14px), -50%); }
  /* Pin the positioning transform on hover: the generic button:hover rule
     outranks .pin-confirm, so without these the bubble would jump away
     from the cursor when hovered (its translate is what places it). */
  .pin-confirm:hover:not(:disabled) { transform: translate(14px, -50%); background: #184636; }
  .pin-confirm.flipped:hover:not(:disabled) { transform: translate(calc(-100% - 14px), -50%); }
  .pin-confirm::before {
    content: ""; position: absolute; left: -5px; top: 50%;
    width: 10px; height: 10px; background: var(--accent-btn); transform: translateY(-50%) rotate(45deg);
  }
  .pin-confirm.flipped::before { left: auto; right: -5px; }
  .state-shape { fill: var(--state-fill); stroke: var(--state-stroke); stroke-width: 2; stroke-linejoin: round; }
  .layer-interstate path { fill: none; stroke: var(--interstate); stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
  .layer-highway path { fill: none; stroke: var(--highway); stroke-width: 1.3; stroke-linecap: round; stroke-linejoin: round; opacity: .85; }
  .layer-river path { fill: none; stroke: var(--river); stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; opacity: .9; }
  .layer-lake path { fill: var(--lake-fill); stroke: var(--lake-stroke); stroke-width: 1; fill-rule: evenodd; }
  .layer-hidden { display: none; }
  .connector { stroke: var(--guess-red); stroke-width: 1.8; stroke-dasharray: 6 4; opacity: .8; }
  .truth-marker circle { fill: none; stroke: var(--truth); stroke-width: 2.4; }
  .truth-marker line { stroke: var(--truth); stroke-width: 2.4; stroke-linecap: round; }
  .guess-pin { pointer-events: none; }
  /* Counties mode: the draggable puzzle piece — the county's own shape
     at 1:1 scale, in a warm rust so it reads as a piece waiting to be
     placed. touch-action none so a touch drag moves the piece instead of
     scrolling the page. */
  .county-piece { fill: #d98a68; fill-opacity: 0.85; stroke: #a34a28; stroke-width: 2; cursor: grab; touch-action: none; }
  .county-piece.dragging { cursor: grabbing; fill-opacity: 0.95; }
  /* Reveal: the true county in green, the placed piece in rust — where
     they overlap the two fills blend, so the coverage reads at a glance. */
  .county-true { fill: #205c46; fill-opacity: 0.35; stroke: #205c46; stroke-width: 2.5; }
  .county-placed { fill: #c0563a; fill-opacity: 0.4; stroke: #a34a28; stroke-width: 2; }
  /* Name the county mode: the grid of county boundaries drawn over the
     blank map, the selected county in blue, and a wrong pick in rust
     (the true county reuses .county-true above). */
  .county-boundary { fill: rgba(255, 255, 255, 0.12); stroke: #6b8a6f; stroke-width: 1.3; }
  .county-selected { fill: #3b82c4; fill-opacity: 0.45; stroke: #1d4ed8; stroke-width: 2; }
  .county-wrong { fill: #c0563a; fill-opacity: 0.4; stroke: #a34a28; stroke-width: 2; }
  .map-label {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 20px; font-weight: 700; fill: var(--truth); text-anchor: middle;
    paint-order: stroke; stroke: #fffdf6; stroke-width: 4px; stroke-linejoin: round;
  }

  .legend { font-size: 13.5px; color: var(--muted); margin: 0 0 4px; }
  .dot { display: inline-block; width: 11px; height: 11px; border-radius: 50%; vertical-align: -1px; margin: 0 4px 0 10px; }
  .dot.red { background: var(--guess-red); } .dot.green { background: var(--truth); } .dot.blue { background: var(--guess-blue); }

  table.results { width: 100%; border-collapse: collapse; font-size: 15px; }
  table.results th, table.results td { padding: 8px 4px; text-align: left; vertical-align: top; }
  table.results thead th { font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--faint); border-bottom: 1px solid var(--line); }
  table.results tbody tr + tr td { border-top: 1px solid #e7ecec; }
  table.results td.num, table.results th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  tr.best td { background: #e8f3ec; }
  tr.hardest td { background: #fbeeee; }
  .badge { display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; border-radius: 999px; padding: 2px 8px; margin-left: 8px; }
  .badge.best { background: #177245; color: #fff; }
  .badge.hardest { background: #8a3b2e; color: #fff; }
  .total-big { font-family: Georgia, serif; font-size: 44px; font-weight: 600; line-height: 1.1; font-variant-numeric: tabular-nums; }
  .total-big small { font-size: 20px; color: var(--muted); }
  /* The summary is read-only, so it is a styled box, not a text field.
     pre-line keeps the line break between the score line and the link;
     the long URL wraps instead of overflowing the box. */
  .summary-box { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 13.5px; width: 100%; padding: 12px 14px; min-height: 48px; border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--ink); white-space: pre-line; overflow-wrap: break-word; }
  .copied { color: var(--truth); font-weight: 600; font-size: 13.5px; }
  footer { margin-top: 22px; color: var(--faint); font-size: 12.5px; line-height: 1.6; max-width: 900px; }
  footer code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; }
  @media (max-width: 700px) {
    .wrap { padding: 20px 14px 32px; }
    h1 { font-size: 25px; }
    #round-heading { font-size: 19px; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1 id="game-title"><svg class="wordmark-logo" viewBox="0 0 96 96" aria-hidden="true"><path class="pin-fill" d="M48 8 C32.5 8 20 20.5 20 34 C20 55 48 86 48 86 C48 86 76 55 76 34 C76 20.5 63.5 8 48 8 Z" /><text class="mark-fill" x="48" y="46" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-weight="700" font-size="34">?!</text></svg><span id="game-title-text">Where in the State</span></h1>
  </header>

  <!-- ================= START ================= -->
  <section id="screen-start" class="screen" aria-label="Start a game">
    <div class="card">
      <h2>Game mode</h2>
      <div class="mode-grid" role="group" aria-label="Game mode">
        <button type="button" class="mode-button" data-mode="city-county" aria-pressed="false">
          <svg class="mode-preview" viewBox="0 0 1000 757.4" aria-hidden="true">
            <path d="M892.2,350.7 L921.2,360.4 L931.0,374.0 L921.0,386.4 L926.2,397.0 L915.2,428.3 L915.2,731.4 L60.0,731.7 L42.8,712.4 L33.7,677.8 L37.5,627.7 L17.9,593.2 L37.3,515.4 L57.4,473.8 L67.3,415.3 L92.5,125.6 L86.0,78.5 L93.6,62.7 L83.9,30.6 L102.5,43.6 L144.6,24.8 L160.0,45.4 L190.4,39.0 L215.6,55.8 L226.4,76.1 L232.3,126.4 L288.2,145.2 L345.7,118.2 L402.1,118.5 L422.3,134.8 L485.7,111.7 L513.2,119.4 L600.6,93.3 L608.8,83.0 L665.3,80.8 L681.8,69.7 L928.4,70.4 L944.2,98.5 L972.3,110.9 L982.2,135.4 L936.5,231.4 L935.4,254.8 L910.9,280.2 L891.6,320.7 L892.2,350.7 Z" class="preview-state" />
            <path d="M737.5,283.8 L765.4,276.3 L783.8,227.7 L851.2,236.3 L851.3,222.0 L944.1,222.1 L891.6,320.7 L892.2,350.7 L860.4,350.9 L848.0,327.0 L802.7,327.1 L776.3,358.2 L740.1,358.3 L762.9,303.1 L737.5,283.8 Z M107.0,343.5 L133.1,328.9 L132.5,281.2 L195.4,291.6 L173.3,308.0 L182.8,353.6 L107.0,343.5 Z M220.0,182.6 L246.9,158.7 L344.7,158.7 L361.4,185.9 L363.9,224.1 L346.4,233.2 L357.2,250.6 L263.1,248.6 L220.0,182.6 Z M83.7,30.5 L102.5,43.6 L151.0,28.3 L161.2,106.1 L88.9,105.5 L83.7,30.5 Z M160.6,60.0 L160.9,45.4 L184.4,38.4 L215.7,55.8 L232.5,114.6 L161.2,106.1 L160.6,60.0 Z M30.2,567.4 L59.2,464.9 L100.0,465.3 L120.4,523.3 L107.6,600.9 L69.4,621.1 L66.0,585.3 L30.2,567.4 Z M429.4,357.2 L429.5,335.9 L462.9,321.7 L462.8,307.4 L515.3,307.2 L515.3,328.4 L558.7,327.9 L573.3,349.8 L602.3,349.7 L587.8,450.5 L530.6,450.4 L516.2,421.6 L443.9,407.0 L429.4,357.2 Z M18.0,592.3 L28.1,573.5 L54.5,573.4 L69.4,621.1 L119.0,601.5 L80.2,667.3 L110.0,692.1 L106.9,731.6 L60.0,731.7 L43.4,714.8 L37.5,627.7 L18.0,592.3 Z M323.0,464.0 L326.2,424.1 L350.7,383.8 L341.9,335.6 L429.5,335.9 L443.9,407.0 L516.2,421.6 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z M59.7,462.1 L66.3,423.1 L120.5,409.8 L148.3,432.0 L187.9,437.0 L191.4,476.6 L235.0,475.9 L235.0,493.6 L307.5,493.2 L326.3,522.7 L314.2,554.8 L289.6,554.8 L228.7,602.7 L139.7,614.0 L107.6,600.9 L120.4,523.3 L100.0,465.3 L59.7,462.1 Z M483.5,113.1 L513.2,119.4 L561.4,100.7 L560.5,192.5 L589.9,207.1 L589.8,221.6 L502.4,223.8 L498.4,168.9 L518.7,146.8 L483.5,113.1 Z M600.3,235.9 L770.2,242.0 L765.4,276.3 L737.5,283.8 L762.9,303.1 L740.1,358.3 L771.7,358.0 L772.2,393.9 L602.1,407.3 L600.3,235.9 Z M568.0,606.7 L573.5,450.5 L587.8,450.5 L588.0,407.3 L772.2,393.9 L775.8,731.9 L637.5,732.4 L636.8,607.5 L568.0,606.7 Z M332.8,144.5 L339.1,120.4 L389.8,119.7 L384.9,192.4 L359.4,192.4 L332.8,144.5 Z M176.7,730.6 L176.9,614.0 L289.6,566.6 L288.8,730.1 L176.7,730.6 Z M341.2,323.0 L352.7,263.2 L517.1,264.6 L515.3,307.2 L462.8,307.4 L443.7,336.0 L341.9,335.6 L341.2,323.0 Z M80.2,667.3 L119.0,601.7 L174.6,611.6 L176.7,730.8 L106.4,732.2 L110.0,692.1 L80.2,667.3 Z M288.7,710.4 L289.6,554.8 L314.2,554.8 L326.3,522.7 L307.7,473.8 L402.6,464.0 L400.7,607.9 L456.2,608.3 L456.6,732.5 L288.8,730.1 L288.7,710.4 Z M400.5,579.2 L402.6,464.0 L573.6,464.9 L568.0,607.9 L636.8,607.5 L637.5,732.4 L456.6,732.5 L456.2,608.3 L400.7,607.9 L400.5,579.2 Z M67.3,415.3 L71.6,354.7 L349.7,363.9 L307.5,493.2 L235.0,493.6 L235.0,475.9 L191.4,476.6 L187.9,437.0 L148.3,432.0 L120.5,409.8 L91.6,423.3 L67.3,415.3 Z M71.5,353.1 L84.2,227.7 L118.0,227.7 L133.1,328.9 L118.5,328.8 L111.9,353.6 L71.5,353.1 Z M173.2,308.3 L195.5,292.9 L187.1,276.6 L204.2,286.9 L230.1,269.1 L347.1,287.4 L347.1,357.8 L278.1,365.9 L220.2,353.0 L215.4,367.3 L184.6,367.4 L173.2,308.3 Z M771.7,358.2 L802.7,327.1 L848.0,327.0 L860.4,350.9 L905.5,354.1 L930.8,372.2 L914.4,428.7 L915.2,731.4 L775.8,731.9 L771.7,358.2 Z M182.7,258.7 L199.3,243.7 L208.1,187.9 L235.3,192.2 L229.4,213.5 L263.1,248.6 L355.0,254.5 L347.7,287.4 L230.1,269.1 L203.4,286.9 L182.7,258.7 Z M560.6,177.1 L561.4,100.7 L628.9,83.2 L628.6,135.3 L663.0,149.7 L660.9,235.7 L586.1,236.0 L589.9,207.1 L560.5,192.5 L560.6,177.1 Z M212.7,124.1 L232.5,114.5 L242.9,132.9 L288.2,145.2 L332.5,127.7 L344.7,158.7 L234.7,163.4 L212.7,124.1 Z M117.9,231.2 L196.1,222.7 L186.5,281.4 L120.4,281.2 L117.9,231.2 Z M438.6,187.8 L461.8,157.5 L452.3,129.0 L483.5,113.1 L508.9,131.5 L518.4,151.0 L502.3,158.1 L495.2,188.6 L506.2,218.4 L474.4,221.2 L438.6,187.8 Z M83.3,224.4 L87.7,107.2 L161.2,106.1 L146.5,117.8 L168.6,134.6 L146.5,161.1 L149.1,199.3 L110.9,199.3 L118.0,227.7 L83.3,224.4 Z M628.6,98.0 L628.9,83.2 L681.8,69.7 L802.0,69.5 L785.5,157.2 L716.3,177.9 L737.6,235.8 L660.9,235.7 L663.0,149.7 L628.6,135.3 L628.6,98.0 Z M716.3,177.9 L785.5,157.2 L794.0,99.9 L829.4,92.6 L839.4,174.6 L861.6,207.5 L886.7,207.5 L886.7,221.8 L747.4,241.3 L716.3,177.9 Z M802.0,69.5 L928.4,70.4 L972.3,110.8 L982.2,135.4 L944.1,222.1 L861.6,207.5 L831.8,149.9 L829.4,92.6 L802.0,92.7 L802.0,69.5 Z M346.4,233.2 L363.9,224.1 L359.4,192.4 L384.9,192.4 L389.8,119.7 L420.4,134.8 L448.9,126.5 L463.0,150.0 L439.4,198.9 L501.3,221.3 L517.1,264.6 L356.0,264.0 L346.4,233.2 Z M146.5,161.1 L168.6,137.0 L146.5,117.8 L200.6,106.2 L234.7,149.1 L234.7,180.2 L146.5,161.1 Z M502.4,223.8 L586.2,223.9 L600.3,235.9 L602.3,349.7 L573.3,349.8 L558.7,327.9 L515.3,328.4 L502.4,223.8 Z M110.8,207.5 L149.1,199.3 L148.9,163.4 L200.4,168.1 L222.1,192.1 L204.7,191.3 L196.1,222.7 L110.9,222.4 L110.8,207.5 Z" class="preview-grid" />
            <path d="M323.0,464.0 L327.4,462.2 L326.2,424.1 L338.8,415.1 L350.7,383.8 L341.9,335.6 L429.5,335.9 L430.0,377.7 L443.8,378.4 L443.9,407.0 L472.2,407.6 L472.3,421.8 L516.2,421.6 L516.3,436.0 L530.5,436.1 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z" class="preview-selected" />
            <circle cx="404.7" cy="390.9" r="16" class="preview-guess" />
            <circle cx="404.7" cy="390.9" r="6" class="preview-guess-dot" />
          </svg>
          <span class="mode-button-title">City County Mode</span>
          <span class="mode-button-desc">Pins and counties, mixed</span>
        </button>
        <button type="button" class="mode-button" data-mode="cities" aria-pressed="true">
          <svg class="mode-preview" viewBox="0 0 1000 757.4" aria-hidden="true">
            <path d="M892.2,350.7 L921.2,360.4 L931.0,374.0 L921.0,386.4 L926.2,397.0 L915.2,428.3 L915.2,731.4 L60.0,731.7 L42.8,712.4 L33.7,677.8 L37.5,627.7 L17.9,593.2 L37.3,515.4 L57.4,473.8 L67.3,415.3 L92.5,125.6 L86.0,78.5 L93.6,62.7 L83.9,30.6 L102.5,43.6 L144.6,24.8 L160.0,45.4 L190.4,39.0 L215.6,55.8 L226.4,76.1 L232.3,126.4 L288.2,145.2 L345.7,118.2 L402.1,118.5 L422.3,134.8 L485.7,111.7 L513.2,119.4 L600.6,93.3 L608.8,83.0 L665.3,80.8 L681.8,69.7 L928.4,70.4 L944.2,98.5 L972.3,110.9 L982.2,135.4 L936.5,231.4 L935.4,254.8 L910.9,280.2 L891.6,320.7 L892.2,350.7 Z" class="preview-state" />
            <line x1="228.0" y1="466.7" x2="404.7" y2="390.9" class="preview-line" />
            <circle cx="228.0" cy="466.7" r="16" class="preview-guess" />
            <circle cx="228.0" cy="466.7" r="6" class="preview-guess-dot" />
            <circle cx="404.7" cy="390.9" r="14" class="preview-target" />
            <circle cx="404.7" cy="390.9" r="5" class="preview-target-dot" />
          </svg>
          <span class="mode-button-title">Cities</span>
          <span class="mode-button-desc">Drop a pin for a named city</span>
        </button>
        <button type="button" class="mode-button" data-mode="counties" aria-pressed="false">
          <svg class="mode-preview" viewBox="0 0 1000 757.4" aria-hidden="true">
            <defs>
              <marker id="preview-arrowhead" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" class="preview-arrowhead" />
              </marker>
            </defs>
            <path d="M892.2,350.7 L921.2,360.4 L931.0,374.0 L921.0,386.4 L926.2,397.0 L915.2,428.3 L915.2,731.4 L60.0,731.7 L42.8,712.4 L33.7,677.8 L37.5,627.7 L17.9,593.2 L37.3,515.4 L57.4,473.8 L67.3,415.3 L92.5,125.6 L86.0,78.5 L93.6,62.7 L83.9,30.6 L102.5,43.6 L144.6,24.8 L160.0,45.4 L190.4,39.0 L215.6,55.8 L226.4,76.1 L232.3,126.4 L288.2,145.2 L345.7,118.2 L402.1,118.5 L422.3,134.8 L485.7,111.7 L513.2,119.4 L600.6,93.3 L608.8,83.0 L665.3,80.8 L681.8,69.7 L928.4,70.4 L944.2,98.5 L972.3,110.9 L982.2,135.4 L936.5,231.4 L935.4,254.8 L910.9,280.2 L891.6,320.7 L892.2,350.7 Z" class="preview-state" />
            <path d="M323.0,464.0 L327.4,462.2 L326.2,424.1 L338.8,415.1 L350.7,383.8 L341.9,335.6 L429.5,335.9 L430.0,377.7 L443.8,378.4 L443.9,407.0 L472.2,407.6 L472.3,421.8 L516.2,421.6 L516.3,436.0 L530.5,436.1 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z" class="preview-ghost" />
            <path d="M323.0,464.0 L327.4,462.2 L326.2,424.1 L338.8,415.1 L350.7,383.8 L341.9,335.6 L429.5,335.9 L430.0,377.7 L443.8,378.4 L443.9,407.0 L472.2,407.6 L472.3,421.8 L516.2,421.6 L516.3,436.0 L530.5,436.1 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z" transform="translate(-160 -130)" class="preview-piece" />
            <path d="M400,315 Q395,355 375,385" class="preview-arrow" marker-end="url(#preview-arrowhead)" />
          </svg>
          <span class="mode-button-title">Counties</span>
          <span class="mode-button-desc">Drag the county's shape onto the map</span>
        </button>
        <button type="button" class="mode-button" data-mode="name-the-county" aria-pressed="false">
          <svg class="mode-preview" viewBox="0 0 1000 757.4" aria-hidden="true">
            <path d="M892.2,350.7 L921.2,360.4 L931.0,374.0 L921.0,386.4 L926.2,397.0 L915.2,428.3 L915.2,731.4 L60.0,731.7 L42.8,712.4 L33.7,677.8 L37.5,627.7 L17.9,593.2 L37.3,515.4 L57.4,473.8 L67.3,415.3 L92.5,125.6 L86.0,78.5 L93.6,62.7 L83.9,30.6 L102.5,43.6 L144.6,24.8 L160.0,45.4 L190.4,39.0 L215.6,55.8 L226.4,76.1 L232.3,126.4 L288.2,145.2 L345.7,118.2 L402.1,118.5 L422.3,134.8 L485.7,111.7 L513.2,119.4 L600.6,93.3 L608.8,83.0 L665.3,80.8 L681.8,69.7 L928.4,70.4 L944.2,98.5 L972.3,110.9 L982.2,135.4 L936.5,231.4 L935.4,254.8 L910.9,280.2 L891.6,320.7 L892.2,350.7 Z" class="preview-state" />
            <path d="M737.5,283.8 L765.4,276.3 L783.8,227.7 L851.2,236.3 L851.3,222.0 L944.1,222.1 L891.6,320.7 L892.2,350.7 L860.4,350.9 L848.0,327.0 L802.7,327.1 L776.3,358.2 L740.1,358.3 L762.9,303.1 L737.5,283.8 Z M107.0,343.5 L133.1,328.9 L132.5,281.2 L195.4,291.6 L173.3,308.0 L182.8,353.6 L107.0,343.5 Z M220.0,182.6 L246.9,158.7 L344.7,158.7 L361.4,185.9 L363.9,224.1 L346.4,233.2 L357.2,250.6 L263.1,248.6 L220.0,182.6 Z M83.7,30.5 L102.5,43.6 L151.0,28.3 L161.2,106.1 L88.9,105.5 L83.7,30.5 Z M160.6,60.0 L160.9,45.4 L184.4,38.4 L215.7,55.8 L232.5,114.6 L161.2,106.1 L160.6,60.0 Z M30.2,567.4 L59.2,464.9 L100.0,465.3 L120.4,523.3 L107.6,600.9 L69.4,621.1 L66.0,585.3 L30.2,567.4 Z M429.4,357.2 L429.5,335.9 L462.9,321.7 L462.8,307.4 L515.3,307.2 L515.3,328.4 L558.7,327.9 L573.3,349.8 L602.3,349.7 L587.8,450.5 L530.6,450.4 L516.2,421.6 L443.9,407.0 L429.4,357.2 Z M18.0,592.3 L28.1,573.5 L54.5,573.4 L69.4,621.1 L119.0,601.5 L80.2,667.3 L110.0,692.1 L106.9,731.6 L60.0,731.7 L43.4,714.8 L37.5,627.7 L18.0,592.3 Z M323.0,464.0 L326.2,424.1 L350.7,383.8 L341.9,335.6 L429.5,335.9 L443.9,407.0 L516.2,421.6 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z M59.7,462.1 L66.3,423.1 L120.5,409.8 L148.3,432.0 L187.9,437.0 L191.4,476.6 L235.0,475.9 L235.0,493.6 L307.5,493.2 L326.3,522.7 L314.2,554.8 L289.6,554.8 L228.7,602.7 L139.7,614.0 L107.6,600.9 L120.4,523.3 L100.0,465.3 L59.7,462.1 Z M483.5,113.1 L513.2,119.4 L561.4,100.7 L560.5,192.5 L589.9,207.1 L589.8,221.6 L502.4,223.8 L498.4,168.9 L518.7,146.8 L483.5,113.1 Z M600.3,235.9 L770.2,242.0 L765.4,276.3 L737.5,283.8 L762.9,303.1 L740.1,358.3 L771.7,358.0 L772.2,393.9 L602.1,407.3 L600.3,235.9 Z M568.0,606.7 L573.5,450.5 L587.8,450.5 L588.0,407.3 L772.2,393.9 L775.8,731.9 L637.5,732.4 L636.8,607.5 L568.0,606.7 Z M332.8,144.5 L339.1,120.4 L389.8,119.7 L384.9,192.4 L359.4,192.4 L332.8,144.5 Z M176.7,730.6 L176.9,614.0 L289.6,566.6 L288.8,730.1 L176.7,730.6 Z M341.2,323.0 L352.7,263.2 L517.1,264.6 L515.3,307.2 L462.8,307.4 L443.7,336.0 L341.9,335.6 L341.2,323.0 Z M80.2,667.3 L119.0,601.7 L174.6,611.6 L176.7,730.8 L106.4,732.2 L110.0,692.1 L80.2,667.3 Z M288.7,710.4 L289.6,554.8 L314.2,554.8 L326.3,522.7 L307.7,473.8 L402.6,464.0 L400.7,607.9 L456.2,608.3 L456.6,732.5 L288.8,730.1 L288.7,710.4 Z M400.5,579.2 L402.6,464.0 L573.6,464.9 L568.0,607.9 L636.8,607.5 L637.5,732.4 L456.6,732.5 L456.2,608.3 L400.7,607.9 L400.5,579.2 Z M67.3,415.3 L71.6,354.7 L349.7,363.9 L307.5,493.2 L235.0,493.6 L235.0,475.9 L191.4,476.6 L187.9,437.0 L148.3,432.0 L120.5,409.8 L91.6,423.3 L67.3,415.3 Z M71.5,353.1 L84.2,227.7 L118.0,227.7 L133.1,328.9 L118.5,328.8 L111.9,353.6 L71.5,353.1 Z M173.2,308.3 L195.5,292.9 L187.1,276.6 L204.2,286.9 L230.1,269.1 L347.1,287.4 L347.1,357.8 L278.1,365.9 L220.2,353.0 L215.4,367.3 L184.6,367.4 L173.2,308.3 Z M771.7,358.2 L802.7,327.1 L848.0,327.0 L860.4,350.9 L905.5,354.1 L930.8,372.2 L914.4,428.7 L915.2,731.4 L775.8,731.9 L771.7,358.2 Z M182.7,258.7 L199.3,243.7 L208.1,187.9 L235.3,192.2 L229.4,213.5 L263.1,248.6 L355.0,254.5 L347.7,287.4 L230.1,269.1 L203.4,286.9 L182.7,258.7 Z M560.6,177.1 L561.4,100.7 L628.9,83.2 L628.6,135.3 L663.0,149.7 L660.9,235.7 L586.1,236.0 L589.9,207.1 L560.5,192.5 L560.6,177.1 Z M212.7,124.1 L232.5,114.5 L242.9,132.9 L288.2,145.2 L332.5,127.7 L344.7,158.7 L234.7,163.4 L212.7,124.1 Z M117.9,231.2 L196.1,222.7 L186.5,281.4 L120.4,281.2 L117.9,231.2 Z M438.6,187.8 L461.8,157.5 L452.3,129.0 L483.5,113.1 L508.9,131.5 L518.4,151.0 L502.3,158.1 L495.2,188.6 L506.2,218.4 L474.4,221.2 L438.6,187.8 Z M83.3,224.4 L87.7,107.2 L161.2,106.1 L146.5,117.8 L168.6,134.6 L146.5,161.1 L149.1,199.3 L110.9,199.3 L118.0,227.7 L83.3,224.4 Z M628.6,98.0 L628.9,83.2 L681.8,69.7 L802.0,69.5 L785.5,157.2 L716.3,177.9 L737.6,235.8 L660.9,235.7 L663.0,149.7 L628.6,135.3 L628.6,98.0 Z M716.3,177.9 L785.5,157.2 L794.0,99.9 L829.4,92.6 L839.4,174.6 L861.6,207.5 L886.7,207.5 L886.7,221.8 L747.4,241.3 L716.3,177.9 Z M802.0,69.5 L928.4,70.4 L972.3,110.8 L982.2,135.4 L944.1,222.1 L861.6,207.5 L831.8,149.9 L829.4,92.6 L802.0,92.7 L802.0,69.5 Z M346.4,233.2 L363.9,224.1 L359.4,192.4 L384.9,192.4 L389.8,119.7 L420.4,134.8 L448.9,126.5 L463.0,150.0 L439.4,198.9 L501.3,221.3 L517.1,264.6 L356.0,264.0 L346.4,233.2 Z M146.5,161.1 L168.6,137.0 L146.5,117.8 L200.6,106.2 L234.7,149.1 L234.7,180.2 L146.5,161.1 Z M502.4,223.8 L586.2,223.9 L600.3,235.9 L602.3,349.7 L573.3,349.8 L558.7,327.9 L515.3,328.4 L502.4,223.8 Z M110.8,207.5 L149.1,199.3 L148.9,163.4 L200.4,168.1 L222.1,192.1 L204.7,191.3 L196.1,222.7 L110.9,222.4 L110.8,207.5 Z" class="preview-grid" />
            <path d="M323.0,464.0 L327.4,462.2 L326.2,424.1 L338.8,415.1 L350.7,383.8 L341.9,335.6 L429.5,335.9 L430.0,377.7 L443.8,378.4 L443.9,407.0 L472.2,407.6 L472.3,421.8 L516.2,421.6 L516.3,436.0 L530.5,436.1 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z" class="preview-selected" />
          </svg>
          <span class="mode-button-title">Name the county</span>
          <span class="mode-button-desc">Click the named county on the map</span>
        </button>
      </div>
      <div class="mode-instructions" id="mode-instructions"></div>
      <div class="mode-lines" id="game-lines"></div>
      <div class="btn-row">
        <button type="button" class="btn-primary btn-big" id="btn-start">Start game</button>
      </div>
    </div>

    <div class="card">
      <h2>Seed — same seed, same game</h2>
      <label class="field-label" for="seed-input">Game seed</label>
      <div class="seed-row">
        <input type="text" id="seed-input" autocomplete="off" spellcheck="false" maxlength="20" />
        <button type="button" id="btn-daily-seed">Use today&rsquo;s daily seed</button>
        <button type="button" id="btn-random-seed">Random seed</button>
      </div>
      <p class="muted small" style="margin-top:12px" id="seed-hint">Same seed = same 10 cities, in the same order, for anyone, any time.
        Share the seed (or the game link) to play the same game as another player.</p>
    </div>

    <div class="card">
      <h2>Map landmarks</h2>
      <div class="toggle-row" role="group" aria-label="Map layers">
        <button type="button" class="toggle" data-layer="interstate" aria-pressed="true"><span class="swatch"></span>Interstates</button>
        <button type="button" class="toggle" data-layer="highway" aria-pressed="true"><span class="swatch"></span>Highways</button>
        <button type="button" class="toggle" data-layer="river" aria-pressed="true"><span class="swatch"></span>Rivers</button>
        <button type="button" class="toggle" data-layer="lake" aria-pressed="true"><span class="swatch fill"></span>Lakes</button>
      </div>
      <p class="muted small" style="margin-top:12px">Landmarks are for orientation only — they don&rsquo;t affect scoring. Your choices stay in effect during play.</p>
    </div>
  </section>

  <!-- ================= ROUND ================= -->
  <section id="screen-game" class="screen" aria-label="Playing" hidden>
    <h2 id="round-heading">Question 1 of 10 &mdash; Where is &hellip;?</h2>
    <div class="round-status">
      <div class="progress-wrap">
        <div class="progress-track" id="progress-track" role="progressbar" aria-valuenow="0" aria-valuemin="0" aria-valuemax="1000" aria-label="Score out of 1000" aria-valuetext="0 out of 1000; maximum 100 after question 1">
          <div class="progress-fill" id="progress-fill" style="width: 0%"></div>
        </div>
        <div class="progress-max" id="progress-max" style="left: 10%" title="Maximum possible after question 1: 100" aria-hidden="true"></div>
      </div>
      <p class="score-line">Score: <span id="running-total">0</span> / <span id="running-max">1000</span> &nbsp;&middot;&nbsp; Seed: <span id="game-seed-label"></span></p>
    </div>

    <div class="map-card">
      <div class="game-controls">
        <div class="btn-row" id="guess-controls">
          <button type="button" class="btn-primary" id="btn-confirm" disabled>Confirm guess</button>
          <button type="button" id="btn-pass">Pass (0 points)</button>
          <span class="controls-hint" id="hint-text">Tap the map to drop a pin. Tap again (or drag) to move it, then confirm.</span>
        </div>
        <div class="btn-row" id="reveal-controls" hidden>
          <button type="button" class="btn-primary" id="btn-next">Next city</button>
          <span class="reveal-line" id="reveal-line"></span>
        </div>
      </div>
      <div class="map-frame">
        <svg id="map" viewBox="0 0 1000 757.4" role="img" aria-label="Blank map of Oregon with interstates, highways, rivers and lakes. Tap to place a pin.">
          <path class="state-shape" id="state-shape" d=""></path>
          <g id="layer-lake" class="layer-lake"></g>
          <g id="layer-river" class="layer-river"></g>
          <g id="layer-highway" class="layer-highway"></g>
          <g id="layer-interstate" class="layer-interstate"></g>
          <g id="county-grid" class="layer-hidden"></g>
          <g id="county-selected" class="layer-hidden"><path id="county-selected-path" class="county-selected" d="" /></g>
          <g id="county-true" class="layer-hidden"><path id="county-true-path" class="county-true" d="" /></g>
          <text id="county-label" class="map-label layer-hidden" x="0" y="0"></text>
          <g id="county-wrong" class="layer-hidden"><path id="county-wrong-path" class="county-wrong" d="" /></g>
          <g id="county-piece" class="layer-hidden"><path id="county-piece-path" class="county-piece" d="" /></g>
          <line id="connector" class="connector layer-hidden" x1="0" y1="0" x2="0" y2="0"></line>
          <g id="truth-marker" class="truth-marker layer-hidden">
            <circle id="truth-circle" r="8" cx="0" cy="0"></circle>
            <line id="truth-h1" x1="0" y1="0" x2="0" y2="0"></line>
            <line id="truth-h2" x1="0" y1="0" x2="0" y2="0"></line>
            <line id="truth-v1" x1="0" y1="0" x2="0" y2="0"></line>
            <line id="truth-v2" x1="0" y1="0" x2="0" y2="0"></line>
          </g>
          <g id="guess-pin" class="guess-pin layer-hidden">
            <path id="guess-pin-shape" d="" fill="#2563eb" stroke="#ffffff" stroke-width="1.6"></path>
            <circle id="guess-pin-hole" r="3.4" fill="#ffffff"></circle>
          </g>
        </svg>
        <button type="button" class="pin-confirm" id="pin-confirm" hidden aria-label="Confirm guess">Confirm</button>
      </div>
    </div>
  </section>

  <!-- ================= RESULTS ================= -->
  <section id="screen-results" class="screen" aria-label="Results" hidden>
    <div class="card">
      <h2>Your score</h2>
      <div class="total-big"><span id="final-total">0</span> <small>/ <span id="final-max">1000</span></small></div>
      <p class="muted" id="final-sub"></p>
      <p id="final-highlights"></p>
    </div>

    <div class="card">
      <h2>Round by round</h2>
      <table class="results">
        <thead><tr><th>#</th><th id="col-item">City</th><th class="num" id="col-metric">Distance</th><th class="num">Points</th></tr></thead>
        <tbody id="results-body"></tbody>
      </table>
    </div>

    <div class="card">
      <h2>Share this game</h2>
      <p class="muted small" id="share-note">Anyone opening this link with the same seed gets the same 10 cities in the same order.</p>
      <div class="btn-row">
        <button type="button" id="btn-copy-link">Copy game link</button>
        <button type="button" id="btn-replay">Replay same seed</button>
        <button type="button" class="btn-primary" id="btn-again">Play again (new seed)</button>
        <span class="copied" id="copy-note" hidden>Copied!</span>
      </div>
      <p class="field-label" style="margin-top:16px">Send a challenge!</p>
      <div class="summary-box" id="summary-text"></div>
      <div class="btn-row">
        <button type="button" id="btn-copy-summary">Copy</button>
      </div>
    </div>
  </section>

  <footer>
    Projection: equirectangular with cos(44&deg;) correction. Bounds lon &minus;124.716 to &minus;116.314,
    lat 41.843 to 46.421, viewBox <code>0 0 1000 757.4</code>. One function projects lon/lat &rarr; x/y for drawing;
    its exact inverse converts taps back. Distances use the Haversine formula (Earth radius 3,959 miles).
    Scoring: <code>100 if rounded miles &le; 5, else max(0, 100 &minus; (rounded miles &minus; 5))</code>.
    Counties mode scores by overlap: the percentage of the real county covered by the placed piece
    (100 for a perfect fit), sampled on a 4-unit grid in map units. Name the county mode: 100 points
    for naming the right county, 50 for a county that touches it, 0 for any other county or a pass —
    1,000 points maximum.<br />
    Seeded shuffle: this web version hashes the seed with SHA-256 (WebCrypto) and uses the first 4 bytes as a
    signed 32-bit integer to drive a mulberry32 PRNG through a Fisher&ndash;Yates shuffle of the 241-city pool
    (or the 36-county pool in either county mode).
    The Blazor C# version (spec &sect;5) uses the same SHA-256 seed integer with <code>System.Random(seedInt)</code>
    instead of mulberry32, so the 10 cities picked for a given seed may differ between the JavaScript and C#
    versions — but the seed format, scoring, and projection are the same.<br />
    Map data: state outline &copy; U.S. Census Bureau (public domain); interstates, highways, rivers and lakes
    from Natural Earth (public domain). City coordinates for the 241 incorporated Oregon cities via OpenStreetMap / Nominatim.<br />
    Version 0.18.
  </footer>
</div>

<script type="application/json" id="data-cities">__CITIES__</script>
<script type="application/json" id="data-outline">__OUTLINE__</script>
<script type="application/json" id="data-landmarks">__LANDMARKS__</script>
<script type="application/json" id="data-counties">__COUNTIES__</script>

<script>
(function () {
  "use strict";
__PURE_JS__

  /* ============ Data & map drawing ============ */
  var cities = JSON.parse(document.getElementById("data-cities").textContent);
  var outline = JSON.parse(document.getElementById("data-outline").textContent);
  var landmarks = JSON.parse(document.getElementById("data-landmarks").textContent);
  var counties = JSON.parse(document.getElementById("data-counties").textContent);
  var SVGNS = "http://www.w3.org/2000/svg";
  function fmt(n) { return Math.round(n * 10) / 10; }
  function coordsToPath(coords, close) {
    var d = "";
    for (var i = 0; i < coords.length; i++) {
      var p = project(coords[i][0], coords[i][1]);
      d += (i === 0 ? "M" : "L") + fmt(p[0]) + "," + fmt(p[1]);
    }
    return close ? d + "Z" : d;
  }
  function geometryToPath(geom) {
    var i, j, d = "";
    if (!geom) return "";
    switch (geom.type) {
      case "LineString": return coordsToPath(geom.coordinates, false);
      case "MultiLineString":
        for (i = 0; i < geom.coordinates.length; i++) d += coordsToPath(geom.coordinates[i], false);
        return d;
      case "Polygon":
        for (i = 0; i < geom.coordinates.length; i++) d += coordsToPath(geom.coordinates[i], true);
        return d;
      case "MultiPolygon":
        for (i = 0; i < geom.coordinates.length; i++)
          for (j = 0; j < geom.coordinates[i].length; j++)
            d += coordsToPath(geom.coordinates[i][j], true);
        return d;
    }
    return "";
  }
  function makePath(d) {
    var p = document.createElementNS(SVGNS, "path");
    p.setAttribute("d", d);
    return p;
  }

  outline.features.forEach(function (f) {
    document.getElementById("state-shape").setAttribute("d", geometryToPath(f.geometry));
  });
  var layerGroups = {
    interstate: document.getElementById("layer-interstate"),
    highway: document.getElementById("layer-highway"),
    river: document.getElementById("layer-river"),
    lake: document.getElementById("layer-lake")
  };
  landmarks.features.forEach(function (f) {
    var g = layerGroups[f.properties.layer];
    if (g) g.appendChild(makePath(geometryToPath(f.geometry)));
  });

  /* ============ Landmark toggles (start screen only) ============ */
  var layerState = { interstate: true, highway: true, river: true, lake: true };
  document.querySelectorAll(".toggle[data-layer]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var layer = btn.getAttribute("data-layer");
      layerState[layer] = !layerState[layer];
      document.querySelectorAll('.toggle[data-layer="' + layer + '"]').forEach(function (b) {
        b.setAttribute("aria-pressed", String(layerState[layer]));
      });
      layerGroups[layer].classList.toggle("layer-hidden", !layerState[layer]);
    });
  });

  /* ============ Screens ============ */
  var screenStart = document.getElementById("screen-start");
  var screenGame = document.getElementById("screen-game");
  var screenResults = document.getElementById("screen-results");
  function showScreen(which) {
    screenStart.hidden = which !== "start";
    screenGame.hidden = which !== "game";
    screenResults.hidden = which !== "results";
    /* Once a game starts, the header is the in-game title — and it stays
       that way on the results screen. The start screen shows the state
       title too, because this file is the Oregon edition (the state is
       known); the browser tab follows the same rule. In the Blazor app
       the start title is state-specific only when the URL named the state. */
    var title = "Where in the " + STATE_NAME + "?!";
    document.getElementById("game-title-text").textContent = title;
    document.title = title;
    window.scrollTo(0, 0);
  }

  /* ============ Start screen ============ */
  var seedInput = document.getElementById("seed-input");
  function paramsFromUrl() {
    try { return new URLSearchParams(window.location.search); } catch (e) { return new URLSearchParams(""); }
  }
  var urlParams = paramsFromUrl();
  var urlSeed = urlParams.get("seed");
  seedInput.value = (urlSeed && urlSeed.trim()) ? urlSeed.trim().toUpperCase() : dailySeed();
  /* Force seeds to upper case as the player types, so the box always
     shows the canonical form. The cursor is kept where it was. */
  seedInput.addEventListener("input", function () {
    var start = seedInput.selectionStart, end = seedInput.selectionEnd;
    var upper = seedInput.value.toUpperCase();
    if (upper !== seedInput.value) {
      seedInput.value = upper;
      seedInput.setSelectionRange(start, end);
    }
  });
  document.getElementById("btn-random-seed").addEventListener("click", function () {
    seedInput.value = randomSeed();
    seedInput.focus();
  });
  document.getElementById("btn-daily-seed").addEventListener("click", function () {
    seedInput.value = dailySeed();
    seedInput.focus();
  });

  /* ============ Game mode (City County / Cities / Counties) ============
     The picker on the start screen; the lede, seed hint, game line and
     how-it-works steps all change with the mode, like the Blazor start
     screen. A shared link carries ?mode=city-county (or counties, or
     name-the-county) for a non-city game. */
  var MODE_COPY = {
    "city-county": {
      lede: "A mix of both: 7 city rounds and 3 county rounds, shuffled together. City rounds: drop a pin where you think the city is. County rounds: click the county on the map. 100 points per question — full points for a pin within 5 miles, 100 for naming the right county, 50 for a county that touches it. 10 questions per game.",
      seedHint: "Same seed = same 7 cities and 3 counties, in the same order, for anyone, any time. Share the seed (or the game link) to play the same game as another player.",
      gameLine: "Seven city questions and three county questions, 100 points per question, 1,000 points maximum.",
      steps: [
        ["Pick a seed", "Same seed, same 7 cities and 3 counties — share it to play together."],
        ["Drop a pin or pick the county", "City rounds: tap the map where you think the city is. County rounds: click the county that matches the name."],
        ["See how close", "The real spot or county is revealed, with your distance or pick and your points."]
      ]
    },
    cities: {
      lede: "Ten Oregon cities, one blank map. Tap where you think each city is — the closer your pin, the more points. Full points within 5 miles, then −1 point per mile beyond that.",
      seedHint: "Same seed = same 10 cities, in the same order, for anyone, any time. Share the seed (or the game link) to play the same game as another player.",
      gameLine: "One pin per city, 100 points per question, 1,000 points maximum.",
      steps: [
        ["Pick a seed", "Same seed, same 10 cities — share it to play together."],
        ["Drop a pin", "Tap the map where you think the city is, then confirm."],
        ["See how close", "The real spot is revealed, with your distance and points."]
      ]
    },
    counties: {
      lede: "A blank map of Oregon — outline and landmarks, but no county lines. Each round names one county; drag its shape onto the map where you think it belongs. 100 points for a perfect fit, scaled by how much of the real county you cover. 10 questions per game.",
      seedHint: "Same seed = same 10 counties, in the same order, for anyone, any time. Share the seed (or the game link) to play the same game as another player.",
      gameLine: "One county per question, 100 points per question, 1,000 points maximum.",
      steps: [
        ["Pick a seed", "Same seed, same 10 counties — share it to play together."],
        ["Drag the piece", "Drag the county's shape onto the map where it belongs, then confirm."],
        ["See the overlap", "The real county is revealed, with how much of it you covered and your points."]
      ]
    },
    "name-the-county": {
      lede: "A map of Oregon with every county outlined, but no county names. Each round names one county; click the county you think it is. 100 points for naming the right county, 50 for a county that touches it, 0 for any other. 10 questions per game.",
      seedHint: "Same seed = same 10 counties, in the same order, for anyone, any time. Share the seed (or the game link) to play the same game as another player.",
      gameLine: "One county per question, 100 points per correct answer, 50 for a neighboring county, 1,000 points maximum.",
      steps: [
        ["Pick a seed", "Same seed, same 10 counties — share it to play together."],
        ["Pick the county", "Click the county on the map that matches the name, then confirm."],
        ["See if you were right", "The real county is revealed, with what you picked and your points."]
      ]
    }
  };
  /* The selected mode, kept in a variable: the mode buttons are plain
     buttons, not radios, so there is no :checked state to read. Clicking a
     button selects the mode (it does not start the game — Start still does
     that); the selected button is marked aria-pressed. */
  var currentMode = "cities";
  function selectedMode() { return currentMode; }
  function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll(".mode-button").forEach(function (btn) {
      btn.setAttribute("aria-pressed", String(btn.getAttribute("data-mode") === mode));
    });
    updateModeUI();
  }
  /* Build the per-mode variants once, at init, from MODE_COPY: the lede +
     1-2-3 steps under the mode picker, and the game line in the Game card.
     All three variants are rendered in one grid cell and only the selected
     one is visible, so the block is always as tall as the tallest variant
     and switching modes never moves anything below it. */
  var MODES = ["city-county", "cities", "counties", "name-the-county"];
  function buildModeVariants() {
    var instructions = document.getElementById("mode-instructions");
    var lines = document.getElementById("game-lines");
    MODES.forEach(function (mode) {
      var copy = MODE_COPY[mode];
      var set = document.createElement("div");
      set.className = "mode-instructions-set";
      set.setAttribute("data-mode", mode);
      var lede = document.createElement("p");
      lede.className = "lede";
      lede.textContent = copy.lede;
      set.appendChild(lede);
      var ol = document.createElement("ol");
      ol.className = "how-it-works";
      copy.steps.forEach(function (step, i) {
        var li = document.createElement("li");
        var strong = document.createElement("strong");
        var num = document.createElement("span");
        num.className = "step-num";
        num.textContent = String(i + 1);
        strong.appendChild(num);
        strong.appendChild(document.createTextNode(step[0]));
        li.appendChild(strong);
        li.appendChild(document.createTextNode(step[1]));
        ol.appendChild(li);
      });
      set.appendChild(ol);
      instructions.appendChild(set);
      var lineSet = document.createElement("div");
      lineSet.className = "mode-lines-set";
      lineSet.setAttribute("data-mode", mode);
      var p = document.createElement("p");
      p.textContent = copy.gameLine;
      lineSet.appendChild(p);
      lines.appendChild(lineSet);
    });
  }
  function updateModeUI() {
    var mode = selectedMode();
    var copy = MODE_COPY[mode];
    document.getElementById("seed-hint").textContent = copy.seedHint;
    document.querySelectorAll(".mode-instructions-set").forEach(function (set) {
      var active = set.getAttribute("data-mode") === mode;
      set.classList.toggle("is-active", active);
      set.setAttribute("aria-hidden", String(!active));
    });
    document.querySelectorAll(".mode-lines-set").forEach(function (set) {
      var active = set.getAttribute("data-mode") === mode;
      set.classList.toggle("is-active", active);
      set.setAttribute("aria-hidden", String(!active));
    });
  }
  buildModeVariants();
  document.querySelectorAll(".mode-button").forEach(function (btn) {
    btn.addEventListener("click", function () { setMode(btn.getAttribute("data-mode")); });
  });
  /* The county modes are only offered when the pack has counties; this file
     always does (36), but the guard mirrors the Blazor disabled handling. */
  if (!counties || !counties.features || counties.features.length === 0) {
    document.querySelectorAll('.mode-button[data-mode="city-county"], .mode-button[data-mode="counties"], .mode-button[data-mode="name-the-county"]').forEach(function (btn) {
      btn.disabled = true;
    });
  }
  var urlMode = urlParams.get("mode");
  if (urlMode) {
    var modeValue = urlMode.toLowerCase();
    if (modeValue === "city-county" || modeValue === "counties" || modeValue === "name-the-county") {
      setMode(modeValue);
    }
  }
  updateModeUI();

  /* ============ Game state ============ */
  var QUESTION_COUNT = 10;
  /* The state name, used to build the in-game title ("Where in the Oregon?!").
     A single constant keeps the generic-derivation principle: a future
     parameterized build only has to change this one value. */
  var STATE_NAME = "Oregon";
  /* The shareable destination is always the live site, never this page's
     own address — in the test-page preview the origin is the preview host,
     which is not a shareable game link. */
  var LIVE_SITE_BASE = "https://matt-lane.github.io/where-in-the-state/";
  function modeQueryParam(mode) {
    return mode === "city-county" ? "?mode=city-county"
      : mode === "counties" ? "?mode=counties"
      : mode === "name-the-county" ? "?mode=name-the-county" : "";
  }
  function gameLink() {
    return LIVE_SITE_BASE + "oregon/" + encodeURIComponent(game.seed) + modeQueryParam(game.mode);
  }
  var game = null; /* { seed, mode, cities, counties, rounds (city-county only), roundIndex, results, total } */
  var guess = null; /* { lat, lon, x, y } */
  var phase = "guess"; /* "guess" | "revealed" */
  var dragging = false;
  /* Counties mode: the current county's rings in SVG units, the piece's
     translation in SVG units, and whether it has been dragged this round
     (Confirm stays disabled until it has — the staging position is not
     an answer). */
  var countyRings = null;
  var pieceDx = 0, pieceDy = 0;
  var countyDragged = false;
  var pieceDragging = false;
  var dragStart = null;
  /* "Name the county" mode: the county the player has selected this round
     (Confirm stays disabled until one is selected), and every county's
     rings in SVG units for the boundary grid and for click hit-testing.
     Counties tile the state without overlapping, so a click lands in at
     most one of them. */
  var selectedCounty = null;
  var allCountyRings = null;

  var svg = document.getElementById("map");
  var guessPin = document.getElementById("guess-pin");
  var pinShape = document.getElementById("guess-pin-shape");
  var pinHole = document.getElementById("guess-pin-hole");
  var connector = document.getElementById("connector");
  var truthMarker = document.getElementById("truth-marker");
  var btnConfirm = document.getElementById("btn-confirm");
  var btnPass = document.getElementById("btn-pass");
  var btnNext = document.getElementById("btn-next");
  var pinConfirm = document.getElementById("pin-confirm");
  var countyPiece = document.getElementById("county-piece");
  var countyPiecePath = document.getElementById("county-piece-path");
  var countyTrue = document.getElementById("county-true");
  var countyTruePath = document.getElementById("county-true-path");
  var countyLabelEl = document.getElementById("county-label");
  var countyGrid = document.getElementById("county-grid");
  var countySelectedEl = document.getElementById("county-selected");
  var countySelectedPath = document.getElementById("county-selected-path");
  var countyWrongEl = document.getElementById("county-wrong");
  var countyWrongPath = document.getElementById("county-wrong-path");

  function pinPath(x, y) {
    return "M" + fmt(x) + "," + fmt(y) +
      " C" + fmt(x - 9) + "," + fmt(y - 11) + " " + fmt(x - 9.5) + "," + fmt(y - 24) + " " + fmt(x) + "," + fmt(y - 24) +
      " C" + fmt(x + 9.5) + "," + fmt(y - 24) + " " + fmt(x + 9) + "," + fmt(y - 11) + " " + fmt(x) + "," + fmt(y) + " Z";
  }
  function setLine(id, x1, y1, x2, y2) {
    var el = document.getElementById(id);
    el.setAttribute("x1", x1); el.setAttribute("y1", y1);
    el.setAttribute("x2", x2); el.setAttribute("y2", y2);
  }
  function showGuessPin() {
    pinShape.setAttribute("d", pinPath(guess.x, guess.y));
    pinHole.setAttribute("cx", fmt(guess.x));
    pinHole.setAttribute("cy", fmt(guess.y - 16.5));
    guessPin.classList.remove("layer-hidden");
  }
  function clearPins() {
    guessPin.classList.add("layer-hidden");
    connector.classList.add("layer-hidden");
    truthMarker.classList.add("layer-hidden");
  }
  function showTruth(city) {
    var tp = project(city.longitude, city.latitude);
    connector.setAttribute("x1", fmt(guess.x)); connector.setAttribute("y1", fmt(guess.y));
    connector.setAttribute("x2", fmt(tp[0])); connector.setAttribute("y2", fmt(tp[1]));
    connector.classList.remove("layer-hidden");
    document.getElementById("truth-circle").setAttribute("cx", fmt(tp[0]));
    document.getElementById("truth-circle").setAttribute("cy", fmt(tp[1]));
    setLine("truth-h1", fmt(tp[0] - 13), fmt(tp[1]), fmt(tp[0] - 4), fmt(tp[1]));
    setLine("truth-h2", fmt(tp[0] + 4), fmt(tp[1]), fmt(tp[0] + 13), fmt(tp[1]));
    setLine("truth-v1", fmt(tp[0]), fmt(tp[1] - 13), fmt(tp[0]), fmt(tp[1] - 4));
    setLine("truth-v2", fmt(tp[0]), fmt(tp[1] + 4), fmt(tp[0]), fmt(tp[1] + 13));
    truthMarker.classList.remove("layer-hidden");
  }

  /* ============ Counties mode helpers ============ */
  /* The county's rings in SVG coordinates. All rings of every polygon
     part (like the Blazor loader's ReadRings) — Clatsop and Curry are
     MultiPolygons, and no Oregon county has holes. */
  function countyRingsSvg(feature) {
    var rings = [];
    var geom = feature.geometry;
    function toSvg(coords) {
      var out = [];
      for (var i = 0; i < coords.length; i++) out.push(project(coords[i][0], coords[i][1]));
      return out;
    }
    if (geom.type === "Polygon") {
      for (var i = 0; i < geom.coordinates.length; i++) rings.push(toSvg(geom.coordinates[i]));
    } else if (geom.type === "MultiPolygon") {
      for (var p = 0; p < geom.coordinates.length; p++)
        for (var r = 0; r < geom.coordinates[p].length; r++) rings.push(toSvg(geom.coordinates[p][r]));
    }
    return rings;
  }
  function ringsToPath(rings) {
    var d = "";
    for (var i = 0; i < rings.length; i++) {
      var ring = rings[i];
      for (var j = 0; j < ring.length; j++) {
        d += (j === 0 ? "M" : "L") + fmt(ring[j][0]) + "," + fmt(ring[j][1]);
      }
      d += "Z";
    }
    return d;
  }
  function ringsBbox(rings) {
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    rings.forEach(function (ring) {
      ring.forEach(function (pt) {
        if (pt[0] < minX) minX = pt[0]; if (pt[0] > maxX) maxX = pt[0];
        if (pt[1] < minY) minY = pt[1]; if (pt[1] > maxY) maxY = pt[1];
      });
    });
    return { minX: minX, minY: minY, maxX: maxX, maxY: maxY };
  }
  /* The staging position: the piece's bounding-box top-left at (10, 10)
     in SVG units — up in the top-left corner, outside the state outline,
     clearly a piece waiting to be placed rather than an answer. */
  function stagingTranslation(rings) {
    var b = ringsBbox(rings);
    return [10 - b.minX, 10 - b.minY];
  }
  function setPieceTransform() {
    countyPiece.setAttribute("transform", "translate(" + fmt(pieceDx) + " " + fmt(pieceDy) + ")");
  }
  function clearCountyOverlays() {
    countyTrue.classList.add("layer-hidden");
    countyLabelEl.classList.add("layer-hidden");
    countyPiece.classList.add("layer-hidden");
    countySelectedEl.classList.add("layer-hidden");
    countyWrongEl.classList.add("layer-hidden");
    countyGrid.classList.add("layer-hidden");
  }
  /* "Name the county" mode: the grid of all county boundaries, drawn once
     at load from the embedded counties data (one path per county, using
     the same geometry-to-path conversion as the landmarks). The grid only
     shows in Name the county mode — the drag mode hides county lines. */
  function buildCountyGrid() {
    allCountyRings = [];
    counties.features.forEach(function (feature) {
      var path = makePath(geometryToPath(feature.geometry));
      path.setAttribute("class", "county-boundary");
      countyGrid.appendChild(path);
      allCountyRings.push({ feature: feature, rings: countyRingsSvg(feature) });
    });
  }
  buildCountyGrid();
  /* Find the county containing a point in SVG units, or null. A click
     outside the state (ocean, a neighbouring state) is in no county. */
  function countyAtPoint(x, y) {
    for (var i = 0; i < allCountyRings.length; i++) {
      if (isInsideAnyRing(x, y, allCountyRings[i].rings)) return allCountyRings[i].feature;
    }
    return null;
  }
  /* Viewport (client) coordinates to SVG viewBox units, from the SVG's
     bounding rect. ClientX/Y are viewport-relative, so the rect is what
     converts them — OffsetX would be relative to the event target
     instead, which is the piece while dragging, not the map. */
  function clientToSvg(clientX, clientY) {
    var rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return { x: (clientX - rect.left) * W / rect.width, y: (clientY - rect.top) * H / rect.height };
  }
  /* The small Confirm bubble next to the piece once it has been dragged,
     like the pin's bubble in the city game: centred on the piece's
     bounding box, flipped to the piece's left near the right edge. */
  function updatePieceBubble() {
    if (!countyRings) return;
    var b = ringsBbox(countyRings);
    var cx = (b.minX + b.maxX) / 2 + pieceDx;
    var cy = (b.minY + b.maxY) / 2 + pieceDy;
    pinConfirm.style.left = (cx / 10).toFixed(2) + "%";
    pinConfirm.style.top = Math.min(96, Math.max(4, cy / 757.4 * 100)).toFixed(2) + "%";
    pinConfirm.classList.toggle("flipped", cx > 750);
    pinConfirm.hidden = false;
  }
  /* The small Confirm bubble next to the selected county in "Name the
     county" mode, like the pin's bubble in the city game and the piece's
     bubble in Counties mode: centred on the selected county's bounding
     box, flipped to the county's left near the right edge. */
  function updateSelectedBubble() {
    if (!selectedCounty) return;
    var rings = countyRingsSvg(selectedCounty);
    var b = ringsBbox(rings);
    var cx = (b.minX + b.maxX) / 2;
    var cy = (b.minY + b.maxY) / 2;
    pinConfirm.style.left = (cx / 10).toFixed(2) + "%";
    pinConfirm.style.top = Math.min(96, Math.max(4, cy / 757.4 * 100)).toFixed(2) + "%";
    pinConfirm.classList.toggle("flipped", cx > 750);
    pinConfirm.hidden = false;
  }
  /* The county name label on the true county at reveal, centred on the
     county's bounding box and clamped so long names don't run off the map. */
  function countyLabelPosition(rings) {
    var b = ringsBbox(rings);
    return {
      x: Math.min(910, Math.max(90, (b.minX + b.maxX) / 2)),
      y: Math.min(730, Math.max(30, (b.minY + b.maxY) / 2))
    };
  }

  function eventToSvg(ev) {
    var pt = svg.createSVGPoint();
    pt.x = ev.clientX; pt.y = ev.clientY;
    var ctm = svg.getScreenCTM();
    if (!ctm) return null;
    return pt.matrixTransform(ctm.inverse());
  }
  function placeGuessAt(x, y) {
    var ll = unproject(x, y);
    guess = { lon: ll[0], lat: ll[1], x: x, y: y };
    pinShape.setAttribute("fill", "#2563eb");
    showGuessPin();
    btnConfirm.disabled = false;
    /* Show the small Confirm bubble next to the pin (flipped to the
       pin's left near the right edge, clamped vertically so it never
       clips out of the map frame). */
    pinConfirm.style.left = (x / 10).toFixed(2) + "%";
    pinConfirm.style.top = Math.min(96, Math.max(4, y / 757.4 * 100)).toFixed(2) + "%";
    pinConfirm.classList.toggle("flipped", x > 750);
    pinConfirm.hidden = false;
    document.getElementById("hint-text").textContent = "Pin dropped — tap again or drag to move it, then confirm your guess.";
  }
  svg.addEventListener("pointerdown", function (ev) {
    if (!game || phase !== "guess" || game.mode === "counties" || game.mode === "name-the-county" || isMixedCountyRound()) return;
    ev.preventDefault();
    var loc = eventToSvg(ev);
    if (!loc) return;
    dragging = true;
    try { svg.setPointerCapture(ev.pointerId); } catch (e) {}
    placeGuessAt(loc.x, loc.y);
  });
  svg.addEventListener("pointermove", function (ev) {
    if (!dragging || !game || phase !== "guess" || game.mode === "counties" || game.mode === "name-the-county" || isMixedCountyRound()) return;
    var loc = eventToSvg(ev);
    if (!loc) return;
    placeGuessAt(loc.x, loc.y);
  });
  function endDrag() { dragging = false; }
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);

  /* ============ "Name the county" click to select ============
     A click on the map selects the county containing that point (the
     counties tile the state, so a click lands in at most one). Clicking
     another county changes the selection; a click outside all counties
     (ocean, a neighbouring state) selects nothing. The selected county
     is highlighted in blue and the Confirm bubble appears next to it.
     Also used for the county rounds of City County Mode. */
  svg.addEventListener("pointerdown", function (ev) {
    if (!game || (game.mode !== "name-the-county" && !isMixedCountyRound()) || phase !== "guess") return;
    ev.preventDefault();
    var loc = eventToSvg(ev);
    if (!loc) return;
    var picked = countyAtPoint(loc.x, loc.y);
    if (!picked) {
      /* A click outside all counties selects nothing: clear any existing
         selection, hide the highlight and the Confirm bubble, and disable
         Confirm again. Without this, a stray click outside the state would
         leave the previous county selected. */
      selectedCounty = null;
      countySelectedEl.classList.add("layer-hidden");
      pinConfirm.hidden = true;
      btnConfirm.disabled = true;
      document.getElementById("hint-text").textContent = "Click a county on the map to select it.";
      return;
    }
    selectedCounty = picked;
    countySelectedPath.setAttribute("d", ringsToPath(countyRingsSvg(picked)));
    countySelectedEl.classList.remove("layer-hidden");
    btnConfirm.disabled = false;
    updateSelectedBubble();
    document.getElementById("hint-text").textContent =
      "County selected — click another county to change it, or confirm.";
  });

  /* ============ County piece drag ============
     pointerdown on the piece starts the drag (recording the pointer's
     SVG position and the current translation); pointermove on the SVG
     moves the piece by the pointer's movement delta; pointerup ends it.
     The piece follows the pointer rigidly — no per-move callbacks, the
     parent only needs the final position at confirm time. */
  countyPiece.addEventListener("pointerdown", function (ev) {
    if (!game || game.mode !== "counties" || phase !== "guess") return;
    ev.preventDefault();
    var loc = clientToSvg(ev.clientX, ev.clientY);
    if (!loc) return;
    pieceDragging = true;
    dragStart = { x: loc.x, y: loc.y, dx: pieceDx, dy: pieceDy };
    try { countyPiece.setPointerCapture(ev.pointerId); } catch (e) {}
    countyPiece.classList.add("dragging");
    /* Hide the Confirm bubble while the piece is being dragged — it only
       shows once the player stops moving it (on drop, see endPieceDrag). */
    pinConfirm.hidden = true;
    if (!countyDragged) {
      countyDragged = true;
      btnConfirm.disabled = false;
      document.getElementById("hint-text").textContent = "Piece placed — drag it again to move it, or confirm.";
    }
  });
  svg.addEventListener("pointermove", function (ev) {
    if (!pieceDragging || !dragStart) return;
    var loc = clientToSvg(ev.clientX, ev.clientY);
    if (!loc) return;
    pieceDx = dragStart.dx + (loc.x - dragStart.x);
    pieceDy = dragStart.dy + (loc.y - dragStart.y);
    setPieceTransform();
  });
  function endPieceDrag() {
    if (!pieceDragging) return;
    pieceDragging = false;
    dragStart = null;
    countyPiece.classList.remove("dragging");
    /* The drag is over — the piece has stopped moving, so show the Confirm
       bubble next to it. It stays hidden while dragging (see pointerdown). */
    if (countyDragged) updatePieceBubble();
  }
  svg.addEventListener("pointerup", endPieceDrag);
  svg.addEventListener("pointercancel", endPieceDrag);
  svg.addEventListener("pointerleave", endPieceDrag);

  /* City County Mode keeps its 10 rounds — 7 city, 3 county, interleaved
     by a seeded shuffle — in game.rounds; the round type decides whether
     the pin UI or the county grid is shown. The other modes index
     game.cities / game.counties directly. */
  function currentRound() { return game.mode === "city-county" ? game.rounds[game.roundIndex] : null; }
  function isMixedCountyRound() { var r = currentRound(); return r ? r.type === "county" : false; }
  function currentCity() { return game.mode === "city-county" ? currentRound().city : game.cities[game.roundIndex]; }
  function currentCounty() { return game.mode === "city-county" ? currentRound().county : game.counties[game.roundIndex]; }
  function updateRoundHeader() {
    var itemName = (game.mode === "counties" || game.mode === "name-the-county" || isMixedCountyRound())
      ? currentCounty().properties.name : currentCity().name;
    document.getElementById("round-heading").textContent =
      "Question " + (game.roundIndex + 1) + " of " + QUESTION_COUNT + " — Where is " + itemName + "?";
    document.getElementById("running-total").textContent = game.total;
    document.getElementById("game-seed-label").textContent = game.seed;
    /* The bar fills by total score (out of the mode's maximum); the tick marks
       the best total possible once the question on screen is scored.
       Every mode is 100 points per question, 1000 per game. */
    var maxTotal = 1000;
    var pointsPerRound = 100;
    var maxScore = (game.roundIndex + 1) * pointsPerRound;
    document.getElementById("progress-fill").style.width = (game.total * 100 / maxTotal) + "%";
    document.getElementById("progress-max").style.left = ((game.roundIndex + 1) * 10) + "%";
    document.getElementById("progress-max").setAttribute("title", "Maximum possible after question " + (game.roundIndex + 1) + ": " + maxScore);
    document.getElementById("running-max").textContent = String(maxTotal);
    var track = document.getElementById("progress-track");
    track.setAttribute("aria-valuenow", String(game.total));
    track.setAttribute("aria-valuemax", String(maxTotal));
    track.setAttribute("aria-label", "Score out of " + maxTotal);
    track.setAttribute("aria-valuetext", game.total + " out of " + maxTotal + "; maximum " + maxScore + " after question " + (game.roundIndex + 1));
  }
  function startRound() {
    phase = "guess";
    guess = null;
    clearPins();
    clearCountyOverlays();
    btnConfirm.disabled = true;
    btnPass.disabled = false;
    pinConfirm.hidden = true;
    document.getElementById("reveal-controls").hidden = true;
    document.getElementById("guess-controls").hidden = false;
    if (game.mode === "counties") {
      /* Stage the county piece: its own shape at 1:1 scale, bounding-box
         top-left at (10, 10) in the top-left corner of the map. */
      countyRings = countyRingsSvg(currentCounty());
      var staged = stagingTranslation(countyRings);
      pieceDx = staged[0]; pieceDy = staged[1];
      countyDragged = false;
      pieceDragging = false;
      dragStart = null;
      countyPiecePath.setAttribute("d", ringsToPath(countyRings));
      countyPiecePath.setAttribute("class", "county-piece");
      countyPiece.setAttribute("class", "county-piece");
      countyPiece.classList.remove("layer-hidden");
      setPieceTransform();
      document.getElementById("hint-text").textContent = "Drag the county piece onto the map.";
      svg.setAttribute("aria-label", "Blank map of Oregon. Drag the county piece onto the map where the county belongs.");
    } else if (game.mode === "name-the-county" || isMixedCountyRound()) {
      /* Show the grid of all county boundaries; the player clicks one to
         select it. No piece, no pin — the counties are the map. Also used
         for the county rounds of City County Mode. */
      countyRings = null;
      selectedCounty = null;
      countyGrid.classList.remove("layer-hidden");
      document.getElementById("hint-text").textContent = "Click a county on the map to select it.";
      svg.setAttribute("aria-label", "Map of Oregon with county boundaries. Click the county you think is named.");
    } else {
      countyRings = null;
      document.getElementById("hint-text").textContent = "Tap the map to drop a pin. Tap again (or drag) to move it, then confirm.";
      svg.setAttribute("aria-label", "Blank map of Oregon with interstates, highways, rivers and lakes. Tap to place a pin.");
    }
    updateRoundHeader();
  }

  function reveal(passed) {
    if (game.mode === "counties") { revealCounty(passed); return; }
    /* A county round — in "Name the county" mode or in City County Mode —
       uses the same reveal: 100 for the right county, 50 for a county
       sharing a border with it, 0 otherwise. */
    if (game.mode === "name-the-county" || isMixedCountyRound()) { revealNameTheCounty(passed); return; }
    var city = currentCity();
    phase = "revealed";
    btnConfirm.disabled = true;
    btnPass.disabled = true;
    pinConfirm.hidden = true;
    document.getElementById("guess-controls").hidden = true;
    var dist = null, points = 0;
    if (!passed && guess) {
      dist = haversineMiles(guess.lat, guess.lon, city.latitude, city.longitude);
      points = scoreForDistance(dist);
      pinShape.setAttribute("fill", "#cf2e4f");
      showGuessPin();
      showTruth(city);
    }
    game.total += points;
    game.results.push({ city: city, distance: dist, points: points, passed: passed });
    /* The controls row at the top of the map card swaps to the result:
       distance and points, plus the Next button. No separate reveal
       panel, and no running total here — the score line at the top
       already shows it. */
    var line = document.getElementById("reveal-line");
    if (passed) {
      line.textContent = "You passed — the green pin is " + city.name + ".";
    } else if (dist < 2) {
      line.textContent = "Dead on — " + dist.toFixed(1) + " mi off · 100 points";
    } else if (Math.round(dist) <= 5) {
      line.textContent = "Within 5 miles — " + dist.toFixed(1) + " mi off · 100 points";
    } else if (points > 0) {
      line.textContent = dist.toFixed(1) + " mi off · " + points + " points";
    } else {
      line.textContent = dist.toFixed(1) + " mi off · 0 points";
    }
    if (passed) {
      guessPin.classList.add("layer-hidden");
      /* For a pass there is no guess pin; still show the true location. */
      var tp = project(city.longitude, city.latitude);
      document.getElementById("truth-circle").setAttribute("cx", fmt(tp[0]));
      document.getElementById("truth-circle").setAttribute("cy", fmt(tp[1]));
      setLine("truth-h1", fmt(tp[0] - 13), fmt(tp[1]), fmt(tp[0] - 4), fmt(tp[1]));
      setLine("truth-h2", fmt(tp[0] + 4), fmt(tp[1]), fmt(tp[0] + 13), fmt(tp[1]));
      setLine("truth-v1", fmt(tp[0]), fmt(tp[1] - 13), fmt(tp[0]), fmt(tp[1] - 4));
      setLine("truth-v2", fmt(tp[0]), fmt(tp[1] + 4), fmt(tp[0]), fmt(tp[1] + 13));
      truthMarker.classList.remove("layer-hidden");
    }
    btnNext.textContent = game.roundIndex + 1 >= QUESTION_COUNT ? "See results" : (game.mode === "city-county" ? "Next question" : "Next city");
    document.getElementById("guess-controls").hidden = true;
    document.getElementById("reveal-controls").hidden = false;
    /* Refresh the header (and the score bar) now that the round is scored. */
    updateRoundHeader();
  }

  /* Counties reveal: the true county in green, the placed piece in red
     (semi-transparent fills, so where they overlap the colors blend),
     the county name on the true county, and the coverage line. A pass
     moves the piece onto the true county, like the city pass shows the
     true location — the green shape is the answer. */
  function revealCounty(passed) {
    var county = currentCounty();
    var countyName = county.properties.name;
    phase = "revealed";
    btnConfirm.disabled = true;
    btnPass.disabled = true;
    pinConfirm.hidden = true;
    document.getElementById("guess-controls").hidden = true;
    var overlap = null, points = 0;
    if (passed) {
      pieceDx = 0; pieceDy = 0;
      setPieceTransform();
    } else if (countyDragged) {
      overlap = overlapFraction(countyRings, pieceDx, pieceDy);
      points = scoreForOverlap(overlap);
    }
    game.total += points;
    game.results.push({ county: county, overlap: overlap, points: points, passed: passed });
    countyTruePath.setAttribute("d", ringsToPath(countyRings));
    countyTrue.classList.remove("layer-hidden");
    countyPiece.setAttribute("class", "");
    countyPiecePath.setAttribute("class", "county-placed");
    var labelPos = countyLabelPosition(countyRings);
    countyLabelEl.setAttribute("x", fmt(labelPos.x));
    countyLabelEl.setAttribute("y", fmt(labelPos.y));
    countyLabelEl.textContent = countyName;
    countyLabelEl.classList.remove("layer-hidden");
    var line = document.getElementById("reveal-line");
    if (passed) {
      line.textContent = "You passed — the green shape is " + countyName + ".";
    } else {
      line.textContent = "You covered " + Math.round(overlap * 100) + "% of " + countyName + " · " + points + " points";
    }
    btnNext.textContent = game.roundIndex + 1 >= QUESTION_COUNT ? "See results" : "Next county";
    document.getElementById("reveal-controls").hidden = false;
    /* Refresh the header (and the score bar) now that the round is scored. */
    updateRoundHeader();
  }

  /* "Name the county" reveal: the true county in green, and if the player
     picked a different county, that one in rust. Scoring: naming the right
     county is 100 points, a county sharing a border with it is 50
     ("Pretty close!"), any other county (or a pass) is 0. Adjacency comes
     from the counties data (properties.neighbors — see GAME-SPEC §6.5).
     The boundary grid stays visible underneath, as in the Blazor version. */
  function revealNameTheCounty(passed) {
    var county = currentCounty();
    var countyName = county.properties.name;
    phase = "revealed";
    btnConfirm.disabled = true;
    btnPass.disabled = true;
    pinConfirm.hidden = true;
    document.getElementById("guess-controls").hidden = true;
    countySelectedEl.classList.add("layer-hidden");
    var pickedName = null, correct = false, adjacent = false, points = 0;
    if (!passed && selectedCounty) {
      pickedName = selectedCounty.properties.name;
      correct = pickedName === countyName;
      adjacent = !correct && county.properties.neighbors
        && county.properties.neighbors.indexOf(pickedName) >= 0;
      points = correct ? 100 : adjacent ? 50 : 0;
    }
    game.total += points;
    game.results.push({ county: county, selected: selectedCounty, correct: correct, adjacent: adjacent, points: points, passed: passed });
    countyTruePath.setAttribute("d", ringsToPath(countyRingsSvg(county)));
    countyTrue.classList.remove("layer-hidden");
    if (!passed && selectedCounty && !correct) {
      countyWrongPath.setAttribute("d", ringsToPath(countyRingsSvg(selectedCounty)));
      countyWrongEl.classList.remove("layer-hidden");
    }
    var labelPos = countyLabelPosition(countyRingsSvg(county));
    countyLabelEl.setAttribute("x", fmt(labelPos.x));
    countyLabelEl.setAttribute("y", fmt(labelPos.y));
    countyLabelEl.textContent = countyName;
    countyLabelEl.classList.remove("layer-hidden");
    var line = document.getElementById("reveal-line");
    if (passed) {
      line.textContent = "You passed — the green county is " + countyName + ".";
    } else if (correct) {
      line.textContent = "Correct — that's " + countyName + " · 100 points";
    } else if (adjacent) {
      line.textContent = "Pretty close! That's " + pickedName + ", not " + countyName + " · 50 points";
    } else {
      line.textContent = "That's " + pickedName + ", not " + countyName + " · 0 points";
    }
    btnNext.textContent = game.roundIndex + 1 >= QUESTION_COUNT ? "See results" : (game.mode === "city-county" ? "Next question" : "Next county");
    document.getElementById("reveal-controls").hidden = false;
    /* Refresh the header (and the score bar) now that the round is scored. */
    updateRoundHeader();
  }

  btnConfirm.addEventListener("click", function () {
    if (phase !== "guess") return;
    if (game.mode === "counties") { if (countyDragged) reveal(false); }
    else if (game.mode === "name-the-county" || isMixedCountyRound()) { if (selectedCounty) reveal(false); }
    else if (guess) reveal(false);
  });
  btnPass.addEventListener("click", function () { if (phase === "guess") reveal(true); });
  pinConfirm.addEventListener("click", function () {
    if (phase !== "guess") return;
    if (game.mode === "counties") { if (countyDragged) reveal(false); }
    else if (game.mode === "name-the-county" || isMixedCountyRound()) { if (selectedCounty) reveal(false); }
    else if (guess) reveal(false);
  });
  btnNext.addEventListener("click", function () {
    game.roundIndex++;
    if (game.roundIndex >= QUESTION_COUNT) showResults();
    else startRound();
  });

  async function startGame(seed) {
    /* Seeds are forced to upper case, so "or-2026-11-06" and
       "OR-2026-11-06" are the same game. */
    seed = (seed || "").trim().toUpperCase();
    if (!seed) seed = randomSeed();
    var seedInt = await seedIntFromString(seed);
    var mode = selectedMode();
    if (mode === "city-county") {
      /* 7 cities and 3 counties, then the 10 rounds interleaved by a
         seeded shuffle — genuinely mixed, not 7-then-3. The same seed
         picks the same 7 cities and 3 counties (same selection as the
         single-type modes); only their order is shuffled. The C# version
         uses System.Random where this version uses mulberry32, so the
         same seed generally picks different cities/counties here than on
         the live site, and the interleaving order can differ too —
         accepted, same as the existing C#/JS divergence. */
      var mixedCities = selectItems(seedInt, cities, 7);
      var mixedCounties = selectItems(seedInt, counties.features, 3);
      var rounds = mixedCities.map(function (c) { return { type: "city", city: c }; })
        .concat(mixedCounties.map(function (c) { return { type: "county", county: c }; }));
      rounds = shuffleItems(seedInt, rounds);
      game = { seed: seed, mode: "city-county", cities: mixedCities, counties: mixedCounties, rounds: rounds, roundIndex: 0, results: [], total: 0 };
    } else if (mode === "counties") {
      var pickedCounties = selectItems(seedInt, counties.features, QUESTION_COUNT);
      game = { seed: seed, mode: "counties", cities: [], counties: pickedCounties, roundIndex: 0, results: [], total: 0 };
    } else if (mode === "name-the-county") {
      /* Same pool and same selection as the Counties drag mode, so the
         same seed picks the same 10 counties in both county modes. */
      var namedCounties = selectItems(seedInt, counties.features, QUESTION_COUNT);
      game = { seed: seed, mode: "name-the-county", cities: [], counties: namedCounties, roundIndex: 0, results: [], total: 0 };
    } else {
      var pickedCities = selectItems(seedInt, cities, QUESTION_COUNT);
      game = { seed: seed, mode: "cities", cities: pickedCities, counties: [], roundIndex: 0, results: [], total: 0 };
    }
    try {
      /* County games add a mode query so a shared link (and a refresh)
         replays the same mode. */
      history.replaceState(null, "", "?state=oregon&seed=" + encodeURIComponent(seed) +
        (mode === "cities" ? "" : "&mode=" + mode));
    } catch (e) {}
    showScreen("game");
    startRound();
  }

  document.getElementById("btn-start").addEventListener("click", function () {
    startGame(seedInput.value);
  });
  seedInput.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") startGame(seedInput.value);
  });

  /* ============ Results ============ */
  function showResults() {
    showScreen("results");
    document.getElementById("final-total").textContent = game.total;
    var isCounties = game.mode === "counties";
    var isName = game.mode === "name-the-county";
    var isMixed = game.mode === "city-county";
    var isCountyMode = isCounties || isName;
    document.getElementById("final-max").textContent = "1000";
    document.getElementById("col-item").textContent = isMixed ? "Target" : isCountyMode ? "County" : "City";
    document.getElementById("col-metric").textContent = isMixed ? "Answer" : isCounties ? "Coverage" : isName ? "Your pick" : "Distance";
    document.getElementById("share-note").textContent = isMixed
      ? "Anyone opening this link with the same seed gets the same 7 cities and 3 counties in the same order."
      : isCountyMode
      ? "Anyone opening this link with the same seed gets the same 10 counties in the same order."
      : "Anyone opening this link with the same seed gets the same 10 cities in the same order.";
    var scored = game.results.filter(function (r) { return !r.passed; });
    if (isMixed) {
      /* City rounds: average distance; county rounds: how many named
         correctly, and how many adjacent. */
      var cityScored = scored.filter(function (r) { return typeof r.distance === "number"; });
      var avgMixed = cityScored.length
        ? (cityScored.reduce(function (s, r) { return s + r.distance; }, 0) / cityScored.length).toFixed(1)
        : "—";
      var namedMixed = game.results.filter(function (r) { return r.correct; }).length;
      var adjacentMixed = game.results.filter(function (r) { return r.adjacent; }).length;
      document.getElementById("final-sub").textContent =
        "Seed " + game.seed + " · " + QUESTION_COUNT + " questions · average distance " + avgMixed + " miles (city rounds) · you named " + namedMixed + " out of 3 counties correctly" + (adjacentMixed > 0 ? " and were adjacent on " + adjacentMixed + " more" : "") + ".";
    } else if (isName) {
      var named = game.results.filter(function (r) { return r.correct; }).length;
      var adjacentNamed = game.results.filter(function (r) { return r.adjacent; }).length;
      document.getElementById("final-sub").textContent =
        "Seed " + game.seed + " · " + QUESTION_COUNT + " questions · you named " + named + " out of " + QUESTION_COUNT + " counties correctly" + (adjacentNamed > 0 ? " and were adjacent on " + adjacentNamed + " more" : "") + ".";
    } else if (isCounties) {
      var avgCov = scored.length
        ? Math.round(scored.reduce(function (s, r) { return s + r.overlap; }, 0) / scored.length * 100)
        : "—";
      document.getElementById("final-sub").textContent =
        "Seed " + game.seed + " · " + QUESTION_COUNT + " questions · average coverage " + avgCov + "% (placed rounds).";
    } else {
      var avg = scored.length
        ? (scored.reduce(function (s, r) { return s + r.distance; }, 0) / scored.length).toFixed(1)
        : "—";
      document.getElementById("final-sub").textContent =
        "Seed " + game.seed + " · " + QUESTION_COUNT + " questions · average distance " + avg + " miles (guessed rounds).";
    }
    var best = null, hardest = null;
    /* City County Mode ranks each round type separately: best city guess =
       smallest distance, hardest city = largest distance, best county pick
       = first county named correctly, hardest county = first one missed
       (preferring a picked wrong county over a pass). */
    var bestMixedCity = null, hardestMixedCity = null, bestMixedCounty = null, hardestMixedCounty = null;
    if (isMixed) {
      game.results.forEach(function (r) {
        if (typeof r.distance === "number") {
          if (!bestMixedCity || r.distance < bestMixedCity.distance) bestMixedCity = r;
          if (!hardestMixedCity || r.distance > hardestMixedCity.distance) hardestMixedCity = r;
        } else {
          if (!bestMixedCounty && r.correct) bestMixedCounty = r;
          if (!hardestMixedCounty && !r.correct && r.selected) hardestMixedCounty = r;
        }
      });
      /* No county named correctly? The best county pick is the first
         adjacent one (50 points) instead. */
      if (!bestMixedCounty) game.results.forEach(function (r) {
        if (!bestMixedCounty && r.adjacent) bestMixedCounty = r;
      });
      if (!hardestMixedCounty) game.results.forEach(function (r) {
        if (!hardestMixedCounty && r.distance === undefined && !r.correct) hardestMixedCounty = r;
      });
    } else if (isName) {
      /* Best pick = the first county named correctly — or, if none was,
         the first adjacent pick (50 points). Hardest county = the first
         one missed (preferring a picked wrong county over a pass). */
      game.results.forEach(function (r) {
        if (!best && r.correct) best = r;
        if (!hardest && !r.correct && r.selected) hardest = r;
      });
      if (!best) game.results.forEach(function (r) {
        if (!best && r.adjacent) best = r;
      });
      if (!hardest) game.results.forEach(function (r) {
        if (!hardest && !r.correct) hardest = r;
      });
    } else if (isCounties) {
      /* Best placement = highest coverage, hardest county = lowest
         coverage, among rounds that were placed (not passed). */
      scored.forEach(function (r) {
        if (!best || r.overlap > best.overlap) best = r;
        if (!hardest || r.overlap < hardest.overlap) hardest = r;
      });
    } else {
      scored.forEach(function (r) {
        if (!best || r.distance < best.distance) best = r;
        if (!hardest || r.distance > hardest.distance) hardest = r;
      });
    }
    var hl = document.getElementById("final-highlights");
    if (isMixed) {
      hl.innerHTML = "";
      var mixedParts = [];
      if (bestMixedCity && hardestMixedCity && bestMixedCity !== hardestMixedCity) {
        mixedParts.push(["Best guess:", bestMixedCity.city.name + " — " + bestMixedCity.distance.toFixed(1) + " miles off (" + bestMixedCity.points + " pts). "]);
        mixedParts.push(["Hardest city:", hardestMixedCity.city.name + " — " + hardestMixedCity.distance.toFixed(1) + " miles off (" + hardestMixedCity.points + " pts). "]);
      } else if (bestMixedCity) {
        mixedParts.push(["Best (and only scored) guess:", bestMixedCity.city.name + " — " + bestMixedCity.distance.toFixed(1) + " miles off. "]);
      }
      if (bestMixedCounty) {
        mixedParts.push(["Best county pick:", bestMixedCounty.county.properties.name + (bestMixedCounty.adjacent ? " — you picked a neighboring county (50 points). " : " — you named it correctly (100 points). ")]);
      }
      if (hardestMixedCounty) {
        mixedParts.push(["Hardest county:", hardestMixedCounty.county.properties.name + " — you picked " + (hardestMixedCounty.selected ? hardestMixedCounty.selected.properties.name : "nothing") + " (" + hardestMixedCounty.points + " points)."]);
      }
      if (mixedParts.length) {
        mixedParts.forEach(function (part) {
          var span = document.createElement("span");
          span.innerHTML = "<strong>" + part[0] + "</strong> ";
          span.appendChild(document.createTextNode(part[1]));
          hl.appendChild(span);
        });
      } else {
        hl.textContent = "Every round was passed — no guesses or picks to rank. Try placing a pin or clicking a county next time!";
      }
    } else if (best && hardest && best !== hardest) {
      hl.innerHTML = "";
      var b1 = document.createElement("span");
      var b2 = document.createElement("span");
      if (isName) {
        b1.innerHTML = "<strong>Best pick:</strong> ";
        b1.appendChild(document.createTextNode(best.county.properties.name + (best.adjacent ? " — you picked a neighboring county (50 points). " : " — you named it correctly (100 points). ")));
        b2.innerHTML = "<strong>Hardest county:</strong> ";
        b2.appendChild(document.createTextNode(hardest.county.properties.name + " — you picked " + (hardest.selected ? hardest.selected.properties.name : "nothing") + " (" + hardest.points + " points)."));
      } else if (isCounties) {
        b1.innerHTML = "<strong>Best placement:</strong> ";
        b1.appendChild(document.createTextNode(best.county.properties.name + " — " + Math.round(best.overlap * 100) + "% covered (" + best.points + " pts). "));
        b2.innerHTML = "<strong>Hardest county:</strong> ";
        b2.appendChild(document.createTextNode(hardest.county.properties.name + " — " + Math.round(hardest.overlap * 100) + "% covered (" + hardest.points + " pts)."));
      } else {
        b1.innerHTML = "<strong>Best guess:</strong> ";
        b1.appendChild(document.createTextNode(best.city.name + " — " + best.distance.toFixed(1) + " miles off (" + best.points + " pts). "));
        b2.innerHTML = "<strong>Hardest city:</strong> ";
        b2.appendChild(document.createTextNode(hardest.city.name + " — " + hardest.distance.toFixed(1) + " miles off (" + hardest.points + " pts)."));
      }
      hl.appendChild(b1); hl.appendChild(b2);
    } else if (best) {
      hl.textContent = isName
        ? (best.adjacent
          ? "Best (and only close) pick: " + best.county.properties.name + " — you picked a neighboring county (50 points)."
          : "Best (and only correct) pick: " + best.county.properties.name + " — you named it correctly.")
        : isCounties
        ? "Best (and only scored) placement: " + best.county.properties.name + " — " + Math.round(best.overlap * 100) + "% covered."
        : "Best (and only scored) guess: " + best.city.name + " — " + best.distance.toFixed(1) + " miles off.";
    } else if (isName) {
      hl.textContent = hardest
        ? "No counties named correctly. Hardest county: " + hardest.county.properties.name + " — you picked " + (hardest.selected ? hardest.selected.properties.name : "nothing") + " (0 points)."
        : "Every round was passed — no picks to rank. Try clicking a county next time!";
    } else {
      hl.textContent = isCounties
        ? "Every round was passed — no placements to rank. Try placing a piece next time!"
        : "Every round was passed — no guesses to rank. Try placing a pin next time!";
    }
    var tbody = document.getElementById("results-body");
    tbody.innerHTML = "";
    game.results.forEach(function (r, i) {
      var tr = document.createElement("tr");
      /* In City County Mode a row is "best" if it is the best city guess
         or the best county pick, "hardest" if it is the hardest city or
         county; a row that is both (only one scored round of its type)
         gets no highlight, like the single-type modes. */
      var mixedBest = isMixed && (r === bestMixedCity || r === bestMixedCounty);
      var mixedHardest = isMixed && (r === hardestMixedCity || r === hardestMixedCounty);
      if (isMixed) {
        if (mixedBest && !mixedHardest) tr.className = "best";
        if (mixedHardest && !mixedBest) tr.className = "hardest";
      } else {
        if (best && r === best && best !== hardest) tr.className = "best";
        if (hardest && r === hardest && best !== hardest) tr.className = "hardest";
      }
      var tdN = document.createElement("td"); tdN.textContent = String(i + 1);
      var tdCity = document.createElement("td");
      tdCity.textContent = isMixed
        ? (game.rounds[i].type === "county" ? r.county.properties.name : r.city.name)
        : isCountyMode ? r.county.properties.name : r.city.name;
      if (isMixed) {
        if (mixedBest && !mixedHardest) {
          var mbb = document.createElement("span"); mbb.className = "badge best"; mbb.textContent = "Best";
          tdCity.appendChild(mbb);
        }
        if (mixedHardest && !mixedBest) {
          var mhb = document.createElement("span"); mhb.className = "badge hardest"; mhb.textContent = "Hardest";
          tdCity.appendChild(mhb);
        }
      } else {
        if (best && r === best && best !== hardest) {
          var bb = document.createElement("span"); bb.className = "badge best"; bb.textContent = "Best";
          tdCity.appendChild(bb);
        }
        if (hardest && r === hardest && best !== hardest) {
          var hb = document.createElement("span"); hb.className = "badge hardest"; hb.textContent = "Hardest";
          tdCity.appendChild(hb);
        }
      }
      var tdD = document.createElement("td"); tdD.className = "num";
      tdD.textContent = isMixed
        ? (game.rounds[i].type === "county"
          ? (r.selected ? r.selected.properties.name : "—")
          : (r.distance === null ? "—" : r.distance.toFixed(1) + " mi"))
        : isCounties
        ? (r.overlap === null ? "—" : Math.round(r.overlap * 100) + "%")
        : isName
        ? (r.selected ? r.selected.properties.name : "—")
        : (r.distance === null ? "—" : r.distance.toFixed(1) + " mi");
      var tdP = document.createElement("td"); tdP.className = "num"; tdP.textContent = String(r.points);
      tr.appendChild(tdN); tr.appendChild(tdCity); tr.appendChild(tdD); tr.appendChild(tdP);
      tbody.appendChild(tr);
    });
    document.getElementById("summary-text").textContent =
      "I scored " + game.total + "/1000 on Where in the " + STATE_NAME + "?!" +
      (isMixed ? " (City County Mode)" : isCounties ? " (Counties)" : isName ? " (Name the county)" : "") + ", seed " + game.seed + "\nPlay the same game: " + gameLink();
  }

  function copyText(text, noteEl) {
    function done() { if (noteEl) { noteEl.hidden = false; setTimeout(function () { noteEl.hidden = true; }, 2000); } }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
    } else { fallbackCopy(text); done(); }
  }
  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
  }
  document.getElementById("btn-copy-link").addEventListener("click", function () {
    copyText(gameLink(), document.getElementById("copy-note"));
  });
  document.getElementById("btn-copy-summary").addEventListener("click", function () {
    copyText(document.getElementById("summary-text").textContent, document.getElementById("copy-note"));
  });
  document.getElementById("btn-replay").addEventListener("click", function () {
    startGame(game.seed);
  });
  document.getElementById("btn-again").addEventListener("click", function () {
    seedInput.value = randomSeed();
    showScreen("start");
    seedInput.focus();
  });
})();
</script>
</body>
</html>
"""

html = (HTML
        .replace("__CITIES__", CITIES_JSON)
        .replace("__OUTLINE__", OUTLINE_JSON)
        .replace("__LANDMARKS__", LANDMARKS_JSON)
        .replace("__COUNTIES__", COUNTIES_JSON)
        .replace("__PURE_JS__", PURE_JS))

with open(OUT, "w") as f:
    f.write(html)
print("wrote", OUT, len(html), "bytes")
