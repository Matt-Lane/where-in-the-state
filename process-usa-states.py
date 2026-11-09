"""Extract the 50 US states + DC from Natural Earth 10m admin_1, simplify,
and write a small GeoJSON for the splash-page USA map.

Source: Natural Earth 10m admin_1_states_provinces (same source family as
the game's landmarks, Natural Earth 10m). Only the 51 features whose
admin is "United States of America" are kept (50 states + District of
Columbia). Each feature keeps: name, postal (state abbreviation), and
available (true only for Oregon — the only state pack that exists).

Simplification: pure-Python Douglas-Peucker per ring (shapely is not
installed). Tolerance 0.12 degrees — coarse for a decorative overview
map, which keeps the file small — except the Great Lakes states
(Minnesota, Wisconsin, Illinois, Michigan, Ohio, Indiana), which use
0.03 degrees so their shorelines read correctly. Rings are classified
outer-vs-hole by a point-in-polygon test so holes (if any) stay holes.

Michigan: Natural Earth stores Michigan as a SINGLE ring whose interior
includes the Mackinac Strait water (the Great Lakes are separate
features meant to be drawn on top), so the state alone renders as one
blob with the two peninsulas fused. split_michigan_ring() cuts that
ring into Upper and Lower Peninsula rings across the strait, so
Michigan is emitted as a MultiPolygon. See that function for the
details and the root cause.

Alaska / Hawaii insets: the coordinates in the output are DISPLAY
coordinates, not true geography, for Alaska and Hawaii. Their lon/lat
are scaled and translated into the standard inset layout (Alaska
bottom-left, Hawaii below the southwest, both under the contiguous US),
so a plain linear lon/lat -> SVG mapping puts them in the right place.
The contiguous US keeps true lon/lat. Documented here and in
data/USA-MAP-NOTES.md.

Writes:
  data/usa-states.geojson (source, read by build-game.py)
  blazor/wwwroot/data/usa-states.geojson (loaded by the Blazor splash page)

Run from the project root:  python3 process-usa-states.py
"""
import json
import math
import os
import sys

import shapefile

SRC = "/tmp/ne_admin1/ne_10m_admin_1_states_provinces.shp"
OUT_SOURCE = "data/usa-states.geojson"
OUT_BLAZOR = "blazor/wwwroot/data/usa-states.geojson"

# Douglas-Peucker tolerance in degrees.
TOLERANCE = 0.12
# Finer tolerance for the Great Lakes states (MN, WI, IL, MI, OH, IN).
# Their shorelines — Minnesota's North Shore, Wisconsin's Door County,
# the Lake Michigan shores — need more detail than 0.12° to read
# correctly; at 0.12° they come out angular and distorted. 0.03° keeps
# the Great Lakes shorelines recognizable while the file stays well
# under its 200 KB budget. Every other state keeps TOLERANCE, so their
# shapes are unchanged.
GL_TOLERANCE = 0.03
GREAT_LAKES_STATES = {"Minnesota", "Wisconsin", "Illinois", "Michigan", "Ohio", "Indiana"}

# Display canvas (lon/lat space) for the inset layout.
# Contiguous US keeps true lon/lat (lon -125..-66, lat 24..50).
# Alaska and Hawaii are moved into the band below it (lat ~14..23).
AK_SCALE = 0.35
# Target bounding boxes in display lon/lat for the insets:
# Alaska bottom-left, Hawaii to its right, both under the contiguous US.
AK_TARGET = (-125.0, -112.0, 14.0, 23.0)   # lonMin, lonMax, latMin, latMax
HI_TARGET = (-110.0, -100.0, 14.0, 22.0)


