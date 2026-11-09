# USA states map — splash page data

## What it is
`usa-states.geojson` is the outline of every US state plus the District of
Columbia (51 features), for the splash/welcome page at the base URL (`/`).
It is a decorative overview map, not a game map: it is only used to draw
the USA on the splash page, where the player picks a state to play.

## Source
Natural Earth 10m `admin_1_states_provinces` (the same source family as
the game's landmarks, Natural Earth 10m), filtered to the 51 features
whose `admin` is "United States of America" — 50 states + District of
Columbia. Download:
`https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_1_states_provinces.zip`

## Processing — `process-usa-states.py`
Run from the project root: `python3 process-usa-states.py`. It:
- Keeps only the 51 USA features (name, postal abbreviation).
- Simplifies each ring with pure-Python Douglas–Peucker, tolerance 0.12
  degrees — coarse on purpose for a decorative map — except the Great
  Lakes states (Minnesota, Wisconsin, Michigan, Illinois, Indiana,
  Ohio, Pennsylvania, New York), which use 0.03 degrees so their
  shorelines read correctly (see "Great Lakes land fix" below). The
  file is 88.9 KB.
- The Great Lakes water is subtracted from the eight lake-bordering
  states, so the outlines follow the land (see "Great Lakes land fix"
  below). Michigan's land is therefore two separate peninsulas
  naturally — no manual split any more.
- Rings are classified outer-vs-hole by a point-in-polygon test, so holes
  (if any) stay holes; paths use `fill-rule="evenodd"`.
- Sets `properties.available` to true only for Oregon (the only state
  pack that exists); the other 50 are false.
- Writes both copies: `data/usa-states.geojson` (source, read by
  `build-game.py`) and `blazor/wwwroot/data/usa-states.geojson` (loaded
  by the Blazor splash page).

## Great Lakes fix (2026-11-09)
Matt reported the Great Lakes states (Minnesota, Wisconsin, Illinois,
Michigan) looked "a little wonky" on the splash map. Two causes, both
fixed in `process-usa-states.py`:

### Michigan was one polygon, not two peninsulas
**Root cause:** Natural Earth stores Michigan as a SINGLE ring (one part,
545 points) whose interior includes the Mackinac Strait water — the
Great Lakes are separate features in the dataset, meant to be drawn on
top of the states, so the state polygon alone fills the strait and the
two peninsulas read as one blob. There was never a separate Upper
Peninsula ring for the processing to lose; the separation has to be
made explicitly. (Verified: the raw Michigan ring is a valid simple
polygon, 0 self-intersections; the strait at (−84.6, 45.85) and northern
Lake Michigan at (−86.0, 45.5) both test inside it.)

**Fix:** `split_michigan_ring()` cuts the single ring into Upper and
Lower Peninsula rings across the strait, from the Upper Peninsula's
eastern tip (near −84.5, 46.5) to the Green Bay / Menominee area
(near −87.85, 45.45). The cut points are found geometrically (closest
ring point to a target coordinate in each area), not by hardcoded index,
and the pair is accepted only if the cut segment crosses the ring
nowhere else — a crossed cut would make an invalid polygon. Michigan is
then emitted as a **MultiPolygon** (Upper Peninsula lon −90.4…−84.49,
lat 45.45…48.3; Lower Peninsula lon −87.86…−82.15, lat 41.7…46.53).
The Lower Peninsula's north reaches 46.53 because it keeps the Les
Cheneaux shore; that is geographically correct, not an error.

**Rendering note:** the two rings share the cut edge, so they are two
separate polygons, NOT one outer ring with a hole. `classify_rings`
would mistake one for a hole of the other (the shared cut points lie on
both rings' boundaries, and a point-on-boundary test is ambiguous), so
Michigan bypasses it and each ring is emitted as its own polygon.
`Splash.razor` draws each ring as a subpath in one `<path>` with
`fill-rule="evenodd"`, and each subpath is stroked, so the shared edge
is drawn and the two peninsulas read as separate shapes even though
they share a boundary. The JS mirror (`buildUsaMap`) handles the
MultiPolygon the same way.

### Great Lakes shorelines were too coarse
**Cause:** the global 0.12° Douglas–Peucker tolerance left Minnesota,
Wisconsin and Illinois with only 29/24/29 points — too few to capture
the Great Lakes shorelines (Minnesota's North Shore on Lake Superior,
Wisconsin's Door County and Lake Michigan shore, Illinois's Lake
Michigan shore), so they came out angular and distorted.

**Fix:** the Great Lakes states (Minnesota, Wisconsin, Illinois,
Michigan, Ohio, Indiana) now simplify at **0.03°**; every other state
keeps 0.12°, so their shapes are unchanged (verified byte-identical
against the previous file — only the 6 Great Lakes states differ).
Point counts, before → after: Minnesota 29 → 77, Wisconsin 24 → 65,
Illinois 29 → 80, Michigan 30 → 61 (now 2 parts), Ohio 20 → 51,
Indiana 19 → 66. File grew 78.2 KB → 82.8 KB, still well under the
200 KB budget.

## Great Lakes land fix (2026-11-09) — supersedes the Michigan split above
Matt compared the map to a real map and explained the real issue: the
state outlines are the correct *territory* for a state, but they are
not representative of the *land* boundary. The Great Lakes water is
included inside the state outlines. He wants the outlines to follow the
**land** — the shoreline — so the Great Lakes are NOT included in the
state shapes. The lakes should read as water (gaps between the states),
not as part of any state.

**Source:** Natural Earth 10m lakes (`ne_10m_lakes`), the five Great
Lakes by name — Superior, Michigan, Huron, Erie, Ontario. Download:
`https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_lakes.zip`
(The earlier `/tmp` shapefile is gone; this is a fresh download.)

**Method:** `process-usa-states.py` loads the five lakes, unions them
into one geometry with shapely, and subtracts it from the state
polygon (`polygon.difference(lakes)`) for **all eight states that
border a Great Lake** — Minnesota, Wisconsin, Michigan, Illinois,
Indiana, Ohio, Pennsylvania, New York. Matt named MN/WI/IL/MI, but
IN/OH/PA/NY get the same treatment or they would still include lake
water and look inconsistent with their neighbours. The subtraction runs
on the raw (unsimplified) geometry so the shoreline keeps its detail;
the result is then simplified (0.03° for the eight lake states, 0.12°
for the rest). Shapely is used only for the subtraction, not for
simplification. The other 43 states are untouched.

**Michigan and the manual split:** once the lakes are subtracted, the
Mackinac Strait water is removed, so Michigan's *land* is naturally
two separate polygons (Upper + Lower Peninsula) — the manual
`split_michigan_ring()` is gone (it would be redundant, and it cut
across the strait with a straight line). Michigan is now a MultiPolygon
whose two main parts are the Upper Peninsula (area 4.82, lon
−90.41…−83.89, lat 45.1…47.24) and the Lower Peninsula (area 12.0, lon
−86.84…−82.42, lat 41.7…45.8). The subtraction also reveals real
Michigan land that the single territory ring had hidden: the Keweenaw
Peninsula (area 0.16 — it is cut off from the Upper Peninsula by the
Portage waterway, which the lake data includes), Isle Royale (0.065),
Drummond Island (0.037), Beaver Island (0.016), and smaller islands,
for 15 parts total. Those are real Michigan land, not artefacts, so
they are kept; the two peninsulas are the requirement, the islands are
the bonus. The same applies elsewhere: New York keeps Long Island
(0.38) and its Lake Ontario islands, Wisconsin keeps Washington Island
and Door County.

**Validation (land vs water):** test points in the middle of each lake
— Lake Michigan (−87, 43.5) and (−86, 45.5), Mackinac Strait (−84.6,
45.85), Lake Superior (−88, 47), Lake Huron (−82, 44), Lake Erie (−81,
42), Lake Ontario (−78, 43.6), Green Bay (−87.9, 44.7), Saginaw Bay
(−83.9, 43.8) — are inside **no** state's polygon (before this fix
they were inside the state polygons). Land points are inside the
correct state: Chicago (Illinois), Detroit (Michigan), Duluth
(Minnesota), Milwaukee (Wisconsin), Cleveland (Ohio), Buffalo (New
York), Pittsburgh (Pennsylvania), Indianapolis (Indiana), Traverse
City / Marquette / Keweenaw (Michigan), Green Bay city (Wisconsin),
Erie PA, Rochester NY, Isle Royale, Door County, Washington Island,
Long Island. (A few first test points sat in the water itself — Buffalo
(−78.9, 42.9) is Lake Erie, Detroit (−83, 42.3) is on the river border,
(−88.2, 47.2) is Keweenaw Bay — and were replaced with points on
land; the subtraction is working, the test points were wrong.)

**File:** 4,369 points; 88.9 KB (was 82.8 KB), still well under the
200 KB budget. Pennsylvania and New York now also use the 0.03°
tolerance (they border lakes too), so their shapes have more points
than before; the other 43 states are unchanged.

## Alaska / Hawaii insets — read this before reusing the coordinates
The coordinates in this file are **display** coordinates, not true
geography, for Alaska and Hawaii. They are scaled and translated into
the standard inset layout (Alaska bottom-left, Hawaii below the
southwest, both under the contiguous US), so a plain linear lon/lat →
SVG mapping puts them in the right place. The contiguous US keeps true
lon/lat. Do not use these coordinates for distance or scoring — they
are only for drawing the splash map.

- Alaska: scaled 0.35 about its bounding-box centre, then translated so
  its box sits at display lon −125…−112, lat 24.7…30.5.
- Hawaii: translated (no scale) so its box sits at display lon
  −110…−104.6, lat 25.5…28.8.
- The insets sit just under the mainland, with only a small gap (about
  2.5 degrees, ~54 px) to the mainland's southern edge in their own
  longitude band — close enough to read as one map, not a separate
  strip floating far below. The mainland's southern edge is not flat,
  so the two insets sit at different heights: Alaska's top is 1.99
  degrees below California's southern edge (32.5), and Hawaii's
  closest approach is 2.50 degrees to Arizona. The overall map spans
  lat 24.54…49.37 (Florida's tip is the southernmost point, just below
  Alaska's bottom edge), so the viewBox is `0 0 1000 535.8` (was
  763.3) — the old layout left a ~12-degree empty band under the
  mainland. The viewBox height is computed from the data extents in
  both the Blazor splash and the JS mirror, so it tightens
  automatically when the data changes.
- Hawaii keeps only the 8 main islands. The shapefile also carries the
  far northwestern atolls (Midway, Kure, …) as degenerate point-rings at
  lon −162…−178, lat 23…28 — uninhabited, and keeping them would stretch
  Hawaii's bounding box to 23 degrees wide and squeeze the main islands
  to nothing. Main islands are all below latitude 23; the atolls are all
  above it, so the filter is a latitude cut at 23.

### Alaska ring-count quirk — the number of tiny islands kept is fragile
Alaska's shape has 181 rings (the mainland plus many small Aleutian
islands). After the 0.35 scaling the tiny islands are sub-pixel and
cluster at the inset's corner, and `classify_rings` decides
outer-vs-hole from each ring's first point only: a ring whose first
point falls inside another ring is a hole, and a hole whose container
is itself a hole is dropped entirely (the emitter has no way to
represent an island inside a hole). Which tiny rings survive therefore
depends on floating-point-sensitive point-in-polygon tests that flip
when the inset is translated — moving Alaska from lat 14…19.8 to
24.7…30.5 changed the kept rings from 30 to 68 (the extra 38 are tiny
Aleutian islands at the corner, total area 0.041 sq deg, invisible at
map scale). The main Alaska ring and the larger islands are unaffected.
This is a pre-existing quirk, not a regression: the old layout also
dropped most of the 181 rings (151 of them). If the tiny-island count
ever matters, `classify_rings` needs a depth-based (even/odd) rule
instead of first-point containment; until then, do not treat Alaska's
ring count as meaningful.

