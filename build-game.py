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
usa_states = json.load(open(os.path.join(BASE, "data/usa-states.geojson")))
# The Risk Pool edition's member lists (from the GitHub wiki, canonical
# game names — see GAME-SPEC §4.6). The single source of truth is the
# pack file; this build reads it from there.
risk_pool = json.load(open(os.path.join(BASE, "blazor/wwwroot/data/states/oregon/risk-pool.json")))
assert len(cities) == 241, len(cities)
assert len(outline["features"]) == 1
assert len(landmarks["features"]) == 224, len(landmarks["features"])
assert len(counties["features"]) == 36, len(counties["features"])
assert len(usa_states["features"]) == 51, len(usa_states["features"])
assert len(risk_pool["cities"]) == 236, len(risk_pool["cities"])
assert len(risk_pool["counties"]) == 28, len(risk_pool["counties"])
assert all(c in {x["name"] for x in cities} for c in risk_pool["cities"])
assert all(c in {f["properties"]["name"] for f in counties["features"]} for c in risk_pool["counties"])

CITIES_JSON = json.dumps(cities, separators=(",", ":"))
OUTLINE_JSON = json.dumps(outline, separators=(",", ":"))
LANDMARKS_JSON = json.dumps(landmarks, separators=(",", ":"))
COUNTIES_JSON = json.dumps(counties, separators=(",", ":"))
USA_STATES_JSON = json.dumps(usa_states, separators=(",", ":"))
RISK_POOL_JSON = json.dumps(risk_pool, separators=(",", ":"))

# PostHog analytics (see GAME-SPEC §13): the project API key and host.
# The key is a public client key, designed to be embedded in frontend
# code. This is the single place the key and host are defined for the
# standalone version — the generated HTML gets them via the
# __POSTHOG_KEY__ / __POSTHOG_HOST__ placeholders in the snippet.
POSTHOG_KEY = "phc_m9r8eSEfJH6ZaEby76WZGTgafxtKYdEg6xFQbpsUNw3i"
POSTHOG_HOST = "https://us.i.posthog.com"

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

/* ============ Map viewport: pinch-to-zoom and pan ============
   The visible window onto the map, as a sub-rectangle of the full
   viewBox (0 0 W H). The SVG's viewBox attribute is bound to it, so the
   map re-renders zoomed/panned with no other drawing changes. All
   conversions between client (CSS pixel) coordinates and SVG viewBox
   coordinates go through here, so a tap always resolves against the
   CURRENT view — never the full map. Zoom keeps the viewBox aspect
   ratio and clamps to the map bounds, so the window never shows area
   outside the state. These are pure functions of their arguments (the
   vb object is passed in) so the tap math can be executed in a test. */
var VB_MIN_W = 250;          /* maximum zoom-in: 4x */
var TAP_MOVE_PX = 10;        /* movement under this many CSS px still counts as a tap */
function vbFull() { return { x: 0, y: 0, w: W, h: H }; }
function vbIsZoomed(vb) { return vb.w < W - 0.5; }
function vbClamp(vb) {
  vb.x = Math.min(Math.max(vb.x, 0), W - vb.w);
  vb.y = Math.min(Math.max(vb.y, 0), H - vb.h);
  return vb;
}
function vbClientToSvg(vb, rect, clientX, clientY) {
  return { x: vb.x + (clientX - rect.left) * vb.w / rect.width,
           y: vb.y + (clientY - rect.top) * vb.h / rect.height };
}
function vbZoomAt(vb, anchorSvg, anchorClient, rect, newW) {
  newW = Math.min(Math.max(newW, VB_MIN_W), W);
  var newH = newW * H / W;
  vb.w = newW; vb.h = newH;
  vb.x = anchorSvg.x - (anchorClient.x - rect.left) * newW / rect.width;
  vb.y = anchorSvg.y - (anchorClient.y - rect.top) * newH / rect.height;
  return vbClamp(vb);
}
function vbPan(vb, dxClient, dyClient, rect) {
  if (!vbIsZoomed(vb)) return vb;
  vb.x -= dxClient * vb.w / rect.width;
  vb.y -= dyClient * vb.h / rect.height;
  return vbClamp(vb);
}
function vbContains(vb, x, y) { return x >= vb.x && x <= vb.x + vb.w && y >= vb.y && y <= vb.y + vb.h; }
function vbToPercent(vb, x, y) { return { left: (x - vb.x) / vb.w * 100, top: (y - vb.y) / vb.h * 100 }; }

/* Smoothing: gestures write to a TARGET viewport (vbTarget), and the
   displayed viewport (vb) eases toward it once per animation frame.
   The displayed viewport is what the viewBox shows and what taps
   resolve against (eventToSvg uses getScreenCTM, which reads the DOM
   viewBox); the target is where the fingers are asking it to go. This
   makes the zoom track the fingers without their micro-jitter — the
   displayed viewport is a low-pass filter on the input — and batches
   viewBox updates to the display refresh instead of writing the
   attribute on every pointermove. When a gesture ends, vbSnapTo makes
   the displayed viewport exactly the target, so taps and the next
   gesture start from an exact state. */
var VB_EASE = 0.35;     /* fraction of the gap closed per animation frame */
var VB_EPSILON = 0.05;  /* below this gap (SVG units) the viewports count as settled */
function vbIsSettled(vb, vbT) {
  return Math.abs(vb.x - vbT.x) <= VB_EPSILON && Math.abs(vb.y - vbT.y) <= VB_EPSILON &&
         Math.abs(vb.w - vbT.w) <= VB_EPSILON && Math.abs(vb.h - vbT.h) <= VB_EPSILON;
}
/* Move the displayed viewport one animation frame toward its target.
   Returns true if the displayed viewport changed. Snaps exactly to the
   target when the gap is under the epsilon, so the easing always
   terminates and the final state is exact. */
