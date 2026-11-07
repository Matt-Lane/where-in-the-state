#!/usr/bin/env python3
"""Geocode 241 Oregon cities via Nominatim, 1 req/sec, resumable."""
import csv, json, time, urllib.parse, urllib.request, urllib.error, os, sys

BASE = os.path.expanduser("~/workspace/game-project")
INPUT = os.path.join(BASE, "oregon-cities.csv")
PROGRESS = os.path.join(BASE, "geocode-progress.json")
OUT_CSV = os.path.join(BASE, "oregon-cities-with-coords.csv")
OUT_JSON = os.path.join(BASE, "oregon-cities-with-coords.json")

UA = "OregonGeographyGame/1.0 (Muse agent geocoding Oregon cities for a Blazor geography game)"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}

LAT_MIN, LAT_MAX = 42.0, 46.3
LON_MIN, LON_MAX = -124.7, -116.5

def in_bounds(lat, lon):
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX

def load_cities():
    with open(INPUT, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        return [row['city'].strip() for row in r if row['city'].strip()]

def load_progress():
    if os.path.exists(PROGRESS):
        with open(PROGRESS, encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_progress(p):
    with open(PROGRESS, 'w', encoding='utf-8') as f:
        json.dump(p, f, indent=2, ensure_ascii=False)

def nominatim_query(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": q, "format": "json", "limit": 5, "addressdetails": 1,
    })
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code} for {q} attempt {attempt+1}", flush=True)
            if e.code in (429, 403, 503):
                wait = 60 * (attempt + 1)
                print(f"  rate/block, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            print(f"error {e} for {q} attempt {attempt+1}", flush=True)
            time.sleep(10)
    raise RuntimeError(f"failed after retries: {q}")

def pick_result(city, results):
    """Return best Oregon result, or (None, reason)."""
    if not results:
        return None, "no results"
    for r in results:
        try:
            lat = float(r["lat"]); lon = float(r["lon"])
        except Exception:
            continue
        addr = r.get("address", {}) or {}
        state = addr.get("state", "")
        country = addr.get("country_code", "")
        disp = r.get("display_name", "")
        # Must be Oregon, USA
        if state != "Oregon" and "Oregon" not in disp:
            continue
        if country and country != "us":
            continue
        if not in_bounds(lat, lon):
            continue
        # Prefer place results
        return {"city": city, "latitude": lat, "longitude": lon,
                "source": "Nominatim OpenStreetMap",
                "display_name": disp, "osm_type": r.get("type"), "osm_class": r.get("class")}, None
    return None, f"no Oregon/in-bounds result among {len(results)}: {[r.get('display_name') for r in results]}"

def main():
    cities = load_cities()
    print(f"{len(cities)} cities loaded", flush=True)
    progress = load_progress()
    done = progress.get("results", {})
    notes = progress.get("notes", {})
    print(f"resuming with {len(done)} already done", flush=True)

    for i, city in enumerate(cities):
        if city in done:
            continue
        q = f"{city}, Oregon, USA"
        print(f"[{len(done)+1}/{len(cities)}] {city}", flush=True)
        try:
            results = nominatim_query(q)
        except Exception as e:
            print(f"  ABORTING on error: {e}", flush=True)
            progress["results"] = done; progress["notes"] = notes
            save_progress(progress)
            sys.exit(2)
        picked, reason = pick_result(city, results)
        if picked:
            done[city] = picked
            print(f"  -> {picked['latitude']}, {picked['longitude']}  ({picked['display_name']})", flush=True)
        else:
            # retry with a more explicit query once
            q2 = f"{city} city, Oregon, United States"
            print(f"  first query failed ({reason}); retrying: {q2}", flush=True)
            time.sleep(1.2)
            try:
                results2 = nominatim_query(q2)
            except Exception as e:
                print(f"  ABORTING on retry error: {e}", flush=True)
                progress["results"] = done; progress["notes"] = notes
                save_progress(progress)
                sys.exit(2)
            picked2, reason2 = pick_result(city, results2)
            if picked2:
                done[city] = picked2
                print(f"  -> {picked2['latitude']}, {picked2['longitude']}  ({picked2['display_name']})", flush=True)
            else:
                notes[city] = f"unresolved: {reason} | retry: {reason2}"
                print(f"  UNRESOLVED: {notes[city]}", flush=True)
        progress["results"] = done; progress["notes"] = notes
        save_progress(progress)
        time.sleep(1.1)

    print(f"DONE: {len(done)} found, {len(notes)} unresolved", flush=True)
    if notes:
        for c, n in notes.items():
            print(f"  UNRESOLVED {c}: {n}", flush=True)

    # Write final outputs in input order
    rows = []
    for city in cities:
        if city in done:
            d = done[city]
            rows.append({"city": city, "latitude": d["latitude"], "longitude": d["longitude"], "source": d["source"]})
    with open(OUT_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=["city", "latitude", "longitude", "source"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump([{"name": r["city"], "latitude": r["latitude"], "longitude": r["longitude"]} for r in rows],
                  f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT_CSV} ({len(rows)} rows) and {OUT_JSON}", flush=True)

if __name__ == "__main__":
    main()
