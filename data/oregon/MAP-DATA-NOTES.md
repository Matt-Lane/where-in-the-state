# Oregon map data — notes

**Date:** 2026-11-06
**For:** Oregon geography game (Blazor WebAssembly, SVG + GeoJSON, v1)
**Files in this folder:**
- `outline.geojson` — 5,622 bytes, Oregon state outline, 209 points (simplified from 960)
- `landmarks.geojson` — 86,650 bytes, 177 features total:
  - 26 interstate segments (I-5, I-82, I-84, I-205)
  - 100 highway segments (US + state routes)
  - 40 river segments, 20 named rivers
  - 11 lakes/reservoirs
- Each landmark feature has `properties.layer` = `interstate` | `highway` | `river` | `lake` and a `properties.name`.

## Sources (all public domain / openly licensed)

| Layer | Source | License |
|---|---|---|
| State outline | U.S. Census Bureau, 2010 cartographic boundary file `gz_2010_us_040_00_500k.json` (Oregon feature, `GEO_ID 0400000US41`), via https://eric.clst.org/assets/wiki/uploads/Stuff/gz_2010_us_040_00_500k.json | Public domain (U.S. federal government) |
| Rivers, lakes, roads | Natural Earth 10m, via https://github.com/nvkelso/natural-earth-vector (geojson): `ne_10m_rivers_lake_centerlines.geojson`, `ne_10m_rivers_north_america.geojson`, `ne_10m_lakes.geojson`, `ne_10m_lakes_north_america.geojson`, `ne_10m_roads.geojson` | Public domain (Natural Earth) |

No geometry was invented. No live map tiles are used; all data is shipped with the app.

## Processing

Script: `process-map-data.py` in this folder (copy of the script used; run it from a
directory holding the raw downloads listed above — it writes to this folder).
Steps:
1. **Outline:** extract the Oregon polygon from the Census file; simplify with
   Douglas-Peucker, tolerance 0.008° (960 → 209 points). Bounding box of the
   simplified outline: lon −124.566 to −116.464, lat 41.992 to 46.271.
2. **Rivers:** keep only named major rivers in the Oregon bbox, from both Natural
   Earth river files (the global file alone misses Deschutes, Umpqua, Grande Ronde,
   etc.; the North America file supplies them). Kept: Columbia, Willamette, Rogue,
   John Day, Klamath, Deschutes, Umpqua, North/South Umpqua, Grande Ronde, Malheur,
   Owyhee, Clackamas, Nehalem, Santiam (as "South Santium" in Natural Earth — see
   gaps below), Crooked, Williamson, Sprague, North Fork Sprague, Sycan.
   Clip each polyline to the Oregon bbox (lon −124.75 to −116.35, lat 41.90 to 46.40),
   simplify at 0.004°.
3. **Lakes:** keep named lakes/reservoirs intersecting Oregon: Goose Lake, Malheur
   Lake, Harney Lake, Upper Klamath Lake, Lake Abert, Summer Lake, Crater Lake,
   Owyhee Reservoir, Fern Ridge Reservoir, Wickiup Reservoir, Warm Springs Reservoir.
   Simplify polygons at 0.004°. (Goose Lake straddles the California border; its full
   polygon is kept — the map clips rendering to the state outline.)
4. **Roads:** Natural Earth 10m roads overlapping the Oregon bbox. Interstate =
   route number in {5, 84, 82, 205, 405}; everything else with type Major Highway /
   Secondary Highway / Road goes to the highway layer. Unnamed segments dropped.
   Clip to bbox, simplify at 0.004°.
5. **Out-of-state filter:** the bbox clip alone lets in fragments of roads/rivers
   just across the Columbia River in Washington and across the Snake in Idaho.
   A line feature is kept only if at least one of its points lies inside the
   simplified outline or within 0.02° of it (so border-crossing roads and the
   Columbia River itself survive). This dropped 20 fragments (e.g. I-82 and US-95
   segments in Washington/Idaho, US-101 north of the Columbia mouth).

## Projection (must match the game and the prototype)

Equirectangular with cos(44°) correction, exactly as in GAME-SPEC.md §9.4:
- Bounds: outline bbox + 0.15° margin → lon −124.716 to −116.314, lat 41.843 to 46.421
- `x = (lon − lon_min) · cos(44°) / x_range · 1000`, `y = (lat_max − lat) / y_range · H`,
  where `x_range = (lon_max − lon_min)·cos(44°)`, `y_range = lat_max − lat_min`,
  `H = 1000 · y_range / x_range ≈ 757.4` (viewBox `0 0 1000 757.4`).
- The inverse of the same formulas converts a click back to lat/lon. The same
  function must be used for drawing and for clicks.

## Validation (2026-11-06)

- **Cities inside outline:** 241 / 241 from `oregon-cities-with-coords.json` fall
  inside the simplified outline (point-in-polygon), and 241 / 241 inside the
  unsimplified Census outline.
- **Projection round-trip:** converting every city's lat/lon to SVG x/y and back
  returns the original coordinates exactly (max error 0.00°, target < 0.01°).
  Spot checks: Portland → SVG (243.0, 149.0); Salem → (200.3, 245.2);
  Bend → (404.7, 390.9); Medford → (219.5, 677.4).
- **File sizes:** outline 5.6 KB, landmarks 86.7 KB — well under the ~500 KB target.

## Known gaps / things still missing

- **I-405 (Portland loop) is missing.** Natural Earth 10m roads has no I-405 segment
  in Oregon. It is a short (~4 mi) urban loop; it can be added later from
  OpenStreetMap / Census TIGER roads if wanted.
- **Snake River is not drawn as a river layer.** Natural Earth's Snake River geometry
  covers only fragments in Idaho/Wyoming, not the Oregon-border stretch. The Snake
  *is* traced by the eastern state outline (the border follows the river), so the
  border is correct — but there is no separate blue "Snake River" line. Same is
  partly true of the Columbia: it is drawn as a river where Natural Earth has it,
  and the northern outline follows it.
- **Santiam River naming:** Natural Earth spells it "South Santium" (likely a typo
  in the source data). The North Santiam and main Santiam are not separate features
  in the Natural Earth files used. The name is kept as-is in the data; the game
  does not label rivers, so this is cosmetic.
- **Overpass API was tried for the Snake River and timed out** (overpass-api.de,
  70 s timeout, 2026-11-06) — not pursued further; the outline already traces it.
- **Lakes are the major ones only.** Small lakes (e.g. Detroit Lake, Timothy Lake)
  are not in Natural Earth 10m and are not included. That is intentional for a
  clean blank map.

## Regenerating

1. Download the raw files listed under Sources into one folder.
2. Copy `process-map-data.py` into that folder and run `python3 process-map-data.py`
   (pure standard library — no shapely/geopandas/mapshaper needed).
3. It writes `outline.geojson` and `landmarks.geojson` into this folder.
4. Re-run the validation: all 241 cities must fall inside the outline, and the
   projection round-trip must stay within 0.01°.
5. If `oregon-cities.csv` changes, re-geocode first (see `geocoding-notes.md`),
   then re-run this step — the city list is independent of the map data.
