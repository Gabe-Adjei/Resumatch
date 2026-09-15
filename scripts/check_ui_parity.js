// Verify the browser engine agrees with the Python engine, placement for
// placement.
//
//   python3 -m resumatch generate --seed 42 -o data/cohort.json
//   python3 -m resumatch match data/cohort.json -o data/run.json
//   python3 scripts/export_ui_data.py
//   node scripts/check_ui_parity.js
//
// WHY THIS EXISTS
// ---------------
// ui/engine.js is a deliberate second implementation of deferred acceptance,
// so the board can answer a drag instantly without a server. Two copies of an
// algorithm drift, and this drift would be invisible: both versions would keep
// producing plausible, stable-looking matches that quietly disagree about
// where real people go.
//
// Run this after any change to matching.py, scoring.py or engine.js. It must
// report zero mismatches.

const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
global.window = global;

eval(fs.readFileSync(path.join(root, "ui/sha256.js"), "utf8"));
eval(fs.readFileSync(path.join(root, "ui/data.js"), "utf8"));
eval(fs.readFileSync(path.join(root, "ui/engine.js"), "utf8"));

const D = window.RESUMATCH_DATA;
const E = window.RESUMATCH;

const runPath = path.join(root, "data/run.json");
if (!fs.existsSync(runPath)) {
  console.error("Missing data/run.json — run the two python commands above first.");
  process.exit(2);
}

const py = JSON.parse(fs.readFileSync(runPath, "utf8"));
if (py.cohort_hash !== D.cohortHash) {
  console.error(
    "Cohort mismatch: data/run.json is " + py.cohort_hash.slice(0, 12) +
    " but ui/data.js is " + D.cohortHash.slice(0, 12) + ".\n" +
    "Re-run scripts/export_ui_data.py against the same cohort."
  );
  process.exit(2);
}

const js = E.runMatch(D.teams.map((t) => t.capacity), {});
const pyTeamOf = {};
py.assignments.forEach((a) => {
  pyTeamOf[a.candidate_id] = a.team_id;
});

let mismatches = 0;
D.candidates.forEach((c, i) => {
  const jsTeam = js.assignedTeam[i] === -1 ? null : D.teams[js.assignedTeam[i]].id;
  const pyTeam = pyTeamOf[c.id] || null;
  if (jsTeam !== pyTeam) {
    mismatches++;
    if (mismatches <= 10) {
      console.log(`  ${c.id} ${c.name}: browser=${jsTeam} python=${pyTeam}`);
    }
  }
});

const pairs = [
  ["first choice", js.metrics.firstChoice, py.metrics.first_choice],
  ["top three", js.metrics.topThree, py.metrics.top_three],
  ["fallback", js.metrics.fallback, py.metrics.matched_by_fallback],
  ["unplaced", js.metrics.unplaced, py.metrics.unplaced],
  ["blocking pairs", js.metrics.blockingPairs, py.metrics.blocking_pairs],
  ["low fit", js.metrics.lowFit.length, py.metrics.low_fit_count],
];

let metricDrift = 0;
pairs.forEach(([label, a, b]) => {
  const ok = a === b;
  if (!ok) metricDrift++;
  console.log(`  ${ok ? "ok  " : "DIFF"} ${label.padEnd(16)} browser=${a} python=${b}`);
});

// The browser can add a candidate at runtime, which means rebuilding the team
// orderings locally — and that requires reproducing Python's seeded SHA-256
// tie-break exactly. If it ever diverges, adding one person would quietly
// reshuffle everyone else's ranking, which is the failure mode that
// test_adding_a_candidate_does_not_reshuffle_existing_tie_breaks guards on the
// Python side.
(async () => {
  const orderDrift = await E.verifyOrders();
  console.log("");
  if (orderDrift.length) {
    console.error(
      `TIE-BREAK FAILED — the browser's ordering diverges from Python in ` +
        `${orderDrift.length} team(s), e.g. ${orderDrift[0].team} at position ${orderDrift[0].position}.`
    );
    process.exit(1);
  }
  console.log(`  ok   tie-break reproduces Python's ordering (${D.teams.length} teams)`);

  console.log("");
  if (mismatches === 0 && metricDrift === 0) {
    console.log(`PARITY OK — ${D.candidates.length} placements identical.`);
    process.exit(0);
  }
  console.error(
    `PARITY FAILED — ${mismatches} placement mismatch(es), ${metricDrift} metric diff(s).`
  );
  process.exit(1);
})();
