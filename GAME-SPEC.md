# Where in the State — Game Spec (v1 draft)

**First edition:** Oregon. The game name is generic for any state; Oregon is the first state pack. There is no "Oregon Edition" label in the UI; once a game starts, the header title is `Where in the {StateName}?!` — derived from the state pack's `Name` field (so a future state gets its own title automatically) — and it stays that way through the results screen; the browser tab follows the same rule. Before a game starts the title is "Where in the State" — except when the URL named the state (e.g. `/oregon/`), in which case the start screen header already says `Where in the {StateName}?!`. The root URL `/` is the splash/welcome page (see §4.1), not the start screen.

**Version:** 0.35, shown in the footer of both the Blazor app and the standalone JavaScript version. Format is `major.minor`; the minor number is incremented on every merge to main.

**Date:** 2026-11-06
**Status:** Draft for Matt to review — map approach decided 2026-11-06: SVG + GeoJSON natively in Blazor (see §9, Option A). Click-test prototype built and audited 2026-11-06 (see Appendix).
**Owner:** Matt
**Purpose:** A fun learning tool for Matt's organization, whose work touches many different Oregon cities. Players learn where those cities actually are by guessing, seeing how far off they were, and trying again.

---

## 1. Overview & goals

### 1.1 The game in one paragraph
A web game shows a blank map of a state — outline plus landmarks for orientation, but no city names or labels. Each round names one city ("Where is Bend?"). The player clicks or taps to drop a pin where they think that city is. The game then reveals the real location, shows the distance between the guess and the real city, and awards points based on that distance. After 10 rounds, the player gets a total score and a round-by-round breakdown.

### 1.2 Goals
- **Teach geography, kindly.** Scoring is forgiving (see §6). A bad guess costs points for that round, never goes negative, and the reveal is a learning moment, not a punishment.
- **Playable by anyone, anywhere, at different times, with the same game.** A seed (see §5) makes a game reproducible and shareable, so players can play the same 10 cities in the same order and compare scores fairly.
- **Oregon first, any state later.** Nothing in the game logic may hardcode Oregon. Oregon is the first *data pack*; adding a state means adding a data pack, not rewriting the game.
- **No server required to play.** The game runs entirely in the browser. That keeps hosting simple and makes the seed logic deterministic on the client.

### 1.3 Out of scope for v1
- Accounts, logins, saved profiles.
- A server-side leaderboard or score database. (Players can compare scores by sharing a seed and reporting their total — see Future Work, §12.)
- Multiple states in one game session, timed rounds, or streaks / difficulty modes.
- Offline map tiles (unless the chosen map approach in §9 makes it trivial).

---

## 2. Tech stack

| Area | Choice | Notes |
|---|---|---|
| Language / framework | **C# with Blazor WebAssembly** | Runs entirely in the browser; no server round-trip per guess. Blazor Server was considered and rejected for v1: it needs a live connection per player and adds hosting/state complexity for no gameplay benefit. |
| Hosting | Static hosting (any static host / GitHub Pages / Azure Static Web Apps, etc.) | The built Blazor WASM app is static files. No API server is needed for v1. |
| Map rendering | **SVG + GeoJSON natively in Blazor (decided 2026-11-06)** | Equirectangular projection with cos(44°) correction, same function for drawing and click-to-lat/lon. See §9, Option A. |
| Data | JSON files shipped with the app (per state pack) | City list + coordinates, state outline, landmark layers. See §3. |
| Randomization | `System.Random` seeded from a hash of the seed string (§5) | Deterministic across browsers and runs. Do not use `Guid` / `Random.Shared` / time-based seeds for game selection. |
| Distance | Haversine formula on latitude/longitude, in miles (§6) | Standard, well-understood, accurate enough for a learning game (earth treated as a sphere, radius 3,959 miles). |
| Styling | Plain CSS / Blazor components; keep the map the focus | No heavy UI framework required for v1. |

**Target browsers:** Modern desktop and mobile browsers. Touch (tap to place a pin) is a first-class input, not an afterthought — see §8.

**Favicon:** the pin logo (green pin, white "?!") ships as `blazor/wwwroot/favicon.svg` (SVG favicon, linked from `index.html`); the pin has a white stroke so it is invisible against light browser chrome but pops in dark mode. The standalone version inlines the same SVG as a data URI so it stays a single file. No `.ico` — the push tooling only handles UTF-8 text files, so the binary ICO cannot be pushed via the API, and every browser that runs the game supports SVG favicons.

**Blazor source maps:** `blazor/wwwroot/_framework/dotnet.js.map` and `dotnet.runtime.js.map` are committed (from the .NET 8.0.33 runtime pack) because `dotnet publish` does not emit them even though the runtime JS references them — without them DevTools logs 404s when it is open (players and gameplay are unaffected). If the runtime version changes, replace them with the matching version's maps from the runtime pack.

---

## 3. Generic state-pack architecture

This is the central architectural decision: **the game code knows nothing about Oregon.** It knows how to load a *state pack* and play a game from it.

### 3.1 What a state pack contains
A state pack is a folder of data files, e.g. `wwwroot/data/states/oregon/`:

| File | Contents |
|---|---|
| `state.json` (manifest) | State name, abbreviation, display name, default zoom / map bounds, the list of data files in the pack, landmark layers available, and the city file name. |
| `cities.json` | The city pool for this state. Array of `{ "name", "latitude", "longitude" }`. For Oregon this is generated from `oregon-cities-with-coords.json` — 241 cities. See §3.3. |
| `outline.geojson` | The state boundary as a GeoJSON Polygon / MultiPolygon. Sourced from a public dataset (see §3.4). Used to draw the blank map and to clip / bound the playable area. |
| `landmarks.geojson` (one file per layer, or one file with a `layer` property) | Interstates, US/state highways, rivers, lakes. Each feature carries a type so the renderer can style it (e.g. interstate = thick line + shield label, river = blue line, lake = blue fill). Additional layers (county lines, neighboring-state outlines, major mountain ranges) are optional additions to this file — same shape, new `layer` value. |
| `counties.geojson` (optional) | The state's counties, one Polygon / MultiPolygon feature per county, each with `properties.layer` = `county` and `properties.name` = e.g. "Multnomah County". Only used by Counties mode (§4.3); a pack without this file still loads, and Counties mode is simply unavailable for that state. |
| `risk-pool.json` (optional) | The Risk Pool edition's member lists (§4.6): `{ "cities": [names…], "counties": [names…] }`. Names must match the pack's city/county names exactly (county names carry the " County" suffix). A pack without this file simply has no Risk Pool edition. |

### 3.2 C# models (sketch)

```csharp
public sealed record City(string Name, double Latitude, double Longitude);

public sealed record StatePack(
    string Id,              // "oregon"
    string Name,            // "Oregon"
    string Abbreviation,    // "OR"
    IReadOnlyList<City> Cities,
    GeoJsonDocument Outline,
    IReadOnlyList<LandmarkLayer> Landmarks);

public sealed record LandmarkLayer(string Id, string Label, bool VisibleByDefault);

public sealed record GameConfig(
    string StateId,
    string Seed,            // the seed string, e.g. "2026-11-06"
    int QuestionCount = 10);
```

The game service takes a `StatePack` + `GameConfig` and produces a game. Swapping states = swapping the `StatePack`. No `if (state == "Oregon")` anywhere in game logic.

### 3.3 Oregon city data (v1)
- **Source file (authoritative, human-edited):** `oregon-cities.csv` — 241 cities, one per line, alphabetical, no duplicates. Matt owns this list; cities may be added or removed later.
- **Generated file (used by the app):** `oregon-cities-with-coords.json` — array of `{ "name", "latitude", "longitude" }`, same 241 cities with coordinates added by geocoding (Nominatim / OpenStreetMap, verified inside Oregon bounds lat 42.0–46.3, lon −124.7 to −116.5). See `geocoding-notes.md` in the project folder for the verification log.
- **Rule:** Never hand-edit coordinates into the CSV. Regenerate the JSON from the CSV when the list changes, so the list stays the single source of truth for *which* cities are in the pool.

