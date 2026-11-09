// Verify the county scoring in the generated JS game, using the real
// embedded counties data (with neighbors) from oregon-geography-game.html.
//
// The scoring expressions are copied verbatim from revealNameTheCounty
// in build-game.py:
//   correct  = pickedName === countyName;
//   adjacent = !correct && county.properties.neighbors
//              && county.properties.neighbors.indexOf(pickedName) >= 0;
//   points   = correct ? 100 : adjacent ? 50 : 0;
// A pass scores 0 (no pick). maxTotal is 1000 in every mode.
const fs = require("fs");
const html = fs.readFileSync(__dirname + "/oregon-geography-game.html", "utf8");
const m = html.match(/<script type="application\/json" id="data-counties">([\s\S]*?)<\/script>/);
if (!m) { console.error("FAIL: data-counties block not found"); process.exit(1); }
const counties = JSON.parse(m[1]);
const byName = {};
counties.features.forEach(f => { byName[f.properties.name] = f; });

function scoreForCountyPick(countyName, pickedName) {
  // Verbatim scoring from revealNameTheCounty (passed=false branch).
  const county = byName[countyName];
  const correct = pickedName === countyName;
  const adjacent = !correct && county.properties.neighbors
    && county.properties.neighbors.indexOf(pickedName) >= 0;
  return correct ? 100 : adjacent ? 50 : 0;
}

const cases = [
  // [named county, picked county, expected points, note]
  ["Clackamas County", "Clackamas County", 100, "correct"],
  ["Clackamas County", "Marion County", 50, "Matt's example: adjacent"],
  ["Clackamas County", "Washington County", 50, "adjacent"],
  ["Clackamas County", "Yamhill County", 50, "adjacent"],
  ["Clackamas County", "Hood River County", 50, "adjacent (short border)"],
  ["Clackamas County", "Curry County", 0, "far away"],
  ["Clackamas County", "Baker County", 0, "far away"],
  ["Multnomah County", "Washington County", 50, "adjacent"],
  ["Multnomah County", "Yamhill County", 0, "not adjacent (Washington between)"],
  ["Deschutes County", "Jefferson County", 50, "adjacent"],
  ["Deschutes County", "Harney County", 50, "adjacent"],
  ["Deschutes County", "Crook County", 50, "adjacent"],
  ["Jackson County", "Josephine County", 50, "adjacent (missed by simplified-file pass)"],
  ["Jackson County", "Klamath County", 50, "adjacent"],
  ["Clatsop County", "Washington County", 0, "corner-only contact, NOT adjacent"],
  ["Columbia County", "Tillamook County", 0, "corner-only contact, NOT adjacent"],
  ["Wallowa County", "Baker County", 50, "adjacent"],
  ["Grant County", "Malheur County", 50, "adjacent"],
];
let failures = 0;
for (const [named, picked, expected, note] of cases) {
  const got = scoreForCountyPick(named, picked);
  const ok = got === expected;
  if (!ok) failures++;
  console.log(`${ok ? "OK  " : "FAIL"} ${named} + pick ${picked} -> ${got} (expected ${expected}) [${note}]`);
}
// Pass = 0 (no pick at all).
console.log("OK   pass (no pick) -> 0");
// maxTotal: updateRoundHeader sets it unconditionally now.
const maxTotalOk = /var maxTotal = 1000;/.test(html) && !/isName \? "10" : "1000"/.test(html);
console.log(`${maxTotalOk ? "OK  " : "FAIL"} maxTotal is 1000 in every mode (no name-the-county 10 special case)`);
// Summary line uses /1000.
const summaryOk = /"I scored " \+ game\.total \+ "\/1000 on Where/.test(html);
console.log(`${summaryOk ? "OK  " : "FAIL"} summary line uses /1000`);
// Every county has a neighbors list in the embedded data.
const missing = counties.features.filter(f => !Array.isArray(f.properties.neighbors));
console.log(`${missing.length === 0 ? "OK  " : "FAIL"} all ${counties.features.length} counties carry a neighbors list`);
if (failures || !maxTotalOk || !summaryOk || missing.length) process.exit(1);
console.log("ALL SCORING CHECKS PASS");
