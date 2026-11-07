#!/usr/bin/env python3
"""Fix 9 county-centroid results with county-specific Nominatim queries."""
import json, time, urllib.parse, urllib.request, os

BASE = os.path.expanduser("~/workspace/game-project")
PROGRESS = os.path.join(BASE, "geocode-progress.json")

FIXES = {
    "Hood River": "Hood River, Hood River County, Oregon, USA",
    "Jefferson": "Jefferson, Marion County, Oregon, USA",
    "Tillamook": "Tillamook, Tillamook County, Oregon, USA",
    "Umatilla": "Umatilla, Umatilla County, Oregon, USA",
    "Union": "Union, Union County, Oregon, USA",
    "Wallowa": "Wallowa, Wallowa County, Oregon, USA",
    "Wasco": "Wasco, Sherman County, Oregon, USA",
    "Wheeler": "Wheeler, Tillamook County, Oregon, USA",
    "Yamhill": "Yamhill, Yamhill County, Oregon, USA",
}
HEADERS = {"User-Agent": "OregonGeographyGame/1.0 (Muse agent geocoding Oregon cities for a Blazor geography game)", "Accept": "application/json"}

def query(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "limit": 5, "addressdetails": 1})
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))

def main():
    progress = json.load(open(PROGRESS, encoding='utf-8'))
    results = progress["results"]
    notes = progress.get("notes", {})
    corrections = progress.get("corrections", {})
    for city, q in FIXES.items():
        old = results[city]
        print(f"{city}: old {old['latitude']}, {old['longitude']} ({old['display_name']})", flush=True)
        res = query(q)
        print(f"  candidates: {[r.get('display_name') for r in res]}", flush=True)
        picked = None
        for r in res:
            disp = r.get("display_name", "")
            first = disp.split(",")[0].strip()
            # accept if first component is the city itself, not a county, and in Oregon
            if "County" in first:
                continue
            if first.lower() not in (city.lower(), city.lower().replace("mt.", "mount"), city.lower().replace("st.", "saint")):
                # allow exact city name match only (plus Mt/St variants handled above)
                if first.lower() != city.lower():
                    continue
            lat, lon = float(r["lat"]), float(r["lon"])
            if not (42.0 <= lat <= 46.3 and -124.7 <= lon <= -116.5):
                continue
            if (r.get("address") or {}).get("state") != "Oregon":
                continue
            picked = {"city": city, "latitude": lat, "longitude": lon,
                      "source": "Nominatim OpenStreetMap", "display_name": disp,
                      "osm_type": r.get("type"), "osm_class": r.get("class")}
            break
        if picked:
            corrections[city] = {"old": old, "new": picked}
            results[city] = picked
            print(f"  FIXED -> {picked['latitude']}, {picked['longitude']} ({picked['display_name']})", flush=True)
        else:
            notes[city] = f"county-centroid fix failed; candidates: {[r.get('display_name') for r in res]}"
            print(f"  STILL UNRESOLVED", flush=True)
        time.sleep(1.2)
    progress["results"] = results
    progress["notes"] = notes
    progress["corrections"] = corrections
    with open(PROGRESS, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)
    print(f"Corrected {len(corrections)} cities", flush=True)
    for c, v in corrections.items():
        print(f"  {c}: {v['old']['latitude']},{v['old']['longitude']} -> {v['new']['latitude']},{v['new']['longitude']}", flush=True)

if __name__ == "__main__":
    main()
