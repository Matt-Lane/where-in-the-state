# Where in the State — Blazor WebAssembly

**Name:** the game is called **"Where in the State"** (first edition: Oregon).
Suggested GitHub repo name: `where-in-the-state`.

> **Rename note (2026-11-06):** the display name was changed from
> "Oregon Geography Game" to "Where in the State" (Oregon edition).
> Deliberately left unchanged: the `OregonGeographyGame.csproj` filename
> and the `OregonGeographyGame` C# namespace — renaming those would risk
> breaking the build for no user-visible benefit, and the project is
> Oregon-first anyway. Human-visible titles (this README, `Game.razor`,
> `index.html`) all say "Where in the State".

A web geography game in C# with Blazor WebAssembly. A blank map of a state
(outline + landmarks, no city names) is shown; each round names a city and
the player clicks/taps where they think it is. Points are based on the
distance between the guess and the real city. 10 questions per game, max
1,000 points. Oregon is the first state pack; the architecture is generic
for any state.

> **Build status:** `dotnet` is **not installed** in the VM where this
> skeleton was written, so `dotnet build` / `dotnet run` have **not** been
> run here and no successful build is claimed. The files were written to
> match the spec and checked for syntactic plausibility (balanced braces,
> no invented namespaces), but run `dotnet build` on a machine with the
> .NET 8 SDK before trusting a build.

## Prerequisites

- .NET 8 SDK (`dotnet --version` should report 8.x)
- A modern browser

## How to run

```bash
cd blazor
dotnet run
```

Then open the URL printed by `dotnet run` (usually `https://localhost:XXXX`
or `http://localhost:5XXX`). No server is needed beyond serving the static
Blazor WebAssembly files — the game runs entirely in the browser.

## Project layout

```
OregonGeographyGame.csproj     Blazor WebAssembly, net8.0
Program.cs                     Host builder; registers HttpClient, SeededGameService,
                               DistanceService, StatePackLoader; root component App
App.razor                      Router
_Imports.razor                 Shared usings
Shared/MainLayout.razor        Minimal page layout
Models/
  City.cs                      record City(Name, Latitude, Longitude)
  StatePack.cs                 StatePack, LandmarkLayer, MapFeature, MapBounds
  GameConfig.cs                GameConfig(StateId, Seed, QuestionCount = 10)
  RoundResult.cs               RoundResult(City, GuessLat/Lon, DistanceMiles, Points)
Services/
  SeededGameService.cs         SHA-256 -> int -> Random -> Fisher-Yates, Take(10);
                               DailySeed() "yyyy-MM-dd", RandomSeed() 6 chars
  DistanceService.cs           Haversine (R = 3959 mi) + ScoreForDistance
  MapProjection.cs             Equirectangular + cos(44°); LatLonToSvg / SvgToLatLon
                               are exact inverses; viewBox 0 0 1000 757.4
  StatePackLoader.cs           Loads state.json / cities.json / outline.geojson /
                               landmarks.geojson via HttpClient; parses GeoJSON
                               with System.Text.Json into MapFeature values
Components/
  MapView.razor                SVG map: outline + landmark layers with toggles,
                               provisional (blue) / guess (red) / true (green)
                               pins, dashed connecting line, click -> lat/lon.
                               No city labels, ever.
Pages/
  Game.razor                   Full flow: Start -> 10 Rounds (+ Reveal) -> Results.
                               Routed at "/", "/{state}", "/{state}/{mode}" and
                               "/{state}/{mode}/{seed}".
wwwroot/
  index.html                   #app div + blazor.webassembly.js
  css/app.css                  Map + page styling (pins, layers, layout)
  data/states.json             Index of state packs: [{"id":"oregon","name":"Oregon"}]
  data/states/oregon/
    state.json                 Pack manifest (bounds, layers, file names)
    cities.json                241 Oregon cities with coordinates (copied verbatim)
    outline.geojson            State outline (copied verbatim)
    landmarks.geojson          177 landmark features (copied verbatim)
```

## How seed, scoring, and projection work

### Seed (SeededGameService, GAME-SPEC.md §5)

1. SHA-256 of the UTF-8 seed string; first 4 bytes as an `int`
   (`BitConverter.ToInt32(hash, 0)`).
2. `new Random(seedInt)`, Fisher-Yates shuffle of a *copy* of the city pool.
3. Take the first 10. No repeats within a game (shuffle = sampling without
   replacement). `string.GetHashCode()` is never used — it is not stable
   across runtimes/runs.
