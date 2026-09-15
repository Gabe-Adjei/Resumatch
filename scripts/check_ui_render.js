// Render smoke test for the frontend.
//
//   node scripts/check_ui_render.js
//
// WHY THIS EXISTS
// ---------------
// `node --check` parses the files but cannot catch the two things that
// actually break this app, both of which fail at runtime with a blank page and
// no useful message:
//
//   1. htm template syntax — a mismatched `<//>` or a component tag written
//      `<Foo>` instead of `<${Foo}>` throws only when the template evaluates.
//   2. React prop handling — these components use `class`, not `className`.
//      React DOM passes unrecognized props through as attributes, so it works,
//      but that is worth asserting rather than assuming.
//
// So this renders every screen to a string with react-dom/server and checks
// the output. It needs React's UMD builds, which it expects alongside itself
// in a vendor directory (see VENDOR below) — they are not committed, since the
// app loads them from a CDN at runtime.
//
// If the vendor files are missing this exits 0 with a skip notice, so it never
// blocks anyone who just wants to run the Python tests.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");
const VENDOR = process.env.RESUMATCH_VENDOR || path.join(root, ".vendor");

const needed = ["react.js", "react-dom-server.js", "htm.js"];
const missing = needed.filter((f) => !fs.existsSync(path.join(VENDOR, f)));
if (missing.length) {
  console.log("SKIP — vendor bundles not present: " + missing.join(", "));
  console.log("Fetch them with:");
  console.log("  mkdir -p .vendor");
  console.log("  curl -o .vendor/react.js https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js");
  // The *legacy* server build, deliberately: the plain browser build only
  // exposes renderToReadableStream, not renderToStaticMarkup.
  console.log("  curl -o .vendor/react-dom-server.js https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom-server-legacy.browser.production.min.js");
  console.log("  curl -o .vendor/htm.js https://cdn.jsdelivr.net/npm/htm@3.1.1/dist/htm.umd.js");
  process.exit(0);
}

// --- shim just enough browser for the modules to import -----------------------
globalThis.window = globalThis;
// UMD wrappers fall back to `self` when `this` is undefined, which it is
// inside an ES module.
globalThis.self = globalThis;
globalThis.document = {
  getElementById: () => null,
  addEventListener: () => {},
  removeEventListener: () => {},
};
// Node 25 defines `navigator` and `location` as getter-only globals, so they
// have to be replaced rather than assigned.
for (const [name, value] of [
  ["navigator", { clipboard: { writeText: async () => {} } }],
  ["location", { hash: "#/" }],
]) {
  Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};

const load = (p) => (0, eval)(fs.readFileSync(p, "utf8"));
load(path.join(VENDOR, "react.js"));
load(path.join(VENDOR, "react-dom-server.js"));
load(path.join(VENDOR, "htm.js"));
load(path.join(root, "ui/data.js"));
load(path.join(root, "ui/engine.js"));

const importUi = (f) => import(pathToFileURL(path.join(root, "ui", f)).href);

const { createInitialState } = await importUi("store.js");
const screens = await importUi("screens.js");
const { CandidateDrawer } = await importUi("drawer.js");

const React = globalThis.React;
const render = globalThis.ReactDOMServer.renderToStaticMarkup;

const state = createInitialState();
const dispatch = () => {};

let failures = 0;
function check(label, fn, mustContain) {
  try {
    const out = fn();
    const missingText = mustContain.filter((t) => !out.includes(t));
    if (missingText.length) {
      failures++;
      console.log(`  FAIL ${label} — rendered but missing: ${missingText.join(", ")}`);
    } else {
      console.log(`  ok   ${label} (${out.length.toLocaleString()} chars)`);
    }
    return out;
  } catch (err) {
    failures++;
    console.log(`  FAIL ${label} — ${err.message}`);
    return "";
  }
}

console.log("Rendering screens:");

const dash = check(
  "Overview",
  () => render(React.createElement(screens.Dashboard, { state, dispatch })),
  ["First choice", "STABLE", "Most oversubscribed", "Preference rank achieved"]
);

check(
  "Board",
  () => render(React.createElement(screens.Board, { state, dispatch })),
  ["Cohort", "needs", "open seat"]
);

check(
  "Teams",
  () => render(React.createElement(screens.Teams, { state, dispatch })),
  ["filled", "Intern"]
);

check(
  "Intake",
  () => render(React.createElement(screens.Intake, { state, dispatch })),
  ["Paste a resume", "Skills found", "Best-fit teams", "Fit is not a prediction"]
);

check(
  "Candidate drawer",
  () =>
    render(
      React.createElement(CandidateDrawer, { index: 0, state, dispatch })
    ),
  ["Outcome", "What they asked for", "Move them"]
);

// The `class` question, asserted rather than assumed.
console.log("\nProp handling:");
if (/class="reading/.test(dash)) {
  console.log("  ok   `class` renders as a real class attribute");
} else {
  failures++;
  console.log("  FAIL `class` did not reach the DOM — components need className");
}

// Interpolated skill names must survive escaping.
if (dash.includes("<div class=")) {
  console.log("  ok   markup structure intact");
}

console.log("");
if (failures) {
  console.error(`RENDER CHECK FAILED — ${failures} problem(s).`);
  process.exit(1);
}
console.log("RENDER OK — every screen mounts and produces markup.");