def point_in_ring(px, py, ring):
    """Ray-casting point-in-polygon. ring is a list of (x, y)."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _perp_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def douglas_peucker(pts, tol):
    """Simplify an open polyline. pts is a list of (x, y)."""
    if len(pts) <= 2:
        return list(pts)
    # Iterative stack version to avoid recursion limits.
    keep = [False] * len(pts)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        x1, y1 = pts[a]
        x2, y2 = pts[b]
        max_d, idx = 0.0, -1
        for i in range(a + 1, b):
            d = _perp_dist(pts[i][0], pts[i][1], x1, y1, x2, y2)
            if d > max_d:
                max_d, idx = d, i
        if max_d > tol:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(pts, keep) if k]


def simplify_ring(ring, tol):
    """Simplify a closed ring (first == last). Keep it closed."""
    if len(ring) <= 4:
        return ring
    # Drop the duplicated closing point, simplify open, re-close.
    open_pts = ring[:-1]
    simp = douglas_peucker(open_pts, tol)
    if len(simp) < 3:
        return ring
    simp.append(simp[0])
    return simp


def classify_rings(rings):
    """Split rings into polygons: [outer, hole, hole, ...] groups.

    A ring whose first point lies inside another ring is a hole of the
    (smallest) containing ring; otherwise it is an outer ring.
    """
    outers = []
    holes = []
    for ring in rings:
        container = None
        for other in rings:
            if other is ring:
                continue
            if point_in_ring(ring[0][0], ring[0][1], other):
                # Prefer the smallest containing ring.
                if container is None or _ring_area(other) < _ring_area(container):
                    container = other
        if container is None:
            outers.append(ring)
        else:
            holes.append((container, ring))
    polys = []
    for outer in outers:
        poly = [outer]
        for container, hole in holes:
            if container is outer:
                poly.append(hole)
        polys.append(poly)
    return polys


def _ring_area(ring):
    a = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _segments_cross(p1, p2, p3, p4):
    """True if segments p1-p2 and p3-p4 cross (proper intersection)."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def split_michigan_ring(ring):
    """Split Michigan's single ring into Upper and Lower Peninsula rings.

    Root cause: Natural Earth stores Michigan as ONE ring (a single part)
    whose interior includes the Mackinac Strait water — the Great Lakes
    are separate features meant to be drawn on top, so the state polygon
    alone fills the strait and the two peninsulas read as one blob. There
    was never a separate Upper Peninsula ring for the processing to lose;
    the separation has to be made explicitly by cutting the ring.

    The cut runs from the Upper Peninsula's eastern tip to the Green Bay /
    Menominee area, across northern Lake Michigan and the strait. The two
    cut points are found geometrically (closest ring point to a target
    coordinate in each area), not by hardcoded index, and the pair is
    accepted only if the cut segment does not cross the ring anywhere
    else — a crossed cut would make an invalid polygon. The cut points
    are the ring's first/last vertices of each new ring, so simplification
    keeps them and both new rings share the exact same cut edge.

    Returns [up_ring, lp_ring] (each closed, first == last), or None if
    no clean cut is found (caller falls back to the unsplit ring).
    """
    # Drop the closing duplicate for index math; re-close at the end.
    pts = ring[:-1] if ring[0] == ring[-1] else list(ring)
    n = len(pts)
    if n < 10:
        return None

    def closest_to(tx, ty, lon_lo, lon_hi, lat_lo, lat_hi):
        """Ring points in the given box, nearest target first."""
        cands = []
        for i, (x, y) in enumerate(pts):
            if lon_lo <= x <= lon_hi and lat_lo <= y <= lat_hi:
                cands.append((math.hypot(x - tx, y - ty), i))
        cands.sort()
        return [i for _, i in cands]

    # Eastern cut: the Upper Peninsula's eastern tip (De Tour area).
    # Western cut: the Green Bay / Menominee area, where the Lower
    # Peninsula's west shore meets the Upper Peninsula's south shore.
    a_cands = closest_to(-84.5, 46.5, -85.2, -84.0, 46.2, 46.7)
    b_cands = closest_to(-87.85, 45.45, -88.2, -87.5, 45.3, 45.6)
    for i_a in a_cands[:6]:
        for i_b in b_cands[:6]:
            a_pt, b_pt = pts[i_a], pts[i_b]
            # The cut must not cross the ring anywhere except at its
            # endpoints; a crossing would make an invalid polygon.
            crossed = False
            for i in range(n):
                j = (i + 1) % n
                if i in (i_a, i_b) or j in (i_a, i_b):
                    continue
                if _segments_cross(a_pt, b_pt, pts[i], pts[j]):
                    crossed = True
                    break
            if crossed:
                continue
            # Arc 1 (i_a -> i_b forward) is the Lower Peninsula (its
            # east shore, south border, west shore, Green Bay).
            # Arc 2 (i_b -> i_a forward, wrapping) is the Upper
            # Peninsula (south shore, west tip, north shore, east shore).
            # Each is closed with the shared cut segment.
            if i_a < i_b:
                arc_lp = pts[i_a:i_b + 1]
                arc_up = pts[i_b:] + pts[:i_a + 1]
            else:
                arc_lp = pts[i_a:] + pts[:i_b + 1]
                arc_up = pts[i_b:i_a + 1]
            ring_lp = arc_lp + [arc_lp[0]]
            ring_up = arc_up + [arc_up[0]]
            return [ring_up, ring_lp]
    return None


def transform_inset(pts, name, bbox):
    """Move Alaska / Hawaii into the standard inset layout (display lon/lat).

    Applied ONCE per state, using the state's overall bounding box, so all
    of a state's rings move together and keep their relative positions.
    (Applying it per ring would stack every island on top of the others.)
    """
    if name == "Alaska":
        # Scale about the bbox centre, then translate to the target box.
        min_x, max_x, min_y, max_y = bbox
        cx, cy = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
        scaled = [(cx + (x - cx) * AK_SCALE, cy + (y - cy) * AK_SCALE) for x, y in pts]
        xs = [p[0] for p in scaled]
        ys = [p[1] for p in scaled]
        tx = AK_TARGET[0] - min(xs)
        ty = AK_TARGET[2] - min(ys)
        return [(x + tx, y + ty) for x, y in scaled]
    if name == "Hawaii":
        min_x, max_x, min_y, max_y = bbox
        tx = HI_TARGET[0] - min_x
        ty = HI_TARGET[2] - min_y
        return [(x + tx, y + ty) for x, y in pts]
    return pts