function vbStepTowards(vb, vbT) {
  if (vbIsSettled(vb, vbT)) return false;
  vb.x += (vbT.x - vb.x) * VB_EASE;
  vb.y += (vbT.y - vb.y) * VB_EASE;
  vb.w += (vbT.w - vb.w) * VB_EASE;
  vb.h += (vbT.h - vb.h) * VB_EASE;
  if (vbIsSettled(vb, vbT)) {
    vb.x = vbT.x; vb.y = vbT.y; vb.w = vbT.w; vb.h = vbT.h;
  } else {
    /* Safety net: the lerp of two in-bounds viewports stays in bounds,
       but clamp anyway so the displayed viewport can never show
       outside the map. */
    vb.w = Math.min(Math.max(vb.w, VB_MIN_W), W);
    vb.h = vb.w * H / W;
    vbClamp(vb);
  }
  return true;
}
function vbSnapTo(vb, vbT) { vb.x = vbT.x; vb.y = vbT.y; vb.w = vbT.w; vb.h = vbT.h; return vb; }

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
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}
function randomSeed() {
  var chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  var out = "";
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
<!-- Favicon: the pin logo (green pin, white "?!"), inlined as a data-URI
     SVG so the standalone file stays self-contained. Same artwork as
     blazor/wwwroot/favicon.svg. -->
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2096%2096%22%3E%3Cpath%20fill%3D%22%23205c46%22%20stroke%3D%22%23ffffff%22%20stroke-width%3D%227%22%20d%3D%22M48%208%20C32.5%208%2020%2020.5%2020%2034%20C20%2055%2048%2086%2048%2086%20C48%2086%2076%2055%2076%2034%20C76%2020.5%2063.5%208%2048%208%20Z%22%2F%3E%3Ctext%20x%3D%2248%22%20y%3D%2246%22%20text-anchor%3D%22middle%22%20font-family%3D%22Georgia%2C%20%27Times%20New%20Roman%27%2C%20serif%22%20font-weight%3D%22700%22%20font-size%3D%2234%22%20fill%3D%22%23fff%22%3E%3F%21%3C%2Ftext%3E%3C%2Fsvg%3E" />
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
  .seed-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: end; }
  /* The Game # box is short (20 chars max) and sits below the Play button,
     out of the normal player's path — just wide enough for the daily Game #
     (~12 characters), with a calendar button to restore today's Game # and a
     dice button for a random one beside it. */
  .seed-row input { flex: 0 0 auto; width: 13ch; max-width: 13ch; }
  /* Icon-only buttons beside the Game # box (calendar for today's Game #,
     dice for a random one). No text label — the icon is the button, with an
     aria-label for screen readers. Same height as the input, so the row
     lines up with it. */
  .icon-btn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 48px; min-width: 48px; height: 48px; min-height: 48px; padding: 0; flex-shrink: 0;
  }
  .icon-btn svg { display: block; }
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
  /* ---------- Splash / welcome page ---------- */
  .splash-hero { text-align: center; padding: 16px 0 8px; }
  .splash-logo { width: 72px; height: 72px; }
  .splash-logo .pin-fill { fill: var(--accent); }
  .splash-logo .mark-fill { fill: #fff; }
  .splash-hero h1 { font-size: 40px; margin: 8px 0 8px; }
  .splash-tagline { font-size: 18px; color: var(--muted); max-width: 560px; margin: 0 auto 24px; }
  .splash-map-card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px 16px 12px; margin-bottom: 18px; }
  .splash-map { display: block; width: 100%; height: auto; }
  .usa-state { fill-rule: evenodd; stroke: #fff; stroke-width: 1.5; stroke-linejoin: round; cursor: pointer; transition: fill 0.15s ease; }
  .usa-state.usa-unavailable { fill: url(#usa-hatch); }
  .usa-state.usa-unavailable:hover { stroke: var(--faint); }
  /* Oregon's border: a darker green (#173f31) and a slightly thicker
     stroke, so the whole outline — the north edge along the Columbia
     included — reads clearly and consistently against the neighbouring
     hatched states. */
  .usa-state.usa-available { fill: #e3ede6; stroke: #173f31; stroke-width: 2.5; }
  /* Hover: a noticeably stronger, more vivid green — clearly greener
     than the resting soft fill, still lighter than the solid selected
     fill. */
  .usa-state.usa-available:hover { fill: #6fb98e; }
  .usa-state.usa-selected { fill: var(--accent); stroke: #173f31; stroke-width: 2.5; }
  .splash-hint { text-align: center; color: var(--muted); margin: 12px 0 8px; min-height: 1.5em; }
  .splash-actions { display: flex; justify-content: center; padding-bottom: 8px; }
  .splash-play { font-size: 17px; padding: 12px 32px; }
  .splash-note { text-align: center; color: var(--faint); font-size: 14px; margin: 16px 0 0; }
  @media (max-width: 700px) {
    .splash-hero h1 { font-size: 30px; }
    .splash-tagline { font-size: 17px; }
    .splash-play { width: 100%; }
  }
  .btn-primary:hover:not(:disabled) { background: #184636; }
  .btn-big { font-size: 17px; padding: 12px 26px; }

  .state-badge {
    display: inline-block; font-weight: 700; font-size: 18px;
    border: 1px solid var(--line); background: var(--panel-soft);
    border-radius: 8px; padding: 10px 16px; margin-bottom: 4px;
  }
  /* The edition badge: a pill directly beneath the header, at the top of
     the game page content, naming the edition being played ("Risk Pool
     Edition"). Pale green fill and dark green text, like the selected
     mode button. Only shown for the Risk Pool edition; the All edition
     shows no badge. */
  .edition-badge {
    display: inline-block; font-weight: 700; font-size: 14px; color: #173f31;
    background: #c8e6cf; border: 1px solid var(--accent); border-radius: 999px;
    padding: 5px 14px; margin: 0 0 12px;
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
  /* Game-mode selector: one big preview image of the selected mode, with
     three compact buttons underneath to change it. Matches the Blazor
     start screen: selected button gets a green border and a soft green
     fill. All four previews are stacked in one grid cell and only the
     selected mode's is visible, so the big image is always the same size
     and switching modes never moves the Play button below it. The
     Counties drag mode is hidden from the picker; its preview is still
     stacked here so a /oregon/counties/ link still shows the right image. */
  .mode-preview-big { display: grid; }
  .mode-preview-big > * { grid-area: 1 / 1; }
  .mode-preview-big > :not(.is-active) { visibility: hidden; }
  .mode-switch-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .mode-switch {
    flex: 1 1 0; min-height: 48px;
    display: flex; align-items: center; justify-content: center; text-align: center;
    background: var(--panel); border: 2px solid var(--line); border-radius: 14px;
    padding: 8px 6px; cursor: pointer; font: inherit; font-weight: 700; color: var(--ink);
  }
  .mode-switch:hover:not(:disabled) { border-color: var(--accent); box-shadow: 0 1px 2px rgba(30, 42, 36, 0.06), 0 6px 18px rgba(30, 42, 36, 0.07); }
  .mode-switch[aria-pressed="true"] { border: 3px solid #173f31; background: #c8e6cf; font-weight: 800; box-shadow: 0 1px 2px rgba(30, 42, 36, 0.06), 0 6px 18px rgba(30, 42, 36, 0.07); }
  .mode-switch:disabled { opacity: 0.45; cursor: not-allowed; }
  /* "Play today's game": the prominent first-screen action — full width. */
  .play-today { width: 100%; }
  /* Collapsible start-screen sections ("How to play", "Advanced options"):
     a full-width header button, minimized by default. */
  .section-toggle {
    display: flex; align-items: center; gap: 8px; width: 100%; text-align: left;
    font: inherit; font-weight: 700; font-size: 16px;
    background: var(--panel-soft); border: 1px solid var(--line); border-radius: 8px;
    padding: 10px 14px; cursor: pointer; color: var(--ink); margin-top: 16px;
  }
  .section-toggle:hover:not(:disabled) { background: var(--panel); }
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
  .preview-county-pick { fill: #3b82c4; fill-opacity: 0.45; stroke: #1d4ed8; stroke-width: 2; }
  .preview-split-line { stroke: #fff; stroke-width: 3; }
  .lede { margin: 0 0 20px; color: var(--muted); font-size: 15.5px; max-width: 760px; }
  .lede strong { color: var(--ink); }
  /* Mode instructions (lede + steps, behind "How to play") and the Game card's
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
  /* Two lines at the top of the map card: the buttons on the first line,
     and one unified message line below them. The message line holds the
     round's status — the guessing hint while placing, then the reveal
     distance/points or county message after confirming. It reserves two
     lines of height at all times (long county names wrap to the second
     line; anything longer is clamped), so switching messages never moves
     the buttons above it or the map below it. Landmark toggles live on the
     start screen only, so nothing below the map needs a scroll to reach. */
  .game-controls { padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid var(--line); }
  .game-controls .btn-row { margin-top: 0; flex-wrap: nowrap; }
  .game-controls .btn-row button { flex-shrink: 0; }
  .controls-hint { margin: 8px 0 0; min-height: 3.2rem; line-height: 1.6rem; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; color: var(--muted); font-size: 13.5px; }
  .reveal-line { margin: 8px 0 0; min-height: 3.2rem; line-height: 1.6rem; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; font-weight: 700; font-size: 16px; color: var(--accent); font-variant-numeric: tabular-nums; }
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
  /* Reset view: only shown once zoomed in, small and in the map's
     top-right corner, so the player can always get back to the full
     state without pushing the game off one screen. */
  #btn-reset-view {
    position: absolute; top: 8px; right: 8px; z-index: 3;
    min-height: 32px; padding: 4px 12px; font-size: 13.5px;
    background: #fffdf5; border: 1px solid var(--line); border-radius: 6px;
    box-shadow: 0 1px 4px rgb(0 0 0 / 0.15); cursor: pointer; color: var(--ink);
  }
  #btn-reset-view:hover { background: #fff; }
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
  /* The Copy button sits on the same row as the summary box. */
  .summary-row { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
  .summary-row .summary-box { flex: 1 1 auto; min-width: 0; width: auto; }
  .summary-row button { flex: 0 0 auto; }
  /* Always rendered: visibility toggles, so the "Copied!" note never
     moves anything on the screen. The min-height reserves one line. */
  .copied { color: var(--truth); font-weight: 600; font-size: 13.5px; min-height: 1.25em; margin: 0.25rem 0 0; }
  footer { margin-top: 22px; color: var(--faint); font-size: 12.5px; line-height: 1.6; max-width: 900px; }
  footer code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; }
  @media (max-width: 700px) {
    .wrap { padding: 20px 14px 32px; }
    h1 { font-size: 25px; }
    #round-heading { font-size: 19px; }
  }
</style>
<!-- PostHog analytics (see GAME-SPEC §13). The project API key below is
     a public client key, designed to be embedded in frontend code; the
     key and host are defined once in build-game.py (POSTHOG_KEY /
     POSTHOG_HOST) and substituted here at build time.
     capture_pageview and autocapture are off, so only the four explicit
     game events (game_started, round_completed, game_completed,
     game_abandoned) are ever sent. The snippet defines window.posthog
     as a queuing stub, so capture calls made before array.js loads are
     queued, not dropped — and if an ad blocker stops the library loading
     entirely, the calls just queue forever, harmlessly. -->
<script>
    !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],Object.defineProperty(u,"toString",{configurable:!0,enumerable:!0,writable:!0,value:function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e}}),Object.defineProperty(u.people,"toString",{configurable:!0,enumerable:!0,writable:!0,value:function(){return u.toString(1)+".people (stub)"}}),o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagResult isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);

    posthog.init('__POSTHOG_KEY__', {
        api_host: '__POSTHOG_HOST__',
        defaults: '2026-08-30',
        capture_pageview: false,
        autocapture: false
    })
</script>
</head>
<body>
<div class="wrap">
  <header>
    <h1 id="game-title"><svg class="wordmark-logo" viewBox="0 0 96 96" aria-hidden="true"><path class="pin-fill" d="M48 8 C32.5 8 20 20.5 20 34 C20 55 48 86 48 86 C48 86 76 55 76 34 C76 20.5 63.5 8 48 8 Z" /><text class="mark-fill" x="48" y="46" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-weight="700" font-size="34">?!</text></svg><span id="game-title-text">Where in the State</span></h1>
  </header>
  <!-- The edition badge: directly beneath the header, at the top of the
       game page content, so the player knows which edition they are
       playing before they start — on the start screen and during play.
       Only for the Risk Pool edition (the default); the All edition
       shows no badge. Hidden on the splash page (no game in progress),
       shown by updateEditionBadge when a game screen is shown. -->
  <p id="edition-badge" class="edition-badge" hidden>Risk Pool Edition</p>

  <!-- ================= SPLASH / WELCOME ================= -->
  <section id="screen-splash" class="screen" aria-label="Welcome">
    <div class="splash-hero">
      <svg class="splash-logo" viewBox="0 0 96 96" aria-hidden="true"><path class="pin-fill" d="M48 8 C32.5 8 20 20.5 20 34 C20 55 48 86 48 86 C48 86 76 55 76 34 C76 20.5 63.5 8 48 8 Z" /><text class="mark-fill" x="48" y="46" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-weight="700" font-size="34">?!</text></svg>
      <h1>Where in the State</h1>
      <p class="splash-tagline">How well do you know your state? Pin the city, name the county &mdash; 10 questions, one blank map.</p>
    </div>
    <div class="splash-map-card">
      <svg class="splash-map" id="usa-map" role="group" aria-label="Map of the United States. Oregon is ready to play; the other states are coming soon.">
        <defs>
          <pattern id="usa-hatch" width="8" height="8" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <rect width="8" height="8" fill="#efece0" />
            <line x1="0" y1="0" x2="0" y2="8" stroke="#c9c4b4" stroke-width="1.5" />
          </pattern>
        </defs>
      </svg>
      <p class="splash-hint" id="splash-hint" aria-live="polite">Oregon is ready to play &mdash; click it on the map.</p>
      <div class="splash-actions">
        <button type="button" class="btn-primary splash-play" id="btn-play-oregon" disabled>Play Oregon</button>
      </div>
    </div>
    <p class="splash-note">Oregon is the first state. More states are on the way &mdash; pick Oregon to start playing.</p>
  </section>

  <!-- ================= START ================= -->
  <section id="screen-start" class="screen" aria-label="Start a game" hidden>
    <div class="card">
      <h2>Game mode</h2>
      <div class="mode-preview-big" id="mode-preview-big" aria-hidden="true">
        <div class="mode-preview-set is-active" data-mode="city-county">
          <svg class="mode-preview" viewBox="0 0 1000 757.4" aria-hidden="true">
            <defs>
              <clipPath id="preview-split-county">
                <polygon points="0,0 0,757.4 1000,757.4" />
              </clipPath>
              <clipPath id="preview-split-city">
                <polygon points="0,0 1000,0 1000,757.4" />
              </clipPath>
            </defs>
            <path d="M892.2,350.7 L898.1,357.7 L901.9,357.6 L906.0,354.2 L912.0,362.6 L914.6,359.4 L921.2,360.4 L921.7,367.9 L927.2,368.8 L931.0,374.0 L926.2,384.0 L921.0,386.4 L921.5,392.4 L926.2,397.0 L925.1,402.6 L921.8,406.3 L922.8,412.4 L920.5,422.2 L917.1,423.3 L915.2,428.3 L915.2,731.4 L438.1,732.5 L278.2,729.9 L60.0,731.7 L53.0,723.9 L49.6,722.9 L42.8,712.4 L42.3,701.5 L39.6,693.8 L36.3,690.0 L36.4,680.6 L33.7,677.8 L34.7,669.0 L33.4,658.6 L38.7,637.7 L37.5,627.7 L35.6,622.0 L31.6,619.6 L28.8,610.2 L26.7,608.7 L24.1,609.8 L21.4,596.7 L17.9,593.2 L25.7,579.6 L30.8,565.9 L33.5,546.8 L37.4,535.4 L39.7,521.3 L37.3,515.4 L40.8,509.9 L44.6,507.9 L47.7,501.7 L57.4,473.8 L67.3,415.3 L70.6,383.3 L71.5,353.1 L75.2,331.8 L77.2,329.6 L75.8,329.3 L75.2,320.0 L77.2,299.9 L75.2,299.4 L77.5,297.6 L78.3,291.5 L76.8,287.5 L78.2,278.5 L76.4,268.5 L82.2,247.0 L84.7,227.5 L83.1,226.9 L83.3,224.4 L86.5,219.5 L88.1,211.0 L89.5,182.6 L88.4,179.4 L84.3,179.4 L88.4,176.4 L89.3,171.2 L89.9,163.8 L88.0,154.1 L90.3,150.7 L92.5,125.6 L92.0,114.8 L87.3,109.1 L88.9,105.7 L89.7,91.2 L89.1,84.9 L86.0,78.5 L88.8,74.8 L92.7,73.4 L93.6,62.7 L90.1,46.2 L82.3,31.7 L83.9,30.6 L85.4,30.7 L86.7,34.7 L91.2,35.9 L96.6,41.6 L102.5,43.6 L104.1,41.6 L101.4,38.3 L128.5,34.2 L130.1,30.5 L134.5,31.8 L139.0,28.6 L139.1,26.8 L144.6,24.8 L151.0,28.3 L153.3,31.7 L153.0,39.6 L160.0,45.4 L170.9,45.7 L184.4,38.4 L190.4,39.0 L215.6,55.8 L218.7,64.5 L226.4,76.1 L226.7,84.1 L229.8,91.5 L228.6,101.1 L232.6,109.5 L231.1,122.5 L232.3,126.4 L246.6,134.2 L258.0,136.4 L271.0,141.9 L278.0,139.8 L283.8,144.4 L288.2,145.2 L293.6,144.5 L301.4,139.5 L311.2,138.6 L325.3,132.1 L328.5,128.6 L334.2,126.8 L339.1,120.4 L345.7,118.2 L358.1,120.1 L378.8,114.9 L391.9,120.3 L402.1,118.5 L416.6,124.0 L418.9,133.1 L422.3,134.8 L426.6,134.2 L434.6,127.1 L448.9,126.5 L454.7,128.7 L459.5,124.0 L479.2,116.7 L485.7,111.7 L494.7,112.9 L503.9,120.2 L513.2,119.4 L536.2,115.0 L541.0,109.0 L565.4,98.7 L600.6,93.3 L608.8,83.0 L612.3,82.0 L622.3,85.2 L649.7,79.6 L657.0,81.6 L665.3,80.8 L677.1,74.8 L681.8,69.7 L928.4,70.4 L931.1,73.9 L935.0,85.0 L942.6,93.1 L944.2,98.5 L946.9,100.1 L952.7,98.4 L958.2,105.7 L966.8,106.3 L972.3,110.9 L973.6,120.7 L979.3,127.6 L982.2,135.4 L975.0,144.7 L971.5,152.5 L971.3,158.5 L967.4,161.8 L966.3,166.8 L957.2,181.9 L957.1,189.4 L953.6,195.4 L950.5,211.6 L945.2,217.6 L942.5,225.1 L936.5,231.4 L935.2,238.6 L938.3,246.2 L935.4,254.8 L930.7,260.2 L926.1,270.9 L913.8,276.8 L910.9,280.2 L911.0,283.6 L906.9,290.6 L903.5,303.9 L900.7,307.2 L900.6,311.8 L891.6,320.7 L892.8,329.9 L889.4,335.9 L895.8,344.9 L892.2,350.7 Z" class="preview-state" />
            <g clip-path="url(#preview-split-county)">
              <path d="M737.5,283.8 L740.7,282.5 L743.3,284.1 L746.5,280.7 L749.4,281.6 L749.7,280.3 L752.2,280.4 L755.6,276.9 L761.0,277.9 L765.4,276.3 L764.2,266.0 L761.4,262.2 L764.8,257.2 L772.2,257.3 L771.1,250.2 L772.7,245.5 L770.2,244.3 L770.2,241.6 L771.7,241.6 L773.8,233.9 L777.1,231.9 L780.1,232.5 L783.8,227.7 L787.6,227.7 L791.0,232.3 L794.9,234.4 L802.0,235.9 L808.7,231.9 L814.4,224.2 L815.7,226.1 L818.7,226.0 L821.0,230.8 L822.5,229.7 L823.9,230.8 L825.8,236.4 L851.2,236.3 L851.3,222.0 L944.1,222.1 L936.5,231.4 L935.4,239.2 L939.0,238.0 L936.1,242.0 L938.3,246.4 L935.4,254.8 L930.5,259.2 L926.1,270.8 L913.8,276.8 L910.9,280.2 L911.0,283.6 L906.9,290.6 L903.5,304.0 L900.7,307.2 L900.6,311.8 L896.7,314.0 L894.5,319.1 L891.6,320.7 L892.8,329.9 L889.4,335.9 L895.8,344.9 L892.2,350.7 L860.4,350.9 L860.4,336.5 L857.7,336.5 L857.7,334.1 L855.3,334.1 L855.3,331.8 L850.5,331.8 L850.6,329.4 L848.0,329.4 L848.0,327.0 L802.7,327.1 L802.7,329.5 L798.0,329.5 L798.0,331.8 L795.6,331.8 L795.5,336.0 L793.1,336.0 L793.2,339.0 L790.8,339.0 L790.8,341.4 L789.0,341.4 L788.4,346.2 L786.0,346.1 L786.0,348.5 L783.6,348.5 L783.6,351.0 L781.2,351.0 L781.1,355.8 L776.3,355.8 L776.3,358.2 L740.1,358.3 L739.8,354.7 L743.5,345.2 L747.6,342.0 L747.8,339.5 L750.8,339.2 L747.4,334.0 L749.5,329.0 L749.2,325.2 L754.7,324.6 L756.4,322.5 L755.1,312.7 L759.0,306.7 L760.8,307.5 L762.9,303.1 L759.0,299.5 L757.1,294.8 L754.2,293.6 L751.1,294.4 L748.7,292.2 L746.2,293.0 L739.3,290.5 L737.5,283.8 Z M107.0,343.5 L116.8,343.3 L116.7,340.9 L119.1,340.9 L118.5,328.8 L133.1,328.9 L132.5,281.2 L186.5,281.4 L190.3,288.5 L193.5,288.8 L195.4,291.6 L192.9,294.5 L183.9,295.6 L184.0,297.5 L180.7,300.8 L182.2,303.4 L174.3,305.5 L173.3,308.0 L175.4,310.0 L174.3,313.4 L175.9,313.2 L178.9,317.0 L177.9,320.3 L179.8,327.2 L177.1,329.1 L177.6,335.4 L175.1,337.3 L178.2,340.6 L176.3,341.5 L177.0,343.9 L175.0,345.6 L178.0,346.0 L178.5,349.1 L181.2,349.7 L181.2,352.4 L182.8,353.6 L133.6,354.8 L111.9,353.6 L111.9,348.2 L107.1,348.4 L107.0,343.5 Z M220.0,182.6 L222.5,182.6 L222.5,177.9 L227.2,177.8 L227.4,180.2 L234.7,180.2 L234.7,163.4 L246.0,163.5 L244.6,159.4 L246.9,158.7 L344.7,158.7 L349.9,168.5 L356.1,170.0 L359.3,173.3 L358.6,180.3 L361.4,185.9 L359.4,192.8 L361.2,193.6 L361.0,197.2 L353.4,201.0 L353.2,203.4 L357.6,209.8 L359.0,214.9 L363.0,215.3 L364.6,218.2 L363.9,224.1 L360.0,224.2 L356.3,227.6 L356.9,228.9 L349.6,228.9 L349.3,232.5 L346.4,233.2 L346.7,238.9 L348.8,243.3 L347.5,245.5 L351.3,244.7 L353.3,249.2 L357.2,250.6 L354.9,254.0 L275.5,254.0 L275.7,251.0 L271.3,251.2 L265.4,247.9 L263.1,248.6 L259.5,245.6 L255.7,238.0 L252.4,236.6 L252.4,231.9 L239.3,225.3 L234.0,217.3 L229.4,213.5 L233.8,205.0 L232.9,201.5 L234.5,199.4 L233.8,195.0 L235.3,192.2 L229.9,192.1 L229.8,189.7 L223.9,189.7 L222.1,192.1 L219.9,192.1 L220.0,182.6 Z M83.7,30.5 L86.5,32.1 L86.4,35.0 L90.7,35.4 L96.5,39.8 L96.8,41.7 L102.5,43.6 L104.5,41.3 L101.4,38.3 L111.0,36.8 L114.1,34.4 L118.8,38.4 L121.7,38.3 L124.0,36.9 L124.9,33.6 L130.5,34.0 L139.0,28.5 L139.1,26.8 L144.6,24.8 L147.7,25.3 L151.0,28.3 L153.3,31.7 L152.9,39.6 L160.9,45.4 L161.2,106.1 L118.5,107.2 L118.6,105.5 L88.9,105.5 L89.1,84.9 L86.0,78.5 L88.8,74.8 L92.7,73.4 L93.6,62.7 L90.1,46.2 L82.7,31.6 L83.7,30.5 Z M81.0,22.5 L82.4,21.5 L84.2,25.7 L81.0,22.5 Z M160.6,60.0 L160.9,45.4 L170.9,45.7 L184.4,38.4 L190.4,39.0 L215.7,55.8 L218.7,64.5 L226.4,76.1 L226.7,84.1 L229.8,91.5 L228.6,101.1 L231.7,105.9 L232.5,114.6 L229.9,114.5 L229.9,115.8 L212.7,115.7 L212.7,113.4 L205.4,113.2 L205.4,110.9 L200.5,110.8 L200.6,106.2 L161.2,106.1 L160.6,60.0 Z M30.2,567.4 L33.3,554.2 L33.1,547.1 L37.4,535.4 L39.7,521.3 L37.3,515.4 L39.4,510.9 L44.4,507.8 L47.7,501.7 L54.8,482.9 L59.2,464.9 L100.0,465.3 L100.0,480.6 L107.0,480.5 L106.9,494.6 L113.2,494.6 L113.6,496.1 L113.3,523.3 L120.4,523.3 L120.7,551.6 L113.6,552.2 L113.6,566.6 L106.5,566.6 L107.6,600.9 L103.1,600.9 L100.9,603.2 L94.1,603.3 L94.0,609.0 L92.7,609.0 L92.7,610.8 L90.3,610.8 L90.3,613.2 L88.0,613.2 L88.0,615.6 L85.7,615.6 L85.7,618.0 L74.5,618.0 L74.5,619.2 L71.0,619.2 L69.4,621.1 L68.7,609.0 L66.2,609.0 L65.6,596.1 L66.1,594.4 L68.4,594.4 L66.0,585.3 L63.7,585.4 L62.6,583.1 L59.7,581.9 L59.1,576.9 L56.7,576.9 L54.5,573.4 L28.1,573.5 L30.2,567.4 Z M429.4,357.2 L429.5,335.9 L443.7,336.0 L443.6,321.7 L462.9,321.7 L462.8,307.4 L515.3,307.2 L515.3,328.4 L558.7,327.9 L558.8,336.1 L573.3,336.1 L573.3,349.8 L602.3,349.7 L602.1,407.3 L588.0,407.3 L587.8,450.5 L530.6,450.4 L530.5,436.1 L516.3,436.0 L516.2,421.6 L472.3,421.8 L472.2,407.6 L443.9,407.0 L443.8,378.4 L430.0,377.7 L429.4,357.2 Z M18.0,592.3 L19.8,591.9 L28.1,573.5 L54.5,573.4 L56.7,576.9 L59.1,576.9 L59.7,581.9 L62.6,583.1 L63.7,585.4 L66.0,585.3 L65.9,587.5 L67.8,588.8 L68.4,594.4 L66.1,594.4 L65.6,600.7 L66.2,609.0 L68.7,609.0 L69.4,621.1 L71.0,619.2 L74.5,619.2 L74.5,618.0 L85.7,618.0 L85.7,615.6 L88.0,615.6 L88.0,613.2 L90.3,613.2 L90.3,610.8 L92.7,610.8 L92.7,609.0 L94.0,609.0 L94.1,603.3 L100.9,603.2 L103.1,600.9 L108.6,601.1 L111.0,599.2 L117.1,602.4 L119.0,601.5 L105.3,626.8 L106.7,630.1 L103.1,634.9 L100.1,646.5 L94.8,649.6 L91.7,648.5 L84.2,649.3 L84.2,662.0 L80.2,667.3 L82.0,672.0 L92.8,671.6 L94.7,674.1 L98.5,673.3 L100.7,678.0 L104.3,679.8 L103.4,681.9 L107.6,691.1 L110.0,692.1 L110.2,694.9 L108.0,695.5 L106.6,698.5 L107.5,703.3 L102.1,709.1 L104.4,710.8 L106.4,717.1 L103.2,724.0 L104.4,728.9 L106.9,731.6 L60.0,731.7 L53.0,723.9 L50.5,724.1 L43.4,714.8 L43.3,709.1 L41.6,705.2 L42.3,701.5 L39.6,693.8 L35.9,689.7 L36.2,680.6 L33.7,677.8 L34.7,669.0 L33.4,658.3 L38.8,636.3 L36.6,633.0 L37.5,627.7 L35.6,622.0 L31.6,619.6 L28.8,610.2 L26.7,608.7 L24.1,610.2 L22.8,600.8 L18.0,592.3 Z M323.0,464.0 L323.2,462.3 L327.4,462.2 L324.8,457.8 L327.2,449.7 L325.5,443.1 L327.9,439.6 L326.2,424.1 L331.8,415.6 L338.8,415.1 L340.0,406.9 L342.7,405.3 L341.7,404.5 L343.7,402.4 L344.4,398.5 L343.0,394.0 L346.8,391.8 L350.7,383.8 L349.0,376.0 L350.4,372.8 L348.8,366.2 L349.7,363.9 L348.3,359.3 L344.8,357.2 L344.0,353.7 L342.1,353.3 L341.9,335.6 L429.5,335.9 L430.0,377.7 L443.8,378.4 L443.9,407.0 L472.2,407.6 L472.3,421.8 L516.2,421.6 L516.3,436.0 L530.5,436.1 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z M59.7,462.1 L66.3,423.1 L94.1,422.7 L94.0,417.3 L99.2,416.3 L105.2,410.0 L120.5,409.8 L120.5,410.9 L125.8,411.0 L125.8,413.5 L130.6,413.6 L130.5,418.5 L135.3,418.6 L135.2,422.3 L141.3,422.3 L141.3,428.6 L148.3,428.5 L148.3,432.0 L162.8,432.1 L162.8,436.9 L187.9,437.0 L187.9,465.7 L191.5,465.7 L191.4,476.6 L235.0,475.9 L235.0,493.6 L307.5,493.2 L311.2,495.7 L312.4,495.0 L316.5,499.9 L316.2,502.0 L319.7,505.7 L319.2,507.0 L320.7,506.1 L322.3,510.2 L321.4,512.3 L323.3,514.9 L322.4,518.3 L326.3,522.7 L323.0,527.1 L318.4,529.9 L318.6,534.3 L312.3,551.6 L312.1,553.4 L314.2,554.8 L289.6,554.8 L289.6,566.6 L275.5,566.5 L275.5,568.7 L273.2,568.7 L273.2,571.1 L270.8,571.1 L270.8,573.5 L268.5,573.5 L268.5,575.9 L256.6,576.0 L256.6,578.4 L254.2,578.4 L254.2,580.7 L251.8,580.7 L251.8,583.2 L247.3,583.0 L247.4,585.7 L242.7,585.7 L242.7,588.1 L240.3,588.1 L240.3,590.5 L238.0,590.5 L238.0,592.8 L235.6,592.8 L235.6,595.2 L231.0,594.3 L228.7,602.7 L210.0,603.2 L207.7,605.5 L203.1,605.8 L203.1,607.0 L186.1,606.4 L186.1,609.4 L182.8,609.4 L176.9,615.2 L174.6,615.2 L174.6,611.6 L171.6,611.5 L171.6,610.3 L165.1,610.9 L160.6,610.3 L160.6,609.1 L160.0,611.5 L156.6,611.5 L156.5,613.9 L151.3,613.8 L150.0,615.7 L139.7,614.0 L135.0,609.0 L123.6,609.0 L123.6,607.3 L121.3,606.7 L121.3,609.1 L119.0,609.0 L119.0,601.5 L117.1,602.4 L111.0,599.2 L107.6,600.9 L106.5,566.6 L113.6,566.6 L113.6,552.2 L120.7,551.6 L120.4,523.3 L113.3,523.3 L113.6,496.1 L113.2,494.6 L106.9,494.6 L107.0,480.5 L100.0,480.6 L100.0,465.3 L59.2,464.9 L59.7,462.1 Z M483.5,113.1 L490.9,111.6 L494.7,112.9 L501.1,119.3 L513.2,119.4 L536.2,115.0 L541.0,109.0 L561.4,100.7 L560.5,192.5 L575.3,192.6 L575.1,207.1 L589.9,207.1 L589.8,221.6 L586.2,221.6 L586.2,223.9 L502.4,223.8 L500.0,219.4 L504.5,216.6 L506.2,218.4 L505.9,213.6 L507.9,211.4 L504.6,210.0 L505.5,208.0 L503.7,206.9 L505.0,205.7 L503.2,205.2 L504.0,203.1 L496.8,200.3 L498.9,198.3 L496.4,198.3 L495.1,193.7 L497.8,192.2 L496.2,191.6 L496.8,188.9 L495.2,188.6 L496.6,187.8 L496.0,185.7 L498.9,185.4 L496.9,183.6 L498.5,181.5 L496.9,180.6 L498.2,179.0 L496.6,177.9 L497.7,173.8 L500.3,172.5 L497.9,172.0 L499.6,169.8 L498.4,168.9 L503.8,165.5 L501.1,164.3 L503.7,163.0 L502.2,161.2 L503.9,159.1 L502.3,158.1 L507.2,154.8 L512.5,157.3 L510.5,152.7 L517.5,153.2 L518.4,151.0 L516.0,148.5 L518.7,146.8 L512.9,142.8 L512.4,136.6 L508.4,134.6 L508.9,131.5 L505.6,132.6 L503.4,129.7 L504.2,128.4 L502.8,128.6 L503.1,126.7 L498.1,123.9 L496.1,124.4 L493.5,120.3 L489.6,118.8 L487.7,115.7 L484.7,115.6 L483.5,113.1 Z M600.3,235.9 L743.5,235.9 L747.3,237.6 L747.4,241.3 L751.2,239.0 L752.9,239.7 L753.2,237.8 L756.5,236.4 L763.7,241.6 L770.2,242.0 L770.2,244.3 L772.7,245.5 L771.1,250.2 L772.2,257.3 L764.8,257.2 L761.4,262.2 L764.2,266.0 L765.4,276.3 L761.0,277.9 L755.6,276.9 L752.2,280.4 L749.7,280.3 L749.4,281.6 L746.5,280.7 L743.3,284.1 L740.7,282.5 L737.5,283.8 L739.3,290.5 L746.2,293.0 L748.7,292.2 L751.1,294.4 L754.2,293.6 L757.1,294.8 L759.0,299.5 L762.9,303.1 L760.8,307.5 L759.0,306.7 L755.1,312.7 L756.4,322.5 L754.7,324.6 L749.2,325.2 L749.5,329.0 L747.4,334.0 L750.8,339.2 L747.8,339.5 L747.6,342.0 L743.5,345.2 L739.8,354.7 L740.1,358.3 L771.7,358.0 L772.2,393.9 L702.1,392.6 L702.1,407.0 L602.1,407.3 L602.7,264.3 L600.4,264.3 L600.3,235.9 Z M568.0,606.7 L569.3,536.4 L573.6,536.4 L573.5,450.5 L587.8,450.5 L588.0,407.3 L702.1,407.0 L702.1,392.6 L772.2,393.9 L772.1,580.1 L773.5,580.1 L773.8,685.8 L776.1,685.8 L775.8,731.9 L637.5,732.4 L636.8,607.5 L568.0,607.9 L568.0,606.7 Z M332.8,144.5 L334.9,143.1 L333.0,138.2 L332.5,127.7 L339.1,120.4 L345.7,118.2 L358.1,120.1 L378.8,114.9 L389.8,119.7 L389.8,149.2 L384.9,149.1 L384.9,192.4 L359.4,192.4 L361.4,185.9 L358.6,180.3 L358.9,172.5 L347.9,166.4 L346.3,159.9 L339.9,154.1 L338.8,150.0 L334.4,148.9 L332.8,144.5 Z M176.7,730.6 L176.9,614.0 L179.2,614.0 L182.8,609.4 L186.1,609.4 L186.1,606.4 L203.1,607.0 L203.1,605.8 L207.7,605.5 L210.0,603.2 L228.7,602.7 L231.0,594.3 L235.6,595.2 L235.6,592.8 L238.0,592.8 L238.0,590.5 L240.3,590.5 L240.3,588.1 L242.7,588.1 L242.7,585.7 L247.4,585.7 L247.3,583.0 L251.8,583.2 L251.8,580.7 L254.2,580.7 L254.2,578.4 L256.6,578.4 L256.6,576.0 L268.5,575.9 L268.5,573.5 L270.8,573.5 L270.8,571.1 L273.2,571.1 L273.2,568.7 L275.5,568.7 L275.5,566.5 L289.6,566.6 L288.8,730.1 L176.7,730.6 Z M341.2,323.0 L341.5,319.3 L345.9,315.4 L345.1,311.6 L347.8,302.2 L345.7,298.7 L347.3,294.6 L347.0,287.5 L348.6,286.5 L346.5,279.9 L351.8,274.4 L350.2,272.2 L347.5,272.7 L345.6,271.2 L344.6,268.2 L345.6,266.3 L352.7,263.2 L517.1,264.6 L515.5,268.8 L514.2,267.5 L513.1,269.1 L515.4,274.6 L515.3,307.2 L462.8,307.4 L462.9,321.7 L443.6,321.7 L443.7,336.0 L341.9,335.6 L341.2,323.0 Z M80.2,667.3 L84.2,662.0 L84.2,649.3 L91.7,648.5 L94.8,649.6 L100.1,646.5 L103.1,634.9 L106.7,630.1 L105.3,626.8 L119.0,601.7 L119.0,609.0 L121.3,609.1 L121.3,606.7 L123.6,607.3 L123.6,609.0 L135.0,609.0 L135.0,610.3 L136.8,609.7 L137.3,612.7 L145.4,614.1 L145.4,615.3 L150.0,615.7 L153.6,613.2 L156.5,613.9 L156.6,611.5 L160.0,611.5 L160.0,609.1 L160.6,610.3 L174.6,611.6 L174.6,615.2 L176.9,615.2 L176.7,730.8 L106.4,732.2 L103.2,724.0 L106.4,717.1 L104.4,710.8 L102.1,709.1 L107.5,703.3 L106.6,698.5 L108.0,695.5 L110.2,694.9 L110.0,692.1 L107.6,691.1 L103.4,681.9 L104.3,679.8 L100.7,678.0 L98.5,673.3 L94.7,674.1 L92.8,671.6 L82.0,672.0 L80.2,667.3 Z M288.7,710.4 L289.6,554.8 L314.2,554.8 L312.1,553.4 L312.3,551.6 L318.6,534.3 L318.4,529.9 L323.0,527.1 L326.3,522.7 L322.5,518.7 L323.3,514.9 L321.4,512.3 L322.0,509.0 L316.6,502.9 L316.5,499.9 L312.4,495.0 L311.2,495.7 L305.0,491.9 L307.0,490.5 L307.7,485.7 L307.8,482.3 L305.5,479.8 L307.7,473.8 L323.0,464.2 L402.6,464.0 L402.7,507.0 L400.8,507.0 L400.7,607.9 L456.2,608.3 L456.6,732.5 L288.8,730.1 L288.7,710.4 Z M400.5,579.2 L400.8,507.0 L402.7,507.0 L402.6,464.0 L573.6,464.9 L573.6,536.4 L569.3,536.4 L568.0,607.9 L636.8,607.5 L637.5,732.4 L456.6,732.5 L456.2,608.3 L400.7,607.9 L400.5,579.2 Z M67.3,415.3 L71.6,354.7 L182.8,353.6 L183.0,359.0 L186.3,363.0 L184.6,367.4 L215.4,367.3 L215.7,357.7 L220.2,357.7 L220.2,353.0 L225.3,355.2 L227.1,353.5 L236.2,352.9 L245.0,355.7 L247.1,359.3 L252.6,360.1 L254.6,362.8 L259.5,361.7 L263.4,363.9 L275.1,364.0 L278.1,365.9 L284.3,362.3 L284.3,358.7 L347.1,357.8 L349.7,363.9 L348.8,366.2 L350.3,373.5 L349.0,376.0 L350.3,377.4 L350.3,385.5 L346.8,391.8 L343.0,394.0 L344.4,398.5 L341.7,404.5 L342.7,405.3 L340.0,406.9 L338.8,415.1 L331.8,415.6 L326.2,424.1 L327.9,439.6 L325.5,443.1 L327.2,449.7 L324.8,457.8 L327.4,462.2 L323.2,462.3 L321.9,465.2 L307.7,473.8 L305.5,479.8 L307.8,482.3 L307.7,485.7 L307.0,490.5 L305.0,491.9 L307.5,493.2 L235.0,493.6 L235.0,475.9 L191.4,476.6 L191.5,465.7 L187.9,465.7 L187.9,437.0 L162.8,436.9 L162.8,432.1 L148.3,432.0 L148.3,428.5 L141.3,428.6 L141.3,422.3 L135.2,422.3 L135.3,418.6 L130.5,418.5 L130.6,413.6 L125.8,413.5 L125.8,411.0 L120.5,410.9 L120.5,409.8 L105.8,409.7 L99.2,416.3 L94.0,417.3 L94.1,422.7 L91.6,421.8 L91.6,423.3 L66.3,423.1 L67.3,415.3 Z M71.5,353.1 L74.9,333.5 L78.3,291.6 L75.8,288.5 L78.3,278.9 L76.4,268.5 L81.4,251.5 L84.2,227.7 L118.0,227.7 L117.9,278.3 L120.4,278.3 L120.4,281.2 L132.5,281.2 L133.1,328.9 L118.5,328.8 L119.1,340.9 L116.7,340.9 L116.8,343.3 L107.0,343.5 L107.1,348.4 L111.9,348.2 L111.9,353.6 L77.7,355.0 L71.6,354.7 L71.5,353.1 Z M173.2,308.3 L174.3,305.5 L182.2,303.4 L180.7,300.8 L184.7,295.1 L191.7,294.8 L195.5,292.9 L193.7,289.0 L190.3,288.5 L186.9,282.8 L186.3,280.2 L188.5,277.9 L187.1,276.6 L190.8,274.9 L192.3,277.1 L196.8,276.8 L200.2,281.3 L201.9,280.5 L202.0,285.0 L204.2,286.9 L209.3,281.2 L212.1,282.1 L216.4,277.3 L222.1,274.4 L222.4,272.5 L225.0,272.9 L230.1,269.1 L236.9,269.3 L240.9,272.3 L249.7,270.0 L256.1,273.5 L261.1,274.1 L261.3,275.8 L263.4,276.5 L285.3,274.9 L289.6,276.4 L297.3,285.9 L306.2,280.4 L319.2,287.1 L325.4,285.8 L327.6,287.4 L347.1,287.4 L347.3,294.6 L345.7,298.7 L347.8,302.2 L345.1,311.6 L345.9,315.4 L341.5,319.3 L341.2,323.3 L342.1,353.3 L344.1,353.8 L344.8,357.2 L347.1,357.8 L284.3,358.7 L284.3,362.3 L278.1,365.9 L275.1,364.0 L263.4,363.9 L259.5,361.7 L254.6,362.8 L252.6,360.1 L247.1,359.3 L245.0,355.7 L236.2,352.9 L227.1,353.5 L225.3,355.2 L220.2,353.0 L220.2,357.7 L215.7,357.7 L215.4,367.3 L184.6,367.4 L186.3,363.0 L183.0,359.0 L183.4,355.0 L181.2,352.4 L181.2,349.7 L178.5,349.1 L178.0,346.0 L175.0,345.6 L177.0,343.9 L176.3,341.5 L178.2,340.6 L175.1,337.3 L177.6,335.4 L177.1,329.1 L179.8,327.2 L177.9,320.3 L178.9,317.0 L175.9,313.2 L174.3,313.4 L175.4,310.0 L173.2,308.3 Z M771.7,358.2 L776.3,358.2 L776.3,355.8 L781.1,355.8 L781.2,351.0 L783.6,351.0 L783.6,348.5 L786.0,348.5 L786.0,346.1 L788.4,346.2 L789.0,341.4 L790.8,341.4 L790.8,339.0 L793.2,339.0 L793.1,336.0 L795.5,336.0 L795.6,331.8 L798.0,331.8 L798.0,329.5 L802.7,329.5 L802.7,327.1 L848.0,327.0 L848.0,329.4 L850.6,329.4 L850.5,331.8 L855.3,331.8 L855.3,334.1 L857.7,334.1 L857.7,336.5 L860.4,336.5 L860.4,350.9 L892.2,350.7 L894.7,355.2 L899.7,357.9 L905.5,354.1 L912.0,362.6 L914.6,359.4 L921.2,360.4 L921.7,367.9 L927.2,368.9 L930.8,372.2 L926.2,384.0 L921.0,386.4 L921.5,392.4 L925.8,395.7 L926.0,402.7 L921.2,404.7 L923.2,406.1 L921.6,407.4 L923.1,408.0 L922.0,410.8 L923.3,413.2 L920.5,415.0 L920.4,422.4 L916.0,423.9 L917.1,426.2 L914.4,428.7 L915.8,430.4 L915.2,731.4 L775.8,731.9 L776.1,685.8 L773.8,685.8 L773.5,580.1 L772.1,580.1 L771.7,358.2 Z M182.7,258.7 L186.5,258.0 L189.3,250.1 L191.5,248.3 L191.0,246.6 L195.6,247.1 L199.3,243.7 L199.6,237.3 L196.6,236.8 L195.2,232.7 L196.1,222.2 L204.7,215.6 L200.4,210.8 L200.9,208.4 L204.1,207.9 L201.8,202.0 L199.0,202.1 L198.2,200.2 L199.9,198.3 L204.3,198.0 L204.1,192.2 L208.1,187.9 L210.5,190.8 L220.0,193.2 L223.9,189.7 L229.8,189.7 L229.9,192.1 L235.3,192.2 L233.8,195.0 L234.5,199.4 L232.9,201.5 L233.8,205.0 L229.4,213.5 L234.0,217.3 L239.3,225.3 L252.4,231.9 L252.4,236.6 L255.7,238.0 L259.5,245.6 L263.1,248.6 L265.4,247.9 L271.3,251.2 L275.7,251.0 L275.5,254.0 L355.0,254.5 L352.7,258.0 L354.0,260.3 L352.6,263.4 L345.6,266.3 L344.6,268.2 L345.6,271.2 L347.5,272.7 L350.2,272.2 L351.8,274.4 L346.5,279.9 L347.7,280.4 L346.7,283.2 L348.6,286.5 L347.7,287.4 L327.6,287.4 L325.4,285.8 L319.2,287.1 L306.2,280.4 L297.3,285.9 L289.6,276.4 L285.3,274.9 L263.4,276.5 L261.3,275.8 L261.1,274.1 L256.1,273.5 L249.7,270.0 L240.9,272.3 L236.9,269.3 L230.1,269.1 L225.0,272.9 L222.4,272.5 L222.1,274.4 L216.4,277.3 L212.3,281.9 L209.3,281.2 L207.3,285.0 L203.4,286.9 L202.0,285.0 L202.4,281.2 L199.5,280.8 L199.5,278.8 L197.1,278.5 L196.8,276.8 L192.3,277.1 L190.8,274.9 L186.6,276.2 L188.9,270.0 L192.6,268.3 L193.3,266.3 L189.2,263.9 L183.4,263.0 L182.7,258.7 Z M560.6,177.1 L561.4,100.7 L584.8,94.9 L600.6,93.3 L606.1,85.3 L612.3,82.0 L622.3,85.2 L628.9,83.2 L628.6,135.3 L650.7,135.5 L650.8,149.7 L663.0,149.7 L662.9,221.4 L660.9,221.4 L660.9,235.7 L586.1,236.0 L586.2,221.6 L589.8,221.6 L589.9,207.1 L575.1,207.1 L575.3,192.6 L560.5,192.5 L560.6,177.1 Z M212.7,124.1 L212.7,115.7 L229.9,115.8 L229.9,114.5 L232.5,114.5 L231.1,122.5 L232.3,126.4 L242.9,132.9 L258.0,136.4 L271.0,141.9 L278.0,139.8 L281.3,140.9 L283.8,144.4 L288.2,145.2 L293.6,144.5 L301.4,139.5 L311.2,138.6 L332.5,127.7 L333.0,138.2 L334.9,143.1 L332.5,144.6 L334.4,148.9 L338.8,150.0 L339.9,154.1 L344.7,158.7 L246.9,158.7 L244.6,159.4 L246.0,163.5 L234.7,163.4 L234.7,149.1 L232.3,149.1 L232.3,146.8 L229.9,146.7 L229.9,144.4 L227.4,142.0 L224.9,142.0 L224.9,139.6 L222.4,139.6 L222.5,137.2 L220.0,137.2 L220.0,134.8 L217.6,134.8 L217.6,132.4 L215.1,132.4 L215.1,130.0 L212.7,130.0 L212.7,124.1 Z M117.9,231.2 L118.0,222.5 L196.1,222.7 L195.2,232.7 L196.6,236.8 L199.5,237.0 L199.0,244.2 L195.7,247.0 L191.0,246.6 L191.5,248.3 L189.3,250.1 L186.5,258.0 L182.7,258.7 L183.4,263.0 L189.2,263.9 L193.3,266.3 L186.9,273.1 L186.6,276.2 L188.5,277.9 L186.5,281.4 L120.4,281.2 L120.4,278.3 L117.9,278.3 L117.9,231.2 Z M438.6,187.8 L440.4,184.3 L443.1,184.2 L444.3,181.8 L447.1,184.2 L448.7,181.3 L447.8,179.3 L450.2,180.3 L449.6,177.7 L454.0,175.3 L456.4,170.1 L458.2,170.4 L458.6,164.4 L460.2,163.7 L458.2,161.5 L459.1,158.9 L461.8,157.5 L461.4,152.1 L463.0,150.0 L456.2,147.8 L453.2,142.7 L454.7,137.6 L452.8,135.0 L453.7,133.0 L452.3,129.0 L454.7,128.7 L459.5,124.0 L479.2,116.7 L483.5,113.1 L484.7,115.6 L487.7,115.7 L489.6,118.8 L493.5,120.3 L496.1,124.4 L498.1,123.9 L503.1,126.7 L502.8,128.6 L504.2,128.4 L503.4,129.7 L505.6,132.6 L508.9,131.5 L508.4,134.6 L512.4,136.6 L512.9,142.8 L518.7,146.8 L516.0,148.5 L518.4,151.0 L517.5,153.2 L510.5,152.7 L512.5,157.3 L507.2,154.8 L502.3,158.1 L503.9,159.1 L502.2,161.2 L503.7,163.0 L501.1,164.3 L503.8,165.5 L498.4,168.9 L499.6,169.8 L497.9,172.0 L500.3,172.5 L497.7,173.8 L496.6,177.9 L498.2,179.0 L496.9,180.6 L498.5,181.5 L496.9,183.6 L498.9,185.4 L497.7,186.3 L496.8,184.7 L496.6,187.8 L495.2,188.6 L496.8,188.9 L496.2,191.6 L497.8,192.2 L495.1,193.7 L496.4,198.3 L498.9,198.3 L496.8,200.3 L504.0,203.1 L503.2,205.2 L505.0,205.7 L503.7,206.9 L505.5,208.0 L504.6,210.0 L507.9,211.4 L505.9,213.6 L506.2,218.4 L504.5,216.6 L501.0,218.1 L500.0,219.4 L501.3,221.3 L474.4,221.2 L475.2,213.5 L470.7,211.2 L469.5,208.2 L465.2,207.4 L457.8,202.2 L444.1,202.4 L440.0,199.9 L440.2,188.0 L438.6,187.8 Z M83.3,224.4 L86.5,219.5 L88.7,206.5 L89.5,182.6 L88.4,179.4 L84.3,179.4 L88.4,176.4 L89.3,171.2 L89.7,161.8 L87.8,154.5 L90.3,150.7 L92.7,126.5 L92.0,114.8 L88.8,108.7 L87.4,108.9 L87.7,107.2 L88.9,105.5 L118.6,105.5 L118.5,107.2 L161.2,106.1 L161.3,117.8 L146.5,117.8 L146.5,122.7 L149.0,122.7 L149.0,125.1 L151.4,125.1 L151.4,127.4 L153.9,127.5 L153.9,129.8 L159.0,129.9 L158.9,132.2 L163.7,132.2 L163.7,134.6 L168.6,134.6 L168.6,137.0 L166.1,137.0 L166.2,139.4 L161.3,139.3 L161.3,144.1 L156.4,144.1 L156.4,146.5 L154.0,146.5 L154.0,148.8 L151.5,148.9 L151.7,153.8 L149.3,153.8 L149.0,161.1 L146.5,161.1 L146.4,163.4 L148.9,163.4 L149.1,199.3 L110.9,199.3 L110.9,222.4 L118.0,222.4 L118.0,227.7 L84.2,227.7 L83.3,224.4 Z M628.6,98.0 L628.9,83.2 L649.7,79.6 L657.0,81.6 L665.3,80.8 L677.1,74.8 L681.8,69.7 L802.0,69.5 L802.6,99.9 L794.0,99.9 L794.0,107.1 L791.4,107.1 L791.4,121.2 L785.4,121.2 L785.5,157.2 L775.8,157.3 L775.8,164.4 L755.7,164.1 L753.6,161.9 L751.2,161.9 L751.2,164.1 L748.3,164.1 L748.4,176.3 L726.4,176.4 L726.4,178.9 L716.3,177.9 L716.4,192.5 L721.2,192.5 L721.3,202.5 L734.3,202.5 L734.1,221.7 L737.6,221.7 L737.6,235.8 L660.9,235.7 L660.9,221.4 L662.9,221.4 L663.0,149.7 L650.8,149.7 L650.7,135.5 L628.6,135.3 L628.6,98.0 Z M716.3,177.9 L726.4,178.9 L726.4,176.4 L748.4,176.3 L748.3,164.1 L751.2,164.1 L751.2,161.9 L753.6,161.9 L755.7,164.1 L775.8,164.4 L775.8,157.3 L785.5,157.2 L785.4,121.2 L791.4,121.2 L791.4,107.1 L794.0,107.1 L794.0,99.9 L802.6,99.9 L802.5,92.7 L829.4,92.6 L829.4,107.1 L824.5,107.1 L824.6,121.0 L827.1,121.0 L827.1,125.9 L829.6,125.8 L829.6,133.1 L831.8,133.0 L831.8,149.9 L836.9,149.9 L837.0,164.2 L839.3,164.2 L839.4,174.6 L841.8,174.7 L841.8,179.4 L849.0,179.2 L849.1,183.8 L851.4,183.8 L851.5,186.1 L853.8,186.1 L853.8,190.9 L856.2,190.8 L856.4,200.4 L861.6,200.4 L861.6,207.5 L886.7,207.5 L886.7,221.8 L851.3,222.0 L851.2,236.3 L825.8,236.4 L823.9,230.8 L822.5,229.7 L821.0,230.8 L818.7,226.0 L815.7,226.1 L814.4,224.2 L810.5,230.1 L803.0,235.8 L794.9,234.4 L786.2,227.3 L783.8,227.7 L780.1,232.5 L777.1,231.9 L773.8,233.9 L771.7,241.6 L763.7,241.6 L756.5,236.4 L753.2,237.8 L752.9,239.7 L751.2,239.0 L747.4,241.3 L746.2,236.7 L737.6,235.8 L737.6,221.7 L734.1,221.7 L734.3,202.5 L721.3,202.5 L721.2,192.5 L716.4,192.1 L716.3,177.9 Z M802.0,69.5 L928.4,70.4 L933.1,77.2 L935.0,85.0 L942.6,93.1 L944.2,98.5 L946.9,100.1 L952.7,98.4 L958.2,105.7 L966.8,106.3 L972.3,110.8 L973.6,120.7 L979.3,127.6 L982.2,135.4 L979.9,139.6 L974.5,143.9 L971.0,151.8 L971.3,158.5 L967.4,161.8 L966.3,166.8 L957.2,181.9 L957.1,189.4 L953.7,195.3 L950.5,211.6 L945.2,217.6 L944.1,222.1 L886.7,221.8 L886.7,207.5 L861.6,207.5 L861.6,200.4 L856.4,200.4 L856.2,190.8 L853.8,190.9 L853.8,186.1 L851.5,186.1 L851.4,183.8 L849.1,183.8 L849.0,179.2 L841.8,179.4 L841.8,174.7 L839.4,174.6 L839.3,164.2 L837.0,164.2 L836.9,149.9 L831.8,149.9 L831.8,133.0 L829.6,133.1 L829.6,125.8 L827.1,125.9 L827.1,121.0 L824.6,121.0 L824.5,107.1 L829.4,107.1 L829.4,92.6 L802.0,92.7 L802.0,69.5 Z M346.4,233.2 L349.3,232.5 L349.6,228.9 L356.9,228.9 L356.3,227.6 L360.0,224.2 L363.9,224.1 L364.6,218.2 L362.9,215.2 L359.5,215.7 L353.2,203.4 L353.4,201.0 L361.0,197.2 L361.2,193.6 L359.4,192.4 L384.9,192.4 L384.9,149.1 L389.8,149.2 L389.8,119.7 L394.5,120.5 L402.1,118.5 L416.6,124.0 L420.4,134.8 L426.6,134.2 L432.2,127.9 L434.6,127.1 L444.2,127.8 L448.9,126.5 L452.3,129.0 L453.6,132.3 L452.8,135.0 L454.7,137.6 L453.1,142.3 L454.4,145.1 L456.2,147.8 L463.0,150.0 L461.4,152.1 L461.8,157.5 L459.1,158.9 L458.2,161.5 L460.2,163.7 L458.6,164.4 L458.1,170.7 L456.4,170.1 L454.0,175.3 L449.6,177.7 L450.2,180.3 L447.8,179.3 L448.7,181.3 L447.1,184.2 L444.3,181.8 L443.1,184.2 L440.4,184.3 L438.6,187.8 L440.2,188.4 L439.4,198.9 L444.1,202.4 L457.8,202.2 L465.2,207.4 L469.5,208.2 L470.7,211.2 L475.2,213.5 L474.4,221.2 L501.3,221.3 L503.9,225.8 L503.3,234.6 L504.5,240.5 L503.1,243.2 L505.0,245.8 L504.9,250.3 L507.6,250.2 L509.4,252.6 L506.6,255.9 L512.2,259.5 L513.6,263.2 L517.1,264.6 L356.0,264.0 L352.7,263.2 L354.0,260.3 L352.7,258.0 L357.2,250.6 L353.3,249.2 L351.3,244.7 L347.6,245.7 L348.8,243.3 L346.7,238.9 L346.4,233.2 Z M146.5,161.1 L149.0,161.1 L149.3,153.8 L151.7,153.8 L151.5,148.9 L154.0,148.8 L154.0,146.5 L156.4,146.5 L156.4,144.1 L161.3,144.1 L161.3,139.3 L166.2,139.4 L166.1,137.0 L168.6,137.0 L168.6,134.6 L163.7,134.6 L163.7,132.2 L158.9,132.2 L159.0,129.9 L153.9,129.8 L153.9,127.5 L151.4,127.4 L151.4,125.1 L149.0,125.1 L149.0,122.7 L146.5,122.7 L146.5,117.8 L161.3,117.8 L161.2,106.1 L200.6,106.2 L200.5,110.8 L205.4,110.9 L205.4,113.2 L212.7,113.4 L212.7,130.0 L215.1,130.0 L215.1,132.4 L217.6,132.4 L217.6,134.8 L220.0,134.8 L220.0,137.2 L222.5,137.2 L222.4,139.6 L224.9,139.6 L224.9,142.0 L227.4,142.0 L229.9,144.4 L229.9,146.7 L232.3,146.8 L232.3,149.1 L234.7,149.1 L234.7,180.2 L227.4,180.2 L227.2,177.8 L222.5,177.9 L222.5,182.6 L215.1,182.6 L215.1,177.8 L207.8,177.8 L207.8,175.4 L205.3,175.4 L205.3,173.0 L202.8,172.8 L202.9,170.4 L200.4,170.4 L200.4,168.1 L190.6,168.2 L190.6,165.8 L188.2,165.8 L188.1,163.4 L146.4,163.4 L146.5,161.1 Z M502.4,223.8 L586.2,223.9 L586.1,236.0 L600.3,235.9 L600.4,264.3 L602.7,264.3 L602.3,349.7 L573.3,349.8 L573.3,336.1 L558.8,336.1 L558.7,327.9 L515.3,328.4 L515.4,274.6 L513.1,269.1 L514.2,267.5 L515.5,268.8 L517.1,264.6 L513.5,263.1 L512.0,259.4 L507.1,257.3 L506.7,254.7 L509.4,252.6 L507.6,250.2 L504.9,250.3 L505.0,245.8 L503.1,243.2 L504.5,238.1 L503.3,234.6 L503.9,225.8 L502.4,223.8 Z M110.8,207.5 L110.9,199.3 L149.1,199.3 L148.9,163.4 L188.1,163.4 L188.2,165.8 L190.6,165.8 L190.6,168.2 L200.4,168.1 L200.4,170.4 L202.9,170.4 L202.8,172.8 L205.3,173.0 L205.3,175.4 L207.8,175.4 L207.8,177.8 L215.1,177.8 L215.1,182.6 L220.0,182.6 L219.9,192.1 L222.1,192.1 L216.2,192.6 L214.4,190.9 L210.2,190.7 L208.1,187.9 L204.7,191.3 L204.3,198.0 L199.9,198.3 L198.2,200.2 L199.0,202.1 L201.8,202.0 L204.1,207.6 L200.9,208.4 L200.3,210.1 L204.6,215.7 L196.1,222.7 L110.9,222.4 L110.8,207.5 Z" class="preview-grid" />
              <path d="M59.7,462.1 L66.3,423.1 L94.1,422.7 L94.0,417.3 L99.2,416.3 L105.2,410.0 L120.5,409.8 L120.5,410.9 L125.8,411.0 L125.8,413.5 L130.6,413.6 L130.5,418.5 L135.3,418.6 L135.2,422.3 L141.3,422.3 L141.3,428.6 L148.3,428.5 L148.3,432.0 L162.8,432.1 L162.8,436.9 L187.9,437.0 L187.9,465.7 L191.5,465.7 L191.4,476.6 L235.0,475.9 L235.0,493.6 L307.5,493.2 L311.2,495.7 L312.4,495.0 L316.5,499.9 L316.2,502.0 L319.7,505.7 L319.2,507.0 L320.7,506.1 L322.3,510.2 L321.4,512.3 L323.3,514.9 L322.4,518.3 L326.3,522.7 L323.0,527.1 L318.4,529.9 L318.6,534.3 L312.3,551.6 L312.1,553.4 L314.2,554.8 L289.6,554.8 L289.6,566.6 L275.5,566.5 L275.5,568.7 L273.2,568.7 L273.2,571.1 L270.8,571.1 L270.8,573.5 L268.5,573.5 L268.5,575.9 L256.6,576.0 L256.6,578.4 L254.2,578.4 L254.2,580.7 L251.8,580.7 L251.8,583.2 L247.3,583.0 L247.4,585.7 L242.7,585.7 L242.7,588.1 L240.3,588.1 L240.3,590.5 L238.0,590.5 L238.0,592.8 L235.6,592.8 L235.6,595.2 L231.0,594.3 L228.7,602.7 L210.0,603.2 L207.7,605.5 L203.1,605.8 L203.1,607.0 L186.1,606.4 L186.1,609.4 L182.8,609.4 L176.9,615.2 L174.6,615.2 L174.6,611.6 L171.6,611.5 L171.6,610.3 L165.1,610.9 L160.6,610.3 L160.6,609.1 L160.0,611.5 L156.6,611.5 L156.5,613.9 L151.3,613.8 L150.0,615.7 L139.7,614.0 L135.0,609.0 L123.6,609.0 L123.6,607.3 L121.3,606.7 L121.3,609.1 L119.0,609.0 L119.0,601.5 L117.1,602.4 L111.0,599.2 L107.6,600.9 L106.5,566.6 L113.6,566.6 L113.6,552.2 L120.7,551.6 L120.4,523.3 L113.3,523.3 L113.6,496.1 L113.2,494.6 L106.9,494.6 L107.0,480.5 L100.0,480.6 L100.0,465.3 L59.2,464.9 L59.7,462.1 Z" class="preview-county-pick" />
            </g>
            <g clip-path="url(#preview-split-city)">
              <line x1="608.9" y1="259.9" x2="788.3" y2="181.5" class="preview-line" />
              <circle cx="608.9" cy="259.9" r="16" class="preview-guess" />
              <circle cx="608.9" cy="259.9" r="6" class="preview-guess-dot" />
              <circle cx="788.3" cy="181.5" r="14" class="preview-target" />
              <circle cx="788.3" cy="181.5" r="5" class="preview-target-dot" />
            </g>
            <line x1="0" y1="0" x2="1000" y2="757.4" class="preview-split-line" />
          </svg>
        </div>
        <div class="mode-preview-set" data-mode="cities">
          <svg class="mode-preview" viewBox="0 0 1000 757.4" aria-hidden="true">
            <path d="M892.2,350.7 L898.1,357.7 L901.9,357.6 L906.0,354.2 L912.0,362.6 L914.6,359.4 L921.2,360.4 L921.7,367.9 L927.2,368.8 L931.0,374.0 L926.2,384.0 L921.0,386.4 L921.5,392.4 L926.2,397.0 L925.1,402.6 L921.8,406.3 L922.8,412.4 L920.5,422.2 L917.1,423.3 L915.2,428.3 L915.2,731.4 L438.1,732.5 L278.2,729.9 L60.0,731.7 L53.0,723.9 L49.6,722.9 L42.8,712.4 L42.3,701.5 L39.6,693.8 L36.3,690.0 L36.4,680.6 L33.7,677.8 L34.7,669.0 L33.4,658.6 L38.7,637.7 L37.5,627.7 L35.6,622.0 L31.6,619.6 L28.8,610.2 L26.7,608.7 L24.1,609.8 L21.4,596.7 L17.9,593.2 L25.7,579.6 L30.8,565.9 L33.5,546.8 L37.4,535.4 L39.7,521.3 L37.3,515.4 L40.8,509.9 L44.6,507.9 L47.7,501.7 L57.4,473.8 L67.3,415.3 L70.6,383.3 L71.5,353.1 L75.2,331.8 L77.2,329.6 L75.8,329.3 L75.2,320.0 L77.2,299.9 L75.2,299.4 L77.5,297.6 L78.3,291.5 L76.8,287.5 L78.2,278.5 L76.4,268.5 L82.2,247.0 L84.7,227.5 L83.1,226.9 L83.3,224.4 L86.5,219.5 L88.1,211.0 L89.5,182.6 L88.4,179.4 L84.3,179.4 L88.4,176.4 L89.3,171.2 L89.9,163.8 L88.0,154.1 L90.3,150.7 L92.5,125.6 L92.0,114.8 L87.3,109.1 L88.9,105.7 L89.7,91.2 L89.1,84.9 L86.0,78.5 L88.8,74.8 L92.7,73.4 L93.6,62.7 L90.1,46.2 L82.3,31.7 L83.9,30.6 L85.4,30.7 L86.7,34.7 L91.2,35.9 L96.6,41.6 L102.5,43.6 L104.1,41.6 L101.4,38.3 L128.5,34.2 L130.1,30.5 L134.5,31.8 L139.0,28.6 L139.1,26.8 L144.6,24.8 L151.0,28.3 L153.3,31.7 L153.0,39.6 L160.0,45.4 L170.9,45.7 L184.4,38.4 L190.4,39.0 L215.6,55.8 L218.7,64.5 L226.4,76.1 L226.7,84.1 L229.8,91.5 L228.6,101.1 L232.6,109.5 L231.1,122.5 L232.3,126.4 L246.6,134.2 L258.0,136.4 L271.0,141.9 L278.0,139.8 L283.8,144.4 L288.2,145.2 L293.6,144.5 L301.4,139.5 L311.2,138.6 L325.3,132.1 L328.5,128.6 L334.2,126.8 L339.1,120.4 L345.7,118.2 L358.1,120.1 L378.8,114.9 L391.9,120.3 L402.1,118.5 L416.6,124.0 L418.9,133.1 L422.3,134.8 L426.6,134.2 L434.6,127.1 L448.9,126.5 L454.7,128.7 L459.5,124.0 L479.2,116.7 L485.7,111.7 L494.7,112.9 L503.9,120.2 L513.2,119.4 L536.2,115.0 L541.0,109.0 L565.4,98.7 L600.6,93.3 L608.8,83.0 L612.3,82.0 L622.3,85.2 L649.7,79.6 L657.0,81.6 L665.3,80.8 L677.1,74.8 L681.8,69.7 L928.4,70.4 L931.1,73.9 L935.0,85.0 L942.6,93.1 L944.2,98.5 L946.9,100.1 L952.7,98.4 L958.2,105.7 L966.8,106.3 L972.3,110.9 L973.6,120.7 L979.3,127.6 L982.2,135.4 L975.0,144.7 L971.5,152.5 L971.3,158.5 L967.4,161.8 L966.3,166.8 L957.2,181.9 L957.1,189.4 L953.6,195.4 L950.5,211.6 L945.2,217.6 L942.5,225.1 L936.5,231.4 L935.2,238.6 L938.3,246.2 L935.4,254.8 L930.7,260.2 L926.1,270.9 L913.8,276.8 L910.9,280.2 L911.0,283.6 L906.9,290.6 L903.5,303.9 L900.7,307.2 L900.6,311.8 L891.6,320.7 L892.8,329.9 L889.4,335.9 L895.8,344.9 L892.2,350.7 Z" class="preview-state" />
            <line x1="228.0" y1="466.7" x2="404.7" y2="390.9" class="preview-line" />
            <circle cx="228.0" cy="466.7" r="16" class="preview-guess" />
            <circle cx="228.0" cy="466.7" r="6" class="preview-guess-dot" />
            <circle cx="404.7" cy="390.9" r="14" class="preview-target" />
            <circle cx="404.7" cy="390.9" r="5" class="preview-target-dot" />
          </svg>
        </div>
        <div class="mode-preview-set" data-mode="counties">
          <svg class="mode-preview" viewBox="0 0 1000 757.4" aria-hidden="true">
            <defs>
              <marker id="preview-arrowhead" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" class="preview-arrowhead" />
              </marker>
            </defs>
            <path d="M892.2,350.7 L898.1,357.7 L901.9,357.6 L906.0,354.2 L912.0,362.6 L914.6,359.4 L921.2,360.4 L921.7,367.9 L927.2,368.8 L931.0,374.0 L926.2,384.0 L921.0,386.4 L921.5,392.4 L926.2,397.0 L925.1,402.6 L921.8,406.3 L922.8,412.4 L920.5,422.2 L917.1,423.3 L915.2,428.3 L915.2,731.4 L438.1,732.5 L278.2,729.9 L60.0,731.7 L53.0,723.9 L49.6,722.9 L42.8,712.4 L42.3,701.5 L39.6,693.8 L36.3,690.0 L36.4,680.6 L33.7,677.8 L34.7,669.0 L33.4,658.6 L38.7,637.7 L37.5,627.7 L35.6,622.0 L31.6,619.6 L28.8,610.2 L26.7,608.7 L24.1,609.8 L21.4,596.7 L17.9,593.2 L25.7,579.6 L30.8,565.9 L33.5,546.8 L37.4,535.4 L39.7,521.3 L37.3,515.4 L40.8,509.9 L44.6,507.9 L47.7,501.7 L57.4,473.8 L67.3,415.3 L70.6,383.3 L71.5,353.1 L75.2,331.8 L77.2,329.6 L75.8,329.3 L75.2,320.0 L77.2,299.9 L75.2,299.4 L77.5,297.6 L78.3,291.5 L76.8,287.5 L78.2,278.5 L76.4,268.5 L82.2,247.0 L84.7,227.5 L83.1,226.9 L83.3,224.4 L86.5,219.5 L88.1,211.0 L89.5,182.6 L88.4,179.4 L84.3,179.4 L88.4,176.4 L89.3,171.2 L89.9,163.8 L88.0,154.1 L90.3,150.7 L92.5,125.6 L92.0,114.8 L87.3,109.1 L88.9,105.7 L89.7,91.2 L89.1,84.9 L86.0,78.5 L88.8,74.8 L92.7,73.4 L93.6,62.7 L90.1,46.2 L82.3,31.7 L83.9,30.6 L85.4,30.7 L86.7,34.7 L91.2,35.9 L96.6,41.6 L102.5,43.6 L104.1,41.6 L101.4,38.3 L128.5,34.2 L130.1,30.5 L134.5,31.8 L139.0,28.6 L139.1,26.8 L144.6,24.8 L151.0,28.3 L153.3,31.7 L153.0,39.6 L160.0,45.4 L170.9,45.7 L184.4,38.4 L190.4,39.0 L215.6,55.8 L218.7,64.5 L226.4,76.1 L226.7,84.1 L229.8,91.5 L228.6,101.1 L232.6,109.5 L231.1,122.5 L232.3,126.4 L246.6,134.2 L258.0,136.4 L271.0,141.9 L278.0,139.8 L283.8,144.4 L288.2,145.2 L293.6,144.5 L301.4,139.5 L311.2,138.6 L325.3,132.1 L328.5,128.6 L334.2,126.8 L339.1,120.4 L345.7,118.2 L358.1,120.1 L378.8,114.9 L391.9,120.3 L402.1,118.5 L416.6,124.0 L418.9,133.1 L422.3,134.8 L426.6,134.2 L434.6,127.1 L448.9,126.5 L454.7,128.7 L459.5,124.0 L479.2,116.7 L485.7,111.7 L494.7,112.9 L503.9,120.2 L513.2,119.4 L536.2,115.0 L541.0,109.0 L565.4,98.7 L600.6,93.3 L608.8,83.0 L612.3,82.0 L622.3,85.2 L649.7,79.6 L657.0,81.6 L665.3,80.8 L677.1,74.8 L681.8,69.7 L928.4,70.4 L931.1,73.9 L935.0,85.0 L942.6,93.1 L944.2,98.5 L946.9,100.1 L952.7,98.4 L958.2,105.7 L966.8,106.3 L972.3,110.9 L973.6,120.7 L979.3,127.6 L982.2,135.4 L975.0,144.7 L971.5,152.5 L971.3,158.5 L967.4,161.8 L966.3,166.8 L957.2,181.9 L957.1,189.4 L953.6,195.4 L950.5,211.6 L945.2,217.6 L942.5,225.1 L936.5,231.4 L935.2,238.6 L938.3,246.2 L935.4,254.8 L930.7,260.2 L926.1,270.9 L913.8,276.8 L910.9,280.2 L911.0,283.6 L906.9,290.6 L903.5,303.9 L900.7,307.2 L900.6,311.8 L891.6,320.7 L892.8,329.9 L889.4,335.9 L895.8,344.9 L892.2,350.7 Z" class="preview-state" />
            <path d="M323.0,464.0 L323.2,462.3 L327.4,462.2 L324.8,457.8 L327.2,449.7 L325.5,443.1 L327.9,439.6 L326.2,424.1 L331.8,415.6 L338.8,415.1 L340.0,406.9 L342.7,405.3 L341.7,404.5 L343.7,402.4 L344.4,398.5 L343.0,394.0 L346.8,391.8 L350.7,383.8 L349.0,376.0 L350.4,372.8 L348.8,366.2 L349.7,363.9 L348.3,359.3 L344.8,357.2 L344.0,353.7 L342.1,353.3 L341.9,335.6 L429.5,335.9 L430.0,377.7 L443.8,378.4 L443.9,407.0 L472.2,407.6 L472.3,421.8 L516.2,421.6 L516.3,436.0 L530.5,436.1 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z" class="preview-ghost" />
            <path d="M323.0,464.0 L323.2,462.3 L327.4,462.2 L324.8,457.8 L327.2,449.7 L325.5,443.1 L327.9,439.6 L326.2,424.1 L331.8,415.6 L338.8,415.1 L340.0,406.9 L342.7,405.3 L341.7,404.5 L343.7,402.4 L344.4,398.5 L343.0,394.0 L346.8,391.8 L350.7,383.8 L349.0,376.0 L350.4,372.8 L348.8,366.2 L349.7,363.9 L348.3,359.3 L344.8,357.2 L344.0,353.7 L342.1,353.3 L341.9,335.6 L429.5,335.9 L430.0,377.7 L443.8,378.4 L443.9,407.0 L472.2,407.6 L472.3,421.8 L516.2,421.6 L516.3,436.0 L530.5,436.1 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z" transform="translate(-160 -130)" class="preview-piece" />
            <path d="M400,315 Q395,355 375,385" class="preview-arrow" marker-end="url(#preview-arrowhead)" />
          </svg>
        </div>
        <div class="mode-preview-set" data-mode="name-the-county">
          <svg class="mode-preview" viewBox="0 0 1000 757.4" aria-hidden="true">
            <path d="M892.2,350.7 L898.1,357.7 L901.9,357.6 L906.0,354.2 L912.0,362.6 L914.6,359.4 L921.2,360.4 L921.7,367.9 L927.2,368.8 L931.0,374.0 L926.2,384.0 L921.0,386.4 L921.5,392.4 L926.2,397.0 L925.1,402.6 L921.8,406.3 L922.8,412.4 L920.5,422.2 L917.1,423.3 L915.2,428.3 L915.2,731.4 L438.1,732.5 L278.2,729.9 L60.0,731.7 L53.0,723.9 L49.6,722.9 L42.8,712.4 L42.3,701.5 L39.6,693.8 L36.3,690.0 L36.4,680.6 L33.7,677.8 L34.7,669.0 L33.4,658.6 L38.7,637.7 L37.5,627.7 L35.6,622.0 L31.6,619.6 L28.8,610.2 L26.7,608.7 L24.1,609.8 L21.4,596.7 L17.9,593.2 L25.7,579.6 L30.8,565.9 L33.5,546.8 L37.4,535.4 L39.7,521.3 L37.3,515.4 L40.8,509.9 L44.6,507.9 L47.7,501.7 L57.4,473.8 L67.3,415.3 L70.6,383.3 L71.5,353.1 L75.2,331.8 L77.2,329.6 L75.8,329.3 L75.2,320.0 L77.2,299.9 L75.2,299.4 L77.5,297.6 L78.3,291.5 L76.8,287.5 L78.2,278.5 L76.4,268.5 L82.2,247.0 L84.7,227.5 L83.1,226.9 L83.3,224.4 L86.5,219.5 L88.1,211.0 L89.5,182.6 L88.4,179.4 L84.3,179.4 L88.4,176.4 L89.3,171.2 L89.9,163.8 L88.0,154.1 L90.3,150.7 L92.5,125.6 L92.0,114.8 L87.3,109.1 L88.9,105.7 L89.7,91.2 L89.1,84.9 L86.0,78.5 L88.8,74.8 L92.7,73.4 L93.6,62.7 L90.1,46.2 L82.3,31.7 L83.9,30.6 L85.4,30.7 L86.7,34.7 L91.2,35.9 L96.6,41.6 L102.5,43.6 L104.1,41.6 L101.4,38.3 L128.5,34.2 L130.1,30.5 L134.5,31.8 L139.0,28.6 L139.1,26.8 L144.6,24.8 L151.0,28.3 L153.3,31.7 L153.0,39.6 L160.0,45.4 L170.9,45.7 L184.4,38.4 L190.4,39.0 L215.6,55.8 L218.7,64.5 L226.4,76.1 L226.7,84.1 L229.8,91.5 L228.6,101.1 L232.6,109.5 L231.1,122.5 L232.3,126.4 L246.6,134.2 L258.0,136.4 L271.0,141.9 L278.0,139.8 L283.8,144.4 L288.2,145.2 L293.6,144.5 L301.4,139.5 L311.2,138.6 L325.3,132.1 L328.5,128.6 L334.2,126.8 L339.1,120.4 L345.7,118.2 L358.1,120.1 L378.8,114.9 L391.9,120.3 L402.1,118.5 L416.6,124.0 L418.9,133.1 L422.3,134.8 L426.6,134.2 L434.6,127.1 L448.9,126.5 L454.7,128.7 L459.5,124.0 L479.2,116.7 L485.7,111.7 L494.7,112.9 L503.9,120.2 L513.2,119.4 L536.2,115.0 L541.0,109.0 L565.4,98.7 L600.6,93.3 L608.8,83.0 L612.3,82.0 L622.3,85.2 L649.7,79.6 L657.0,81.6 L665.3,80.8 L677.1,74.8 L681.8,69.7 L928.4,70.4 L931.1,73.9 L935.0,85.0 L942.6,93.1 L944.2,98.5 L946.9,100.1 L952.7,98.4 L958.2,105.7 L966.8,106.3 L972.3,110.9 L973.6,120.7 L979.3,127.6 L982.2,135.4 L975.0,144.7 L971.5,152.5 L971.3,158.5 L967.4,161.8 L966.3,166.8 L957.2,181.9 L957.1,189.4 L953.6,195.4 L950.5,211.6 L945.2,217.6 L942.5,225.1 L936.5,231.4 L935.2,238.6 L938.3,246.2 L935.4,254.8 L930.7,260.2 L926.1,270.9 L913.8,276.8 L910.9,280.2 L911.0,283.6 L906.9,290.6 L903.5,303.9 L900.7,307.2 L900.6,311.8 L891.6,320.7 L892.8,329.9 L889.4,335.9 L895.8,344.9 L892.2,350.7 Z" class="preview-state" />
            <path d="M737.5,283.8 L740.7,282.5 L743.3,284.1 L746.5,280.7 L749.4,281.6 L749.7,280.3 L752.2,280.4 L755.6,276.9 L761.0,277.9 L765.4,276.3 L764.2,266.0 L761.4,262.2 L764.8,257.2 L772.2,257.3 L771.1,250.2 L772.7,245.5 L770.2,244.3 L770.2,241.6 L771.7,241.6 L773.8,233.9 L777.1,231.9 L780.1,232.5 L783.8,227.7 L787.6,227.7 L791.0,232.3 L794.9,234.4 L802.0,235.9 L808.7,231.9 L814.4,224.2 L815.7,226.1 L818.7,226.0 L821.0,230.8 L822.5,229.7 L823.9,230.8 L825.8,236.4 L851.2,236.3 L851.3,222.0 L944.1,222.1 L936.5,231.4 L935.4,239.2 L939.0,238.0 L936.1,242.0 L938.3,246.4 L935.4,254.8 L930.5,259.2 L926.1,270.8 L913.8,276.8 L910.9,280.2 L911.0,283.6 L906.9,290.6 L903.5,304.0 L900.7,307.2 L900.6,311.8 L896.7,314.0 L894.5,319.1 L891.6,320.7 L892.8,329.9 L889.4,335.9 L895.8,344.9 L892.2,350.7 L860.4,350.9 L860.4,336.5 L857.7,336.5 L857.7,334.1 L855.3,334.1 L855.3,331.8 L850.5,331.8 L850.6,329.4 L848.0,329.4 L848.0,327.0 L802.7,327.1 L802.7,329.5 L798.0,329.5 L798.0,331.8 L795.6,331.8 L795.5,336.0 L793.1,336.0 L793.2,339.0 L790.8,339.0 L790.8,341.4 L789.0,341.4 L788.4,346.2 L786.0,346.1 L786.0,348.5 L783.6,348.5 L783.6,351.0 L781.2,351.0 L781.1,355.8 L776.3,355.8 L776.3,358.2 L740.1,358.3 L739.8,354.7 L743.5,345.2 L747.6,342.0 L747.8,339.5 L750.8,339.2 L747.4,334.0 L749.5,329.0 L749.2,325.2 L754.7,324.6 L756.4,322.5 L755.1,312.7 L759.0,306.7 L760.8,307.5 L762.9,303.1 L759.0,299.5 L757.1,294.8 L754.2,293.6 L751.1,294.4 L748.7,292.2 L746.2,293.0 L739.3,290.5 L737.5,283.8 Z M107.0,343.5 L116.8,343.3 L116.7,340.9 L119.1,340.9 L118.5,328.8 L133.1,328.9 L132.5,281.2 L186.5,281.4 L190.3,288.5 L193.5,288.8 L195.4,291.6 L192.9,294.5 L183.9,295.6 L184.0,297.5 L180.7,300.8 L182.2,303.4 L174.3,305.5 L173.3,308.0 L175.4,310.0 L174.3,313.4 L175.9,313.2 L178.9,317.0 L177.9,320.3 L179.8,327.2 L177.1,329.1 L177.6,335.4 L175.1,337.3 L178.2,340.6 L176.3,341.5 L177.0,343.9 L175.0,345.6 L178.0,346.0 L178.5,349.1 L181.2,349.7 L181.2,352.4 L182.8,353.6 L133.6,354.8 L111.9,353.6 L111.9,348.2 L107.1,348.4 L107.0,343.5 Z M220.0,182.6 L222.5,182.6 L222.5,177.9 L227.2,177.8 L227.4,180.2 L234.7,180.2 L234.7,163.4 L246.0,163.5 L244.6,159.4 L246.9,158.7 L344.7,158.7 L349.9,168.5 L356.1,170.0 L359.3,173.3 L358.6,180.3 L361.4,185.9 L359.4,192.8 L361.2,193.6 L361.0,197.2 L353.4,201.0 L353.2,203.4 L357.6,209.8 L359.0,214.9 L363.0,215.3 L364.6,218.2 L363.9,224.1 L360.0,224.2 L356.3,227.6 L356.9,228.9 L349.6,228.9 L349.3,232.5 L346.4,233.2 L346.7,238.9 L348.8,243.3 L347.5,245.5 L351.3,244.7 L353.3,249.2 L357.2,250.6 L354.9,254.0 L275.5,254.0 L275.7,251.0 L271.3,251.2 L265.4,247.9 L263.1,248.6 L259.5,245.6 L255.7,238.0 L252.4,236.6 L252.4,231.9 L239.3,225.3 L234.0,217.3 L229.4,213.5 L233.8,205.0 L232.9,201.5 L234.5,199.4 L233.8,195.0 L235.3,192.2 L229.9,192.1 L229.8,189.7 L223.9,189.7 L222.1,192.1 L219.9,192.1 L220.0,182.6 Z M83.7,30.5 L86.5,32.1 L86.4,35.0 L90.7,35.4 L96.5,39.8 L96.8,41.7 L102.5,43.6 L104.5,41.3 L101.4,38.3 L111.0,36.8 L114.1,34.4 L118.8,38.4 L121.7,38.3 L124.0,36.9 L124.9,33.6 L130.5,34.0 L139.0,28.5 L139.1,26.8 L144.6,24.8 L147.7,25.3 L151.0,28.3 L153.3,31.7 L152.9,39.6 L160.9,45.4 L161.2,106.1 L118.5,107.2 L118.6,105.5 L88.9,105.5 L89.1,84.9 L86.0,78.5 L88.8,74.8 L92.7,73.4 L93.6,62.7 L90.1,46.2 L82.7,31.6 L83.7,30.5 Z M81.0,22.5 L82.4,21.5 L84.2,25.7 L81.0,22.5 Z M160.6,60.0 L160.9,45.4 L170.9,45.7 L184.4,38.4 L190.4,39.0 L215.7,55.8 L218.7,64.5 L226.4,76.1 L226.7,84.1 L229.8,91.5 L228.6,101.1 L231.7,105.9 L232.5,114.6 L229.9,114.5 L229.9,115.8 L212.7,115.7 L212.7,113.4 L205.4,113.2 L205.4,110.9 L200.5,110.8 L200.6,106.2 L161.2,106.1 L160.6,60.0 Z M30.2,567.4 L33.3,554.2 L33.1,547.1 L37.4,535.4 L39.7,521.3 L37.3,515.4 L39.4,510.9 L44.4,507.8 L47.7,501.7 L54.8,482.9 L59.2,464.9 L100.0,465.3 L100.0,480.6 L107.0,480.5 L106.9,494.6 L113.2,494.6 L113.6,496.1 L113.3,523.3 L120.4,523.3 L120.7,551.6 L113.6,552.2 L113.6,566.6 L106.5,566.6 L107.6,600.9 L103.1,600.9 L100.9,603.2 L94.1,603.3 L94.0,609.0 L92.7,609.0 L92.7,610.8 L90.3,610.8 L90.3,613.2 L88.0,613.2 L88.0,615.6 L85.7,615.6 L85.7,618.0 L74.5,618.0 L74.5,619.2 L71.0,619.2 L69.4,621.1 L68.7,609.0 L66.2,609.0 L65.6,596.1 L66.1,594.4 L68.4,594.4 L66.0,585.3 L63.7,585.4 L62.6,583.1 L59.7,581.9 L59.1,576.9 L56.7,576.9 L54.5,573.4 L28.1,573.5 L30.2,567.4 Z M429.4,357.2 L429.5,335.9 L443.7,336.0 L443.6,321.7 L462.9,321.7 L462.8,307.4 L515.3,307.2 L515.3,328.4 L558.7,327.9 L558.8,336.1 L573.3,336.1 L573.3,349.8 L602.3,349.7 L602.1,407.3 L588.0,407.3 L587.8,450.5 L530.6,450.4 L530.5,436.1 L516.3,436.0 L516.2,421.6 L472.3,421.8 L472.2,407.6 L443.9,407.0 L443.8,378.4 L430.0,377.7 L429.4,357.2 Z M18.0,592.3 L19.8,591.9 L28.1,573.5 L54.5,573.4 L56.7,576.9 L59.1,576.9 L59.7,581.9 L62.6,583.1 L63.7,585.4 L66.0,585.3 L65.9,587.5 L67.8,588.8 L68.4,594.4 L66.1,594.4 L65.6,600.7 L66.2,609.0 L68.7,609.0 L69.4,621.1 L71.0,619.2 L74.5,619.2 L74.5,618.0 L85.7,618.0 L85.7,615.6 L88.0,615.6 L88.0,613.2 L90.3,613.2 L90.3,610.8 L92.7,610.8 L92.7,609.0 L94.0,609.0 L94.1,603.3 L100.9,603.2 L103.1,600.9 L108.6,601.1 L111.0,599.2 L117.1,602.4 L119.0,601.5 L105.3,626.8 L106.7,630.1 L103.1,634.9 L100.1,646.5 L94.8,649.6 L91.7,648.5 L84.2,649.3 L84.2,662.0 L80.2,667.3 L82.0,672.0 L92.8,671.6 L94.7,674.1 L98.5,673.3 L100.7,678.0 L104.3,679.8 L103.4,681.9 L107.6,691.1 L110.0,692.1 L110.2,694.9 L108.0,695.5 L106.6,698.5 L107.5,703.3 L102.1,709.1 L104.4,710.8 L106.4,717.1 L103.2,724.0 L104.4,728.9 L106.9,731.6 L60.0,731.7 L53.0,723.9 L50.5,724.1 L43.4,714.8 L43.3,709.1 L41.6,705.2 L42.3,701.5 L39.6,693.8 L35.9,689.7 L36.2,680.6 L33.7,677.8 L34.7,669.0 L33.4,658.3 L38.8,636.3 L36.6,633.0 L37.5,627.7 L35.6,622.0 L31.6,619.6 L28.8,610.2 L26.7,608.7 L24.1,610.2 L22.8,600.8 L18.0,592.3 Z M323.0,464.0 L323.2,462.3 L327.4,462.2 L324.8,457.8 L327.2,449.7 L325.5,443.1 L327.9,439.6 L326.2,424.1 L331.8,415.6 L338.8,415.1 L340.0,406.9 L342.7,405.3 L341.7,404.5 L343.7,402.4 L344.4,398.5 L343.0,394.0 L346.8,391.8 L350.7,383.8 L349.0,376.0 L350.4,372.8 L348.8,366.2 L349.7,363.9 L348.3,359.3 L344.8,357.2 L344.0,353.7 L342.1,353.3 L341.9,335.6 L429.5,335.9 L430.0,377.7 L443.8,378.4 L443.9,407.0 L472.2,407.6 L472.3,421.8 L516.2,421.6 L516.3,436.0 L530.5,436.1 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z M59.7,462.1 L66.3,423.1 L94.1,422.7 L94.0,417.3 L99.2,416.3 L105.2,410.0 L120.5,409.8 L120.5,410.9 L125.8,411.0 L125.8,413.5 L130.6,413.6 L130.5,418.5 L135.3,418.6 L135.2,422.3 L141.3,422.3 L141.3,428.6 L148.3,428.5 L148.3,432.0 L162.8,432.1 L162.8,436.9 L187.9,437.0 L187.9,465.7 L191.5,465.7 L191.4,476.6 L235.0,475.9 L235.0,493.6 L307.5,493.2 L311.2,495.7 L312.4,495.0 L316.5,499.9 L316.2,502.0 L319.7,505.7 L319.2,507.0 L320.7,506.1 L322.3,510.2 L321.4,512.3 L323.3,514.9 L322.4,518.3 L326.3,522.7 L323.0,527.1 L318.4,529.9 L318.6,534.3 L312.3,551.6 L312.1,553.4 L314.2,554.8 L289.6,554.8 L289.6,566.6 L275.5,566.5 L275.5,568.7 L273.2,568.7 L273.2,571.1 L270.8,571.1 L270.8,573.5 L268.5,573.5 L268.5,575.9 L256.6,576.0 L256.6,578.4 L254.2,578.4 L254.2,580.7 L251.8,580.7 L251.8,583.2 L247.3,583.0 L247.4,585.7 L242.7,585.7 L242.7,588.1 L240.3,588.1 L240.3,590.5 L238.0,590.5 L238.0,592.8 L235.6,592.8 L235.6,595.2 L231.0,594.3 L228.7,602.7 L210.0,603.2 L207.7,605.5 L203.1,605.8 L203.1,607.0 L186.1,606.4 L186.1,609.4 L182.8,609.4 L176.9,615.2 L174.6,615.2 L174.6,611.6 L171.6,611.5 L171.6,610.3 L165.1,610.9 L160.6,610.3 L160.6,609.1 L160.0,611.5 L156.6,611.5 L156.5,613.9 L151.3,613.8 L150.0,615.7 L139.7,614.0 L135.0,609.0 L123.6,609.0 L123.6,607.3 L121.3,606.7 L121.3,609.1 L119.0,609.0 L119.0,601.5 L117.1,602.4 L111.0,599.2 L107.6,600.9 L106.5,566.6 L113.6,566.6 L113.6,552.2 L120.7,551.6 L120.4,523.3 L113.3,523.3 L113.6,496.1 L113.2,494.6 L106.9,494.6 L107.0,480.5 L100.0,480.6 L100.0,465.3 L59.2,464.9 L59.7,462.1 Z M483.5,113.1 L490.9,111.6 L494.7,112.9 L501.1,119.3 L513.2,119.4 L536.2,115.0 L541.0,109.0 L561.4,100.7 L560.5,192.5 L575.3,192.6 L575.1,207.1 L589.9,207.1 L589.8,221.6 L586.2,221.6 L586.2,223.9 L502.4,223.8 L500.0,219.4 L504.5,216.6 L506.2,218.4 L505.9,213.6 L507.9,211.4 L504.6,210.0 L505.5,208.0 L503.7,206.9 L505.0,205.7 L503.2,205.2 L504.0,203.1 L496.8,200.3 L498.9,198.3 L496.4,198.3 L495.1,193.7 L497.8,192.2 L496.2,191.6 L496.8,188.9 L495.2,188.6 L496.6,187.8 L496.0,185.7 L498.9,185.4 L496.9,183.6 L498.5,181.5 L496.9,180.6 L498.2,179.0 L496.6,177.9 L497.7,173.8 L500.3,172.5 L497.9,172.0 L499.6,169.8 L498.4,168.9 L503.8,165.5 L501.1,164.3 L503.7,163.0 L502.2,161.2 L503.9,159.1 L502.3,158.1 L507.2,154.8 L512.5,157.3 L510.5,152.7 L517.5,153.2 L518.4,151.0 L516.0,148.5 L518.7,146.8 L512.9,142.8 L512.4,136.6 L508.4,134.6 L508.9,131.5 L505.6,132.6 L503.4,129.7 L504.2,128.4 L502.8,128.6 L503.1,126.7 L498.1,123.9 L496.1,124.4 L493.5,120.3 L489.6,118.8 L487.7,115.7 L484.7,115.6 L483.5,113.1 Z M600.3,235.9 L743.5,235.9 L747.3,237.6 L747.4,241.3 L751.2,239.0 L752.9,239.7 L753.2,237.8 L756.5,236.4 L763.7,241.6 L770.2,242.0 L770.2,244.3 L772.7,245.5 L771.1,250.2 L772.2,257.3 L764.8,257.2 L761.4,262.2 L764.2,266.0 L765.4,276.3 L761.0,277.9 L755.6,276.9 L752.2,280.4 L749.7,280.3 L749.4,281.6 L746.5,280.7 L743.3,284.1 L740.7,282.5 L737.5,283.8 L739.3,290.5 L746.2,293.0 L748.7,292.2 L751.1,294.4 L754.2,293.6 L757.1,294.8 L759.0,299.5 L762.9,303.1 L760.8,307.5 L759.0,306.7 L755.1,312.7 L756.4,322.5 L754.7,324.6 L749.2,325.2 L749.5,329.0 L747.4,334.0 L750.8,339.2 L747.8,339.5 L747.6,342.0 L743.5,345.2 L739.8,354.7 L740.1,358.3 L771.7,358.0 L772.2,393.9 L702.1,392.6 L702.1,407.0 L602.1,407.3 L602.7,264.3 L600.4,264.3 L600.3,235.9 Z M568.0,606.7 L569.3,536.4 L573.6,536.4 L573.5,450.5 L587.8,450.5 L588.0,407.3 L702.1,407.0 L702.1,392.6 L772.2,393.9 L772.1,580.1 L773.5,580.1 L773.8,685.8 L776.1,685.8 L775.8,731.9 L637.5,732.4 L636.8,607.5 L568.0,607.9 L568.0,606.7 Z M332.8,144.5 L334.9,143.1 L333.0,138.2 L332.5,127.7 L339.1,120.4 L345.7,118.2 L358.1,120.1 L378.8,114.9 L389.8,119.7 L389.8,149.2 L384.9,149.1 L384.9,192.4 L359.4,192.4 L361.4,185.9 L358.6,180.3 L358.9,172.5 L347.9,166.4 L346.3,159.9 L339.9,154.1 L338.8,150.0 L334.4,148.9 L332.8,144.5 Z M176.7,730.6 L176.9,614.0 L179.2,614.0 L182.8,609.4 L186.1,609.4 L186.1,606.4 L203.1,607.0 L203.1,605.8 L207.7,605.5 L210.0,603.2 L228.7,602.7 L231.0,594.3 L235.6,595.2 L235.6,592.8 L238.0,592.8 L238.0,590.5 L240.3,590.5 L240.3,588.1 L242.7,588.1 L242.7,585.7 L247.4,585.7 L247.3,583.0 L251.8,583.2 L251.8,580.7 L254.2,580.7 L254.2,578.4 L256.6,578.4 L256.6,576.0 L268.5,575.9 L268.5,573.5 L270.8,573.5 L270.8,571.1 L273.2,571.1 L273.2,568.7 L275.5,568.7 L275.5,566.5 L289.6,566.6 L288.8,730.1 L176.7,730.6 Z M341.2,323.0 L341.5,319.3 L345.9,315.4 L345.1,311.6 L347.8,302.2 L345.7,298.7 L347.3,294.6 L347.0,287.5 L348.6,286.5 L346.5,279.9 L351.8,274.4 L350.2,272.2 L347.5,272.7 L345.6,271.2 L344.6,268.2 L345.6,266.3 L352.7,263.2 L517.1,264.6 L515.5,268.8 L514.2,267.5 L513.1,269.1 L515.4,274.6 L515.3,307.2 L462.8,307.4 L462.9,321.7 L443.6,321.7 L443.7,336.0 L341.9,335.6 L341.2,323.0 Z M80.2,667.3 L84.2,662.0 L84.2,649.3 L91.7,648.5 L94.8,649.6 L100.1,646.5 L103.1,634.9 L106.7,630.1 L105.3,626.8 L119.0,601.7 L119.0,609.0 L121.3,609.1 L121.3,606.7 L123.6,607.3 L123.6,609.0 L135.0,609.0 L135.0,610.3 L136.8,609.7 L137.3,612.7 L145.4,614.1 L145.4,615.3 L150.0,615.7 L153.6,613.2 L156.5,613.9 L156.6,611.5 L160.0,611.5 L160.0,609.1 L160.6,610.3 L174.6,611.6 L174.6,615.2 L176.9,615.2 L176.7,730.8 L106.4,732.2 L103.2,724.0 L106.4,717.1 L104.4,710.8 L102.1,709.1 L107.5,703.3 L106.6,698.5 L108.0,695.5 L110.2,694.9 L110.0,692.1 L107.6,691.1 L103.4,681.9 L104.3,679.8 L100.7,678.0 L98.5,673.3 L94.7,674.1 L92.8,671.6 L82.0,672.0 L80.2,667.3 Z M288.7,710.4 L289.6,554.8 L314.2,554.8 L312.1,553.4 L312.3,551.6 L318.6,534.3 L318.4,529.9 L323.0,527.1 L326.3,522.7 L322.5,518.7 L323.3,514.9 L321.4,512.3 L322.0,509.0 L316.6,502.9 L316.5,499.9 L312.4,495.0 L311.2,495.7 L305.0,491.9 L307.0,490.5 L307.7,485.7 L307.8,482.3 L305.5,479.8 L307.7,473.8 L323.0,464.2 L402.6,464.0 L402.7,507.0 L400.8,507.0 L400.7,607.9 L456.2,608.3 L456.6,732.5 L288.8,730.1 L288.7,710.4 Z M400.5,579.2 L400.8,507.0 L402.7,507.0 L402.6,464.0 L573.6,464.9 L573.6,536.4 L569.3,536.4 L568.0,607.9 L636.8,607.5 L637.5,732.4 L456.6,732.5 L456.2,608.3 L400.7,607.9 L400.5,579.2 Z M67.3,415.3 L71.6,354.7 L182.8,353.6 L183.0,359.0 L186.3,363.0 L184.6,367.4 L215.4,367.3 L215.7,357.7 L220.2,357.7 L220.2,353.0 L225.3,355.2 L227.1,353.5 L236.2,352.9 L245.0,355.7 L247.1,359.3 L252.6,360.1 L254.6,362.8 L259.5,361.7 L263.4,363.9 L275.1,364.0 L278.1,365.9 L284.3,362.3 L284.3,358.7 L347.1,357.8 L349.7,363.9 L348.8,366.2 L350.3,373.5 L349.0,376.0 L350.3,377.4 L350.3,385.5 L346.8,391.8 L343.0,394.0 L344.4,398.5 L341.7,404.5 L342.7,405.3 L340.0,406.9 L338.8,415.1 L331.8,415.6 L326.2,424.1 L327.9,439.6 L325.5,443.1 L327.2,449.7 L324.8,457.8 L327.4,462.2 L323.2,462.3 L321.9,465.2 L307.7,473.8 L305.5,479.8 L307.8,482.3 L307.7,485.7 L307.0,490.5 L305.0,491.9 L307.5,493.2 L235.0,493.6 L235.0,475.9 L191.4,476.6 L191.5,465.7 L187.9,465.7 L187.9,437.0 L162.8,436.9 L162.8,432.1 L148.3,432.0 L148.3,428.5 L141.3,428.6 L141.3,422.3 L135.2,422.3 L135.3,418.6 L130.5,418.5 L130.6,413.6 L125.8,413.5 L125.8,411.0 L120.5,410.9 L120.5,409.8 L105.8,409.7 L99.2,416.3 L94.0,417.3 L94.1,422.7 L91.6,421.8 L91.6,423.3 L66.3,423.1 L67.3,415.3 Z M71.5,353.1 L74.9,333.5 L78.3,291.6 L75.8,288.5 L78.3,278.9 L76.4,268.5 L81.4,251.5 L84.2,227.7 L118.0,227.7 L117.9,278.3 L120.4,278.3 L120.4,281.2 L132.5,281.2 L133.1,328.9 L118.5,328.8 L119.1,340.9 L116.7,340.9 L116.8,343.3 L107.0,343.5 L107.1,348.4 L111.9,348.2 L111.9,353.6 L77.7,355.0 L71.6,354.7 L71.5,353.1 Z M173.2,308.3 L174.3,305.5 L182.2,303.4 L180.7,300.8 L184.7,295.1 L191.7,294.8 L195.5,292.9 L193.7,289.0 L190.3,288.5 L186.9,282.8 L186.3,280.2 L188.5,277.9 L187.1,276.6 L190.8,274.9 L192.3,277.1 L196.8,276.8 L200.2,281.3 L201.9,280.5 L202.0,285.0 L204.2,286.9 L209.3,281.2 L212.1,282.1 L216.4,277.3 L222.1,274.4 L222.4,272.5 L225.0,272.9 L230.1,269.1 L236.9,269.3 L240.9,272.3 L249.7,270.0 L256.1,273.5 L261.1,274.1 L261.3,275.8 L263.4,276.5 L285.3,274.9 L289.6,276.4 L297.3,285.9 L306.2,280.4 L319.2,287.1 L325.4,285.8 L327.6,287.4 L347.1,287.4 L347.3,294.6 L345.7,298.7 L347.8,302.2 L345.1,311.6 L345.9,315.4 L341.5,319.3 L341.2,323.3 L342.1,353.3 L344.1,353.8 L344.8,357.2 L347.1,357.8 L284.3,358.7 L284.3,362.3 L278.1,365.9 L275.1,364.0 L263.4,363.9 L259.5,361.7 L254.6,362.8 L252.6,360.1 L247.1,359.3 L245.0,355.7 L236.2,352.9 L227.1,353.5 L225.3,355.2 L220.2,353.0 L220.2,357.7 L215.7,357.7 L215.4,367.3 L184.6,367.4 L186.3,363.0 L183.0,359.0 L183.4,355.0 L181.2,352.4 L181.2,349.7 L178.5,349.1 L178.0,346.0 L175.0,345.6 L177.0,343.9 L176.3,341.5 L178.2,340.6 L175.1,337.3 L177.6,335.4 L177.1,329.1 L179.8,327.2 L177.9,320.3 L178.9,317.0 L175.9,313.2 L174.3,313.4 L175.4,310.0 L173.2,308.3 Z M771.7,358.2 L776.3,358.2 L776.3,355.8 L781.1,355.8 L781.2,351.0 L783.6,351.0 L783.6,348.5 L786.0,348.5 L786.0,346.1 L788.4,346.2 L789.0,341.4 L790.8,341.4 L790.8,339.0 L793.2,339.0 L793.1,336.0 L795.5,336.0 L795.6,331.8 L798.0,331.8 L798.0,329.5 L802.7,329.5 L802.7,327.1 L848.0,327.0 L848.0,329.4 L850.6,329.4 L850.5,331.8 L855.3,331.8 L855.3,334.1 L857.7,334.1 L857.7,336.5 L860.4,336.5 L860.4,350.9 L892.2,350.7 L894.7,355.2 L899.7,357.9 L905.5,354.1 L912.0,362.6 L914.6,359.4 L921.2,360.4 L921.7,367.9 L927.2,368.9 L930.8,372.2 L926.2,384.0 L921.0,386.4 L921.5,392.4 L925.8,395.7 L926.0,402.7 L921.2,404.7 L923.2,406.1 L921.6,407.4 L923.1,408.0 L922.0,410.8 L923.3,413.2 L920.5,415.0 L920.4,422.4 L916.0,423.9 L917.1,426.2 L914.4,428.7 L915.8,430.4 L915.2,731.4 L775.8,731.9 L776.1,685.8 L773.8,685.8 L773.5,580.1 L772.1,580.1 L771.7,358.2 Z M182.7,258.7 L186.5,258.0 L189.3,250.1 L191.5,248.3 L191.0,246.6 L195.6,247.1 L199.3,243.7 L199.6,237.3 L196.6,236.8 L195.2,232.7 L196.1,222.2 L204.7,215.6 L200.4,210.8 L200.9,208.4 L204.1,207.9 L201.8,202.0 L199.0,202.1 L198.2,200.2 L199.9,198.3 L204.3,198.0 L204.1,192.2 L208.1,187.9 L210.5,190.8 L220.0,193.2 L223.9,189.7 L229.8,189.7 L229.9,192.1 L235.3,192.2 L233.8,195.0 L234.5,199.4 L232.9,201.5 L233.8,205.0 L229.4,213.5 L234.0,217.3 L239.3,225.3 L252.4,231.9 L252.4,236.6 L255.7,238.0 L259.5,245.6 L263.1,248.6 L265.4,247.9 L271.3,251.2 L275.7,251.0 L275.5,254.0 L355.0,254.5 L352.7,258.0 L354.0,260.3 L352.6,263.4 L345.6,266.3 L344.6,268.2 L345.6,271.2 L347.5,272.7 L350.2,272.2 L351.8,274.4 L346.5,279.9 L347.7,280.4 L346.7,283.2 L348.6,286.5 L347.7,287.4 L327.6,287.4 L325.4,285.8 L319.2,287.1 L306.2,280.4 L297.3,285.9 L289.6,276.4 L285.3,274.9 L263.4,276.5 L261.3,275.8 L261.1,274.1 L256.1,273.5 L249.7,270.0 L240.9,272.3 L236.9,269.3 L230.1,269.1 L225.0,272.9 L222.4,272.5 L222.1,274.4 L216.4,277.3 L212.3,281.9 L209.3,281.2 L207.3,285.0 L203.4,286.9 L202.0,285.0 L202.4,281.2 L199.5,280.8 L199.5,278.8 L197.1,278.5 L196.8,276.8 L192.3,277.1 L190.8,274.9 L186.6,276.2 L188.9,270.0 L192.6,268.3 L193.3,266.3 L189.2,263.9 L183.4,263.0 L182.7,258.7 Z M560.6,177.1 L561.4,100.7 L584.8,94.9 L600.6,93.3 L606.1,85.3 L612.3,82.0 L622.3,85.2 L628.9,83.2 L628.6,135.3 L650.7,135.5 L650.8,149.7 L663.0,149.7 L662.9,221.4 L660.9,221.4 L660.9,235.7 L586.1,236.0 L586.2,221.6 L589.8,221.6 L589.9,207.1 L575.1,207.1 L575.3,192.6 L560.5,192.5 L560.6,177.1 Z M212.7,124.1 L212.7,115.7 L229.9,115.8 L229.9,114.5 L232.5,114.5 L231.1,122.5 L232.3,126.4 L242.9,132.9 L258.0,136.4 L271.0,141.9 L278.0,139.8 L281.3,140.9 L283.8,144.4 L288.2,145.2 L293.6,144.5 L301.4,139.5 L311.2,138.6 L332.5,127.7 L333.0,138.2 L334.9,143.1 L332.5,144.6 L334.4,148.9 L338.8,150.0 L339.9,154.1 L344.7,158.7 L246.9,158.7 L244.6,159.4 L246.0,163.5 L234.7,163.4 L234.7,149.1 L232.3,149.1 L232.3,146.8 L229.9,146.7 L229.9,144.4 L227.4,142.0 L224.9,142.0 L224.9,139.6 L222.4,139.6 L222.5,137.2 L220.0,137.2 L220.0,134.8 L217.6,134.8 L217.6,132.4 L215.1,132.4 L215.1,130.0 L212.7,130.0 L212.7,124.1 Z M117.9,231.2 L118.0,222.5 L196.1,222.7 L195.2,232.7 L196.6,236.8 L199.5,237.0 L199.0,244.2 L195.7,247.0 L191.0,246.6 L191.5,248.3 L189.3,250.1 L186.5,258.0 L182.7,258.7 L183.4,263.0 L189.2,263.9 L193.3,266.3 L186.9,273.1 L186.6,276.2 L188.5,277.9 L186.5,281.4 L120.4,281.2 L120.4,278.3 L117.9,278.3 L117.9,231.2 Z M438.6,187.8 L440.4,184.3 L443.1,184.2 L444.3,181.8 L447.1,184.2 L448.7,181.3 L447.8,179.3 L450.2,180.3 L449.6,177.7 L454.0,175.3 L456.4,170.1 L458.2,170.4 L458.6,164.4 L460.2,163.7 L458.2,161.5 L459.1,158.9 L461.8,157.5 L461.4,152.1 L463.0,150.0 L456.2,147.8 L453.2,142.7 L454.7,137.6 L452.8,135.0 L453.7,133.0 L452.3,129.0 L454.7,128.7 L459.5,124.0 L479.2,116.7 L483.5,113.1 L484.7,115.6 L487.7,115.7 L489.6,118.8 L493.5,120.3 L496.1,124.4 L498.1,123.9 L503.1,126.7 L502.8,128.6 L504.2,128.4 L503.4,129.7 L505.6,132.6 L508.9,131.5 L508.4,134.6 L512.4,136.6 L512.9,142.8 L518.7,146.8 L516.0,148.5 L518.4,151.0 L517.5,153.2 L510.5,152.7 L512.5,157.3 L507.2,154.8 L502.3,158.1 L503.9,159.1 L502.2,161.2 L503.7,163.0 L501.1,164.3 L503.8,165.5 L498.4,168.9 L499.6,169.8 L497.9,172.0 L500.3,172.5 L497.7,173.8 L496.6,177.9 L498.2,179.0 L496.9,180.6 L498.5,181.5 L496.9,183.6 L498.9,185.4 L497.7,186.3 L496.8,184.7 L496.6,187.8 L495.2,188.6 L496.8,188.9 L496.2,191.6 L497.8,192.2 L495.1,193.7 L496.4,198.3 L498.9,198.3 L496.8,200.3 L504.0,203.1 L503.2,205.2 L505.0,205.7 L503.7,206.9 L505.5,208.0 L504.6,210.0 L507.9,211.4 L505.9,213.6 L506.2,218.4 L504.5,216.6 L501.0,218.1 L500.0,219.4 L501.3,221.3 L474.4,221.2 L475.2,213.5 L470.7,211.2 L469.5,208.2 L465.2,207.4 L457.8,202.2 L444.1,202.4 L440.0,199.9 L440.2,188.0 L438.6,187.8 Z M83.3,224.4 L86.5,219.5 L88.7,206.5 L89.5,182.6 L88.4,179.4 L84.3,179.4 L88.4,176.4 L89.3,171.2 L89.7,161.8 L87.8,154.5 L90.3,150.7 L92.7,126.5 L92.0,114.8 L88.8,108.7 L87.4,108.9 L87.7,107.2 L88.9,105.5 L118.6,105.5 L118.5,107.2 L161.2,106.1 L161.3,117.8 L146.5,117.8 L146.5,122.7 L149.0,122.7 L149.0,125.1 L151.4,125.1 L151.4,127.4 L153.9,127.5 L153.9,129.8 L159.0,129.9 L158.9,132.2 L163.7,132.2 L163.7,134.6 L168.6,134.6 L168.6,137.0 L166.1,137.0 L166.2,139.4 L161.3,139.3 L161.3,144.1 L156.4,144.1 L156.4,146.5 L154.0,146.5 L154.0,148.8 L151.5,148.9 L151.7,153.8 L149.3,153.8 L149.0,161.1 L146.5,161.1 L146.4,163.4 L148.9,163.4 L149.1,199.3 L110.9,199.3 L110.9,222.4 L118.0,222.4 L118.0,227.7 L84.2,227.7 L83.3,224.4 Z M628.6,98.0 L628.9,83.2 L649.7,79.6 L657.0,81.6 L665.3,80.8 L677.1,74.8 L681.8,69.7 L802.0,69.5 L802.6,99.9 L794.0,99.9 L794.0,107.1 L791.4,107.1 L791.4,121.2 L785.4,121.2 L785.5,157.2 L775.8,157.3 L775.8,164.4 L755.7,164.1 L753.6,161.9 L751.2,161.9 L751.2,164.1 L748.3,164.1 L748.4,176.3 L726.4,176.4 L726.4,178.9 L716.3,177.9 L716.4,192.5 L721.2,192.5 L721.3,202.5 L734.3,202.5 L734.1,221.7 L737.6,221.7 L737.6,235.8 L660.9,235.7 L660.9,221.4 L662.9,221.4 L663.0,149.7 L650.8,149.7 L650.7,135.5 L628.6,135.3 L628.6,98.0 Z M716.3,177.9 L726.4,178.9 L726.4,176.4 L748.4,176.3 L748.3,164.1 L751.2,164.1 L751.2,161.9 L753.6,161.9 L755.7,164.1 L775.8,164.4 L775.8,157.3 L785.5,157.2 L785.4,121.2 L791.4,121.2 L791.4,107.1 L794.0,107.1 L794.0,99.9 L802.6,99.9 L802.5,92.7 L829.4,92.6 L829.4,107.1 L824.5,107.1 L824.6,121.0 L827.1,121.0 L827.1,125.9 L829.6,125.8 L829.6,133.1 L831.8,133.0 L831.8,149.9 L836.9,149.9 L837.0,164.2 L839.3,164.2 L839.4,174.6 L841.8,174.7 L841.8,179.4 L849.0,179.2 L849.1,183.8 L851.4,183.8 L851.5,186.1 L853.8,186.1 L853.8,190.9 L856.2,190.8 L856.4,200.4 L861.6,200.4 L861.6,207.5 L886.7,207.5 L886.7,221.8 L851.3,222.0 L851.2,236.3 L825.8,236.4 L823.9,230.8 L822.5,229.7 L821.0,230.8 L818.7,226.0 L815.7,226.1 L814.4,224.2 L810.5,230.1 L803.0,235.8 L794.9,234.4 L786.2,227.3 L783.8,227.7 L780.1,232.5 L777.1,231.9 L773.8,233.9 L771.7,241.6 L763.7,241.6 L756.5,236.4 L753.2,237.8 L752.9,239.7 L751.2,239.0 L747.4,241.3 L746.2,236.7 L737.6,235.8 L737.6,221.7 L734.1,221.7 L734.3,202.5 L721.3,202.5 L721.2,192.5 L716.4,192.1 L716.3,177.9 Z M802.0,69.5 L928.4,70.4 L933.1,77.2 L935.0,85.0 L942.6,93.1 L944.2,98.5 L946.9,100.1 L952.7,98.4 L958.2,105.7 L966.8,106.3 L972.3,110.8 L973.6,120.7 L979.3,127.6 L982.2,135.4 L979.9,139.6 L974.5,143.9 L971.0,151.8 L971.3,158.5 L967.4,161.8 L966.3,166.8 L957.2,181.9 L957.1,189.4 L953.7,195.3 L950.5,211.6 L945.2,217.6 L944.1,222.1 L886.7,221.8 L886.7,207.5 L861.6,207.5 L861.6,200.4 L856.4,200.4 L856.2,190.8 L853.8,190.9 L853.8,186.1 L851.5,186.1 L851.4,183.8 L849.1,183.8 L849.0,179.2 L841.8,179.4 L841.8,174.7 L839.4,174.6 L839.3,164.2 L837.0,164.2 L836.9,149.9 L831.8,149.9 L831.8,133.0 L829.6,133.1 L829.6,125.8 L827.1,125.9 L827.1,121.0 L824.6,121.0 L824.5,107.1 L829.4,107.1 L829.4,92.6 L802.0,92.7 L802.0,69.5 Z M346.4,233.2 L349.3,232.5 L349.6,228.9 L356.9,228.9 L356.3,227.6 L360.0,224.2 L363.9,224.1 L364.6,218.2 L362.9,215.2 L359.5,215.7 L353.2,203.4 L353.4,201.0 L361.0,197.2 L361.2,193.6 L359.4,192.4 L384.9,192.4 L384.9,149.1 L389.8,149.2 L389.8,119.7 L394.5,120.5 L402.1,118.5 L416.6,124.0 L420.4,134.8 L426.6,134.2 L432.2,127.9 L434.6,127.1 L444.2,127.8 L448.9,126.5 L452.3,129.0 L453.6,132.3 L452.8,135.0 L454.7,137.6 L453.1,142.3 L454.4,145.1 L456.2,147.8 L463.0,150.0 L461.4,152.1 L461.8,157.5 L459.1,158.9 L458.2,161.5 L460.2,163.7 L458.6,164.4 L458.1,170.7 L456.4,170.1 L454.0,175.3 L449.6,177.7 L450.2,180.3 L447.8,179.3 L448.7,181.3 L447.1,184.2 L444.3,181.8 L443.1,184.2 L440.4,184.3 L438.6,187.8 L440.2,188.4 L439.4,198.9 L444.1,202.4 L457.8,202.2 L465.2,207.4 L469.5,208.2 L470.7,211.2 L475.2,213.5 L474.4,221.2 L501.3,221.3 L503.9,225.8 L503.3,234.6 L504.5,240.5 L503.1,243.2 L505.0,245.8 L504.9,250.3 L507.6,250.2 L509.4,252.6 L506.6,255.9 L512.2,259.5 L513.6,263.2 L517.1,264.6 L356.0,264.0 L352.7,263.2 L354.0,260.3 L352.7,258.0 L357.2,250.6 L353.3,249.2 L351.3,244.7 L347.6,245.7 L348.8,243.3 L346.7,238.9 L346.4,233.2 Z M146.5,161.1 L149.0,161.1 L149.3,153.8 L151.7,153.8 L151.5,148.9 L154.0,148.8 L154.0,146.5 L156.4,146.5 L156.4,144.1 L161.3,144.1 L161.3,139.3 L166.2,139.4 L166.1,137.0 L168.6,137.0 L168.6,134.6 L163.7,134.6 L163.7,132.2 L158.9,132.2 L159.0,129.9 L153.9,129.8 L153.9,127.5 L151.4,127.4 L151.4,125.1 L149.0,125.1 L149.0,122.7 L146.5,122.7 L146.5,117.8 L161.3,117.8 L161.2,106.1 L200.6,106.2 L200.5,110.8 L205.4,110.9 L205.4,113.2 L212.7,113.4 L212.7,130.0 L215.1,130.0 L215.1,132.4 L217.6,132.4 L217.6,134.8 L220.0,134.8 L220.0,137.2 L222.5,137.2 L222.4,139.6 L224.9,139.6 L224.9,142.0 L227.4,142.0 L229.9,144.4 L229.9,146.7 L232.3,146.8 L232.3,149.1 L234.7,149.1 L234.7,180.2 L227.4,180.2 L227.2,177.8 L222.5,177.9 L222.5,182.6 L215.1,182.6 L215.1,177.8 L207.8,177.8 L207.8,175.4 L205.3,175.4 L205.3,173.0 L202.8,172.8 L202.9,170.4 L200.4,170.4 L200.4,168.1 L190.6,168.2 L190.6,165.8 L188.2,165.8 L188.1,163.4 L146.4,163.4 L146.5,161.1 Z M502.4,223.8 L586.2,223.9 L586.1,236.0 L600.3,235.9 L600.4,264.3 L602.7,264.3 L602.3,349.7 L573.3,349.8 L573.3,336.1 L558.8,336.1 L558.7,327.9 L515.3,328.4 L515.4,274.6 L513.1,269.1 L514.2,267.5 L515.5,268.8 L517.1,264.6 L513.5,263.1 L512.0,259.4 L507.1,257.3 L506.7,254.7 L509.4,252.6 L507.6,250.2 L504.9,250.3 L505.0,245.8 L503.1,243.2 L504.5,238.1 L503.3,234.6 L503.9,225.8 L502.4,223.8 Z M110.8,207.5 L110.9,199.3 L149.1,199.3 L148.9,163.4 L188.1,163.4 L188.2,165.8 L190.6,165.8 L190.6,168.2 L200.4,168.1 L200.4,170.4 L202.9,170.4 L202.8,172.8 L205.3,173.0 L205.3,175.4 L207.8,175.4 L207.8,177.8 L215.1,177.8 L215.1,182.6 L220.0,182.6 L219.9,192.1 L222.1,192.1 L216.2,192.6 L214.4,190.9 L210.2,190.7 L208.1,187.9 L204.7,191.3 L204.3,198.0 L199.9,198.3 L198.2,200.2 L199.0,202.1 L201.8,202.0 L204.1,207.6 L200.9,208.4 L200.3,210.1 L204.6,215.7 L196.1,222.7 L110.9,222.4 L110.8,207.5 Z" class="preview-grid" />
            <path d="M323.0,464.0 L323.2,462.3 L327.4,462.2 L324.8,457.8 L327.2,449.7 L325.5,443.1 L327.9,439.6 L326.2,424.1 L331.8,415.6 L338.8,415.1 L340.0,406.9 L342.7,405.3 L341.7,404.5 L343.7,402.4 L344.4,398.5 L343.0,394.0 L346.8,391.8 L350.7,383.8 L349.0,376.0 L350.4,372.8 L348.8,366.2 L349.7,363.9 L348.3,359.3 L344.8,357.2 L344.0,353.7 L342.1,353.3 L341.9,335.6 L429.5,335.9 L430.0,377.7 L443.8,378.4 L443.9,407.0 L472.2,407.6 L472.3,421.8 L516.2,421.6 L516.3,436.0 L530.5,436.1 L530.6,450.4 L573.5,450.5 L573.6,464.9 L323.0,464.0 Z" class="preview-selected" />
          </svg>
        </div>
      </div>
      <div class="mode-switch-row" role="group" aria-label="Game mode">
        <button type="button" class="mode-switch" data-mode="city-county" aria-pressed="true">City/County</button>
        <button type="button" class="mode-switch" data-mode="cities" aria-pressed="false">City</button>
        <button type="button" class="mode-switch" data-mode="name-the-county" aria-pressed="false">County</button>
      </div>
      <div class="btn-row">
        <button type="button" class="btn-primary btn-big play-today" id="btn-play-today">Play Today's Game</button>
      </div>
    </div>

    <div class="card">
      <h2>Game # — same Game #, same game</h2>
      <label class="field-label" for="seed-input">Game #</label>
      <div class="seed-row">
        <input type="text" id="seed-input" autocomplete="off" spellcheck="false" maxlength="20" size="11" />
        <button type="button" class="icon-btn" id="btn-daily-seed" aria-label="Use today's game number">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="2" /><line x1="3" y1="10" x2="21" y2="10" stroke="currentColor" stroke-width="2" /><line x1="8" y1="3" x2="8" y2="7" stroke="currentColor" stroke-width="2" /><line x1="16" y1="3" x2="16" y2="7" stroke="currentColor" stroke-width="2" /></svg>
        </button>
        <button type="button" class="icon-btn" id="btn-random-seed" aria-label="Random game number">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="4" fill="none" stroke="currentColor" stroke-width="2" /><circle cx="8" cy="8" r="1.8" fill="currentColor" /><circle cx="16" cy="8" r="1.8" fill="currentColor" /><circle cx="12" cy="12" r="1.8" fill="currentColor" /><circle cx="8" cy="16" r="1.8" fill="currentColor" /><circle cx="16" cy="16" r="1.8" fill="currentColor" /></svg>
        </button>
      </div>
      <p class="muted small" style="margin-top:12px" id="seed-hint">Same Game # = same 10 cities, in the same order, for anyone, any time.
        Share the Game # (or the game link) to play the same game as another player.</p>
    </div>

    <div class="card">
      <button type="button" class="section-toggle" id="btn-how-to-play" aria-expanded="false" aria-controls="how-to-play">▸ How to play</button>
      <div id="how-to-play" hidden>
        <div class="mode-instructions" id="mode-instructions"></div>
        <div class="mode-lines" id="game-lines"></div>
      </div>
    </div>

    <div class="card">
      <button type="button" class="section-toggle" id="btn-advanced" aria-expanded="false" aria-controls="advanced-options">▸ Advanced options</button>
      <div id="advanced-options" hidden>
        <h2>Map landmarks</h2>
      <div class="toggle-row" role="group" aria-label="Map layers">
        <button type="button" class="toggle" data-layer="interstate" aria-pressed="true"><span class="swatch"></span>Interstates</button>
        <button type="button" class="toggle" data-layer="highway" aria-pressed="true"><span class="swatch"></span>Highways</button>
        <button type="button" class="toggle" data-layer="river" aria-pressed="true"><span class="swatch"></span>Rivers</button>
        <button type="button" class="toggle" data-layer="lake" aria-pressed="true"><span class="swatch fill"></span>Lakes</button>
      </div>
      <p class="muted small" style="margin-top:12px">Landmarks are for orientation only — they don&rsquo;t affect scoring. Your choices stay in effect during play.</p>
      <h2>City &amp; County List</h2>
      <div class="mode-switch-row" role="group" aria-label="City and county list">
        <button type="button" class="mode-switch" data-edition="risk-pool" aria-pressed="true">Risk Pool</button>
        <button type="button" class="mode-switch" data-edition="all" aria-pressed="false">All</button>
      </div>
      <p class="muted small" style="margin-top:12px" id="edition-hint">Risk Pool limits the game to the risk pool&rsquo;s 236 cities and 28 counties. All uses the full list of 241 cities and 36 counties.</p>
      </div>
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
      <p class="score-line">Score: <span id="running-total">0</span> / <span id="running-max">1000</span> &nbsp;&middot;&nbsp; Game #: <span id="game-seed-label"></span></p>
    </div>

    <div class="map-card">
      <div class="game-controls">
        <div class="btn-row" id="guess-controls">
          <button type="button" class="btn-primary" id="btn-confirm" disabled>Confirm guess</button>
          <button type="button" id="btn-pass">Pass (0 points)</button>
        </div>
        <div class="btn-row" id="reveal-controls" hidden>
          <button type="button" class="btn-primary" id="btn-next">Next city</button>
        </div>
        <p class="controls-hint" id="hint-text">Tap the map to drop a pin. Tap again (or drag) to move it, then confirm.</p>
        <p class="reveal-line" id="reveal-line" hidden></p>
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
        <button type="button" id="btn-reset-view" hidden aria-label="Reset map view to the full state">Reset view</button>
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
      <p class="muted small" id="share-note">Anyone opening this link with the same Game # gets the same 10 cities in the same order.</p>
      <div class="summary-row">
        <div class="summary-box" id="summary-text"></div>
        <button type="button" id="btn-copy-summary">Copy</button>
      </div>
      <!-- Always rendered: visibility toggles, so showing "Copied!" never
           moves anything on the screen. -->
      <p class="copied" id="copy-note" style="visibility:hidden">Copied!</p>
      <div class="btn-row">
        <button type="button" class="btn-primary" id="btn-again">Play again (new game)</button>
      </div>
    </div>

    <div class="btn-row">
      <button type="button" id="btn-back-select">Back to game selection</button>
    </div>
  </section>

  <footer>
    Projection: equirectangular with cos(44&deg;) correction. Bounds lon &minus;124.716 to &minus;116.314,
    lat 41.843 to 46.421, viewBox <code>0 0 1000 757.4</code>. One function projects lon/lat &rarr; x/y for drawing;
    its exact inverse converts taps back. Distances use the Haversine formula (Earth radius 3,959 miles).
    Scoring: <code>100 if rounded miles &le; 5, else max(0, 100 &minus; (rounded miles &minus; 5))</code>.
    Counties mode scores by overlap: the percentage of the real county covered by the placed piece
    (100 for a perfect fit), sampled on a 4-unit grid in map units. County mode: 100 points
    for naming the right county, 50 for a county that touches it, 0 for any other county or a pass —
    1,000 points maximum.<br />
    Game # shuffle: this web version hashes the Game # with SHA-256 (WebCrypto) and uses the first 4 bytes as a
    signed 32-bit integer to drive a mulberry32 PRNG through a Fisher&ndash;Yates shuffle of the 241-city pool
    (or the 36-county pool in either county mode) — or, in the Risk Pool edition (the default), the 236-city
    and 28-county risk pool (see the edition option in Advanced options; the pool is filtered before the
    shuffle, so the same Game # picks different questions in the two editions).
    The Blazor C# version (spec &sect;5) uses the same SHA-256 hash with <code>System.Random(seedInt)</code>
    instead of mulberry32, so the 10 cities picked for a given Game # may differ between the JavaScript and C#
    versions — but the format, scoring, and projection are the same.<br />
    Map data: state outline &copy; U.S. Census Bureau (public domain); interstates, highways, rivers and lakes
    from Natural Earth (public domain). City coordinates for the 241 incorporated Oregon cities via OpenStreetMap / Nominatim.<br />
    Version 0.34.
  </footer>
</div>

<script type="application/json" id="data-cities">__CITIES__</script>
<script type="application/json" id="data-outline">__OUTLINE__</script>
<script type="application/json" id="data-landmarks">__LANDMARKS__</script>
<script type="application/json" id="data-counties">__COUNTIES__</script>
<script type="application/json" id="data-usa-states">__USA_STATES__</script>
<script type="application/json" id="data-risk-pool">__RISK_POOL__</script>

<script>
(function () {
  "use strict";
__PURE_JS__

  /* ============ Data & map drawing ============ */
  var cities = JSON.parse(document.getElementById("data-cities").textContent);
  var outline = JSON.parse(document.getElementById("data-outline").textContent);
  var landmarks = JSON.parse(document.getElementById("data-landmarks").textContent);
  var counties = JSON.parse(document.getElementById("data-counties").textContent);
  var usaStates = JSON.parse(document.getElementById("data-usa-states").textContent);
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

  /* ============ Edition: Risk Pool vs All (see GAME-SPEC §4.6) ============
     The edition limits the pool the game draws from. Risk Pool (the
     default) draws only from the risk pool's 236 cities and 28 counties;
     All draws from the full 241 cities and 36 counties. The filter
     applies BEFORE the seeded shuffle, so the same Game # picks different
     questions in the two editions. The edition is carried in the share
     link as ?list=all (All only — Risk Pool, the default, has no
     parameter), and read back on load. */
  var riskPoolData = JSON.parse(document.getElementById("data-risk-pool").textContent);
  var riskPoolCityNames = {};
  riskPoolData.cities.forEach(function (n) { riskPoolCityNames[n] = true; });
  var riskPoolCountyNames = {};
  riskPoolData.counties.forEach(function (n) { riskPoolCountyNames[n] = true; });
  var riskPoolCities = cities.filter(function (c) { return riskPoolCityNames[c.name]; });
  var riskPoolCounties = counties.features.filter(function (f) { return riskPoolCountyNames[f.properties.name]; });
  var currentEdition = "risk-pool";
  (function () {
    try {
      if (new URLSearchParams(window.location.search).get("list") === "all") currentEdition = "all";
    } catch (e) {}
  })();
  function editionPools() {
    return currentEdition === "all"
      ? { cities: cities, counties: counties.features }
      : { cities: riskPoolCities, counties: riskPoolCounties };
  }
  function editionLabel(edition) { return edition === "all" ? "All Edition" : "Risk Pool Edition"; }
  var editionBadge = document.getElementById("edition-badge");
  function updateEditionBadge(which) {
    /* The badge names the edition being played, directly beneath the
       header. It shows on the start, game and results screens when the
       edition is Risk Pool, and never on the splash page or in the All
       edition. */
    if (!editionBadge) return;
    editionBadge.hidden = which === "splash" || currentEdition !== "risk-pool";
  }
  function setEdition(edition) {
    currentEdition = edition;
    document.querySelectorAll(".mode-switch[data-edition]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", String(btn.getAttribute("data-edition") === edition));
    });
    /* The buttons live on the start screen, where the badge shows iff
       the edition is Risk Pool. */
    if (editionBadge) editionBadge.hidden = edition !== "risk-pool";
  }
  document.querySelectorAll(".mode-switch[data-edition]").forEach(function (btn) {
    btn.addEventListener("click", function () { setEdition(btn.getAttribute("data-edition")); });
  });
  /* Sync the buttons with the edition the URL asked for (?list=all). */
  document.querySelectorAll(".mode-switch[data-edition]").forEach(function (btn) {
    btn.setAttribute("aria-pressed", String(btn.getAttribute("data-edition") === currentEdition));
  });

  /* ============ Screens ============ */
  var screenSplash = document.getElementById("screen-splash");
  var screenStart = document.getElementById("screen-start");
  var screenGame = document.getElementById("screen-game");
  var screenResults = document.getElementById("screen-results");
  function showScreen(which) {
    screenSplash.hidden = which !== "splash";
    screenStart.hidden = which !== "start";
    screenGame.hidden = which !== "game";
    screenResults.hidden = which !== "results";
    /* The splash page is the product name; once a game starts, the
       header is the in-game title — and it stays that way on the
       results screen. The start screen shows the state title too,
       because this file is the Oregon edition (the state is known);
       the browser tab follows the same rule. In the Blazor app the
       start title is state-specific only when the URL named the state. */
    var title = which === "splash" ? "Where in the State" : "Where in the " + STATE_NAME + "?!";
    document.getElementById("game-title-text").textContent = title;
    document.title = title;
    updateEditionBadge(which);
    window.scrollTo(0, 0);
  }

  /* ============ Splash / welcome page ============
     The USA map: one path per state, from the embedded usa-states
     GeoJSON. Projection is equirectangular with a cos(37 deg)
     correction (the USA's mid-latitude), the same idea as the game
     map's cos(44 deg) correction; the bounds come from the data, so
     the map always fits the viewBox. Alaska and Hawaii are already in
     their inset positions in the data. Unavailable states get the
     diagonal hatch fill; Oregon is soft green, and fills solid green
     when selected. Clicking Oregon toggles the selection and enables
     the Play Oregon button; clicking another state only shows the
     coming-soon hint. */
  var usaSvg = document.getElementById("usa-map");
  var splashHint = document.getElementById("splash-hint");
  var btnPlayOregon = document.getElementById("btn-play-oregon");
  var oregonSelected = false;
  function usaProject(lon, lat, b) {
    var cos37 = Math.cos(37 * Math.PI / 180);
    var scale = 1000 / ((b.lonMax - b.lonMin) * cos37);
    return [(lon - b.lonMin) * cos37 * scale, (b.latMax - lat) * scale];
  }
  function usaStatePath(feature, b) {
    var d = "";
    function ringToPath(ring) {
      var s = "";
      for (var i = 0; i < ring.length; i++) {
        var p = usaProject(ring[i][0], ring[i][1], b);
        s += (i === 0 ? "M" : "L") + fmt(p[0]) + "," + fmt(p[1]);
      }
      return s + "Z";
    }
    var geom = feature.geometry;
    if (!geom) return "";
    if (geom.type === "Polygon") {
      for (var i = 0; i < geom.coordinates.length; i++) d += ringToPath(geom.coordinates[i]);
    } else if (geom.type === "MultiPolygon") {
      for (var p = 0; p < geom.coordinates.length; p++)
        for (var r = 0; r < geom.coordinates[p].length; r++) d += ringToPath(geom.coordinates[p][r]);
    }
    return d;
  }
  function buildUsaMap() {
    if (!usaSvg || !usaStates || !usaStates.features) return;
    /* Bounds from the data (display lon/lat, insets included). */
    var b = { lonMin: Infinity, lonMax: -Infinity, latMin: Infinity, latMax: -Infinity };
    usaStates.features.forEach(function (f) {
      function walk(c) {
        if (typeof c[0] === "number") {
          if (c[0] < b.lonMin) b.lonMin = c[0];
          if (c[0] > b.lonMax) b.lonMax = c[0];
          if (c[1] < b.latMin) b.latMin = c[1];
          if (c[1] > b.latMax) b.latMax = c[1];
        } else {
          for (var i = 0; i < c.length; i++) walk(c[i]);
        }
      }
      if (f.geometry) walk(f.geometry.coordinates);
    });
    var cos37 = Math.cos(37 * Math.PI / 180);
    var scale = 1000 / ((b.lonMax - b.lonMin) * cos37);
    var height = (b.latMax - b.latMin) * scale;
    usaSvg.setAttribute("viewBox", "0 0 1000 " + fmt(height));
    /* Oregon renders last, so its border stroke is painted on top of
       the neighbouring states' fills. (The features arrive
       name-sorted, so Washington — drawn after Oregon — used to cover
       the outer half of Oregon's north-edge stroke with its hatch
       fill, which is why that edge looked lighter than the rest.) */
    var ordered = usaStates.features.slice().sort(function (a, b) {
      return (a.properties.available ? 1 : 0) - (b.properties.available ? 1 : 0);
    });
    ordered.forEach(function (f) {
      var name = f.properties.name;
      var available = !!f.properties.available;
      var path = document.createElementNS(SVGNS, "path");
      path.setAttribute("d", usaStatePath(f, b));
      path.setAttribute("class", "usa-state " + (available ? "usa-available" : "usa-unavailable"));
      path.setAttribute("data-state", name);
      var title = document.createElementNS(SVGNS, "title");
      title.textContent = name + (available ? " — ready to play" : " — coming soon");
      path.appendChild(title);
      path.addEventListener("click", function () { onUsaStateClicked(f, path); });
      usaSvg.appendChild(path);
    });
  }
  function onUsaStateClicked(feature, path) {
    var name = feature.properties.name;
    if (!feature.properties.available) {
      /* An unavailable state never becomes the selection — just a
         quiet one-line hint under the map, no popup or new card. */
      oregonSelected = false;
      btnPlayOregon.disabled = true;
      var sel = usaSvg.querySelector(".usa-selected");
      if (sel) sel.classList.remove("usa-selected");
      splashHint.textContent = name + " isn't ready yet — Oregon is the first state.";
      return;
    }
    /* Oregon toggles: click again to deselect. */
    oregonSelected = !oregonSelected;
    path.classList.toggle("usa-selected", oregonSelected);
    btnPlayOregon.disabled = !oregonSelected;
    splashHint.textContent = oregonSelected
      ? "Oregon selected — ready when you are!"
      : "Oregon is ready to play — click it on the map.";
  }
  btnPlayOregon.addEventListener("click", function () {
    if (!oregonSelected) return;
    showScreen("start");
  });
  buildUsaMap();

  /* ============ Start screen ============ */
  var seedInput = document.getElementById("seed-input");
  /* Parse the game URL from the path: /{state}/{mode}/{seed}, e.g.
     /oregon/cities/2026-11-06. This file is served from any path in
     the test-page preview, so match the pattern at the END of the path:
     the last segments must be a known state id, a mode slug, and a seed.
     /{state}/{mode} (no seed) preselects the mode. Anything else shows
     the start screen with the defaults rather than failing. */
  function parseGameUrl() {
    var segs;
    try {
      segs = window.location.pathname.split("/").filter(function (s) { return s.length > 0; });
    } catch (e) { return {}; }
    function decode(s) {
      try { return decodeURIComponent(s); } catch (e) { return s; }
    }
    /* The mode slugs, kept local: this runs before the MODES list below
       is initialized, so it cannot read that variable. */
    var validModes = ["city-county", "cities", "counties", "name-the-county"];
    var n = segs.length;
    if (n >= 3 && decode(segs[n - 3]).toLowerCase() === "oregon"
        && validModes.indexOf(decode(segs[n - 2]).toLowerCase()) >= 0
        && decode(segs[n - 1]).length > 0) {
      return { state: "oregon", mode: decode(segs[n - 2]).toLowerCase(), seed: decode(segs[n - 1]) };
    }
    if (n >= 2 && decode(segs[n - 2]).toLowerCase() === "oregon"
        && validModes.indexOf(decode(segs[n - 1]).toLowerCase()) >= 0) {
      return { state: "oregon", mode: decode(segs[n - 1]).toLowerCase() };
    }
    return {};
  }
  var urlGame = parseGameUrl();
  var urlSeed = urlGame.seed;
  seedInput.value = (urlSeed && urlSeed.trim()) ? urlSeed.trim().toUpperCase() : dailySeed();
  /* The main Play button's label is dynamic: it reads "Play Today's Game"
     when the box holds today's daily seed, and just "Play" for any other
     seed (or an empty box). It is refreshed on every change to the box —
     typing, the calendar button, or the dice button — so the label always
     matches what is in the box. */
  var playTodayBtn = document.getElementById("btn-play-today");
  function updatePlayLabel() {
    playTodayBtn.textContent = (seedInput.value === dailySeed()) ? "Play Today's Game" : "Play";
  }
  updatePlayLabel();
  /* Force seeds to upper case as the player types, so the box always
     shows the canonical form. The cursor is kept where it was. */
  seedInput.addEventListener("input", function () {
    var start = seedInput.selectionStart, end = seedInput.selectionEnd;
    var upper = seedInput.value.toUpperCase();
    if (upper !== seedInput.value) {
      seedInput.value = upper;
      seedInput.setSelectionRange(start, end);
    }
    updatePlayLabel();
  });
  document.getElementById("btn-random-seed").addEventListener("click", function () {
    seedInput.value = randomSeed();
    updatePlayLabel();
    seedInput.focus();
  });
  document.getElementById("btn-daily-seed").addEventListener("click", function () {
    seedInput.value = dailySeed();
    updatePlayLabel();
    seedInput.focus();
  });

  /* ============ Game mode (City County / Cities / Name the county) ============
     The picker on the start screen: one big preview image plus three small
     mode-switch buttons (the Counties drag mode is hidden from the picker,
     but its copy and game logic stay for direct /oregon/counties/ links).
     The lede, seed hint, game line and how-it-works steps all change with
     the mode, like the Blazor start screen. A shared link carries the mode
     as a path segment: /oregon/city-county/<seed> (or counties, or
     name-the-county). */
  var MODE_COPY = {
    "city-county": {
      lede: "A mix of both: 7 city rounds and 3 county rounds, shuffled together. City rounds: drop a pin where you think the city is. County rounds: click the county on the map. 100 points per question — full points for a pin within 5 miles, 100 for naming the right county, 50 for a county that touches it. 10 questions per game.",
      seedHint: "Same Game # = same 7 cities and 3 counties, in the same order, for anyone, any time. Share the Game # (or the game link) to play the same game as another player.",
      gameLine: "Seven city questions and three county questions, 100 points per question, 1,000 points maximum.",
      steps: [
        ["Pick a Game #", "Same Game #, same 7 cities and 3 counties — share it to play together."],
        ["Drop a pin or pick the county", "City rounds: tap the map where you think the city is. County rounds: click the county that matches the name."],
        ["See how close", "The real spot or county is revealed, with your distance or pick and your points."]
      ]
    },
    cities: {
      lede: "Ten Oregon cities, one blank map. Tap where you think each city is — the closer your pin, the more points. Full points within 5 miles, then −1 point per mile beyond that.",
      seedHint: "Same Game # = same 10 cities, in the same order, for anyone, any time. Share the Game # (or the game link) to play the same game as another player.",
      gameLine: "One pin per city, 100 points per question, 1,000 points maximum.",
      steps: [
        ["Pick a Game #", "Same Game #, same 10 cities — share it to play together."],
        ["Drop a pin", "Tap the map where you think the city is, then confirm."],
        ["See how close", "The real spot is revealed, with your distance and points."]
      ]
    },
    counties: {
      lede: "A blank map of Oregon — outline and landmarks, but no county lines. Each round names one county; drag its shape onto the map where you think it belongs. 100 points for a perfect fit, scaled by how much of the real county you cover. 10 questions per game.",
      seedHint: "Same Game # = same 10 counties, in the same order, for anyone, any time. Share the Game # (or the game link) to play the same game as another player.",
      gameLine: "One county per question, 100 points per question, 1,000 points maximum.",
      steps: [
        ["Pick a Game #", "Same Game #, same 10 counties — share it to play together."],
        ["Drag the piece", "Drag the county's shape onto the map where it belongs, then confirm."],
        ["See the overlap", "The real county is revealed, with how much of it you covered and your points."]
      ]
    },
    "name-the-county": {
      lede: "A map of Oregon with every county outlined, but no county names. Each round names one county; click the county you think it is. 100 points for naming the right county, 50 for a county that touches it, 0 for any other. 10 questions per game.",
      seedHint: "Same Game # = same 10 counties, in the same order, for anyone, any time. Share the Game # (or the game link) to play the same game as another player.",
      gameLine: "One county per question, 100 points per correct answer, 50 for a neighboring county, 1,000 points maximum.",
      steps: [
        ["Pick a Game #", "Same Game #, same 10 counties — share it to play together."],
        ["Pick the county", "Click the county on the map that matches the name, then confirm."],
        ["See if you were right", "The real county is revealed, with what you picked and your points."]
      ]
    }
  };
  /* The selected mode, kept in a variable: the mode buttons are plain
     buttons, not radios, so there is no :checked state to read. Clicking a
     button selects the mode (it does not start the game — Start still does
     that); the selected button is marked aria-pressed, and the big preview
     image above the buttons switches to that mode's artwork. The default
     mode is City County Mode. */
  var currentMode = "city-county";
  function selectedMode() { return currentMode; }
  function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll(".mode-switch").forEach(function (btn) {
      btn.setAttribute("aria-pressed", String(btn.getAttribute("data-mode") === mode));
    });
    document.querySelectorAll(".mode-preview-set").forEach(function (set) {
      var active = set.getAttribute("data-mode") === mode;
      set.classList.toggle("is-active", active);
      set.setAttribute("aria-hidden", String(!active));
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
  document.querySelectorAll(".mode-switch").forEach(function (btn) {
    btn.addEventListener("click", function () { setMode(btn.getAttribute("data-mode")); });
  });
  /* The county modes are only offered when the pack has counties; this file
     always does (36), but the guard mirrors the Blazor disabled handling. */
  if (!counties || !counties.features || counties.features.length === 0) {
    document.querySelectorAll('.mode-switch[data-mode="city-county"], .mode-switch[data-mode="name-the-county"]').forEach(function (btn) {
      btn.disabled = true;
    });
  }
  /* The mode from the game URL (/oregon/<mode>/...) preselects the mode
     on the start screen; anything else leaves the default (City County Mode). */
  if (urlGame.mode) {
    setMode(urlGame.mode);
  }
  updateModeUI();

  /* ============ Game state ============ */
  var QUESTION_COUNT = 10;
  /* The state name, used to build the in-game title ("Where in the Oregon?!").
     A single constant keeps the generic-derivation principle: a future
     parameterized build only has to change this one value. */
  var STATE_NAME = "Oregon";
  /* The first screen: a game URL (/oregon/<mode>/<seed>) goes straight
     to the prefilled start screen, like the Blazor app; anything else
     lands on the splash/welcome page. This must run after STATE_NAME is
     assigned, because showScreen builds the start-screen title from it
     ("Where in the Oregon?!") — calling it earlier would show
     "Where in the undefined?!". */
  showScreen(urlGame.mode || urlGame.seed ? "start" : "splash");
  /* The shareable destination is always the live site, never this page's
     own address — in the test-page preview the origin is the preview host,
     which is not a shareable game link. */
  var LIVE_SITE_BASE = "https://matt-lane.github.io/where-in-the-state/";
  function gameLink() {
    /* The shareable game link: /oregon/{mode}/{seed}, plus ?list=all
       when the edition is All. The Risk Pool edition (the default)
       carries no parameter, so its URLs stay exactly as before. The
       same seed with a different edition picks different questions, so
       the link must carry the edition to reproduce the same game. */
    return LIVE_SITE_BASE + "oregon/" + game.mode + "/" + encodeURIComponent(game.seed) + (game.edition === "all" ? "?list=all" : "");
  }
  var game = null; /* { seed, mode, cities, counties, rounds (city-county only), roundIndex, results, total } */
  var guess = null; /* { lat, lon, x, y } */
  var phase = "guess"; /* "guess" | "revealed" | "results" */

  /* ============ Analytics (PostHog) — see GAME-SPEC §13 ============ */
  /* captureEvent is the only way the game talks to PostHog. It is fully
     guarded: if an ad blocker stops the library loading, or the network
     is down, the call is a no-op and the game plays exactly the same.
     It never throws. The PostHog snippet in <head> defines
     window.posthog as a queuing stub, so calls made before array.js
     loads are queued, not dropped. */
  function captureEvent(name, props) {
    try {
      if (window.posthog && typeof window.posthog.capture === "function") {
        window.posthog.capture(name, props || {});
      }
    } catch (e) { /* Analytics must never break the game. */ }
  }
  /* Common properties for every game event. */
  function baseProps() {
    return { state: STATE_NAME.toLowerCase(), mode: game.mode, edition: game.edition, seed: game.seed };
  }
  /* A round was revealed (confirmed or passed). `extra` holds the
     round-type properties; the common fields are added here. */
  function trackRoundCompleted(extra) {
    var props = baseProps();
    props.round = game.roundIndex + 1;
    for (var k in extra) props[k] = extra[k];
    captureEvent("round_completed", props);
  }
  /* Best-effort game_abandoned: if the player leaves the page (tab
     close, refresh, navigating to another site) while a game is in
     progress — phase "guess" or "revealed" — report how far they got.
     Once the results screen is reached, phase is "results", so leaving
     a finished game is not an abandonment. */
  window.addEventListener("pagehide", function () {
    try {
      if (game && (phase === "guess" || phase === "revealed")) {
        var props = baseProps();
        props.rounds_completed = game.results.length;
        props.score_so_far = game.total;
        captureEvent("game_abandoned", props);
      }
    } catch (e) { /* Analytics must never break the game. */ }
  });
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
  var btnResetView = document.getElementById("btn-reset-view");

  /* The live map viewport (pinch-to-zoom / pan) — see the vb* helpers
     above. The SVG's viewBox attribute is bound to it. Gestures write
     to vbTarget; the displayed vb eases toward it once per animation
     frame (see viewportFrame), so viewBox updates land on the display
     refresh and finger micro-jitter is filtered out. */
  var vb = vbFull();
  var vbTarget = vbFull();
  var vbFramePending = false;
  function scheduleViewportFrame() {
    if (vbFramePending) return;
    vbFramePending = true;
    requestAnimationFrame(viewportFrame);
  }
  function viewportFrame() {
    vbFramePending = false;
    if (vbStepTowards(vb, vbTarget)) {
      setViewBoxAttr();
      updateResetBtn();
      repositionActiveBubble();
    }
    if (!vbIsSettled(vb, vbTarget)) scheduleViewportFrame();
  }
  /* Keep the Confirm bubble with the pin / selected county / piece, or
     hide it while it is outside the visible window. Called from the
     animation-frame loop, so the bubble tracks the displayed viewBox. */
  function repositionActiveBubble() {
    if (guess) positionBubble(guess.x, guess.y);
    else if (selectedCounty) updateSelectedBubble();
    else if (countyDragged) updatePieceBubble();
  }
  function setViewBoxAttr() {
    svg.setAttribute("viewBox", vb.x.toFixed(1) + " " + vb.y.toFixed(1) + " " + vb.w.toFixed(1) + " " + vb.h.toFixed(1));
  }
  function updateResetBtn() { btnResetView.hidden = !(vbIsZoomed(vb) || vbIsZoomed(vbTarget)); }
  function resetView() { vb = vbFull(); vbTarget = vbFull(); setViewBoxAttr(); updateResetBtn(); }
  btnResetView.addEventListener("click", resetView);

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
     instead, which is the piece while dragging, not the map. Converts
     with the CURRENT viewport (zoomed and panned), never the full map. */
  function clientToSvg(clientX, clientY) {
    var rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return vbClientToSvg(vb, rect, clientX, clientY);
  }
  /* Position the Confirm bubble for an SVG point, in percentages of the
     map frame — the frame is exactly the SVG's box, so it tracks the
     point at any zoom or pan. Hidden while the point is outside the
     visible window (the controls-row Confirm is the fallback then). */
  function positionBubble(x, y) {
    if (!vbContains(vb, x, y)) { pinConfirm.hidden = true; return; }
    var pct = vbToPercent(vb, x, y);
    pinConfirm.style.left = pct.left.toFixed(2) + "%";
    pinConfirm.style.top = Math.min(96, Math.max(4, pct.top)).toFixed(2) + "%";
    pinConfirm.classList.toggle("flipped", (x - vb.x) > vb.w * 0.75);
    pinConfirm.hidden = false;
  }
  /* The small Confirm bubble next to the piece once it has been dragged,
     like the pin's bubble in the city game: centred on the piece's
     bounding box, flipped to the piece's left near the right edge. */
  function updatePieceBubble() {
    if (!countyRings) return;
    var b = ringsBbox(countyRings);
    var cx = (b.minX + b.maxX) / 2 + pieceDx;
    var cy = (b.minY + b.maxY) / 2 + pieceDy;
    positionBubble(cx, cy);
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
    positionBubble(cx, cy);
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
       clips out of the map frame; hidden while the pin is outside the
       visible window). */
    positionBubble(x, y);
    document.getElementById("hint-text").textContent = "Pin dropped — tap again or drag to move it, then confirm your guess.";
  }
  /* ============ Pinch-to-zoom and pan (map viewport) ============
     The unified gesture layer, registered before the mode-specific
     handlers so it runs first and they can defer to it. It tracks every
     active pointer on the map by pointerId:
     - Two pointers down: a pinch. The viewBox scales by the change in
       finger distance, anchored at the pinch midpoint, and any pin or
       piece drag in progress is cancelled.
     - One pointer, zoomed in: a drag pans the map (the map follows the
       finger). At full view a drag does nothing here — the mode handlers
       keep their existing drag behaviour (pin drag, piece drag).
     - A tap (one pointer, no pinch, movement under TAP_MOVE_PX) is acted
       on at pointerup, but only when the gesture started zoomed in: at
       full view the mode handlers already act on pointerdown, so acting
       again would double-place. The tap converts with the CURRENT
       viewport (eventToSvg uses getScreenCTM, which is viewBox-aware). */
  var pointers = new Map();
  var pinchState = null;
  var panLast = null;
  var gestureRect = null;
  var downPos = null;
  var downMoved = false;
  var pinchHappened = false;
  var wasZoomedAtDown = false;
  function selectCountyAt(x, y) {
    var picked = countyAtPoint(x, y);
    if (!picked) {
      /* A tap outside all counties selects nothing: clear any existing
         selection, hide the highlight and the Confirm bubble, and disable
         Confirm again. Without this, a stray tap outside the state would
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
  }
  svg.addEventListener("pointerdown", function (ev) {
    if (!game || phase !== "guess") return;
    if (pointers.size === 0) {
      gestureRect = svg.getBoundingClientRect();
      wasZoomedAtDown = vbIsZoomed(vb);
      downPos = { x: ev.clientX, y: ev.clientY };
      downMoved = false;
      panLast = { x: ev.clientX, y: ev.clientY };
    }
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pointers.size === 2) {
      /* Second finger down: this gesture is a pinch. Only the finger
         distance is captured — the zoom is applied incrementally from
         it (see the pointermove handler), and the anchor is recomputed
         from the current midpoint on every move. */
      var pts = Array.from(pointers.values());
      pinchState = { prevDist: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) };
      pinchHappened = true;
      /* Cancel any pin or piece drag in progress — the gesture is a
         pinch now, and the drag must not fight it. */
      dragging = false;
      if (pieceDragging) {
        pieceDragging = false; dragStart = null;
        countyPiece.classList.remove("dragging");
      }
      try { svg.setPointerCapture(ev.pointerId); } catch (e) {}
      return;
    }
    /* One finger, zoomed in: capture so pan moves keep arriving even if
       the finger slides off the map. At full view the mode handlers do
       their own capture as needed. */
    if (vbIsZoomed(vb)) { try { svg.setPointerCapture(ev.pointerId); } catch (e) {} }
  });
  svg.addEventListener("pointermove", function (ev) {
    if (!pointers.has(ev.pointerId)) return;
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pinchState && pointers.size >= 2) {
      /* Pinch: apply the INCREMENTAL change in finger distance to the
         target viewBox, anchored at the CURRENT midpoint. Each step is
         relative to the previous move's distance, so the zoom is
         continuous and immune to a stale baseline, and the anchor
         follows the fingers when they move asymmetrically. The displayed
         viewBox eases toward the target on the next animation frame
         (see viewportFrame) — it is not set here. */
      var pts = Array.from(pointers.values());
      var dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      if (dist > 0 && pinchState.prevDist > 0) {
        var midX = (pts[0].x + pts[1].x) / 2, midY = (pts[0].y + pts[1].y) / 2;
        var anchor = vbClientToSvg(vb, gestureRect, midX, midY);
        vbZoomAt(vbTarget, anchor, { x: midX, y: midY },
          gestureRect, vbTarget.w * pinchState.prevDist / dist);
        scheduleViewportFrame();
      }
      pinchState.prevDist = dist;
      return;
    }
    if (downPos && Math.hypot(ev.clientX - downPos.x, ev.clientY - downPos.y) > TAP_MOVE_PX) downMoved = true;
    /* A pin or piece drag owns the move — never pan while one is in
       progress, or the map and the dragged thing would move together.
       Counties mode has pinch zoom only, no pan: one finger always
       drags the piece, so a pan would fight it. */
    if (dragging || pieceDragging || game.mode === "counties") return;
    if (pointers.size === 1 && vbIsZoomed(vb)) {
      /* One-finger pan when zoomed: the map follows the finger. The pan
         moves the TARGET viewport; the displayed viewport eases toward
         it on the next animation frame (see viewportFrame), which also
         keeps the Confirm bubble with the pin / selected county. */
      var dx = ev.clientX - panLast.x, dy = ev.clientY - panLast.y;
      panLast = { x: ev.clientX, y: ev.clientY };
      vbPan(vbTarget, dx, dy, gestureRect);
      scheduleViewportFrame();
    }
  });
  function endGesture(ev) {
    if (!pointers.has(ev.pointerId)) return;
    pointers.delete(ev.pointerId);
    if (pointers.size === 1) {
      /* One finger lifted mid-pinch: the gesture stays a pinch (no tap
         on release), but the remaining finger becomes a fresh single
         pointer, so it can pan from here. */
      pinchState = null;
      var remaining = Array.from(pointers.values())[0];
      downPos = { x: remaining.x, y: remaining.y };
      downMoved = false;
      panLast = { x: remaining.x, y: remaining.y };
      return;
    }
    if (pointers.size > 0) return;
    /* Gesture over. Snap the displayed viewport to the target first,
       so the tap (if any) resolves against the exact final view. */
    vbSnapTo(vb, vbTarget);
    setViewBoxAttr(); updateResetBtn();
    /* A tap that started zoomed in — one pointer, no pinch, minimal
       movement — acts here (at full view the mode handlers already
       acted on pointerdown). Counties mode has no tap action; the
       piece is dragged, not tapped. */
    var wasTap = wasZoomedAtDown && !pinchHappened && !downMoved;
    pinchState = null; panLast = null; gestureRect = null;
    downPos = null; downMoved = false; pinchHappened = false; wasZoomedAtDown = false;
    if (!wasTap || !game || phase !== "guess" || game.mode === "counties") return;
    var loc = eventToSvg(ev);
    if (!loc) return;
    if (game.mode === "name-the-county" || isMixedCountyRound()) selectCountyAt(loc.x, loc.y);
    else placeGuessAt(loc.x, loc.y);
  }
  svg.addEventListener("pointerup", endGesture);
  svg.addEventListener("pointercancel", endGesture);
  svg.addEventListener("pointerleave", function (ev) {
    /* Safety net if pointer capture failed and a finger slides off the
       map mid-gesture: end the gesture cleanly, with no tap. */
    if (!pointers.has(ev.pointerId)) return;
    pointers.delete(ev.pointerId);
    if (pointers.size === 0) {
      pinchState = null; panLast = null; gestureRect = null;
      downPos = null; downMoved = false; pinchHappened = false; wasZoomedAtDown = false;
      /* Gesture over: snap the displayed viewport to the target. */
      vbSnapTo(vb, vbTarget);
      setViewBoxAttr(); updateResetBtn();
    }
  });

  svg.addEventListener("pointerdown", function (ev) {
    if (!game || phase !== "guess" || game.mode === "counties" || game.mode === "name-the-county" || isMixedCountyRound()) return;
    /* During a pinch, or zoomed in, the pointerdown does nothing here:
       a pinch zooms (see the gesture layer above) and a zoomed tap is
       placed on pointerup, so the pin is never dropped where a pan
       started. At full view the pin drops immediately, as before. */
    if (pinchState || pointers.size > 1 || vbIsZoomed(vb)) return;
    ev.preventDefault();
    var loc = eventToSvg(ev);
    if (!loc) return;
    dragging = true;
    try { svg.setPointerCapture(ev.pointerId); } catch (e) {}
    placeGuessAt(loc.x, loc.y);
  });
  svg.addEventListener("pointermove", function (ev) {
    if (!dragging || !game || phase !== "guess" || game.mode === "counties" || game.mode === "name-the-county" || isMixedCountyRound()) return;
    /* A pinch or a pan owns the move — never move the pin while zooming
       or panning. */
    if (pinchState || vbIsZoomed(vb)) return;
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
    /* During a pinch, or zoomed in, the pointerdown does nothing here:
       a pinch zooms (see the gesture layer above) and a zoomed tap is
       selected on pointerup, so a pan never selects a county by
       accident. At full view the county is selected immediately. */
    if (pinchState || pointers.size > 1 || vbIsZoomed(vb)) return;
    ev.preventDefault();
    var loc = eventToSvg(ev);
    if (!loc) return;
    selectCountyAt(loc.x, loc.y);
  });

  /* ============ County piece drag ============
     pointerdown on the piece starts the drag (recording the pointer's
     SVG position and the current translation); pointermove on the SVG
     moves the piece by the pointer's movement delta; pointerup ends it.
     The piece follows the pointer rigidly — no per-move callbacks, the
     parent only needs the final position at confirm time. */
  countyPiece.addEventListener("pointerdown", function (ev) {
    if (!game || game.mode !== "counties" || phase !== "guess") return;
    /* A second finger means a pinch, not a piece drag: the gesture
       layer (which runs after this handler, by bubbling) starts the
       pinch, so don't start a drag here. */
    if (pointers.size >= 1 || pinchState) return;
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
    /* Every round begins at the full map — a zoomed view is never
       carried across rounds. */
    resetView();
    clearPins();
    clearCountyOverlays();
    btnConfirm.disabled = true;
    btnPass.disabled = false;
    pinConfirm.hidden = true;
    document.getElementById("reveal-controls").hidden = true;
    document.getElementById("guess-controls").hidden = false;
    /* The unified message line below the buttons shows the guessing hint
       while placing; the reveal line stays hidden until the reveal. */
    document.getElementById("reveal-line").hidden = true;
    document.getElementById("hint-text").hidden = false;
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
    /* The reveal reads in full-state context: the guess-to-true line and
       pins are shown on the whole map, not a zoomed window. */
    resetView();
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
    /* A pass has no distance, so the property is omitted, not sent as null.
       `target` is the correct answer (the grouping key for analysis —
       it duplicates `question` for city rounds on purpose, so every
       round_completed event carries one uniform `target` field). */
    var cityRoundProps = { question_type: "city", question: city.name, target: city.name, points: points };
    if (dist !== null) cityRoundProps.distance_miles = Math.round(dist * 10) / 10;
    trackRoundCompleted(cityRoundProps);
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
    /* The message line below the buttons swaps from the guessing hint to
       the reveal distance and points. */
    document.getElementById("hint-text").hidden = true;
    document.getElementById("reveal-line").hidden = false;
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
    /* The reveal reads in full-state context: the true county is shown
       on the whole map, not a zoomed window. */
    resetView();
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
    /* Drag scoring is by overlap, so there is no correct/adjacent — the
       overlap fraction is the metric. A pass has no overlap, so the
       property is omitted, not sent as null. `target` is the correct
       answer (the grouping key for analysis). */
    var dragRoundProps = { question_type: "county", question: countyName, target: countyName, points: points };
    if (overlap !== null) dragRoundProps.overlap_fraction = Math.round(overlap * 1000) / 1000;
    trackRoundCompleted(dragRoundProps);
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
    /* The message line below the buttons swaps from the guessing hint to
       the reveal overlap and points. */
    document.getElementById("hint-text").hidden = true;
    document.getElementById("reveal-line").hidden = false;
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
    /* The reveal reads in full-state context: the true county is shown
       on the whole map, not a zoomed window. */
    resetView();
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
    /* `target` is the correct answer (the grouping key for analysis). */
    trackRoundCompleted({ question_type: "county", question: countyName, target: countyName, correct: correct, adjacent: adjacent, points: points });
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
    /* The message line below the buttons swaps from the guessing hint to
       the reveal message ("Correct — that's …" / "Pretty close! …"). */
    document.getElementById("hint-text").hidden = true;
    document.getElementById("reveal-line").hidden = false;
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
    /* Seeds are forced to upper case, so "friday-game" and
       "FRIDAY-GAME" are the same game. */
    seed = (seed || "").trim().toUpperCase();
    if (!seed) seed = randomSeed();
    var seedInt = await seedIntFromString(seed);
    var mode = selectedMode();
    /* The pools are the edition's pools: the filter applies before the
       seeded shuffle, so the seed + edition together determine the
       game. The edition is stored on the game object (for the summary
       link, the results text, and the analytics events). */
    var pools = editionPools();
    if (mode === "city-county") {
      /* 7 cities and 3 counties, then the 10 rounds interleaved by a
         seeded shuffle — genuinely mixed, not 7-then-3. The same seed
         picks the same 7 cities and 3 counties (same selection as the
         single-type modes); only their order is shuffled. The C# version
         uses System.Random where this version uses mulberry32, so the
         same seed generally picks different cities/counties here than on
         the live site, and the interleaving order can differ too —
         accepted, same as the existing C#/JS divergence. */
      var mixedCities = selectItems(seedInt, pools.cities, 7);
      var mixedCounties = selectItems(seedInt, pools.counties, 3);
      var rounds = mixedCities.map(function (c) { return { type: "city", city: c }; })
        .concat(mixedCounties.map(function (c) { return { type: "county", county: c }; }));
      rounds = shuffleItems(seedInt, rounds);
      game = { seed: seed, mode: "city-county", edition: currentEdition, cities: mixedCities, counties: mixedCounties, rounds: rounds, roundIndex: 0, results: [], total: 0 };
    } else if (mode === "counties") {
      var pickedCounties = selectItems(seedInt, pools.counties, QUESTION_COUNT);
      game = { seed: seed, mode: "counties", edition: currentEdition, cities: [], counties: pickedCounties, roundIndex: 0, results: [], total: 0 };
    } else if (mode === "name-the-county") {
      /* Same pool and same selection as the Counties drag mode, so the
         same seed picks the same 10 counties in both county modes. */
      var namedCounties = selectItems(seedInt, pools.counties, QUESTION_COUNT);
      game = { seed: seed, mode: "name-the-county", edition: currentEdition, cities: [], counties: namedCounties, roundIndex: 0, results: [], total: 0 };
    } else {
      var pickedCities = selectItems(seedInt, pools.cities, QUESTION_COUNT);
      game = { seed: seed, mode: "cities", edition: currentEdition, cities: pickedCities, counties: [], roundIndex: 0, results: [], total: 0 };
    }
    try {
      /* The game URL is /{state}/{mode}/{seed}, so a shared link (and a
         refresh) replays the same mode and seed — plus ?list=all when
         the edition is All, so it replays the same edition too. */
      history.replaceState(null, "", "/oregon/" + mode + "/" + encodeURIComponent(seed) + (currentEdition === "all" ? "?list=all" : ""));
    } catch (e) {}
    showScreen("game");
    startRound();
    var startedProps = baseProps();
    startedProps.questions = QUESTION_COUNT;
    captureEvent("game_started", startedProps);
  }

  seedInput.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") startGame(seedInput.value);
  });

  /* The main Play button is the only way to start a game: it starts with
     whatever Game # is in the box (today's or another one — the label
     says which). Starting with an empty box is preserved: startGame
     falls back to a random seed, as before. */
  playTodayBtn.addEventListener("click", function () {
    startGame(seedInput.value);
  });

  /* Collapsible start-screen sections ("How to play", "Advanced options"):
     minimized by default; tapping the header button expands the section
     (and flips its chevron). Expanding changes the page height, which is
     expected for a collapsed section. The button label is the chevron
     plus the section name, so slice(2) drops the old chevron. */
  function bindSectionToggle(btnId, panelId) {
    var btn = document.getElementById(btnId);
    var panel = document.getElementById(panelId);
    btn.addEventListener("click", function () {
      var open = panel.hidden;
      panel.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      btn.textContent = (open ? "\u25be " : "\u25b8 ") + btn.textContent.slice(2);
    });
  }
  bindSectionToggle("btn-how-to-play", "how-to-play");
  bindSectionToggle("btn-advanced", "advanced-options");

  /* ============ Results ============ */
  function showResults() {
    /* The game is over: leaving the page from here is not an
       abandonment (see the pagehide handler), and the game is reported
       as completed. The game has no per-round or total timing, so no
       duration is reported — see GAME-SPEC §13. */
    phase = "results";
    var completedProps = baseProps();
    completedProps.total_score = game.total;
    completedProps.max_score = 1000;
    completedProps.rounds = QUESTION_COUNT;
    captureEvent("game_completed", completedProps);
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
      ? "Anyone opening this link with the same Game # gets the same 7 cities and 3 counties in the same order."
      : isCountyMode
      ? "Anyone opening this link with the same Game # gets the same 10 counties in the same order."
      : "Anyone opening this link with the same Game # gets the same 10 cities in the same order.";
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
        "Game # " + game.seed + " · " + QUESTION_COUNT + " questions · average distance " + avgMixed + " miles (city rounds) · you named " + namedMixed + " out of 3 counties correctly" + (adjacentMixed > 0 ? " and were adjacent on " + adjacentMixed + " more" : "") + ".";
    } else if (isName) {
      var named = game.results.filter(function (r) { return r.correct; }).length;
      var adjacentNamed = game.results.filter(function (r) { return r.adjacent; }).length;
      document.getElementById("final-sub").textContent =
        "Game # " + game.seed + " · " + QUESTION_COUNT + " questions · you named " + named + " out of " + QUESTION_COUNT + " counties correctly" + (adjacentNamed > 0 ? " and were adjacent on " + adjacentNamed + " more" : "") + ".";
    } else if (isCounties) {
      var avgCov = scored.length
        ? Math.round(scored.reduce(function (s, r) { return s + r.overlap; }, 0) / scored.length * 100)
        : "—";
      document.getElementById("final-sub").textContent =
        "Game # " + game.seed + " · " + QUESTION_COUNT + " questions · average coverage " + avgCov + "% (placed rounds).";
    } else {
      var avg = scored.length
        ? (scored.reduce(function (s, r) { return s + r.distance; }, 0) / scored.length).toFixed(1)
        : "—";
      document.getElementById("final-sub").textContent =
        "Game # " + game.seed + " · " + QUESTION_COUNT + " questions · average distance " + avg + " miles (guessed rounds).";
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
      (isMixed ? " (City/County)" : isCounties ? " (Counties)" : isName ? " (County)" : "") + ", Game # " + game.seed + "\n" + editionLabel(game.edition) + "\nPlay the same game: " + gameLink();
  }

  function copyText(text, noteEl) {
    // The note is always rendered with a reserved line; only its
    // visibility toggles, so showing "Copied!" never moves anything.
    function done() { if (noteEl) { noteEl.style.visibility = "visible"; setTimeout(function () { noteEl.style.visibility = "hidden"; }, 2000); } }
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
  document.getElementById("btn-copy-summary").addEventListener("click", function () {
    copyText(document.getElementById("summary-text").textContent, document.getElementById("copy-note"));
  });
  document.getElementById("btn-back-select").addEventListener("click", function () {
    showScreen("start");
  });
  document.getElementById("btn-again").addEventListener("click", function () {
    seedInput.value = randomSeed();
    updatePlayLabel();
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
        .replace("__USA_STATES__", USA_STATES_JSON)
        .replace("__RISK_POOL__", RISK_POOL_JSON)
        .replace("__POSTHOG_KEY__", POSTHOG_KEY)
        .replace("__POSTHOG_HOST__", POSTHOG_HOST)
        .replace("__PURE_JS__", PURE_JS))

with open(OUT, "w") as f:
    f.write(html)
print("wrote", OUT, len(html), "bytes")
