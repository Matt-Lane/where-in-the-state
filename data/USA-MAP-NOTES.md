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
  Lakes states (Minnesota, Wisconsin, Illinois, Michigan, Ohio,
  Indiana), which use 0.03 degrees so their shorelines read correctly
  (see "Great Lakes fix" below). The file is 82.8 KB.
- Michigan is split into Upper and Lower Peninsula rings (see
  "Great Lakes fix" below) and emitted as a MultiPolygon.
- Rings are classified outer-vs-hole by a point-in-polygon test, so holes
  (if any) stay holes; paths use `fill-rule="evenodd"`. (Michigan's two
  rings bypass that classification — see below.)
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

## Alaska / Hawaii insets — read this before reusing the coordinates
The coordinates in this file are **display** coordinates, not true
geography, for Alaska and Hawaii. They are scaled and translated into
the standard inset layout (Alaska bottom-left, Hawaii below the
southwest, both under the contiguous US), so a plain linear lon/lat →
SVG mapping puts them in the right place. The contiguous US keeps true
lon/lat. Do not use these coordinates for distance or scoring — they
are only for drawing the splash map.

- Alaska: scaled 0.35 about its bounding-box centre, then translated so
  its box sits at display lon −125…−112, lat 14…23.
- Hawaii: translated (no scale) so its box sits at display lon
  −110…−100, lat 14…22.
- Hawaii keeps only the 8 main islands. The shapefile also carries the
  far northwestern atolls (Midway, Kure, …) as degenerate point-rings at
  lon −162…−178, lat 23…28 — uninhabited, and keeping them would stretch
  Hawaii's bounding box to 23 degrees wide and squeeze the main islands
  to nothing. Main islands are all below latitude 23; the atolls are all
  above it, so the filter is a latitude cut at 23.

## Validation (2026-11-09, after the Great Lakes fix)
- 51 features, all 50 state names + District of Columbia present.
- Oregon is the only feature with `available: true`.
- Total 4,042 points; file 82.8 KB (well under the 200 KB budget).
- Michigan is a MultiPolygon with 2 parts (Upper Peninsula lon
  −90.4…−84.49, lat 45.45…48.3; Lower Peninsula lon −87.86…−82.15,
  lat 41.7…46.53).
- Centroid spot-checks: Oregon west/north, California west/mid,
  Florida east/south, Maine east/north, Texas south-central, New York
  northeast, Alaska in the bottom-left inset, Hawaii to its right;
  Washington north of Oregon, Nevada east of California. All pass.
- The splash projection (equirectangular, cos 37°) gives viewBox
  `0 0 1000 763.3`; all 51 paths render inside it, none empty.
- Visual check (rendered PNGs from the regenerated file): the Great
  Lakes close-up shows Michigan as two separate peninsulas (Upper
  Peninsula bar + Lower Peninsula mitten, divided by a stroked shared
  edge, including under the diagonal hatching used for unavailable
  states), and Minnesota / Wisconsin / Illinois have recognizable Great
  Lakes shorelines instead of angular blobs. Full-USA render is
  unchanged apart from the Great Lakes states; Alaska/Hawaii insets
  intact.
- `dotnet publish -c Release` clean; standalone JS `node --check` clean.