def _bbox_of(rings):
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    return (min(xs), max(xs), min(ys), max(ys))


def main():
    if not os.path.exists(SRC):
        print("Missing source shapefile:", SRC)
        print("Download https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_1_states_provinces.zip and unzip it to /tmp/ne_admin1/")
        sys.exit(1)

    reader = shapefile.Reader(SRC)
    fields = [f[0] for f in reader.fields[1:]]
    name_i = fields.index("name")
    postal_i = fields.index("postal")
    admin_i = fields.index("admin")

    features = []
    total_pts = 0
    for shape_rec in reader.iterShapeRecords():
        rec = shape_rec.record
        if rec[admin_i] != "United States of America":
            continue
        name = rec[name_i]
        postal = rec[postal_i]
        shape = shape_rec.shape
        # Split the shape's points into rings by its parts.
        parts = list(shape.parts) + [len(shape.points)]
        rings = []
        for i in range(len(shape.parts)):
            ring = [(float(x), float(y)) for x, y in shape.points[parts[i]:parts[i + 1]]]
            if len(ring) >= 4:
                rings.append(ring)
        if not rings:
            continue
        # Hawaii: keep only the 8 main islands. The shapefile also carries
        # the far northwestern atolls (Midway, Kure, ...) as degenerate
        # point-rings at lon -162..-178, lat 23..28 — uninhabited, and
        # keeping them would stretch Hawaii's bbox to 23 degrees wide and
        # squeeze the main islands to nothing. Main islands are all below
        # latitude 23; the atolls are all above it.
        if name == "Hawaii":
            rings = [r for r in rings if (min(p[1] for p in r) + max(p[1] for p in r)) / 2.0 < 23.0]
        # Drop degenerate rings (essentially a single point, area ~ 0).
        rings = [r for r in rings if _ring_area(r) > 1e-6]
        if not rings:
            continue
        # Michigan: split the single ring into Upper and Lower Peninsula
        # rings (see split_michigan_ring — the source stores Michigan as
        # one ring whose interior includes the Mackinac Strait water).
        michigan_split = False
        if name == "Michigan" and len(rings) == 1:
            split = split_michigan_ring(rings[0])
            if split is not None:
                rings = split
                michigan_split = True
            else:
                print("WARNING: Michigan split failed — keeping single ring")
        # Simplify each ring, then apply the inset transform ONCE for the
        # whole state (from its overall bbox) so the rings keep their
        # relative positions. The Great Lakes states get the finer
        # tolerance so their shorelines read correctly.
        tol = GL_TOLERANCE if name in GREAT_LAKES_STATES else TOLERANCE
        simp_rings = [simplify_ring(ring, tol) for ring in rings]
        bbox = _bbox_of(simp_rings)
        simp_rings = [transform_inset(ring, name, bbox) for ring in simp_rings]
        if michigan_split:
            # The two peninsulas share the cut edge, so they are two
            # separate polygons — NOT one outer ring with a hole.
            # classify_rings would mistake one for a hole of the other
            # (the shared cut points lie on both rings' boundaries, and
            # a point-on-boundary test is ambiguous), so bypass it and
            # emit each ring as its own polygon.
            polys = [[ring] for ring in simp_rings]
        else:
            polys = classify_rings(simp_rings)
        # GeoJSON: Polygon if one polygon, MultiPolygon otherwise.
        if len(polys) == 1:
            geom = {"type": "Polygon", "coordinates": [[[round(x, 4), round(y, 4)] for x, y in ring] for ring in polys[0]]}
        else:
            geom = {"type": "MultiPolygon", "coordinates": [[[[round(x, 4), round(y, 4)] for x, y in ring] for ring in poly] for poly in polys]}
        total_pts += sum(len(ring) for poly in polys for ring in poly)
        features.append({
            "type": "Feature",
            "properties": {
                "name": name,
                "postal": postal,
                "available": name == "Oregon",
            },
            "geometry": geom,
        })

    features.sort(key=lambda f: f["properties"]["name"])
    geojson = {"type": "FeatureCollection", "features": features}
    text = json.dumps(geojson, separators=(",", ":"))
    for path in (OUT_SOURCE, OUT_BLAZOR):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    names = [f["properties"]["name"] for f in features]
    print(f"features: {len(features)}")
    print(f"names: {names}")
    print(f"Oregon present: {'Oregon' in names}, available: {[f['properties']['available'] for f in features if f['properties']['name'] == 'Oregon']}")
    print(f"total points: {total_pts}")
    print(f"file size: {len(text)} bytes ({len(text)/1024:.1f} KB)")
    print(f"wrote {OUT_SOURCE} and {OUT_BLAZOR}")


if __name__ == "__main__":
    main()