### 3.4 Map / landmark data sources (sourced 2026-11-06 — see `data/oregon/MAP-DATA-NOTES.md`)
- **Outline:** U.S. Census Bureau 2010 cartographic boundary (`gz_2010_us_040_00_500k.json`, Oregon feature), public domain. Simplified Douglas–Peucker 0.008°: 960 → 209 points, 5.6 KB.
- **Landmarks:** Natural Earth 10m (public domain) — rivers, lakes, roads — plus 47 more lakes from OpenStreetMap (ODbL, added 2026-11-07). 224 features: 26 interstate segments (I-5, I-82, I-84, I-205), 100 highway segments, 40 river segments (20 named rivers), 58 lakes/reservoirs. ~224 KB total.
- **Counties:** U.S. Census Bureau 2023 cartographic boundary file `cb_2023_us_county_500k.zip` (Oregon features, `STATEFP` 41), public domain. 36 counties; each is one polygon except Clatsop (3 parts — Columbia River islands) and Curry (4 parts — coastal islands), which are MultiPolygons. Simplified Douglas–Peucker 0.004°: 15,199 → 2,888 points, 67.7 KB. Names are the Census `NAME` with " County" appended. Largest county Harney (~25,945 km²), smallest Multnomah (~1,225 km²). Added 2026-11-07 for Counties mode (§4.3). See MAP-DATA-NOTES.md.
- **Validation:** all 241 cities fall inside both the simplified and unsimplified outline; projection round-trip max error 0.00°.
- **Known gaps:** I-405 (Portland loop) missing from Natural Earth 10m; Snake River has no separate river line (the eastern outline follows it); small lakes (e.g. Detroit Lake) not included. See MAP-DATA-NOTES.md for the full list.

### 3.5 Adding a new state (checklist)
1. Create `wwwroot/data/states/<state-id>/` with `state.json`, `cities.json`, `outline.geojson`, `landmarks.geojson`, and `counties.geojson` if the state should support Counties mode.
2. Add the state to the state selector list (driven by a small `states.json` index, not by code).
3. Play a test game with a fixed seed and verify: outline renders, all 10 sampled cities are inside the outline, landmarks render, scoring works.
4. No C# changes should be needed. If a code change *is* needed, that is a sign the pack abstraction leaked and should be fixed.

---

## 4. Game flow

### 4.1 Screens
1. **Splash / welcome page (added 2026-11-09)** — the base URL `/`, the front door to the game.
   - A welcoming hero: the pin logo, the title "Where in the State", and a short inviting tagline ("How well do you know your state? Pin the city, name the county — 10 questions, one blank map.").
   - A map of the USA with the outline of each state (all 50 states + DC), large and prominent. The map is the centerpiece. Data: `data/usa-states.geojson` (see `data/USA-MAP-NOTES.md`) — Natural Earth 10m admin_1, simplified, 51 features. Alaska and Hawaii are drawn as insets below the contiguous US (standard layout); their coordinates in the file are display coordinates, not true geography.
   - States that are not ready yet (all 49 others in v1) get light grey diagonal hatching on the state's background (an SVG pattern), so they read as "not yet". The state that is ready (Oregon) is visually distinct — a soft green fill with a green outline — and when the player clicks it, it fills with the game's green (`#205c46`). Clicking Oregon again deselects it.
   - A selected Oregon shows a "Play Oregon" button (disabled until Oregon is selected); clicking it navigates to the Oregon start screen (`/oregon/`). Clicking a hatched (unavailable) state does nothing to the selection — it shows a single quiet line of text under the map ("{State} isn't ready yet — Oregon is the first state."), no popup or modal.
   - The page keeps the game's design language (warm paper `#f2efe4`, Georgia serif headings, the green/rust/gold palette) so it feels like the same game. It works on mobile (the map scales, the button is reachable, no horizontal overflow).
   - Routing: `/` is the splash page. The start screen is at `/{state}/` and below. A game URL (`/{state}/{mode}/{seed}`) goes straight to the prefilled start screen, bypassing the splash; the not-found screen for an unknown state/mode is unchanged.
2. **Start screen**
   - State: there is no state box on the start screen in v1 — Oregon is the only state, there is no state selector, and the header already says "Where in the Oregon?!", so a badge would add nothing. A state picker / badge comes back when a second state pack is added. (A state badge was shown here until 2026-11-08, then removed.)
   - Start screen order (top to bottom): the game-mode box (one big preview image of the selected mode, with three small buttons underneath to change it — City/County, City, County — then the main Play button), then the Game # box (for joining a shared game), then "How to play" (collapsed by default, holding the instructions for the selected mode), then "Advanced options" (collapsed by default, at the bottom, holding the landmark toggles and the "City & County List" edition option — see §4.6). The Counties drag mode is hidden from the mode picker (its code and /oregon/counties/ route still work, so it can come back) — the big preview still shows its artwork if a counties link is opened. The default mode is City/County (bare /{state}/ URLs start there). The instructions sit behind "How to play" so you read the instructions for the mode you chose, not one you haven't chosen yet. The Game # controls sit below the Play button, out of the normal player's path — most players will just tap Play and start.
   - **Edition badge:** when the Risk Pool edition is selected (the default — see §4.6), a "Risk Pool Edition" badge sits centred on the header's bottom border, at the top of the game page content, so the player knows which edition they are playing before they start — on the start screen and during play. The All edition shows no badge.
   - The instructions must not move the UI when you switch modes: all four mode variants of the lede + steps are rendered stacked in one grid cell and only the selected mode's is visible (`visibility: hidden` on the rest, so they still size the grid), so the block is always as tall as the tallest variant and the Game # / landmarks controls below it never move. The JS version stacks its per-mode game line the same way. (The "Questions: 10." label was removed 2026-11-08 — the count is fixed at 10 and the player can't change it, so it isn't shown.)
   - Game # entry: the player-facing name for the seed — the box is labelled "Game #" and every user-visible mention says "Game #" (the code and the spec's technical language still call it a seed). A text box pre-filled with today's Game # on load (or the Game # from a shared link), with two icon-only buttons beside it: a calendar icon that fills in today's Game # and a dice icon that fills in a random one (both with aria-labels, no visible text). The box is just wide enough for the daily Game # (~12 characters; 20 characters max) and sits below the Play button. A short explainer, worded per mode: "Same Game # = same cities, same order. Share it to play the same game as another player." — City County Mode reads "Same Game # = same 7 cities and 3 counties, same order." Seeds are forced to upper case (see §5.3).
   - Question count: fixed at 10 in v1 and not shown on the start screen — the player can't change it, so there is no need to tell them (avoids seed-comparison confusion — a 10-question game and a 20-question game with the same seed are not comparable).
   - Landmark toggles: pill buttons with a color swatch for Interstates / Highways / Rivers / Lakes (all on by default) — the swatch shows the color that layer draws in, so the toggle doubles as the legend. Purely a display preference; they do not affect scoring. (They were plain checkboxes before 2026-11-08; the toggle buttons match the standalone version.)
   - Play button, inside the game-mode box directly under the mode buttons — it is the only way to start a game, and it starts with whatever Game # is in the box. Its label is dynamic: it reads "Play Today's Game" when the box holds today's Game #, and just "Play" for any other Game # (or an empty box, when it is disabled in Blazor; the JS version falls back to a random seed). The label updates as the box content changes (typing, calendar, dice). Starting also writes the seed into the URL (see §5.4) so the game is shareable / refresh-safe.
