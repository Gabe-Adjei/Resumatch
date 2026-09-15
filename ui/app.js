// Root component: state, routing, chrome.

import React, { html, useEffect, useReducer, useState } from "./h.js";
import { createInitialState, reducer, isTouched, toCsv } from "./store.js";
import { Dashboard, Board, Teams, Intake } from "./screens.js";
import { CandidateDrawer } from "./drawer.js";

const D = window.RESUMATCH_DATA;

const ROUTES = [
  ["#/", "Overview", Dashboard],
  ["#/board", "Board", Board],
  ["#/teams", "Teams", Teams],
  ["#/intake", "Intake", Intake],
];

/** Hash routing — no router dependency, and it survives a republish. */
function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return ROUTES.some((r) => r[0] === hash) ? hash : "#/";
}

function App() {
  const [state, dispatch] = useReducer(reducer, null, createInitialState);
  const route = useHashRoute();
  const Screen = (ROUTES.find((r) => r[0] === route) || ROUTES[0])[2];

  useEffect(() => {
    const onKey = (ev) => {
      if (ev.key === "Escape") dispatch({ type: "deselect" });
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  function exportCsv() {
    // The artifact sandbox blocks page-initiated downloads, so hand the rows
    // over in a way that always works and say plainly what happened.
    navigator.clipboard
      .writeText(toCsv(state))
      .then(() =>
        dispatch({
          type: "note",
          headline:
            `<strong>${D.candidates.length} placements</strong> copied to your clipboard as ` +
            `CSV — paste straight into a sheet.`,
        })
      )
      .catch(() =>
        dispatch({
          type: "note",
          headline:
            "Could not reach the clipboard. Run <strong>python3 -m resumatch export</strong> " +
            "to write the same rows to a file.",
        })
      );
  }

  return html`
    <${React.Fragment}>
      <div class="app">
        <header class="masthead">
          <div class="brand">
            <h1>Resumatch</h1>
            <p class="sub">
              Summer 2026 tech cohort · ${D.candidates.length} interns · ${D.teams.length} teams ·
              synthetic data · cohort <code>${D.cohortHash.slice(0, 12)}</code>
            </p>
          </div>
          <div class="toolbar">
            <button class="btn" disabled=${!state.history.length} onClick=${() => dispatch({ type: "undo" })}>
              Undo
            </button>
            <button class="btn" disabled=${!isTouched(state)} onClick=${() => dispatch({ type: "reset" })}>
              Reset to algorithm
            </button>
            <button class="btn primary" onClick=${exportCsv}>Export CSV</button>
          </div>
        </header>

        <nav class="nav" aria-label="Screens">
          ${ROUTES.map(
            ([path, label]) => html`
              <a key=${path} href=${path} aria-current=${route === path ? "page" : undefined}>
                ${label}
              </a>
            `
          )}
        </nav>

        <${Screen} state=${state} dispatch=${dispatch} />

        <footer class="foot">
          <span>Candidate-proposing deferred acceptance (Gale–Shapley), capacities per team.</span>
          <span>Team rankings computed by <code>resumatch/scoring.py</code>.</span>
          <span>Drag anyone onto a team to override — the board shows what it costs.</span>
        </footer>
      </div>

      <${CandidateDrawer} index=${state.selected} state=${state} dispatch=${dispatch} />
    <//>
  `;
}

const root = window.ReactDOM.createRoot(document.getElementById("root"));
root.render(html`<${App} />`);
