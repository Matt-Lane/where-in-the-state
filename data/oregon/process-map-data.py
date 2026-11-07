#!/usr/bin/env python3
"""Build Oregon map data for the geography game from public sources.

Sources (all downloaded 2026-11-06, see MAP-DATA-NOTES.md):
  - Outline: U.S. Census Bureau 2010 cartographic boundary, gz_2010_us_040_00_500k.json
  - Rivers/lakes/roads: Natural Earth 10m (public domain)
    ne_10m_rivers_lake_centerlines.geojson, ne_10m_rivers_north_america.geojson,
    ne_10m_lakes.geojson, ne_10m_lakes_north_america.geojson, ne_10m_roads.geojson
Usage: python3 process-map-data.py   (run from the directory holding the raw downloads)
Outputs: ../../data/oregon/outline.geojson, ../../data/oregon/landmarks.geojson
"""
import json, math, os, sys

RAW = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.expanduser("~/workspace/game-project/data/oregon")

# Oregon bounds from the Census outline bbox, plus a small margin for clipping.
LON_MIN, LON_MAX = -124.75, -116.35
LAT_MIN, LAT_MAX = 41.90, 46.40

def load(fn):
    with open(os.path.join(RAW, fn)) as f:
        return json.load(f)

def feat_bbox(coords):
    xs, ys = [], []
    def walk(c):
        if isinstance(c, list) and c and isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        elif isinstance(c, list):
            for x in c: walk(x)
    walk(coords)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None

def overlaps(b):
    return bool(b) and b[2] > LON_MIN and b[0] < LON_MAX and b[3] > LAT_MIN and b[1] < LAT_MAX

# ---- Douglas-Peucker simplification (tolerance in degrees) ----
def _perp_dist(p, a, b):
    ax, ay, bx, by, px, py = a[0], a[1], b[0], b[1], p[0], p[1]
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

def dp(points, tol):
    if len(points) <= 2:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        dmax, idx = 0.0, -1
        for k in range(i + 1, j):
            d = _perp_dist(points[k], points[i], points[j])
            if d > dmax:
                dmax, idx = d, k
        if dmax > tol:
            keep[idx] = True
            stack.append((i, idx)); stack.append((idx, j))
    return [p for p, k in zip(points, keep) if k]

def simplify_line(line, tol):
    out = dp(line, tol)
    return out if len(out) >= 2 else line[:2]

def simplify_ring(ring, tol):
    # closed ring: drop duplicate last point, simplify, re-close
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    out = dp(pts + [pts[0]], tol)
    if out[0] != out[-1]:
        out.append(out[0])
    return out

# ---- Clip a polyline to the Oregon bbox (split at boundaries) ----
def clip_line(line):
    segs, cur = [], []
    def inside(p):
        return LON_MIN <= p[0] <= LON_MAX and LAT_MIN <= p[1] <= LAT_MAX
    def intersect(p, q):
        # first bbox-boundary crossing between p (in) and q (out) or vice versa
        best = None
        for t, pt in _crossings(p, q):
            if best is None or t < best[0]:
                best = (t, pt)
        return best[1] if best else q
    for p in line:
        if inside(p):
            if cur and not inside(line[line.index(p) - 1]) if False else False:
                pass
            cur.append(p)
        else:
            if cur:
                cur.append(intersect(cur[-1], p))
                segs.append(cur); cur = []
    if len(cur) >= 2:
        segs.append(cur)
    return [s for s in segs if len(s) >= 2]

def _crossings(p, q):
    out = []
    dx, dy = q[0] - p[0], q[1] - p[1]
    for bound, axis in ((LON_MIN, 0), (LON_MAX, 0), (LAT_MIN, 1), (LAT_MAX, 1)):
        if dx if axis == 0 else dy:
            denom = dx if axis == 0 else dy
            if denom == 0:
                continue
            t = (bound - (p[0] if axis == 0 else p[1])) / denom
            if 0 <= t <= 1:
                out.append((t, [p[0] + t * dx, p[1] + t * dy]))
    return out

