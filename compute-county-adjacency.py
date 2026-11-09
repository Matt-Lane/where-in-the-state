"""Compute county adjacency from the RAW (unsimplified) Census shapefile
and embed the neighbor lists in the simplified counties GeoJSON.

Why the raw file: the simplified GeoJSON was Douglas-Peucker simplified
per county, so a shared border is a different chord in each county and
exact edge matching on the simplified file misses real borders (e.g.
Jackson/Josephine, Deschutes/Klamath). The raw shapefile
(cb_2023_us_county_500k, 15,199 Oregon points) is topologically clean:
counties that share a border use identical coordinates there.

Adjacency = two counties share at least one identical edge (a pair of
consecutive coordinates in a polygon ring, in either direction).
Sharing only a single corner point does NOT count.

Writes the neighbor list (county names, sorted) into each feature's
properties as "neighbors", in BOTH copies of the file:
  data/oregon/counties.geojson (source, read by build-game.py)
  blazor/wwwroot/data/states/oregon/counties.geojson (loaded by Blazor)

Also prints validation: every county's neighbor count, the
vertex-sharing pairs that are NOT edge-adjacent (the corner-only
contacts, which must be excluded), and spot checks against known
Oregon geography. Exits non-zero without writing if validation fails.
"""
import json
from collections import defaultdict

import shapefile

SHP = "data/oregon/counties-raw/cb_2023_us_county_500k.shp"
SRC = "data/oregon/counties.geojson"
DEST = "blazor/wwwroot/data/states/oregon/counties.geojson"


def rings_of_shape(shape):
    """Split a pyshp Polygon shape into its rings (parts)."""
    pts = shape.points
    parts = list(shape.parts) + [len(pts)]
    return [pts[parts[i]:parts[i + 1]] for i in range(len(shape.parts))]


def main():
    reader = shapefile.Reader(SHP)
    field_names = [f[0] for f in reader.fields[1:]]
    idx_state = field_names.index("STATEFP")
    idx_name = field_names.index("NAME")
    records = reader.records()
    shapes = reader.shapes()
    oregon = [(rec[idx_name] + " County", shapes[i])
              for i, rec in enumerate(records) if rec[idx_state] == "41"]
    oregon.sort(key=lambda t: t[0])
    names = [n for n, _ in oregon]
    assert len(names) == 36, f"expected 36 Oregon counties, got {len(names)}"

    # Edge -> set of county indexes sharing it. An edge is the unordered
    # pair of its two endpoints (as exact coordinate tuples).
    edge_owners = defaultdict(set)
    # Vertex -> set of county indexes touching it (for corner-only check).
    vertex_owners = defaultdict(set)
    for i, (_, shape) in enumerate(oregon):
        for ring in rings_of_shape(shape):
            pts = [tuple(p) for p in ring]
            for p in pts:
                vertex_owners[p].add(i)
            for a, b in zip(pts, pts[1:]):
                if a == b:
                    continue
                edge_owners[(a, b) if a < b else (b, a)].add(i)

    neighbors = defaultdict(set)
    for owners in edge_owners.values():
        if len(owners) < 2:
            continue
        for i in owners:
            neighbors[i] |= owners - {i}

    # Vertex-sharing pairs that share NO edge: corner-only contacts.
    vertex_pairs = set()
    for owners in vertex_owners.values():
        owners = sorted(owners)
        for a in range(len(owners)):
            for b in range(a + 1, len(owners)):
                vertex_pairs.add((owners[a], owners[b]))
    edge_pairs = set()
    for owners in edge_owners.values():
        owners = sorted(owners)
        for a in range(len(owners)):
            for b in range(a + 1, len(owners)):
                edge_pairs.add((owners[a], owners[b]))
    corner_only = sorted(vertex_pairs - edge_pairs)

    # Validation output.
    print("Neighbor counts (edge-adjacent, from raw shapefile):")
    counts = []
    for i, name in enumerate(names):
        n = sorted(names[j] for j in neighbors[i])
        counts.append(len(n))
        print(f"  {name}: {len(n)} -> {', '.join(n)}")
    print(f"total counties: {len(names)}, min neighbors: {min(counts)}, "
          f"max neighbors: {max(counts)}, zero-neighbor: "
          f"{[names[i] for i, c in enumerate(counts) if c == 0]}")
    print(f"corner-only (vertex but no edge) pairs: {len(corner_only)}")
    for a, b in corner_only:
        print(f"  {names[a]} <-> {names[b]} (point contact only)")

    # Spot checks against known Oregon geography.
    by_name = {n: i for i, n in enumerate(names)}

    def check(a, b, expect):
        got = by_name[b] in neighbors[by_name[a]]
        print(f"  {'OK ' if got == expect else 'FAIL'} {a} <-> {b}: "
              f"adjacent={got} (expected {expect})")
        return got == expect

    ok = True
    ok &= check("Marion County", "Clackamas County", True)
    ok &= check("Clackamas County", "Multnomah County", True)
    ok &= check("Clackamas County", "Washington County", True)
    ok &= check("Clackamas County", "Yamhill County", True)
    ok &= check("Clackamas County", "Wasco County", True)
    ok &= check("Clackamas County", "Hood River County", True)
    ok &= check("Clackamas County", "Curry County", False)
    ok &= check("Marion County", "Linn County", True)
    ok &= check("Marion County", "Polk County", True)
    ok &= check("Marion County", "Yamhill County", True)
    ok &= check("Marion County", "Jefferson County", True)
    ok &= check("Marion County", "Wasco County", True)
    # Borders the simplified-file pass missed (simplification divergence).
    ok &= check("Jackson County", "Josephine County", True)
    ok &= check("Jackson County", "Klamath County", True)
    ok &= check("Deschutes County", "Klamath County", True)
    ok &= check("Deschutes County", "Jefferson County", True)
    ok &= check("Deschutes County", "Lake County", True)
    ok &= check("Deschutes County", "Harney County", True)
    ok &= check("Crook County", "Grant County", True)
    ok &= check("Grant County", "Malheur County", True)
    ok &= check("Baker County", "Wallowa County", True)
    ok &= check("Umatilla County", "Wallowa County", True)
    ok &= check("Benton County", "Polk County", True)
    ok &= check("Polk County", "Yamhill County", True)
    ok &= check("Clackamas County", "Marion County", True)  # symmetry
    print("spot checks:", "ALL PASS" if ok else "FAILURES — investigate")
    if not ok or min(counts) == 0:
        raise SystemExit("adjacency validation failed; not writing files")

    # Sanity: the neighbor sets must be symmetric.
    for i, name in enumerate(names):
        for j in neighbors[i]:
            assert i in neighbors[j], f"asymmetric: {name} -> {names[j]}"
    print("symmetry: OK")

    with open(SRC) as f:
        data = json.load(f)
    geo_names = {f["properties"]["name"] for f in data["features"]}
    assert geo_names == set(names), "GeoJSON county names differ from shapefile"
    for feat in data["features"]:
        feat["properties"]["neighbors"] = sorted(
            names[j] for j in neighbors[by_name[feat["properties"]["name"]]])

    with open(SRC, "w") as f:
        json.dump(data, f)
    with open(DEST, "w") as f:
        json.dump(data, f)
    print(f"wrote neighbors into {SRC} and {DEST}")


if __name__ == "__main__":
    main()
