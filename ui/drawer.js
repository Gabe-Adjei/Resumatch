// The per-candidate explanation panel.
//
// This is the artifact a recruiter shows when someone pushes back, so it is
// held to a stricter standard than the rest of the UI: every sentence here
// must be traceable to a field in the run record. If you cannot point at the
// number behind a claim, it does not belong on this screen.

import { html } from "./h.js";
import { TIER_LABEL } from "./store.js";
import { pretty } from "./taxonomy.js";

const D = window.RESUMATCH_DATA;
const E = window.RESUMATCH;

function verdictFor(index, result) {
  const c = D.candidates[index];
  const t = result.assignedTeam[index];
  const tier = result.tier[index];
  const teamName = t === -1 ? null : D.teams[t].name;
  const rank = result.rank[index];

  if (tier === "pinned") {
    return html`<${"span"}>
      <b>${teamName}</b> — placed here by a person, not by the algorithm.
      ${rank > 0
        ? ` It was their #${rank} choice.`
        : " They had not ranked this team."}
    <//>`;
  }
  if (tier === "top_choice") return html`<span><b>${teamName}</b> — their first choice.</span>`;
  if (tier === "ranked") return html`<span><b>${teamName}</b> — their #${rank} choice.</span>`;
  if (tier === "fallback") {
    return html`<span>
      <b>${teamName}</b>. None of the ${c.prefs.length} team${c.prefs.length === 1 ? "" : "s"}
      they ranked had a seat left once every team filled its headcount.
    </span>`;
  }
  return html`<span>Not placed — every team is at capacity.</span>`;
}

export function CandidateDrawer({ index, state, dispatch }) {
  const open = index !== null && index !== undefined;
  const close = () => dispatch({ type: "deselect" });

  return html`
    <${"div"}>
      <div class="scrim ${open ? "open" : ""}" onClick=${close}></div>
      <aside class="drawer ${open ? "open" : ""}" aria-hidden=${!open} aria-label="Candidate detail">
        ${open ? html`<${DrawerContents} index=${index} state=${state} dispatch=${dispatch} onClose=${close} />` : null}
      </aside>
    <//>
  `;
}