# Fix clip_line: simpler robust version — walk segments, keep in-bounds portions
def clip_line2(line):
    segs, cur = [], []
    for i in range(len(line) - 1):
        p, q = line[i], line[i + 1]
        pin = LON_MIN <= p[0] <= LON_MAX and LAT_MIN <= p[1] <= LAT_MAX
        qin = LON_MIN <= q[0] <= LON_MAX and LAT_MIN <= q[1] <= LAT_MAX
        if pin and qin:
            if not cur:
                cur = [p]
            cur.append(q)
        elif pin and not qin:
            cross = _crossings(p, q)
            pt = cross[0][1] if cross else q
            if not cur:
                cur = [p]
            cur.append(pt)
            segs.append(cur); cur = []
        elif not pin and qin:
            cross = _crossings(p, q)
            pt = cross[0][1] if cross else q
            cur = [pt, q]
        else:
            # both out: segment may still cross a corner of the box; ignore
            # (rare for these datasets; the outline check below catches issues)
            if cur:
                segs.append(cur); cur = []
    if len(cur) >= 2:
        segs.append(cur)
    return [s for s in segs if len(s) >= 2]

clip_line = clip_line2

# ================= OUTLINE =================
states = load("us-states.json")
oregon = next(f for f in states["features"] if f["properties"].get("NAME") == "Oregon")
ring = oregon["geometry"]["coordinates"][0]
print(f"outline raw points: {len(ring)}")
ring_s = simplify_ring(ring, 0.008)
print(f"outline simplified points: {len(ring_s)}")
outline = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"name": "Oregon", "source": "U.S. Census Bureau, 2010 cartographic boundary (gz_2010_us_040_00_500k)"},
        "geometry": {"type": "Polygon", "coordinates": [ring_s]},
    }],
}

# ================= RIVERS =================
RIVER_NAMES = {
    "Columbia", "Willamette", "Rogue", "John Day", "Klamath", "Deschutes",
    "Umpqua", "North Umpqua", "South Umpqua", "Grande Ronde", "Malheur",
    "Owyhee", "Clackamas", "Nehalem", "Santiam", "North Santiam",
    "South Santium", "Crooked", "Williamson", "Sprague", "North Fork Sprague",
    "Sycan", "North Umpqua",
}
rivers = []
seen_rivers = set()
for fn in ("ne_rivers.geojson", "ne_rivers_na.geojson"):
    d = load(fn)
    for f in d["features"]:
        p = f.get("properties") or {}
        name = p.get("name")
        if not name or name not in RIVER_NAMES:
            continue
        if p.get("featurecla") not in ("River", "Lake Centerline"):
            continue
        g = f.get("geometry")
        if not g or not g.get("coordinates"):
            continue
        key = (name, p.get("featurecla"))
        lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        for line in lines:
            for seg in clip_line(line):
                seg_s = simplify_line(seg, 0.004)
                rivers.append({
                    "type": "Feature",
                    "properties": {"layer": "river", "name": name + " River"},
                    "geometry": {"type": "LineString", "coordinates": [[round(x, 5), round(y, 5)] for x, y in seg_s]},
                })
        seen_rivers.add(name)
print(f"rivers: {len(rivers)} segments, names: {sorted(seen_rivers)}")

# ================= LAKES =================
LAKE_NAMES = {
    "Goose Lake", "Malheur Lake", "Harney Lake", "Upper Klamath Lake",
    "Lake Abert", "Summer Lake", "Crater Lake", "Owyhee Reservoir",
    "Fern Ridge Reservoir", "Wickiup Reservoir", "Warm Springs Reservoir",
}
lakes = []
seen_lakes = set()
for fn in ("ne_lakes.geojson", "ne_lakes_na.geojson"):
    d = load(fn)
    for f in d["features"]:
        p = f.get("properties") or {}
        name = p.get("name")
        if not name or name not in LAKE_NAMES:
            continue
        g = f.get("geometry")
        if not g or not g.get("coordinates"):
            continue
        if name in seen_lakes:
            continue
        seen_lakes.add(name)
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out_polys = []
        for poly in polys:
            rings = [simplify_ring(r, 0.004) for r in poly]
            rings = [[[round(x, 5), round(y, 5)] for x, y in r] for r in rings]
            out_polys.append(rings)
        lakes.append({
            "type": "Feature",
            "properties": {"layer": "lake", "name": name},
            "geometry": {"type": "MultiPolygon", "coordinates": out_polys},
        })