4. Daily seed: `yyyy-MM-dd` (local date). Random seed: 6
   alphanumeric characters. Seeds are forced to upper case and are written into
   the URL on start (`/oregon/cities/<seed>`), so a shared link loads the
   same game; loading with a state/mode/seed pre-fills the start screen. The
   old `?state=oregon&seed=...` query form and the `/{state}/{seed}` path form
   are no longer supported. An unknown state or mode in the URL shows a
   not-found screen instead of hanging on "Loading the map…".

### Scoring (DistanceService, GAME-SPEC.md §6, updated rule)

Distance is Haversine in miles (earth radius 3,959 mi), displayed to
1 decimal place. Points use the *rounded* whole-mile distance:

```
points = 100                         if rounded miles <= 5
points = max(0, 100 - (rounded - 5)) otherwise
```

So 5 mi = 100, 6 mi = 99, 10 mi = 95, 55 mi = 50, 105+ mi = 0. Floored at
0 — never negative. A pass (no pin) = 0 points, distance shown as "—".
Max per game: 10 × 100 = 1,000.

### Projection (MapProjection, GAME-SPEC.md §9)

Equirectangular with a cos(44°) correction (longitude degrees are shorter
than latitude degrees at Oregon's latitude). Bounds: lon −124.716 to
−116.314, lat 41.843 to 46.421; viewBox `0 0 1000 757.4`. The scale is
`1000 / ((LonMax − LonMin) × cos44°)`; the viewBox height is
`(LatMax − LatMin) × scale ≈ 757.4`.

**The same formulas draw the map and convert clicks back to lat/lon:**
`LatLonToSvg` and `SvgToLatLon` are exact inverses. If they ever diverge,
clicks and the drawn outline silently disagree and scoring breaks — that
is a release-blocking check (click a known location, e.g. downtown
Portland, and verify the converted lat/lon is within ~2 miles).

Known limitation in this skeleton: `MapView` converts pointer offsets
(CSS pixels) to viewBox units using its `RenderedWidth`/`RenderedHeight`
parameters (default 1000 × 757.4, i.e. the SVG at its natural size). If the
page CSS scales the SVG to a different rendered size, pass the actual
rendered size — or add a small resize observer / JS interop call to measure
it. The projection itself is unaffected.

### Relation to the playable JS prototype

The click-test prototype (Space "Oregon Map — Click Test") uses the same
seed *format*, the same scoring rule, and the same projection — but its
10-city selection for a given seed will **differ** from this C# version:
the JS prototype hashes the seed with SHA-256 and feeds it to a
**mulberry32** PRNG, while the C# version feeds the SHA-256-derived int to
**`System.Random`**. The PRNGs are not identical, so the same seed picks
different cities in the two versions. The C# `System.Random` version is
the canonical one per the spec. Same seed format, same scoring, different
shuffle output — compare scores only within one implementation.

## How to add a new state pack (no C# changes)

1. Create `wwwroot/data/states/<state-id>/` with the four files:
   - `state.json` — manifest: `id`, `name`, `abbreviation`, `bounds`
     (`lonMin`/`lonMax`/`latMin`/`latMax`), `layers` (each `id`, `label`,
     `visibleByDefault`), `files` (`cities`, `outline`, `landmarks`).
   - `cities.json` — array of `{ "name", "latitude", "longitude" }`.
   - `outline.geojson` — GeoJSON FeatureCollection, Polygon/MultiPolygon.
   - `landmarks.geojson` — GeoJSON FeatureCollection; each feature's
     `properties.layer` is one of the manifest layer ids (e.g.
     `interstate`, `highway`, `river`, `lake`); LineString/MultiLineString
     for lines, Polygon/MultiPolygon for lakes.
2. Add `{"id": "<state-id>", "name": "<Name>"}` to
   `wwwroot/data/states.json`.
3. Play a test game with a fixed seed and verify: outline renders, all 10
   sampled cities are inside the outline, landmarks render, scoring works.
4. No C# changes should be needed. If one is, the pack abstraction leaked
   and should be fixed.

Note: `MapProjection` currently holds the Oregon bounds as constants.
A second state with different bounds will need the projection to take its
bounds from the loaded pack (constructor parameters) instead of constants
— that is the one known piece of Oregon-specific code to generalise when
the second pack lands.
