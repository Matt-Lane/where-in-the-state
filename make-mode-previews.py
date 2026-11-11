#!/usr/bin/env python3
"""Generate the small preview SVGs for the game-mode buttons.

The mode selector shows one large button per mode, each with a little map
preview of how that mode plays:
  - Cities: a guess pin, a dotted line, and the actual city target.
  - Counties: the county "puzzle piece" staged off the map, with a dashed
    ghost of where it belongs and an arrow showing the drag.
  - Name the county: the county-boundary grid with one county highlighted.

The previews reuse the real Oregon outline and county geometry, projected
with the same equirectangular function as the game and simplified lightly
(Douglas-Peucker, tolerance 1.0 SVG unit) so the county boundaries follow
the real shapes instead of looking sketched on. Run it and paste the
printed path data into the Blazor and JS mode buttons.

City County Mode (added 2026-11-08) needs no new geometry: its preview is
a composition of the constants this script already prints — the Oregon
outline (OUTLINE_D), the county-boundary grid (GRID_D, drawn faint), the
Deschutes County piece (DESCHUTES_D, highlighted blue with the
preview-selected style), and a pin at Bend (BEND, the blue guess-pin
style). So there is nothing new to generate here; the Blazor button
(ModePreviewArt) and the JS button compose those four pieces by hand.
(2026-11-10: the City County preview became a diagonal split — Douglas
County highlighted green on the lower-left triangle, and a La Grande
city reveal on the upper-right triangle. Douglas (DOUGLAS_D), La Grande
(LA_GRANDE) and its guess point (SPLIT_GUESS) are printed below.)

Usage: python3 make-mode-previews.py
"""
import json
import math

BASE = "/home/hatch/workspace/game-project"
LON_MIN, LON_MAX = -124.716, -116.314
LAT_MIN, LAT_MAX = 41.843, 46.421
W, H = 1000, 757.4
COS = math.cos(math.radians(44))
X_RANGE = (LON_MAX - LON_MIN) * COS
Y_RANGE = LAT_MAX - LAT_MIN


def project(lon, lat):
    return ((lon - LON_MIN) * COS / X_RANGE * W,
            (LAT_MAX - lat) / Y_RANGE * H)


def douglas_peucker(pts, tol):
    """Simplify a polyline (list of (x, y)) with Douglas-Peucker."""
    if len(pts) <= 2:
        return pts

    def perp_dist(p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0, min(1, t))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def simplify(pts):
        if len(pts) <= 2:
            return pts
        dmax, idx = 0, 0
        for i in range(1, len(pts) - 1):
            d = perp_dist(pts[i], pts[0], pts[-1])
            if d > dmax:
                dmax, idx = d, i
        if dmax > tol:
            return simplify(pts[:idx + 1])[:-1] + simplify(pts[idx:])
        return [pts[0], pts[-1]]

    return simplify(pts)


def ring_to_path(ring_lonlat, tol, close=True):
    pts = [project(lon, lat) for lon, lat in ring_lonlat]
    pts = douglas_peucker(pts, tol)
    # Drop rings that collapsed to fewer than 3 distinct points (tiny
    # island rings that simplify to a dot — they would render as nothing).
    distinct = {(round(x, 1), round(y, 1)) for x, y in pts}
    if len(distinct) < 3:
        return ""
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return d + (" Z" if close else "")


def load_geojson(path):
    with open(path) as f:
        return json.load(f)


def main():
    outline = load_geojson(f"{BASE}/data/oregon/outline.geojson")
    counties = load_geojson(f"{BASE}/data/oregon/counties.geojson")

    # --- Oregon outline, simplified lightly so it stays exact ---
    outer = outline["features"][0]["geometry"]["coordinates"][0]
    outline_d = ring_to_path(outer, 1.0)
    print("OUTLINE_D =")
    print(outline_d)
    print()

    # --- County grid: every county boundary, simplified lightly ---
    grid_parts = []
    for feat in counties["features"]:
        geom = feat["geometry"]
        rings = []
        if geom["type"] == "Polygon":
            rings = geom["coordinates"]
        elif geom["type"] == "MultiPolygon":
            for poly in geom["coordinates"]:
                rings.extend(poly)
        for ring in rings:
            p = ring_to_path(ring, 1.0)
            if p:
                grid_parts.append(p)
    grid_d = " ".join(grid_parts)
    print("GRID_D =")
    print(grid_d)
    print()

    # --- Deschutes County, the puzzle piece (largest ring) ---
    deschutes = next(f for f in counties["features"]
                     if f["properties"]["name"] == "Deschutes County")
    geom = deschutes["geometry"]
    rings = geom["coordinates"] if geom["type"] == "Polygon" else \
        [p for poly in geom["coordinates"] for p in poly]
    # Largest ring by point count is the main body.
    main_ring = max(rings, key=len)
    piece_d = ring_to_path(main_ring, 1.0)
    print("DESCHUTES_D =")
    print(piece_d)
    # Centroid (SVG) of the piece, for the staged offset and the arrow.
    pts = [project(lon, lat) for lon, lat in main_ring]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    print(f"DESCHUTES_CENTROID = ({cx:.1f}, {cy:.1f})")
    print()

    # --- Cities preview: Bend (actual) and a guess southwest of it ---
    bend = (44.0581728, -121.3153096)
    guess = (43.6, -122.8)
    bx, by = project(bend[1], bend[0])
    gx, gy = project(guess[1], guess[0])
    print(f"BEND (actual) = ({bx:.1f}, {by:.1f})")
    print(f"GUESS = ({gx:.1f}, {gy:.1f})")
    print()

    # --- Douglas County, highlighted in the City County split preview ---
    douglas = next(f for f in counties["features"]
                   if f["properties"]["name"] == "Douglas County")
    geom = douglas["geometry"]
    rings = geom["coordinates"] if geom["type"] == "Polygon" else \
        [p for poly in geom["coordinates"] for p in poly]
    main_ring = max(rings, key=len)
    douglas_d = ring_to_path(main_ring, 1.0)
    print("DOUGLAS_D =")
    print(douglas_d)
    print()

    # --- City County split preview, city half: La Grande (actual) and a
    # guess southwest of it. Both sit in the upper-right triangle (above
    # the top-left to bottom-right diagonal), so they survive the clip.
    la_grande = (45.324, -118.093)
    split_guess = (44.85, -119.6)
    lx, ly = project(la_grande[1], la_grande[0])
    sx, sy = project(split_guess[1], split_guess[0])
    print(f"LA_GRANDE (actual) = ({lx:.1f}, {ly:.1f})")
    print(f"SPLIT_GUESS = ({sx:.1f}, {sy:.1f})")
    print()


if __name__ == "__main__":
    main()
