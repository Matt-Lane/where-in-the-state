# Geocoding notes — Oregon cities

**Date:** 2026-11-06
**Source:** Nominatim / OpenStreetMap (`https://nominatim.openstreetmap.org/search`), queried as `"<City>, Oregon, USA"`, 1 request per second with a proper User-Agent, as required by Nominatim's usage policy. No rate limit or block was hit.
**Input:** `oregon-cities.csv` — 241 cities, alphabetical, no duplicates (not edited).
**Outputs:** `oregon-cities-with-coords.csv` (241 rows + header) and `oregon-cities-with-coords.json` (241 entries, `{ "name", "latitude", "longitude" }`), both in the same order as the input file.

## Result

- **Found: 241 / 241**
- **Unresolved: 0**
- **Duplicates: 0** (no two cities share the same coordinates)
- **Out of Oregon bounds: 0** — every coordinate is inside lat 42.0–46.3, lon −124.7 to −116.5, and every result's address state is Oregon, USA.
- **Verification:** every result's `display_name` was checked against the requested city name. Sanity-checked with Haversine distances from the final coordinates: Portland–Salem ≈ 44 miles, Portland–Bend ≈ 121 miles, Eugene–Salem ≈ 62 miles, Medford–Ashland ≈ 12 miles — all consistent with straight-line (not driving) distances.

## Corrections made (9 cities)

The first pass returned the **county** centroid instead of the town for 9 cities whose names match their county (or, for Wasco, a neighbouring county name). Each was re-queried with its county in the query string (e.g. `"Wheeler, Tillamook County, Oregon, USA"`) and the town result was kept:

| City | First result (wrong) | Corrected to |
|---|---|---|
| Hood River | Hood River County, 45.5312, −121.6476 | 45.7088, −121.5124 |
| Jefferson | Jefferson County, 44.6072, −121.2463 | 44.7224, −123.0074 (Marion County) |
| Tillamook | Tillamook County, 45.4603, −123.7267 | 45.4559, −123.8444 |
| Umatilla | Umatilla County, 45.6417, −118.7671 | 45.9174, −119.3425 |
| Union | Union County, 45.2680, −118.0257 | 45.2095, −117.8654 |
| Wallowa | Wallowa County, 45.5583, −117.1990 | 45.5700, −117.5277 |
| Wasco | Wasco County, 45.0430, −121.2154 | 45.5917, −120.6982 (Sherman County) |
| Wheeler | Wheeler County, 44.6768, −120.0484 | 45.6896, −123.8811 (Tillamook County, coast) |
| Yamhill | Yamhill County, 45.2298, −123.2180 | 45.3415, −123.1873 |

The Wheeler correction is the largest: the county centroid is in central Oregon, the town of Wheeler is on the coast (~150 miles away). The other eight were county centroids tens of miles from the towns.

## Naming variants (not errors — 3 cities)

Nominatim spells these with the full word; the coordinates are the correct towns:

- **Mt. Angel** → "Mount Angel", 45.0678, −122.7997
- **Mt. Vernon** → "Mount Vernon", 44.4176, −119.1142
- **St. Helens** → "Saint Helens", 45.8640, −122.8065

## Tiny / ambiguous cities checked

All found confidently as the Oregon town, in the expected county:

- Lonerock (one word) — 45.0890, −119.8831, Gilliam County
- Greenhorn — 44.7091, −118.4972, Baker County
- Shaniko — 45.0044, −120.7532, Wasco County
- Prescott — 46.0489, −122.8877, Columbia County
- Rufus — 45.6948, −120.7359, Sherman County
- Johnson City — 45.4044, −122.5794, Clackamas County
- Maywood Park — 45.5527, −122.5613, Multnomah County

## Reproducing this

- `geocode.py` — the main Nominatim run (resumable; progress in `geocode-progress.json`, log in `geocode.log`).
- `fix-counties.py` — the 9 county-centroid corrections above.
- If the city list in `oregon-cities.csv` changes, re-run `geocode.py` (delete `geocode-progress.json` first for a clean run, or keep it to only geocode new cities) and regenerate the CSV/JSON outputs. Do not hand-edit coordinates.