3. **Round screen (×10)**
   - Header: "Question 3 of 10 — Where is **Baker City**?" plus running total score so far. A bar under the question fills by total score out of 1000, with a terracotta tick marking the best total possible once the question on screen is scored ((question number) × 100 — e.g. 400 on question 4).
   - The map, blank except for outline + enabled landmarks. No city labels, no pins from previous rounds (previous rounds' reveals are cleared — otherwise later rounds get easier by elimination).
   - Player clicks / taps the map to place a pin. The pin can be dragged / re-clicked to move it before confirming. A "Confirm guess" button submits. (Accidental-click protection: a single click places a *provisional* pin; it is not scored until confirmed.) A "Pass" button scores 0 for the round without a pin. Once a pin is placed, a small Confirm bubble also appears next to the pin on the map, so the player can confirm right where they guessed without traveling back to the controls row.
   - Map zoom and pan (added 2026-11-10): on the game map, a two-finger pinch zooms in (up to ~4×) around the pinch midpoint and a one-finger drag pans while zoomed in; a tap (movement under ~10 CSS px) still places a pin / selects a county, and a pinch never places one. The tap-to-lat/lon conversion always uses the current viewBox (x, y, width, height), so a tap on a city resolves to that city even zoomed in. A small "Reset view" button appears in the map's top-right corner while zoomed and returns to the full state; the view also resets to full at the start of every round and on reveal. The Counties drag mode gets pinch zoom and reset only (no pan — one finger drags the piece). The same behavior applies to the Name-the-county map (tap selects a county) and to city rounds in City County Mode. Both the Blazor app and the standalone JS version implement it via Pointer Events and viewBox manipulation; no browser page-zoom is involved. **Smoothing (added 2026-11-11):** pointermove/pan handlers write to a *target* viewBox (incremental pinch ratio — each move applies current-distance / previous-distance to the current target, anchored at the current pinch midpoint — so a finger lifting and re-touching cannot jump the view), and a single requestAnimationFrame loop eases the displayed viewBox toward the target by 0.35 per frame (snapping within 0.05), so finger jitter is filtered out and updates land on the display refresh. When the gesture ends, the displayed viewBox snaps exactly to the target so taps resolve against the final view. **JS-owned gestures (added 2026-11-11):** in the Blazor app the live gesture runs entirely in JavaScript (mapGesture in index.html) — it owns the pointer events, the target/displayed viewBox, and the easing loop, and writes the viewBox attribute straight to the SVG, so a gesture never pays a Blazor re-render or a JS-interop round-trip per frame. Blazor is told exactly once, when the gesture ends (GestureEnded), with the final viewBox (and a tap, if there was one), so its MapViewport stays in sync for taps, the Reset button, and the Confirm bubble; the piece drag in Counties mode is likewise JS-owned (it sets the piece's transform directly) and is first reported to Blazor at the gesture end. The 4× cap, map clamp, 10 px tap threshold, Reset button, and per-round reset are unchanged.
   - After confirming: the map shows both pins — the player's guess and the real city — connected by a line. The buttons stay where they are (Confirm/Pass swap to a "Next city" button, on the left, so the mouse barely moves), and the message line below them swaps to the result: the distance in miles (1 decimal) and points for the round. No separate reveal panel, and no running total below the map — the score chip at the top already shows it.
   - One screen per round: question, controls and map all fit in the viewport without scrolling. The controls are two lines at the top of the map card: the buttons on the first line, and one unified message line below them that holds the round's status — the guessing hint while placing, then the reveal distance/points or county message after confirming. The message line reserves two lines of height at all times (long county names wrap to the second line; anything longer is clamped), so switching messages never moves the buttons above it or the map below it. Landmark toggles live on the start screen only (they stay in effect during play).
   - Edge case: a player who does not want to guess can still confirm with no pin placed — treat as a pass for 0 points for that round (or, alternatively, disable Confirm until a pin is placed; decide in build — the pass option is friendlier for a learning tool).
4. **Results screen**
   - Total score out of 1000, plus a per-round table: city, distance, points.
   - Best guess (smallest distance) and hardest city (largest distance) highlighted — these are the learning hooks.
   - "Play again" (new random game) and "Back to game selection" (returns to the start screen). There is no replay-same-seed button, no "Copy game link" button, and no separate shareable-link textbox — the summary box already carries the game link, and its Copy button is the only copy mechanism.
   - A three-line summary in a styled box, with a "Copy" button on the same row as the box: "I scored 742/1000 on Where in the Oregon?!, Game # 2026-11-06" followed by the edition line ("Risk Pool Edition" or "All Edition") followed by "Play the same game: https://matt-lane.github.io/where-in-the-state/oregon/cities/2026-11-06", so the recipient can open the same seed with one tap — and the edition is visible in the copied text, so a shared result names the edition it was played in. The summary is read-only (no text field), and the link is clickable on the results screen. There is no "Send a challenge!" label. The "Copied" confirmation reserves its line at all times (always rendered, visibility toggles), so showing it never moves any element on the screen.

### 4.2 State during play
- The selected 10 cities and their order are fixed when the game starts (from the seed). They do not change on refresh if the seed is in the URL.
- The game keeps, per round: city, guessed lat/lon (or null for a pass), actual lat/lon, distance, points.
- No persistence in v1 beyond the URL seed. A refresh mid-game restarts that game from round 1 with the same seed (acceptable; note it on the start screen if it proves confusing).

### 4.3 Counties mode (added 2026-11-07)

A second game mode in the same app, alongside the city-pin mode. Same 10 rounds, same seeded shuffle (applied to the 36-county pool), same /1000 total — only the question and the scoring change.

