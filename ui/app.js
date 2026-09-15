// Root component: state, chrome, and one screen.
//
// There is deliberately no router. An earlier version had four tabs
// (Overview / Board / Teams / Intake) and the navigation itself was the main
// source of confusion — abstract names, no obvious starting point, and two
// tabs showing the same rosters. Collapsing to a single workspace removed the
// problem rather than relabelling it.

import React, { html, useEffect, useReducer } from "./h.js";
import { createInitialState, reducer, isTouched, toCsv } from "./store.js";
import { Workspace } from "./screens.js";
import { CandidateDrawer } from "./drawer.js";

const D = window.RESUMATCH_DATA;

function App() {
  const [state, dispatch] = useReducer(reducer, null, createInitialState);

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
            `Copied all ${D.candidates.length} placements. Paste straight into a spreadsheet.`,
        })
      )
      .catch(() =>
        dispatch({
          type: "note",
          headline:
            "Couldn’t reach the clipboard — your browser blocked it. Try again, or run " +
            "<strong>python3 -m resumatch export</strong> to write a file instead.",
        })
      );
  }

  return html`
    <${React.Fragment}>
      <div class="app">
        <header class="masthead">
          <div class="brand">
            <h1>Summer 2026 Placement</h1>
            <p class="sub">
              ${D.candidates.length} interns · ${D.teams.length} teams · example data
            </p>
          </div>
          <div class="toolbar">
            <button
              class="btn"
              disabled=${!state.history.length}
              onClick=${() => dispatch({ type: "undo" })}
            >
              Undo
            </button>
            <button
              class="btn"
              disabled=${!isTouched(state)}
              onClick=${() => dispatch({ type: "reset" })}
            >
              Start over
            </button>
            <button class="btn primary" onClick=${exportCsv}>Copy as spreadsheet</button>
          </div>
        </header>

        <${Workspace} state=${state} dispatch=${dispatch} />
      </div>

      <${CandidateDrawer} index=${state.selected} state=${state} dispatch=${dispatch} />
    <//>
  `;
}

const root = window.ReactDOM.createRoot(document.getElementById("root"));
root.render(html`<${App} />`);
