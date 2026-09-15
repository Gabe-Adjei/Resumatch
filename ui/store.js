// Application state.
//
// Every screen reads the same match result, so the state lives in one reducer
// rather than in the screens. The rule this enforces: nothing outside here
// mutates capacities or pins, and the match is re-run exactly once per change.
//
// `baseline` is the untouched algorithmic result, kept for the life of the
// session. Every override is measured against it, because the question a
// recruiter needs answered is not "what does the board say now" but "what did
// my change cost".

const D = window.RESUMATCH_DATA;
const E = window.RESUMATCH;

export const TIER_LABEL = {
  top_choice: "1st choice",
  ranked: "ranked",
  fallback: "fallback",
  pinned: "manual",
  unplaced: "unplaced",
};

/** First-choice demand per team — the oversubscription signal. */
export const demand = D.teams.map(() => 0);
D.candidates.forEach((c) => {
  if (c.prefs.length) demand[c.prefs[0]]++;
});

export function createInitialState() {
  const capacities = D.teams.map((t) => t.capacity);
  const result = E.runMatch(capacities, {});
  return {
    capacities,
    pins: {},
    history: [],
    result,
    baseline: result,
    selected: null,
    lastChange: null,
  };
}

function snapshot(state) {
  const history = state.history.concat([
    { capacities: state.capacities.slice(), pins: Object.assign({}, state.pins) },
  ]);
  // Bounded so a long session does not accumulate unbounded snapshots.
  return history.length > 40 ? history.slice(1) : history;
}

/** Re-run the match and describe what moved, in one place. */
function applied(state, capacities, pins, headline) {
  const result = E.runMatch(capacities, pins);
  return Object.assign({}, state, {
    capacities,
    pins,
    result,
    history: snapshot(state),
    lastChange: { headline, moved: E.diff(state.result, result) },
  });
}

export function reducer(state, action) {
  switch (action.type) {
    case "select":
      return Object.assign({}, state, { selected: action.candidate });

    case "deselect":
      return Object.assign({}, state, { selected: null });

    case "dismiss":
      return Object.assign({}, state, { lastChange: null });

    case "note":
      // A message with no state change — used for things that did not happen,
      // like a refused pin. Saying why beats silently ignoring the drag.
      return Object.assign({}, state, {
        lastChange: { headline: action.headline, moved: [], info: true },
      });

    case "pin": {
      const { candidate, team } = action;
      if (state.result.assignedTeam[candidate] === team && state.result.tier[candidate] === "pinned") {
        return state;
      }

      // A pin can never exceed capacity. Refuse loudly and name the fix.
      const pinnedHere = Object.keys(state.pins).filter(
        (k) => state.pins[k] === team && Number(k) !== candidate
      ).length;
      if (pinnedHere + 1 > state.capacities[team]) {
        const cap = state.capacities[team];
        return reducer(state, {
          type: "note",
          headline:
            `${D.teams[team].name} has ${cap} slot${cap === 1 ? "" : "s"} and they are all ` +
            `manually assigned, so ${D.candidates[candidate].name} cannot be added. ` +
            `Release an override or add a slot first.`,
        });
      }

      const pins = Object.assign({}, state.pins, { [candidate]: team });
      return applied(
        state,
        state.capacities,
        pins,
        `<strong>${D.candidates[candidate].name}</strong> moved to <strong>${D.teams[team].name}</strong>.`
      );
    }

    case "unpin": {
      const pins = Object.assign({}, state.pins);
      delete pins[action.candidate];
      return applied(
        state,
        state.capacities,
        pins,
        `Override on <strong>${D.candidates[action.candidate].name}</strong> released; ` +
          `the algorithm placed them again.`
      );
    }

    case "capacity": {
      const next = state.capacities[action.team] + action.delta;
      if (next < 0) return state;
      const capacities = state.capacities.slice();
      capacities[action.team] = next;
      return applied(
        state,
        capacities,
        state.pins,
        `<strong>${D.teams[action.team].name}</strong> went from ` +
          `${state.capacities[action.team]} to ${next} slot${next === 1 ? "" : "s"}.`
      );
    }

    case "undo": {
      if (!state.history.length) return state;
      const prev = state.history[state.history.length - 1];
      const result = E.runMatch(prev.capacities, prev.pins);
      return Object.assign({}, state, {
        capacities: prev.capacities,
        pins: prev.pins,
        result,
        history: state.history.slice(0, -1),
        lastChange: { headline: "Reverted the last change.", moved: E.diff(state.result, result) },
      });
    }

    case "reset": {
      const capacities = D.teams.map((t) => t.capacity);
      return applied(
        state,
        capacities,
        {},
        "Back to the algorithm's own result, overrides cleared."
      );
    }

    default:
      return state;
  }
}

/** Has anything been changed from the algorithm's own result? */
export function isTouched(state) {
  return (
    Object.keys(state.pins).length > 0 ||
    state.capacities.some((c, i) => c !== D.teams[i].capacity)
  );
}

/** Assignments as CSV rows, for export. */
export function toCsv(state) {
  const r = state.result;
  const rows = [["candidate_id", "name", "team", "preference_rank", "how_placed", "fit_score"]];
  D.candidates.forEach((c, i) => {
    const t = r.assignedTeam[i];
    rows.push([
      c.id,
      c.name,
      t === -1 ? "UNPLACED" : D.teams[t].name,
      r.rank[i] > 0 ? r.rank[i] : "",
      TIER_LABEL[r.tier[i]],
      t === -1 ? "" : E.score(i, t).toFixed(3),
    ]);
  });
  return rows
    .map((row) =>
      row
        .map((cell) => {
          const s = String(cell);
          return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
        })
        .join(",")
    )
    .join("\n");
}