- **Mode picker:** the start screen has a "Game mode" choice — Cities (drop a pin for a named city) or Counties (drag the county's shape onto the map). Counties is only offered when the pack has a `counties.geojson`. The mode is part of the shareable link: a county game link is `/oregon/counties/<seed>` (e.g. `/oregon/counties/2026-11-06`), and opening such a link preselects Counties. The results summary names the mode: "I scored 742/1000 on Where in the Oregon?! (Counties), Game # …".
- **The piece:** each round names one county ("Where is Multnomah County?"). The county's shape is shown as a puzzle piece — its real outline, filled in, at the same scale and in the same orientation as the map. No rotation, no resizing; the shape and size are the clues. The map stays blank: state outline + landmarks only, no county boundaries drawn (drawing them would let the player match the piece to a visible outline).
- **Staging and dragging:** the piece starts staged in the top-left corner of the map (its bounding-box top-left at (10, 10) in SVG units — outside the state outline, clearly a piece waiting to be placed, not an answer). The player drags it onto the map with pointer events (mouse or touch) and confirms. Confirm stays disabled until the piece has been dragged at least once, so the staging position can't be confirmed as an answer. A small Confirm bubble appears next to the piece once it has been dragged, mirroring the city pin's bubble. Dragging again repositions the piece.
- **Reveal:** the true county is shown in green and the placed piece in red (semi-transparent fills, so where they overlap the colours blend and the coverage reads at a glance), with the county name labelled on the true county. The reveal line reads "You covered 82% of Multnomah County · 82 points" (or "You passed — the green shape is Multnomah County."). The Next button reads "Next county".
- **Results:** the per-round table shows county, coverage %, points. Best placement is the highest coverage; hardest county is the lowest coverage (among rounds that were not passed).
- **Scoring:** see §6.4 — the overlap fraction (what percentage of the real county the placed piece covers), × 100 points per round.

### 4.4 "Name the county" mode (added 2026-11-07)

A third game mode in the same app, alongside the city-pin mode and the Counties drag mode. Same 10 rounds, same seeded shuffle (applied to the 36-county pool — the same seed picks the same 10 counties as the drag mode), same /1000 total. Only the question and the scoring change.

- **Mode picker:** the start screen has a "Game mode" choice — City, Counties (drag the piece), or "County". "County" is only offered when the pack has a `counties.geojson`. The mode is part of the shareable link: a game link is `/oregon/name-the-county/<seed>`, and opening such a link preselects it. The results summary names the mode: "I scored 700/1000 on Where in the Oregon?! (County), Game # …".
- **The grid:** the map shows every county boundary drawn over the blank state (all 36 counties as outlines), so the counties read as a grid of regions to pick from. County lines are NOT drawn in the other modes — here they are the point of the game. Landmarks (rivers, highways, lakes) still show, as orientation clues.
- **Selecting:** each round names one county ("Where is Multnomah County?"). The player clicks or taps a county on the map; the county containing the click (point-in-polygon) is highlighted in blue. The selected county's name is NOT shown anywhere before confirming — no label on the map, no tooltip, and the hint only reads "County selected — click another county to change it, or confirm." — so the player can't check their pick by reading its name. Clicking another county changes the selection. A click outside all counties (ocean, a neighbouring state) selects nothing. Confirm (the controls-row button and the Confirm bubble next to the selected county) stays disabled until a county is selected. A "Pass" button scores 0 for the round without a selection.
- **Reveal:** the true county is shown in green, and if the player picked a different county, that one is shown in rust next to it, with the county name labelled on the true county. The reveal line reads "Correct — that's Multnomah County · 100 points", "Pretty close! That's Washington County, not Multnomah County · 50 points" (Washington touches Multnomah), "That's Yamhill County, not Multnomah County · 0 points", or "You passed — the green county is Multnomah County." The Next button reads "Next county".
- **Results:** the per-round table shows county, your pick, points. A line reports "You named 7 out of 10 counties correctly and were adjacent on 2 more." Best pick is the first county named correctly — or, if none was, the first adjacent pick (50 points); hardest county is the first one missed.
- **Scoring:** see §6.5 — 100 points for the right county, 50 for a county sharing a border with it, 0 for any other (or a pass). A perfect game is 1000.

### 4.5 City County Mode (added 2026-11-09)

A fourth game mode in the same app, mixing the city-pin mode (§4.1) and "Name the county" (§4.4) in one game. Same 10 rounds, same /1000 total — the mix is the point.

- **The mix:** each game has **7 city questions and 3 county questions**, interleaved by a seeded shuffle — genuinely mixed, not 7-then-3. The same seed picks the same 7 cities and 3 counties (the same selection the single-type modes make: the first 7 of the seeded city shuffle, the first 3 of the seeded county shuffle), and then shuffles the 10 rounds into one order. The shuffle is a separate Fisher-Yates pass over the 10 rounds, driven by the same seed (§5.2) — deterministic, so the same seed gives the same mixed game.
- **Mode picker:** the start screen has a "Game mode" choice — City/County first, then City, Counties, "County". Its button is first in the row and its preview is one image split diagonally from the top left to the bottom right: the lower-left triangle is the county half (the county grid with Douglas County filled blue (the same blue as a selected county in County mode)) and the upper-right triangle is the city half (a La Grande reveal — guess pin, dotted line, actual marker). The county boundaries in the previews are the real Census geometry, simplified lightly (Douglas-Peucker tolerance 1.0 SVG unit), generated by `make-mode-previews.py` into `ModePreviewArt` (Blazor) and the JS preview markup. The default mode for a bare URL (no mode segment) is City/County (since 2026-11-10); it is also selected by clicking its button or by a `/oregon/city-county/<seed>` link. It is only offered when the pack has a `counties.geojson`. The mode is part of the shareable link: a game link is `/oregon/city-county/<seed>` (e.g. `/oregon/city-county/2026-11-06`), and opening such a link preselects it. The results summary names the mode: "I scored 742/1000 on Where in the Oregon?! (City/County), Game # …".
- **Playing:** a city round plays exactly like Cities mode — blank map, drop a pin for the named city, Confirm bubble next to the pin. A county round plays exactly like "Name the county" — the map draws all 36 county boundaries, click the named county, it highlights blue, Confirm stays disabled until a county is selected. The selected county's name is never shown before confirming, same as §4.4. The question heading names the round's city or county ("Where is Bend?" / "Where is Deschutes County?"). The Next button reads "Next question" (the next round may be either type); on the last round it reads "See results".
- **Reveal:** a city round reveals like Cities mode (guess pin + true pin, distance and points). A county round reveals like "Name the county" (true county green, wrong pick rust) with the line "Correct — that's Deschutes County · 100 points", "Pretty close! That's Jefferson County, not Deschutes County · 50 points", "That's Washington County, not Deschutes County · 0 points", or "You passed — the green county is Deschutes County."
- **Results:** one combined table, one row per round in game order, with columns #, Target (city or county name), Answer (distance "12.3 mi" for a city round, your pick or "—" for a county round), Points. Best guess (smallest distance) and hardest city (largest distance) are highlighted among the city rounds; best county pick (first county named correctly — or, if none was, the first adjacent pick) and hardest county (first one missed) among the county rounds. Below the table, the best-guess / hardest-city / best-county-pick / hardest-county lines, only the ones that exist.
- **Scoring:** see §6.6 — city rounds score by distance (§6.1); county rounds are 100 points for a correct pick, 50 for a county sharing a border with the named one, 0 otherwise. Max is 1000 (7×100 + 3×100), same as Cities.
- **C#/JS divergence (accepted):** the two versions use different random generators for the shuffle — C# `System.Random`, JS mulberry32 — so the same seed generally picks different cities/counties in the two versions, and the interleaving order can differ too. That is the same divergence as the existing single-type modes (a summary copied from the preview links to the same seed on the live site, but the recipient may get a different game). Within one version, the same seed always gives the same game. Verified 2026-11-09 for seed 2026-11-09: C# picks Heppner, Warrenton, Dundee, Dufur, Stanfield, Cornelius, Fairview + Coos, Lane, Union; JS picks Johnson City, Amity, Long Creek, Hines, Dayton, Creswell, Shaniko + Douglas, Multnomah, Harney.

### 4.6 Risk Pool Edition (added 2026-11-11)

An edition that limits the cities and counties the game draws from to the members of the risk pool — the cities and counties in Matt's organization's risk pool (GitHub wiki page "Risk Pool Members"). Same 10 questions, same seeded shuffle, same /1000 total — only the pool changes.

- **The pool:** the Oregon pack carries `risk-pool.json` — `{ "cities": [236 names…], "counties": [28 names…] }`, from the wiki, with the game's canonical city names (Mt. Angel, Mt. Vernon, St. Helens, St. Paul — spelled with the period, as in the game data). The five Oregon cities not in the pool are Eugene, Greenhorn, Medford, Portland, Salem; the eight counties not in the pool are Clackamas, Deschutes, Douglas, Jackson, Lane, Marion, Multnomah, Washington. The file is data in the pack, loaded optionally — a state pack without one simply has no Risk Pool edition, and no game logic hardcodes Oregon or any member name.
- **What it limits:** when the edition is Risk Pool, Cities mode and the city questions in City County Mode draw only from the 236 risk pool cities; "Name the county", Counties drag mode, and the county questions in City County Mode draw only from the 28 risk pool counties. When the edition is All, the pool is the full 241 cities / 36 counties. The filter applies BEFORE the seeded shuffle, so the seed + edition together determine the game: the same seed gives different questions in the two editions, and the same seed + edition always gives the same game.
- **The option:** "City & County List" in the Advanced options on the start screen (collapsed by default), with two choices — "Risk Pool" and "All" — as segmented buttons matching the mode-button styling. **The default edition is Risk Pool.** Changing it updates the badge and the pool the next game draws from. The option is only shown when the pack has a risk pool; a pack without one plays the full list.
- **The badge:** a "Risk Pool Edition" badge sits centred on the header's bottom border, at the top of the game page content — on the start screen and during play — so the player knows which edition they are playing before they start. The All edition shows no badge.
- **The summary:** the results summary names the edition on its own line — "Risk Pool Edition" or "All Edition" — between the score line and the "Play the same game" link, so it is visible on the results screen and in the copied text.
- **The link:** the edition is encoded in the shareable game link, because the same seed with a different edition picks different questions. The game URL is `/{state}/{mode}/{seed}` plus `?list=all` when the edition is All; the Risk Pool edition (the default) carries no parameter, so its URLs stay exactly as before. The game page reads `?list=all` on load and sets the edition to All. The path format is unchanged, and the old query-string seed/mode formats are not reintroduced. Going back to game selection keeps `?list=all` when the edition is All, so it does not silently reset the edition.
- **Analytics:** every PostHog game event carries an `edition` property — `"risk-pool"` or `"all"`, matching the URL-slug style of `mode` — so Matt can see which edition people play (see §13).

---

## 5. Seeded randomization

### 5.1 Requirement
The same seed string must produce the same 10 cities in the same order, for any player, at any time, in any browser. Different seeds must produce (with overwhelming probability) different selections/orders.

### 5.2 Algorithm
1. **Hash the seed string to an integer.** Use a stable hash — e.g. SHA-256 of the UTF-8 seed string, take the first 4 bytes as an `int`. Do *not* use `string.GetHashCode()` (it is not stable across runtimes / runs in .NET).
   ```csharp
   using var sha = SHA256.Create();
   var hash = sha.ComputeHash(Encoding.UTF8.GetBytes(seed));
   int seedInt = BitConverter.ToInt32(hash, 0);
   ```
2. **Deterministic shuffle (Fisher–Yates) with `System.Random(seedInt)`.**
   ```csharp
   var rng = new Random(seedInt);
   var pool = statePack.Cities.ToList();
   for (int i = pool.Count - 1; i > 0; i--)
   {
       int j = rng.Next(i + 1);
       (pool[i], pool[j]) = (pool[j], pool[i]);
   }
   var gameCities = pool.Take(10).ToList();
   ```
3. Take the first 10 of the shuffled pool. No city repeats within a game (sampling without replacement, guaranteed by the shuffle).
4. **Shuffling a list (City County Mode).** The same seed derivation and Fisher-Yates pass, applied to a copy of any list and returning the shuffled copy: `Shuffle<T>(items, seed)` in C#, `shuffleItems(seedInt, arr)` in JS. City County Mode uses it to interleave its 7 city + 3 county rounds into one mixed order. Note the C# version drives the shuffle with `System.Random(seedInt)` and the JS version with mulberry32, so the same seed generally picks different cities/counties in the two versions and the interleaving order can differ too — the same divergence as the existing single-type modes. Within one version, the same seed always gives the same game.

### 5.3 Seed formats
- **Free-form string:** any text the player types, e.g. `friday-game`, `2026-11-06`. The hash step makes any string a valid seed. An old shared link carrying an `2026-11-06` seed still loads — it is just a different string, so it picks a different game than the same date without the prefix.
- **Daily seed:** a convenience button that sets the seed to `yyyy-MM-dd` in the player's local date (the state prefix was dropped — the state is already in the URL). Everyone playing "today's game" gets the same game that day.
- **Random seed:** generate a short human-friendly seed, e.g. 6 random alphanumeric characters, so players can share it verbally.
- **Validation:** trim whitespace; reject an empty seed (fall back to a random one). Seeds are forced to upper case (canonical case), so `friday-game` and `FRIDAY-GAME` are the same game. The seed box caps input at 20 characters.

### 5.4 Seed in the URL
- The game URL is `/<state>/<mode>/<url-encoded seed>`, e.g. `/oregon/cities/2026-11-06`, `/oregon/counties/2026-11-06`, `/oregon/name-the-county/2026-11-09`, `/oregon/city-county/2026-11-09`. The mode segment is one of the mode slugs: `cities`, `counties`, `name-the-county`, `city-county`. On start, the app navigates to that URL. The results summary's "Play the same game:" line carries this URL. When the edition is All, the URL carries `?list=all` (e.g. `/oregon/cities/2026-11-06?list=all`); the Risk Pool edition (the default) carries no parameter. The game page reads `?list=all` on load and sets the edition to All — see §4.6.
- The results "Copy" button (on the same row as the summary box) copies the three-line summary (score line + edition line + "Play the same game: <link>"), so the recipient can open the same seed with one tap. The "Copied" confirmation is always rendered with its line reserved (visibility toggles), so it never moves any element on the screen. In the standalone JavaScript version the link is built from the live-site base, not the page's own address — in the test-page preview the origin is the preview host, which is not a shareable game link. Note: the preview and the live site use different random generators for the same seed, so a summary copied from the preview links to the same seed on the live site but the recipient may get a different set of 10 cities.
- Loading the app with `/<state>/<mode>/<seed>` pre-fills the start screen with that state, mode and seed, so a shared link is one click to the same game. Loading with `/<state>/<mode>/` (no seed) preselects the mode on the start screen; loading with `/<state>/` shows the start screen for that state with the default mode (City/County); the root URL `/` shows the splash/welcome page (see §4.1), not the start screen.
- The old URL formats are no longer supported: the `?state=…&seed=…` query form and the `/{state}/{seed}` path form (with `?mode=…`) were removed 2026-11-09. The game is still in beta, so old links break — they now land on the not-found screen (an unrecognized mode segment, like the seed in the old two-segment form, is not a mode slug).
- If the state or the mode in the URL doesn't exist, the app shows a "couldn't find that state" screen with a way back to Oregon instead of hanging on "Loading the map…".
- Question count is not in the URL in v1 (fixed at 10).

### 5.5 Testing the seed logic
- Same seed twice → identical city list and order (unit test, run in CI if there is one, otherwise manually before release).
- Different seeds → different lists in practice (spot-check 5 seeds).
- Seed works from a shared link in a different browser / device.
- Daily seed changes at midnight local time and is the same for all players that day.

---

## 6. Scoring & distance

### 6.1 Per-round score
```
distance_miles = Haversine(guessLat, guessLon, cityLat, cityLon)
points = 100 if round(distance_miles) <= 5 else max(0, 100 - (round(distance_miles) - 5))
```
- Full points within 5 miles: 0–5 miles off = 100 points. Then −1 point per mile beyond 5: 6 miles off = 99, 10 miles off = 95, 55 miles off = 50, 105+ miles off = 0.
- **Floor at 0.** No negative points. This is deliberate — see §1.2.
- Distance is displayed to 1 decimal place (e.g. 23.4 miles); points use the rounded whole-mile distance, so the displayed distance and the points always agree.
- A pass (no pin) = 0 points, distance shown as "—".

### 6.2 Total score
- Sum of the 10 round scores. **Maximum 1,000.**
- Show the total as `742 / 1000` on the results screen, plus the average distance per round as a secondary learning stat.

### 6.3 Haversine (miles)
```csharp
public static double HaversineMiles(double lat1, double lon1, double lat2, double lon2)
{
    const double R = 3959.0; // earth radius in miles
    double dLat = DegreesToRadians(lat2 - lat1);
    double dLon = DegreesToRadians(lon2 - lon1);
    double a = Math.Sin(dLat / 2) * Math.Sin(dLat / 2)
             + Math.Cos(DegreesToRadians(lat1)) * Math.Cos(DegreesToRadians(lat2))
             * Math.Sin(dLon / 2) * Math.Sin(dLon / 2);
    return 2 * R * Math.Asin(Math.Sqrt(a));
}
```
- Known reference points for testing, computed with the Haversine formula from the geocoded coordinates in `cities.json`: Portland (45.5202, −122.6742) to Salem (44.9392, −123.0331) is ≈ 44 miles; Portland to Bend (44.0582, −121.3153) is ≈ 121 miles; Eugene (44.0505, −123.0951) to Salem is ≈ 62 miles. (These are straight-line distances, so they are shorter than driving distances. The authoritative city coordinates are the geocoded `cities.json` for the state pack, and distances should be spot-checked against a mapping tool for a few city pairs before release.)

### 6.4 Counties mode scoring — overlap fraction (added 2026-11-07)

```
overlap = area(placed piece ∩ true county) / area(true county)
points  = round(overlap × 100)
```

- The placed piece is the true county translated by (dx, dy) in SVG viewBox units, so the overlap is the fraction of the real county the piece covers. Perfect placement = 1.0 → 100 points; half the county covered = 50; no overlap = 0. A pass = 0 points, coverage shown as "—".
- It is forgiving in the right way: because the piece is exactly the county's shape, the player cannot cover most of the true county without being mostly in the right place — there is no way to game it by dropping a big shape over the area.
- **Computation — grid sampling.** Exact polygon clipping would need a geometry library (NetTopologySuite in C#, Turf.js in JS) and the two libraries can disagree on edge cases. Instead, both versions sample a grid over the true county's bounding box (step 4 SVG units, cell centres) and test each cell centre with point-in-polygon (ray casting): inside the true county, and inside the placed piece (tested by shifting the cell centre back by (dx, dy) and testing against the true rings — the piece is the true county translated, so this is exact). `overlap = cells in both / cells in the true county`. The projection is linear, so area ratios in SVG space equal area ratios on the ground. At a 4-unit step the overlap is accurate to well under a point, and the result is identical in Blazor and JS.
- **County polygons have no holes** (Clatsop and Curry are MultiPolygons of separate outer rings — islands — not holes), so "inside" means inside any ring. If a future pack has a county with a hole, the point-in-polygon test must exclude hole rings.
- **Rounding note:** C# `Math.Round` is banker's rounding and JS `Math.round` rounds halves up, so an exact .5 overlap score (e.g. 50.5%) can differ by 1 point between the Blazor and JS versions. Rare, and within the grid's own error — accepted, as with the city game's whole-mile rounding.
- The stricter alternative, Intersection over Union (IoU = intersection / union), was considered and set aside: for equal-area shapes IoU = overlap / (2 − overlap), so it scores harsher (80% coverage → 67) and is harder to explain in one line. If overlap fraction ever feels too generous, IoU is the fallback.

### 6.5 "Name the county" scoring — 100 / 50 / 0 (added 2026-11-07; 1 point per answer 2026-11-07, changed to 100/50/0 on 2026-11-09)

```
points = 100 if selected county == named county
       =  50 if selected county shares a border with the named county
       =   0 otherwise (any other county, or a pass)
```

- Naming the right county is 100 points; picking a county that **shares a border** with it is 50 points ("Pretty close!"); any other county, or a pass, is 0. A perfect game is 1000, same as the other modes.
- **Adjacency definition:** two counties are adjacent if they share a border **segment** — a common edge — not just a single corner point where four counties meet. E.g. Marion County is adjacent to Clackamas County (they share a border); Clatsop County is NOT adjacent to Washington County (they meet only at one point). The adjacency list is computed from the state's county polygons (see below) and embedded in the pack data, so both versions use the same table.
- **Adjacency data:** each county feature in `counties.geojson` carries a `properties.neighbors` list — the names of its adjacent counties, sorted. It was computed 2026-11-09 by `compute-county-adjacency.py` from the raw (unsimplified) Census 2023 shapefile (`data/oregon/counties-raw/cb_2023_us_county_500k.shp`): two counties are adjacent when they share at least one identical edge in the raw geometry. (The simplified GeoJSON cannot be used for this — per-county Douglas–Peucker simplification turns a shared border into a different chord in each county, so exact edge matching on the simplified file misses real borders such as Jackson/Josephine.) The script validates the result: all 36 counties have 2–8 neighbors, the neighbor relation is symmetric, and spot checks pass (Marion ↔ Clackamas; Clackamas ↔ Multnomah, Washington, Yamhill, Wasco, Hood River; Clackamas NOT ↔ Curry). The only vertex-only contacts in Oregon are Clatsop ↔ Washington and Columbia ↔ Tillamook, correctly excluded. If the county data is ever regenerated, re-run the script to rebuild the neighbor lists. The Blazor loader reads `properties.neighbors` into `MapFeature.Neighbors` (`IsNeighbor(name)`); the JS version reads the same property from the embedded GeoJSON.
- A random guesser would get about 10/36 ≈ 28% right by chance (2–3 out of 10), plus a few adjacent picks, so the mode still separates knowing from guessing.
- The score displays (progress bar, score chip, results hero, summary) all read the maximum from the mode: 1000 for every mode now. The summary reads "I scored 700/1000 on Where in the Oregon?! (County), Game # …".
- Best pick is the first county named correctly — or, if none was, the first adjacent pick (50 points); hardest county is the first one missed (preferring a picked wrong county over a pass).

### 6.6 City County Mode scoring (added 2026-11-09)

```
city round:   points = scoreForDistance(distance)   (§6.1 — 100 within 5 miles, −1 per mile beyond, floored at 0)
county round: points = 100 if selected county == named county
                   =  50 if selected county shares a border with the named county
                   =   0 otherwise (any other county, or a pass)
```

- A county question in this mode is worth **100 points** for a correct pick and **50 for an adjacent pick** — the same 100/50/0 as "Name the county" mode (§6.5), with the same adjacency definition (shares a border segment, not just a corner point) and the same embedded neighbor data. A wrong county or a pass is 0. A perfect game is 1000 (7×100 + 3×100).
- The score displays (progress bar, score chip, results hero, summary) all read the maximum from the mode: 1000 for City/County, same as City. The summary reads "I scored 742/1000 on Where in the Oregon?! (City/County), Game # …".

---

## 7. Data files (v1, Oregon)

| File | Location (project) | Notes |
|---|---|---|
| `oregon-cities.csv` | `game-project/` (working folder) | Human-edited source of truth for the city pool. 241 cities. |
| `oregon-cities-with-coords.csv` / `.json` | `game-project/` → copied into `wwwroot/data/states/oregon/cities.json` at build time | Geocoded coordinates. Regenerate when the CSV changes; do not hand-edit. |
| `geocoding-notes.md` | `game-project/` | Verification log for the coordinates. |
| `outline.geojson` | `wwwroot/data/states/oregon/` | State boundary. Census 2010 cartographic boundary, simplified to 209 points (5.6 KB). Source files in `game-project/data/oregon/`. |
| `landmarks.geojson` | `wwwroot/data/states/oregon/` | Interstates, highways, rivers, lakes (224 features, ~224 KB; Natural Earth 10m + 47 OSM lakes). Simplified before shipping. |
| `counties.geojson` | `wwwroot/data/states/oregon/` | 36 Oregon counties (Census 2023 cartographic boundary, simplified to 2,888 points, 67.7 KB). For Counties mode (§4.3). |
| `usa-states.geojson` | `data/` (source) → `wwwroot/data/` (Blazor) and embedded in the standalone JS | 51 features: all 50 states + DC, for the splash/welcome page (§4.1). Natural Earth 10m admin_1, simplified (3,793 points, 78 KB). Alaska/Hawaii are inset display coordinates, not true geography — see `data/USA-MAP-NOTES.md`. Generated by `process-usa-states.py`. |
| `state.json` | `wwwroot/data/states/oregon/` | Pack manifest (name, bounds, layers, files). |
| `states.json` | `wwwroot/data/` | Index of available state packs (v1: Oregon only). |

---

## 8. UI / UX, accessibility & mobile

- **Map first.** The map is the main element on the round screen; controls are compact and out of the way. The whole round fits on one screen — question, controls row and map in the viewport without scrolling — with the map sized by viewport height on desktop and full-width on mobile.
- **Pin interaction.** Click/tap places a provisional pin; drag or click again to move it; Confirm scores it. After the reveal, both pins and the connecting line are shown, and the map is not clickable until "Next" is pressed. Click coordinates are converted using the SVG's measured rendered size (not an assumed display size), so pins land correctly at any map size.
- **Feedback on every round.** Distance, points, and the reveal are shown immediately — the learning happens in that moment. Do not make the player wait until the end to see where a city was.
- **Landmark toggles.** Interstates / Highways / Rivers / Lakes can be toggled on the start screen; they stay in effect during play but there is no toggle control on the round screen, so the round fits on one screen. Toggles are a display preference only.
- **Touch.** Tap targets at least 44×44 px; the map must support tap-to-place without scrolling the page (touch-action handling) and pinch-to-zoom must not accidentally place a pin. Test on a real phone, not just a desktop browser resized.
- **Keyboard / accessibility.** The question is a real heading; buttons are real buttons; the map has a text alternative for the round ("Question 3 of 10: Where is Baker City?") and the reveal is announced in text, not only visually on the map. A keyboard-only path to place a pin is a nice-to-have for v1 — at minimum, results and navigation must be fully keyboard-usable.
- **No city labels on the map at any point during a round.** Labels would give the game away. Landmark labels (e.g. "I-5", "Willamette River") are fine and help orientation; city names are not.
- **Performance.** The map data for a state should load once per game start, not per round. Keep the total GeoJSON per state well under ~1 MB after simplification.
- **Design language (fun but professional).** Warm paper background, deep forest green as the primary color, terracotta as a sparing accent, serif headings with plain system text. Cards with soft shadows, pill toggles, a score bar (filled by total score out of 1000, with a terracotta tick for the max possible after the current question) and score chip during play, the round's distance and points in the map card's controls row on reveal, and a big score with a score bar on results. Subtle fade-up on screen changes, disabled entirely under `prefers-reduced-motion`. No external fonts or images — everything is CSS.

---

## 9. Map and point-selection — decided: SVG + GeoJSON (Option A, 2026-11-06)

Matt chose **Option A — SVG + GeoJSON, rendered natively in Blazor** for v1. Options B (Leaflet/MapLibre) and C (Canvas) remain documented below as alternatives if pan/zoom needs ever outgrow SVG. A click-test prototype using the same projection and the real Oregon data was built and audited 2026-11-06 (see Appendix).

### Option A — SVG + GeoJSON, rendered natively in Blazor
Render the state outline and landmark layers as SVG paths inside a Blazor component. The click position is converted from SVG pixel coordinates to lat/lon with a projection (see §9.4). Pins are SVG elements.

| Pros | Cons |
|---|---|
| No JavaScript library, no JS interop, no tile server — pure C# + SVG. Easiest to reason about and to keep fully offline / self-contained. | You write the projection, hit-testing, pan/zoom, and landmark styling yourself. SVG can get slow if the geometry is very detailed (mitigated by simplification). |
| Full control over styling — a clean "blank map" look is natural in SVG. | No built-in pan/zoom or touch gestures; you implement the ones you need (or ship without pan/zoom in v1 — the whole state fits on one screen, so this may be fine). |
| Click-to-lat/lon is straightforward once the projection is in place. | Large/complex GeoJSON can make the DOM heavy; keep layers simplified. |

**Best if:** Matt wants the smallest moving parts, a fully self-contained app, and is comfortable writing a small projection + SVG rendering layer.

### Option B — Leaflet / MapLibre via JS interop, with a blank / minimal basemap
Use a mature mapping library (Leaflet is the simplest; MapLibre GL JS is the more powerful vector option) through Blazor JS interop. The state outline and landmarks are added as GeoJSON layers on top of a blank or very light basemap — or with no basemap at all, just the vector layers on a plain background.

| Pros | Cons |
|---|---|
| Pan, zoom, touch, and click-to-lat/lon come for free and are battle-tested on mobile. | A JavaScript dependency and a JS-interop boundary in a C# app — two runtimes to debug, and the map state lives in JS, not in C#. |
| Landmark styling, layer toggles, and popups are built in. | If a tile basemap is used, the game needs tiles at runtime (network dependency, and a tile source that does not label cities — a standard street map would give the game away, so a custom blank/minimal tile style is needed). This can be avoided by using no basemap and only vector layers, but then the library is doing less work for its cost. |
| Accurate projection handling is already solved. | Bundle / load complexity is higher than pure SVG. |

**Best if:** Matt wants polished map interaction (especially pinch/pan on mobile) without writing it, and is comfortable with a JS-interop layer.

### Option C — Canvas rendering
Draw the map on an HTML `<canvas>` from the GeoJSON in C# (via JS interop or Blazor's canvas bindings), handle clicks by converting pixel → lat/lon, and draw pins on the canvas.

| Pros | Cons |
|---|---|
| Fast rendering even with detailed geometry; no DOM bloat. Full control over drawing. | You write the projection, pan/zoom, hit-testing, and accessibility yourself — and canvas is inherently less accessible (screen readers see a bitmap, not elements). Pin interaction and text labels need manual work. |
| No mapping-library dependency. | Debugging a canvas map is harder than inspecting SVG elements in the browser dev tools. |

**Best if:** Performance with very detailed geometry matters most, and Matt is willing to take on the extra interaction/accessibility work. For a single-state blank map, this is usually more machinery than v1 needs.

### 9.4 Click-to-lat/lon — common to all options
Whichever option is chosen, the same conversion is needed:
1. The map has a known geographic bounding box (from the state pack manifest, e.g. Oregon ≈ lat 42.0–46.3, lon −124.7 to −116.5, with a small margin).
2. A screen click gives pixel coordinates in the map element; those are normalized to 0–1 across the map's width/height.
3. A projection maps normalized position → lat/lon. For a learning game at state scale, a simple equirectangular projection (lon = linear in x, lat = linear in y) is acceptable and easy to verify, *provided the map is drawn with the same projection* — otherwise clicks and the drawn outline will disagree. A Mercator projection is more correct for a library-based map; if a library is used, use its built-in `latLng` conversion rather than hand-rolling one.
4. **Accuracy check:** click the four corners and a known city location in testing, and verify the converted lat/lon matches. A mismatch here silently breaks scoring, so this is a release-blocking test (see §11).

### 9.5 Questions for Matt (next conversation)
- Which option feels right given how much JS interop he wants in a C# app?
- Does the map need pan/zoom in v1, or is "whole state fits on screen" enough? (If the latter, Option A gets much simpler.)
- Is a fully offline / no-tile game a requirement, or is a network dependency at play time acceptable?
- How important is pinch-to-zoom on phones for v1?

---

## 10. Implementation plan (suggested order)

1. **Data first.** Finish the Oregon city coordinates (done — see `geocoding-notes.md`) and source + simplify the outline and landmark GeoJSON. Validate every city falls inside the outline.
2. **Core game logic (no map UI).** State-pack loading, seeded shuffle, Haversine scoring, game state machine (start → rounds → results). Unit-test the seed and scoring logic.
3. **Map (chosen approach from §9).** Render outline + landmarks, implement click → lat/lon, provisional pin + confirm, reveal with both pins and distance line.
4. **Screens.** Start screen (state, seed, toggles), round screen, results screen, shareable URL with seed.
5. **Polish & accessibility.** Mobile/touch pass, keyboard pass, landmark toggles during play, copy-link, results summary text.
6. **Playtest.** Play full games with several seeds on desktop and phone; verify seed reproducibility across browsers; fix click-accuracy issues before calling v1 done.

---

## 11. Testing checklist (v1 release gate)

- [ ] Same seed → same 10 cities, same order, in two different browsers.
- [ ] Different seeds → different selections (spot-check).
- [ ] Shared link (`/oregon/cities/2026-11-06`) loads the same game on another device.
- [ ] Shared link with an unknown state (e.g. `/atlantis/cities/2026-11-06`) or an unknown mode (e.g. `/oregon/bogus/2026-11-06`) shows a not-found screen with a way back to Oregon instead of hanging on "Loading the map…".
- [ ] Passing all 10 rounds shows the results screen with no best/hardest guess instead of crashing.
- [ ] Daily seed is the same for all players on the same day.
- [ ] Clicking a known location (e.g. downtown Portland) converts to lat/lon within ~2 miles of the true coordinates.
- [ ] Every one of the 241 Oregon cities, when selected, lies inside the drawn state outline.
- [ ] Scoring: 0–5 miles → 100 pts; 25 miles → 80 pts; 105 miles → 0 pts; 150 miles → 0 pts (not negative).
- [ ] Total of a perfect game = 1,000; a game with no pins placed = 0.
- [ ] 10 rounds per game, no repeats within a game.
- [ ] Pin can be moved before confirming; confirming without a pin is handled (pass = 0, or confirm disabled — whichever was decided).
- [ ] Landmark toggles actually hide/show their layers.
- [ ] Full game is playable by touch on a phone, including placing a pin without the page scrolling.
- [ ] No city names appear on the map during a round.
- [ ] Results screen shows all 10 rounds with city, distance, and points, and the share link copies correctly.

---

## 12. Future work (not v1)

- **More states.** Add state packs using the checklist in §3.5. A state selector on the start screen already exists for this.
- **Leaderboard / score sharing.** A lightweight way to post a score for a seed (e.g. a shared board per seed) — needs a server, so it is a separate decision from the v1 static game.
- **Learning mode.** After the reveal, show a fact about the city, or let the player replay the same seed immediately to improve.
- **Difficulty options.** E.g. a "hard mode" with fewer landmarks, or a timed mode. Keep the default game at 10 questions / 100 points so seeds stay comparable.
- **County / region variants.** Same engine, different pools (e.g. "county seats only", "coastal cities").

---

## 13. Analytics — PostHog (added 2026-11-09)

Anonymous gameplay stats only, so Matt can see how the game is used (games played, modes, scores) without knowing who played. No accounts, no login — the player is anonymous by default.

- **Service:** PostHog Cloud (US), free tier (1M events/month). Project API key `phc_m9r8eSEfJH6ZaEby76WZGTgafxtKYdEg6xFQbpsUNw3i`, host `https://us.i.posthog.com`.
- **Where configured (one place per codebase):** the key and host live in the PostHog JS snippet in `blazor/wwwroot/index.html` (Blazor) and as the `POSTHOG_KEY` / `POSTHOG_HOST` constants in `build-game.py`, substituted into the snippet at build time (standalone JS). The C# / JS game code never touches the key — it only calls a guarded capture helper. The key is a public client key, designed to be embedded in frontend code.
- **Library loading:** the standard PostHog JS snippet in `<head>`. It defines `window.posthog` as a queuing stub, so `capture` calls made before `array.js` loads are queued, not dropped. `capture_pageview` and `autocapture` are off, so only the four explicit game events below are ever sent — no automatic pageviews, no autocaptured clicks.
- **Events (all anonymous):**

  | Event | When | Properties |
  |---|---|---|
  | `game_started` | A game starts (Start game / Play again / Replay) | `state`, `mode`, `edition`, `seed`, `questions` (10) |
  | `round_completed` | A round is revealed/scored (confirmed or passed) | `state`, `mode`, `edition`, `seed`, `round` (1–10), `question_type` (`"city"` \| `"county"`), `question` (city or county name asked), `target` (the correct answer's name — city or county — the grouping key for analysis, e.g. "which target is missed most"; it duplicates `question` on purpose, so every round carries one uniform `target` field), `points`; city rounds add `distance_miles` (1 decimal; omitted on a pass); name-the-county / mixed county rounds add `correct`, `adjacent`; drag-county rounds add `overlap_fraction` (3 decimals; omitted on a pass) instead of `correct`/`adjacent` |
  | `game_completed` | The results screen is reached | `state`, `mode`, `edition`, `seed`, `total_score`, `max_score` (1000), `rounds` (10) |
  | `game_abandoned` | The player leaves the page mid-game (tab close, refresh, navigating to another site) | `state`, `mode`, `edition`, `seed`, `rounds_completed`, `score_so_far` |

  `mode` is the URL slug: `"cities"`, `"counties"`, `"name-the-county"`, `"city-county"`. `edition` is `"risk-pool"` or `"all"` (see §4.6). `state` is the state id (e.g. `"oregon"`).
- **No PII.** The events above contain no personal data: no names, emails, IP addresses, user-agent strings, device fingerprints, or any identifier that could pick out a player. The seed and the city/county names are game data, not personal data. No `identify` call is made — players stay on PostHog's anonymous distinct id. No visible UI is added for this (no cookie banner, no notice).
- **No timing.** The game does not track per-round or total time, so `time_seconds` / `duration_seconds` are not reported. If timing is ever added, it should be reported the same way (seconds, as a number).
- **Never breaks the game.** Every tracking call is guarded: the capture helper checks that the PostHog library loaded (`window.posthog` exists and `capture` is a function) and wraps the call in try/catch, and the Blazor side additionally wraps the JS-interop call in try/catch. Ad blockers commonly block PostHog, and the endpoint may be unreachable — in all of those cases the calls are no-ops and the game plays identically, with no error, freeze, or visible change. Tracking is fire-and-forget; it never blocks gameplay.
- **`game_abandoned` is best-effort.** It fires from a `pagehide` listener when the page is left while a game is in progress (Blazor: a context set at game start, updated after each scored round, cleared at results; standalone JS: the in-progress `game`/`phase` state). A `pagehide` capture may not always reach the server before the page goes away. In-app navigation inside the Blazor SPA does not unload the page, so leaving a game that way is not captured.

## Appendix — Decisions already locked (2026-11-06)

- Web-based, C# with Blazor (WebAssembly preferred).
- First state: Oregon; architecture generic for any state.
- 100 points per question, −1 point per mile, floored at 0; max 1,000 per game.
- 10 questions per game.
- Seeded randomization so the same seed = same cities, same order.
- City pool: Matt's list of 241 Oregon cities (see `oregon-cities.csv`).
- Purpose: fun learning tool for Matt's organization.
- Map rendering (2026-11-06): SVG + GeoJSON natively in Blazor for v1, no Leaflet/Canvas. Projection is equirectangular with cos(44°) correction, same function for drawing and click-to-latlon.
- Oregon map data (2026-11-06): outline from Census 2010 cartographic boundary (960 → 209 points, 5.6 KB); landmarks from Natural Earth 10m (177 features: 26 interstate, 100 highway, 40 river, 11 lake segments; 86.7 KB). All 241 cities inside the outline; projection round-trip error 0.00°. Known gaps: no I-405, no separate Snake River line. Details in `data/oregon/MAP-DATA-NOTES.md`. 2026-11-07: 47 more lakes >= 4 km² added from OpenStreetMap (Detroit Lake, Wallowa Lake, Odell Lake, Crescent Lake, Waldo Lake and 42 more) — 224 features, 58 lakes, ~224 KB.
- Click-test prototype (2026-11-06): `~/workspace/ts-spaces/oregon-map-click-test/` — "Oregon Map — Click Test". Click/tap drops a pin, shows converted lat/lon, nearest of the 241 cities, distance and the 5-mile-grace score (100 pts within 5 mi, then −1/mi beyond 5, floored at 0); test pins for Portland, Salem, Bend, Medford (aim for < ~2 mi error). Audit 2026-11-07T02:48Z passed (desktop + mobile, no console errors).