print(f"lakes: {len(lakes)} names: {sorted(seen_lakes)}")

# ================= ROADS =================
INTERSTATES = {"5", "84", "82", "205", "405"}
roads = load("ne_roads.geojson")
interstates, highways = [], []
for f in roads["features"]:
    p = f.get("properties") or {}
    name = p.get("name")
    if not name:
        continue
    g = f.get("geometry")
    if not g or not g.get("coordinates"):
        continue
    b = feat_bbox(g["coordinates"])
    if not overlaps(b):
        continue
    layer = "interstate" if name in INTERSTATES else "highway"
    # highways: keep Major/Secondary/Road types only (drops Ferry etc.)
    if layer == "highway" and p.get("type") not in ("Major Highway", "Secondary Highway", "Road"):
        continue
    lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
    for line in lines:
        for seg in clip_line(line):
            seg_s = simplify_line(seg, 0.004)
            (interstates if layer == "interstate" else highways).append({
                "type": "Feature",
                "properties": {"layer": layer, "name": ("I-" if layer == "interstate" else "") + name},
                "geometry": {"type": "LineString", "coordinates": [[round(x, 5), round(y, 5)] for x, y in seg_s]},
            })
print(f"interstates: {len(interstates)} segments; highways: {len(highways)} segments")
print("interstate routes:", sorted({f['properties']['name'] for f in interstates}))
print("highway routes:", sorted({f['properties']['name'] for f in highways}))


# ---- Filter line features to those touching Oregon ----
# The bbox clip above lets in fragments of roads/rivers just across the
# Columbia / Snake in Washington and Idaho. A line feature is kept only if
# at least one of its points lies inside the outline or within 0.02 degrees
# of it (so border-crossing roads and the Columbia River itself survive).
def _pip(lon, lat, poly):
    inside = False; n = len(poly); j = n - 1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def _pt_seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

def _touches_oregon(coords):
    for x, y in coords:
        if _pip(x, y, ring_s):
            return True
        d = min(_pt_seg_dist(x, y, ring_s[i][0], ring_s[i][1], ring_s[i + 1][0], ring_s[i + 1][1])
                for i in range(len(ring_s) - 1))
        if d <= 0.02:
            return True
    return False

landmarks = {"type": "FeatureCollection", "features": interstates + highways + rivers + lakes}

kept, dropped = [], []
for _f in landmarks["features"]:
    _g = _f["geometry"]
    if _g["type"] == "LineString":
        if _touches_oregon(_g["coordinates"]):
            kept.append(_f)
        else:
            dropped.append(_f)
    else:
        kept.append(_f)
print(f"outline filter: kept {len(kept)} features, dropped {len(dropped)} out-of-state fragments")
for _f in sorted(dropped, key=lambda f: (f["properties"]["layer"], f["properties"]["name"])):
    print("  dropped:", _f["properties"]["layer"], _f["properties"]["name"])
landmarks = {"type": "FeatureCollection", "features": kept}

os.makedirs(OUTDIR, exist_ok=True)
with open(os.path.join(OUTDIR, "outline.geojson"), "w") as f:
    json.dump(outline, f)
with open(os.path.join(OUTDIR, "landmarks.geojson"), "w") as f:
    json.dump(landmarks, f)
for fn in ("outline.geojson", "landmarks.geojson"):
    p = os.path.join(OUTDIR, fn)
    print(fn, os.path.getsize(p), "bytes")
