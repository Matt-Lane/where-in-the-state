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
assert len(cities) == 241, len(cities)
assert len(outline["features"]) == 1
assert len(landmarks["features"]) == 224, len(landmarks["features"])

CITIES_JSON = json.dumps(cities, separators=(",", ":"))
OUTLINE_JSON = json.dumps(outline, separators=(",", ":"))
LANDMARKS_JSON = json.dumps(landmarks, separators=(",", ":"))

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

/* ============ Seeded randomization ============
   SHA-256 of the seed string (SubtleCrypto), first 4 bytes as a signed
   32-bit int (little-endian, matching C# BitConverter.ToInt32), then
   mulberry32 driving a Fisher-Yates shuffle. Same seed -> same 10
   cities in the same order, in any browser. */
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
function selectCities(seedInt, pool, count) {
  var rng = mulberry32(seedInt);
  var arr = pool.slice();
  for (var i = arr.length - 1; i > 0; i--) {
    var j = Math.floor(rng() * (i + 1));
    var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
  }
  return arr.slice(0, count);
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
  .seed-row input { flex: 1 1 260px; }
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

  .score-line { font-size: 16px; font-weight: 600; margin: 0 0 10px; font-variant-numeric: tabular-nums; }
  /* Round bar: fills by total score (out of 1000), with a terracotta tick
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
    <h1 id="game-title">Where in the State</h1>
    <p>Ten Oregon cities, one blank map. Tap where you think each city is — the closer your pin,
      the more points. Full points within 5 miles, then &minus;1 point per mile beyond that.</p>
  </header>

  <!-- ================= START ================= -->
  <section id="screen-start" class="screen" aria-label="Start a game">
    <div class="card">
      <h2>State</h2>
      <div><span class="state-badge">Oregon</span></div>
      <p class="muted small">Oregon is the only state in v1. More states will be added as data packs — the game itself is built to work for any state.</p>
    </div>

    <div class="card">
      <h2>Seed — same seed, same game</h2>
      <label class="field-label" for="seed-input">Game seed</label>
      <div class="seed-row">
        <input type="text" id="seed-input" autocomplete="off" spellcheck="false" />
      </div>
      <div class="btn-row">
        <button type="button" id="btn-random-seed">Random seed</button>
        <button type="button" id="btn-daily-seed">Use today&rsquo;s daily seed</button>
      </div>
      <p class="muted small" style="margin-top:12px">Same seed = same 10 cities, in the same order, for anyone, any time.
        Share the seed (or the game link) to play the same game as a co-worker. Seeds are case-sensitive.</p>
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

    <div class="card">
      <h2>Game</h2>
      <p><strong>10 questions.</strong> One pin per city, 100 points per question, 1,000 points maximum.</p>
      <div class="btn-row">
        <button type="button" class="btn-primary btn-big" id="btn-start">Start game</button>
      </div>
      <p class="muted small" id="start-note">Starting writes the seed into the page&rsquo;s address, so the link can be shared. Refreshing mid-game restarts that game from question 1 with the same seed.</p>
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
      <p class="score-line">Score: <span id="running-total">0</span> / 1000 &nbsp;&middot;&nbsp; Seed: <span id="game-seed-label"></span></p>
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
      <div class="total-big"><span id="final-total">0</span> <small>/ 1000</small></div>
      <p class="muted" id="final-sub"></p>
      <p id="final-highlights"></p>
    </div>

    <div class="card">
      <h2>Round by round</h2>
      <table class="results">
        <thead><tr><th>#</th><th>City</th><th class="num">Distance</th><th class="num">Points</th></tr></thead>
        <tbody id="results-body"></tbody>
      </table>
    </div>

    <div class="card">
      <h2>Share this game</h2>
      <p class="muted small">Anyone opening this link with the same seed gets the same 10 cities in the same order.</p>
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
    Scoring: <code>100 if rounded miles &le; 5, else max(0, 100 &minus; (rounded miles &minus; 5))</code>.<br />
    Seeded shuffle: this web version hashes the seed with SHA-256 (WebCrypto) and uses the first 4 bytes as a
    signed 32-bit integer to drive a mulberry32 PRNG through a Fisher&ndash;Yates shuffle of the 241-city pool.
    The Blazor C# version (spec &sect;5) uses the same SHA-256 seed integer with <code>System.Random(seedInt)</code>
    instead of mulberry32, so the 10 cities picked for a given seed may differ between the JavaScript and C#
    versions — but the seed format, scoring, and projection are the same.<br />
    Map data: state outline &copy; U.S. Census Bureau (public domain); interstates, highways, rivers and lakes
    from Natural Earth (public domain). City coordinates for the 241 incorporated Oregon cities via OpenStreetMap / Nominatim.
  </footer>
</div>

<script type="application/json" id="data-cities">__CITIES__</script>
<script type="application/json" id="data-outline">__OUTLINE__</script>
<script type="application/json" id="data-landmarks">__LANDMARKS__</script>

<script>
(function () {
  "use strict";
__PURE_JS__

  /* ============ Data & map drawing ============ */
  var cities = JSON.parse(document.getElementById("data-cities").textContent);
  var outline = JSON.parse(document.getElementById("data-outline").textContent);
  var landmarks = JSON.parse(document.getElementById("data-landmarks").textContent);
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
       that way on the results screen. The start screen shows the product
       name, and the browser tab follows the same rule. */
    var title = (which === "game" || which === "results")
      ? "Where in the " + STATE_NAME + "?!"
      : "Where in the State";
    document.getElementById("game-title").textContent = title;
    document.title = (which === "game" || which === "results") ? title : "Where in the State — Oregon";
    window.scrollTo(0, 0);
  }

  /* ============ Start screen ============ */
  var seedInput = document.getElementById("seed-input");
  function paramsFromUrl() {
    try { return new URLSearchParams(window.location.search); } catch (e) { return new URLSearchParams(""); }
  }
  var urlParams = paramsFromUrl();
  var urlSeed = urlParams.get("seed");
  seedInput.value = (urlSeed && urlSeed.trim()) ? urlSeed : dailySeed();
  document.getElementById("btn-random-seed").addEventListener("click", function () {
    seedInput.value = randomSeed();
    seedInput.focus();
  });
  document.getElementById("btn-daily-seed").addEventListener("click", function () {
    seedInput.value = dailySeed();
    seedInput.focus();
  });

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
  function gameLink() { return LIVE_SITE_BASE + "oregon/" + encodeURIComponent(game.seed); }
  var game = null; /* { seed, cities, roundIndex, results, total } */
  var guess = null; /* { lat, lon, x, y } */
  var phase = "guess"; /* "guess" | "revealed" */
  var dragging = false;

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
    if (!game || phase !== "guess") return;
    ev.preventDefault();
    var loc = eventToSvg(ev);
    if (!loc) return;
    dragging = true;
    try { svg.setPointerCapture(ev.pointerId); } catch (e) {}
    placeGuessAt(loc.x, loc.y);
  });
  svg.addEventListener("pointermove", function (ev) {
    if (!dragging || !game || phase !== "guess") return;
    var loc = eventToSvg(ev);
    if (!loc) return;
    placeGuessAt(loc.x, loc.y);
  });
  function endDrag() { dragging = false; }
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);

  function currentCity() { return game.cities[game.roundIndex]; }
  function updateRoundHeader() {
    var city = currentCity();
    document.getElementById("round-heading").textContent =
      "Question " + (game.roundIndex + 1) + " of " + QUESTION_COUNT + " — Where is " + city.name + "?";
    document.getElementById("running-total").textContent = game.total;
    document.getElementById("game-seed-label").textContent = game.seed;
    /* The bar fills by total score (out of 1000); the tick marks the best
       total possible once the question on screen is scored. */
    var maxScore = (game.roundIndex + 1) * 100;
    document.getElementById("progress-fill").style.width = (game.total / 10) + "%";
    document.getElementById("progress-max").style.left = ((game.roundIndex + 1) * 10) + "%";
    document.getElementById("progress-max").setAttribute("title", "Maximum possible after question " + (game.roundIndex + 1) + ": " + maxScore);
    var track = document.getElementById("progress-track");
    track.setAttribute("aria-valuenow", String(game.total));
    track.setAttribute("aria-valuetext", game.total + " out of 1000; maximum " + maxScore + " after question " + (game.roundIndex + 1));
  }
  function startRound() {
    phase = "guess";
    guess = null;
    clearPins();
    btnConfirm.disabled = true;
    btnPass.disabled = false;
    pinConfirm.hidden = true;
    document.getElementById("reveal-controls").hidden = true;
    document.getElementById("guess-controls").hidden = false;
    document.getElementById("hint-text").textContent = "Tap the map to drop a pin. Tap again (or drag) to move it, then confirm.";
    updateRoundHeader();
  }

  function reveal(passed) {
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
    btnNext.textContent = game.roundIndex + 1 >= QUESTION_COUNT ? "See results" : "Next city";
    document.getElementById("guess-controls").hidden = true;
    document.getElementById("reveal-controls").hidden = false;
    /* Refresh the header (and the score bar) now that the round is scored. */
    updateRoundHeader();
  }

  btnConfirm.addEventListener("click", function () { if (guess && phase === "guess") reveal(false); });
  btnPass.addEventListener("click", function () { if (phase === "guess") reveal(true); });
  pinConfirm.addEventListener("click", function () { if (guess && phase === "guess") reveal(false); });
  btnNext.addEventListener("click", function () {
    game.roundIndex++;
    if (game.roundIndex >= QUESTION_COUNT) showResults();
    else startRound();
  });

  async function startGame(seed) {
    seed = (seed || "").trim();
    if (!seed) seed = randomSeed();
    var seedInt = await seedIntFromString(seed);
    var picked = selectCities(seedInt, cities, QUESTION_COUNT);
    game = { seed: seed, cities: picked, roundIndex: 0, results: [], total: 0 };
    try {
      history.replaceState(null, "", "?state=oregon&seed=" + encodeURIComponent(seed));
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
    var scored = game.results.filter(function (r) { return !r.passed; });
    var avg = scored.length
      ? (scored.reduce(function (s, r) { return s + r.distance; }, 0) / scored.length).toFixed(1)
      : "—";
    document.getElementById("final-sub").textContent =
      "Seed " + game.seed + " · " + QUESTION_COUNT + " questions · average distance " + avg + " miles (guessed rounds).";
    var best = null, hardest = null;
    scored.forEach(function (r) {
      if (!best || r.distance < best.distance) best = r;
      if (!hardest || r.distance > hardest.distance) hardest = r;
    });
    var hl = document.getElementById("final-highlights");
    if (best && hardest && best !== hardest) {
      hl.innerHTML = "";
      var b1 = document.createElement("span");
      b1.innerHTML = "<strong>Best guess:</strong> ";
      b1.appendChild(document.createTextNode(best.city.name + " — " + best.distance.toFixed(1) + " miles off (" + best.points + " pts). "));
      var b2 = document.createElement("span");
      b2.innerHTML = "<strong>Hardest city:</strong> ";
      b2.appendChild(document.createTextNode(hardest.city.name + " — " + hardest.distance.toFixed(1) + " miles off (" + hardest.points + " pts)."));
      hl.appendChild(b1); hl.appendChild(b2);
    } else if (best) {
      hl.textContent = "Best (and only scored) guess: " + best.city.name + " — " + best.distance.toFixed(1) + " miles off.";
    } else {
      hl.textContent = "Every round was passed — no guesses to rank. Try placing a pin next time!";
    }
    var tbody = document.getElementById("results-body");
    tbody.innerHTML = "";
    game.results.forEach(function (r, i) {
      var tr = document.createElement("tr");
      if (best && r === best && best !== hardest) tr.className = "best";
      if (hardest && r === hardest && best !== hardest) tr.className = "hardest";
      var tdN = document.createElement("td"); tdN.textContent = String(i + 1);
      var tdCity = document.createElement("td");
      tdCity.textContent = r.city.name;
      if (best && r === best && best !== hardest) {
        var bb = document.createElement("span"); bb.className = "badge best"; bb.textContent = "Best";
        tdCity.appendChild(bb);
      }
      if (hardest && r === hardest && best !== hardest) {
        var hb = document.createElement("span"); hb.className = "badge hardest"; hb.textContent = "Hardest";
        tdCity.appendChild(hb);
      }
      var tdD = document.createElement("td"); tdD.className = "num";
      tdD.textContent = r.distance === null ? "—" : r.distance.toFixed(1) + " mi";
      var tdP = document.createElement("td"); tdP.className = "num"; tdP.textContent = String(r.points);
      tr.appendChild(tdN); tr.appendChild(tdCity); tr.appendChild(tdD); tr.appendChild(tdP);
      tbody.appendChild(tr);
    });
    document.getElementById("summary-text").textContent =
      "I scored " + game.total + "/1000 on Where in the " + STATE_NAME + "?!, seed " + game.seed + "\nPlay the same game: " + gameLink();
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
        .replace("__PURE_JS__", PURE_JS))

with open(OUT, "w") as f:
    f.write(html)
print("wrote", OUT, len(html), "bytes")
