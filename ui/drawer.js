// The per-candidate explanation panel.
//
// This is the artifact a recruiter shows when someone pushes back, so it is
// held to a stricter standard than the rest of the UI: every sentence here
// must be traceable to a field in the run record. If you cannot point at the
// number behind a claim, it does not belong on this screen.

import { html } from "./h.js";
import { matchPct, ordinal } from "./labels.js";
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
      On <b>${teamName}</b> because you put them there.
      ${rank > 0 ? ` It was their ${ordinal(rank)} pick.` : " They hadn’t asked for this team."}
    <//>`;
  }
  if (tier === "top_choice") return html`<span>Got their first pick: <b>${teamName}</b>.</span>`;
  if (tier === "ranked") {
    return html`<span>On <b>${teamName}</b> — their ${ordinal(rank)} pick.</span>`;
  }
  if (tier === "fallback") {
    return html`<span>
      On <b>${teamName}</b>. Every team they asked for was full by the time it came to them, so
      they went to the team that fit them best out of what was left.
    </span>`;
  }
  return html`<span>No seat yet — every team is full.</span>`;
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
          <h3>Where they landed</h3>
          <p class="verdict">${verdictFor(index, result)}</p>
          ${tier !== "unplaced" && tier !== "pinned"
            ? html`<p class="note">
                Every team they wanted more than this one was already full of people those teams
                rated higher. That is the answer if they ask why.
              </p>`
            : null}
          ${tier === "pinned"
            ? html`<p class="note">
                This was your call, not the system’s — and it stays labelled that way so nobody
                mistakes it for an automatic result.
              </p>`
            : null}
        </div>

        ${rejections.length
          ? html`
              <div class="dsec">
                <h3>Teams that didn’t have room</h3>
                <ul class="rejlist">
                  ${rejections.map(
                    (r) => html`
                      <li key=${r.team}>
                        <span class="t">${D.teams[r.team].name}</span><br />
                        <span class="n">
                          filled up with ${r.heldAbove}
                          ${r.heldAbove === 1 ? "person" : "people"} this team rated higher
                        </span>
                      </li>
                    `
                  )}
                </ul>
                <p class="note" style=${{ marginTop: "8px" }}>
                  Listed in the order they asked for them.
                </p>
              </div>
            `
          : null}

        ${fit
          ? html`
              <div class="dsec">
                <h3>How well they fit ${teamName} · ${matchPct(fit.total)}</h3>
                ${fit.total === 0
                  ? html`<p class="note">
                      This team didn’t ask for any of the skills they have. They’re here because
                      the team still had room when the teams they wanted filled up. Worth a word
                      with the manager before this is final.
                    </p>`
                  : null}
                <div class="bars">
                  ${[
                    ["Skills they need", fit.required],
                    ["Skills they’d like", fit.preferred],
                    ["Shared interests", fit.interest],
                    ["Manager asked for them", fit.wishlist],
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
                <h3>What they bring</h3>
                <div class="pillrow">
                  ${c.skills.map(
                    (s) => html`<span class="pill ${required.indexOf(s) !== -1 ? "match" : ""}" key=${s}>
                      ${pretty(s)}
                    </span>`
                  )}
                </div>
                <p class="note" style=${{ marginTop: "7px" }}>
                  Highlighted ones are what this team asked for.
                </p>
              </div>
            `
          : null}

        <div class="dsec">
          <h3>Teams they asked for</h3>
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
                They didn’t submit any team preferences, so we could only place them by fit.
              </p>`}
        </div>

        <div class="dsec">
          <h3>Move them somewhere else</h3>
          <${MoveControl} index=${index} state=${state} dispatch=${dispatch} />
          ${tier === "pinned"
            ? html`<button
                class="btn"
                style=${{ marginTop: "8px" }}
                onClick=${() => dispatch({ type: "unpin", candidate: index })}
              >
                Undo this move
              </button>`
            : null}
          <p class="note" style=${{ marginTop: "8px" }}>
            Moving someone takes a seat from whoever had it. You’ll see who, right after.
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