## Validation (2026-11-09, after the Great Lakes land fix)
- 51 features, all 50 state names + District of Columbia present.
- Oregon is the only feature with `available: true`.
- Total 4,695 points; file 95.0 KB (well under the 200 KB budget).
  The point count rose from 4,369 because moving Alaska's inset
  changed which of its tiny island rings `classify_rings` keeps (see
  "Alaska ring-count quirk" above) — the other 50 states are
  byte-identical to the previous file.
- Michigan is a MultiPolygon whose two main parts are the Upper
  Peninsula (lon −90.41…−83.89, lat 45.1…47.24) and the Lower
  Peninsula (lon −86.84…−82.42, lat 41.7…45.8), plus the Keweenaw
  Peninsula and Michigan's islands as smaller parts (15 parts total).
- Lake points are in no state; land points are in the correct state
  (see "Great Lakes land fix" above for the full lists).
- Centroid spot-checks: Oregon west/north, California west/mid,
  Florida east/south, Maine east/north, Texas south-central, New York
  northeast, Alaska in the bottom-left inset, Hawaii to its right;
  Washington north of Oregon, Nevada east of California. All pass.
- The splash projection (equirectangular, cos 37°) gives viewBox
  `0 0 1000 535.8` (was 763.3); all 51 paths render inside it, none empty.
- Alaska/Hawaii insets (2026-11-09): Alaska lon −125…−111.65, lat
  24.7…30.51; Hawaii lon −110…−104.64, lat 25.5…28.83. Neither inset
  intersects any mainland state or each other (shapely check); closest
  approaches are Alaska–California 2.48° and Hawaii–Arizona 2.50°
  (~54 px each). The insets sit just under the mainland with only a
  small gap, and the map has no big blank band at the bottom.
- Visual check (rendered PNGs from the regenerated file): the Great
  Lakes close-up shows the lakes as water gaps between the states —
  Michigan as two separate peninsulas, Wisconsin's Door County and the
  Lake Michigan shore, Minnesota's North Shore — with the state
  outlines following the shorelines. Full-USA render is unchanged
  apart from the Great Lakes states and the Alaska/Hawaii insets, which
  now sit close under the mainland.
- `dotnet publish -c Release` clean; standalone JS `node --check` clean.