function DrawerContents({ index, state, dispatch, onClose }) {
  const c = D.candidates[index];
  const result = state.result;
  const t = result.assignedTeam[index];
  const tier = result.tier[index];
  const teamName = t === -1 ? null : D.teams[t].name;

  const rejections = (result.rejections[index] || [])
    .slice()
    .sort((a, b) => c.prefs.indexOf(a.team) - c.prefs.indexOf(b.team));

  const fit = t === -1 ? null : E.fitScore(index, t);
  const required = t === -1 ? [] : D.teams[t].required;

  return html`
    <${"div"} style=${{ display: "contents" }}>
      <div class="drawer-head">
        <div>
          <h2>${c.name}</h2>
          <div class="id">${c.id} · ${c.interests.join(", ") || "no stated interests"}</div>
        </div>
        <button class="btn sm" onClick=${onClose} aria-label="Close detail">Close</button>
      </div>

      <div class="drawer-body">
        <div class="dsec">
          <h3>Outcome</h3>
          <p class="verdict">${verdictFor(index, result)}</p>
          ${tier !== "unplaced" && tier !== "pinned"
            ? html`<p class="note">
                No team they ranked above this one would have taken them over someone it
                actually placed. That is what makes the result defensible.
              </p>`
            : null}
          ${tier === "pinned"
            ? html`<p class="note">
                Manual overrides are recorded separately from algorithmic placements, so this
                stays visible as a human decision.
              </p>`
            : null}
        </div>

        ${rejections.length
          ? html`
              <div class="dsec">
                <h3>Teams that could not take them</h3>
                <ul class="rejlist">
                  ${rejections.map(
                    (r) => html`
                      <li key=${r.team}>
                        <span class="t">${D.teams[r.team].name}</span><br />
                        <span class="n">
                          filled with ${r.heldAbove} candidate${r.heldAbove === 1 ? "" : "s"}
                          it scored higher · their fit ${r.yourScore.toFixed(2)}
                          ${r.cutoff !== null ? ` vs cutoff ${r.cutoff.toFixed(2)}` : ""}
                        </span>
                      </li>
                    `
                  )}
                </ul>
              </div>
            `
          : null}

        ${fit
          ? html`
              <div class="dsec">
                <h3>Fit with ${teamName} · ${fit.total.toFixed(2)}</h3>
                ${fit.total === 0
                  ? html`<p class="note">
                      Their skills do not overlap with this team's stated requirements. They are
                      here because the team still had headcount when their higher choices filled.
                      Worth a word with the manager before this is final.
                    </p>`
                  : null}
                <div class="bars">
                  ${[
                    ["Required skills", fit.required],
                    ["Preferred skills", fit.preferred],
                    ["Interest overlap", fit.interest],
                    ["Manager wishlist", fit.wishlist],
                  ].map(
                    ([label, value]) => html`
                      <div class="bar-row" key=${label}>
                        <span>${label}</span>
                        <span class="bar-track">
                          <span class="bar-fill" style=${{ width: (value * 100).toFixed(0) + "%" }}></span>
                        </span>
                        <span class="n">${(value * 100).toFixed(0)}%</span>
                      </div>
                    `
                  )}
                </div>
              </div>

              <div class="dsec">
                <h3>Skills</h3>
                <div class="pillrow">
                  ${c.skills.map(
                    (s) => html`<span class="pill ${required.indexOf(s) !== -1 ? "match" : ""}" key=${s}>
                      ${pretty(s)}
                    </span>`
                  )}
                </div>
              </div>
            `
          : null}

        <div class="dsec">
          <h3>What they asked for</h3>
          ${c.prefs.length
            ? html`
                <ol class="ranklist">
                  ${c.prefs.map(
                    (ti, n) => html`
                      <li class=${ti === t ? "got" : ""} key=${ti}>
                        <span class="num">${n + 1}</span>
                        <span>${D.teams[ti].name}</span>
                        ${ti === t
                          ? html`<span class="tag tier-${tier}" style=${{ marginLeft: "auto" }}>placed</span>`
                          : null}
                      </li>
                    `
                  )}
                </ol>
              `
            : html`<p class="note">
                They submitted no team preferences, so only the fallback round could place them.
              </p>`}
        </div>

        <div class="dsec">
          <h3>Move them</h3>
          <${MoveControl} index=${index} state=${state} dispatch=${dispatch} />
          ${tier === "pinned"
            ? html`<button
                class="btn"
                style=${{ marginTop: "8px" }}
                onClick=${() => dispatch({ type: "unpin", candidate: index })}
              >
                Release override
              </button>`
            : null}
          <p class="note" style=${{ marginTop: "8px" }}>
            Moving someone takes a seat the algorithm gave to somebody else. The board will show
            you who.
          </p>
        </div>
      </div>
    <//>
  `;
}

function MoveControl({ index, state, dispatch }) {
  const current = state.result.assignedTeam[index];
  const selectId = "move-target-" + index;

  return html`
    <div class="movebox">
      <select class="field" id=${selectId} aria-label="Move to team" defaultValue="">
        <option value="">Choose a team…</option>
        ${D.teams.map(
          (t, ti) => html`
            <option value=${ti} disabled=${ti === current} key=${ti}>
              ${t.name} (${state.result.rosters[ti].size}/${state.capacities[ti]})
            </option>
          `
        )}
      </select>
      <button
        class="btn"
        onClick=${() => {
          const el = document.getElementById(selectId);
          if (el && el.value !== "") {
            dispatch({ type: "pin", candidate: index, team: Number(el.value) });
            el.value = "";
          }
        }}
      >
        Move
      </button>
    </div>
  `;
}
