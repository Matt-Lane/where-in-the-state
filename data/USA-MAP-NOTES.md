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
  degrees — coarse on purpose for a decorative map; the file is 78 KB.
- Rings are classified outer-vs-hole by a point-in-polygon test, so holes
  (if any) stay holes; paths use `fill-rule="evenodd"`.
- Sets `properties.available` to true only for Oregon (the only state
  pack that exists); the other 50 are false.
- Writes both copies: `data/usa-states.geojson` (source, read by
  `build-game.py`) and `blazor/wwwroot/data/usa-states.geojson` (loaded
  by the Blazor splash page).

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

## Validation (2026-11-09)
- 51 features, all 50 state names + District of Columbia present.
- Oregon is the only feature with `available: true`.
- Total 3,793 points; file 78.2 KB (well under the 200 KB budget).
- Centroid spot-checks: Oregon west/north, California west/mid,
  Florida east/south, Maine east/north, Texas south-central, New York
  northeast, Alaska in the bottom-left inset, Hawaii to its right;
  Washington north of Oregon, Nevada east of California. All pass.
- The splash projection (equirectangular, cos 37°) gives viewBox
  `0 0 1000 763.3`; all 51 paths render inside it, none empty.
