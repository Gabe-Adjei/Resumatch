// The four screens.
//
// Each one answers a different person's question:
//   Dashboard  the program manager: is this cycle in good shape, and what
//              needs my attention before it goes out?
//   Board      the program manager again, mid-negotiation: move this person,
//              show me what it costs.
//   Teams      a hiring manager: who is on my team, and why them?
//   Intake     a candidate or recruiter: given this resume, where do they fit?

import { html, useMemo, useState } from "./h.js";
import { TIER_LABEL, demand, isTouched } from "./store.js";
import {
  Banner,
  Delta,
  EmptyState,
  FilterChips,
  Histogram,
  Legend,
  PersonRow,
  Reading,
  SlotMeter,
  TierTag,
} from "./components.js";
import { parseResume, pretty } from "./taxonomy.js";

const D = window.RESUMATCH_DATA;
const E = window.RESUMATCH;

/* ========================================================================== */
/* Dashboard                                                                  */
/* ========================================================================== */

export function Dashboard({ state, dispatch }) {
  const m = state.result.metrics;
  const b = state.baseline.metrics;
  const touched = isTouched(state);
  const stable = m.blockingPairs === 0;

  const oversubscribed = useMemo(() => {
    return D.teams
      .map((t, i) => ({
        name: t.name,
        index: i,
        demand: demand[i],
        capacity: state.capacities[i],
        ratio: state.capacities[i] ? demand[i] / state.capacities[i] : null,
      }))
      .sort((a, b2) => (b2.ratio || 0) - (a.ratio || 0))
      .slice(0, 6);
  }, [state.capacities]);

  const maxRatio = Math.max(1, ...oversubscribed.map((o) => o.ratio || 0));

  return html`
    <div class="stack">
      <section class="readings" aria-label="Cohort summary">
        <${Reading}
          label="Placed"
          value=${`${m.placed} / ${m.cohortSize}`}
          detail=${m.unplaced ? `${m.unplaced} unplaced` : "everyone has a seat"}
        />
        <${Reading}
          label="First choice"
          value=${m.firstChoicePct.toFixed(0) + "%"}
          detail=${touched
            ? html`<${Delta} now=${m.firstChoicePct} was=${b.firstChoicePct} />`
            : `${m.firstChoice} interns`}
        />
        <${Reading}
          label="Top three"
          value=${m.topThreePct.toFixed(0) + "%"}
          detail=${touched
            ? html`<${Delta} now=${m.topThreePct} was=${b.topThreePct} />`
            : `${m.topThree} interns`}
        />
        <${Reading}
          label="Mean rank"
          value=${m.meanRank.toFixed(2)}
          detail=${touched
            ? html`<${Delta} now=${m.meanRank} was=${b.meanRank} digits=${2} />`
            : "of the choices they listed"}
        />
        <${Reading} label="Fallback" value=${String(m.fallback)} detail="none of their picks had room" />
        <${Reading}
          label="Manual"
          value=${String(m.pinned)}
          detail=${m.pinned ? "overrides applied" : "no overrides"}
        />
        <${Reading}
          label="Integrity"
          value=${stable ? "STABLE" : `${m.blockingPairs} blocking`}
          detail=${stable ? "no swap both sides would take" : "an override created a better swap"}
          variant=${"integrity" + (stable ? "" : " broken")}
        />
      </section>

      <${Banner} change=${state.lastChange} onDismiss=${() => dispatch({ type: "dismiss" })} />

      <div class="cols two">
        <section class="panel">
          <div class="panel-head">
            Preference rank achieved
            <span class="count">${m.cohortSize} interns</span>
          </div>
          <div class="panel-body">
            <${Histogram}
              histogram=${m.histogram}
              fallback=${m.fallback}
              total=${m.cohortSize}
            />
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            Most oversubscribed
            <span class="count">first choices per slot</span>
          </div>
          <div class="panel-body">
            <div class="table-wrap">
              <table class="data">
                <thead>
                  <tr>
                    <th>Team</th>
                    <th class="num">Want</th>
                    <th class="num">Slots</th>
                    <th>Pressure</th>
                  </tr>
                </thead>
                <tbody>
                  ${oversubscribed.map(
                    (o) => html`
                      <tr key=${o.index}>
                        <td class="name">${o.name}</td>
                        <td class="num">${o.demand}</td>
                        <td class="num">${o.capacity}</td>
                        <td>
                          <div class="ratio">
                            <span class="ratio-track">
                              <span
                                class="ratio-fill ${(o.ratio || 0) <= 1 ? "ok" : ""}"
                                style=${{ width: (100 * (o.ratio || 0)) / maxRatio + "%" }}
                              ></span>
                            </span>
                            <span class="num">${o.ratio === null ? "—" : o.ratio.toFixed(1) + "x"}</span>
                          </div>
                        </td>
                      </tr>
                    `
                  )}
                </tbody>
              </table>
            </div>
            <p class="note" style=${{ marginTop: "10px" }}>
              A team above 1.0x cannot seat everyone who ranked it first. This is the single
              biggest reason someone does not get their top pick.
            </p>
          </div>
        </section>
      </div>

      <${ReviewQueue} state=${state} dispatch=${dispatch} />
    </div>
  `;
}

/**
 * Placements that got their seat on tie-break rather than on any stated skill
 * overlap. Surfaced as a queue rather than buried, because this is exactly the
 * list worth eyeballing before a match goes out.
 */
function ReviewQueue({ state, dispatch }) {
  const m = state.result.metrics;
  if (!m.lowFit.length) {
    return html`
      <section class="panel">
        <div class="panel-head">Needs a human look</div>
        <${EmptyState}>
          Every placement has some stated skill or interest overlap. Nothing to review.
        <//>
      </section>
    `;
  }

  return html`
    <section class="panel">
      <div class="panel-head">
        Needs a human look
        <span class="count">${m.lowFit.length} below ${m.lowFitThreshold.toFixed(2)} fit</span>
      </div>
      <div class="panel-body">
        <p class="note" style=${{ marginBottom: "10px" }}>
          These got their seat on tie-break, not on stated skill overlap — the team had headcount
          and they had ranked it. Legitimate, but worth a conversation with the manager first.
        </p>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>Intern</th>
                <th>Placed on</th>
                <th>How</th>
                <th class="num">Fit</th>
              </tr>
            </thead>
            <tbody>
              ${m.lowFit.slice(0, 12).map((ci) => {
                const t = state.result.assignedTeam[ci];
                return html`
                  <tr key=${ci}>
                    <td>
                      <button class="linkish" onClick=${() => dispatch({ type: "select", candidate: ci })}>
                        ${D.candidates[ci].name}
                      </button>
                    </td>
                    <td>${t === -1 ? "—" : D.teams[t].name}</td>
                    <td><${TierTag} tier=${state.result.tier[ci]} rank=${state.result.rank[ci]} /></td>
                    <td class="num">${t === -1 ? "—" : E.score(ci, t).toFixed(2)}</td>
                  </tr>
                `;
              })}
            </tbody>
          </table>
        </div>
        ${m.lowFit.length > 12
          ? html`<p class="note" style=${{ marginTop: "8px" }}>
              …and ${m.lowFit.length - 12} more.
            </p>`
          : null}
      </div>
    </section>
  `;
}

/* ========================================================================== */
/* Board                                                                      */
/* ========================================================================== */

const FILTERS = [
  ["all", "All"],
  ["top_choice", "1st"],
  ["ranked", "Ranked"],
  ["fallback", "Fallback"],
  ["pinned", "Manual"],
  ["lowfit", "Low fit"],
];

export function Board({ state, dispatch }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");

  const visible = useMemo(() => {
    const r = state.result;
    const lowFit = new Set(r.metrics.lowFit);
    const q = query.trim().toLowerCase();

    return D.candidates
      .map((_, i) => i)
      .filter((i) => {
        if (filter === "lowfit") {
          if (!lowFit.has(i)) return false;
        } else if (filter !== "all" && r.tier[i] !== filter) {
          return false;
        }
        if (!q) return true;
        const c = D.candidates[i];
        return (
          c.name.toLowerCase().includes(q) ||
          c.id.toLowerCase().includes(q) ||
          c.skills.some((s) => pretty(s).includes(q))
        );
      });
  }, [state.result, query, filter]);

  return html`
    <div class="stack">
      <${Banner} change=${state.lastChange} onDismiss=${() => dispatch({ type: "dismiss" })} />

      <div class="board">
        <section class="panel" aria-label="Cohort">
          <div class="panel-head">
            Cohort
            <span class="count">${visible.length} / ${D.candidates.length}</span>
          </div>
          <div class="pool-controls">
            <input
              type="search"
              id="board-search"
              placeholder="Search name or skill…"
              aria-label="Search the cohort"
              value=${query}
              onInput=${(e) => setQuery(e.target.value)}
            />
            <${FilterChips} options=${FILTERS} value=${filter} onChange=${setFilter} />
          </div>
          <div class="pool">
            ${visible.length
              ? visible.map(
                  (i) => html`
                    <${PersonRow}
                      key=${i}
                      index=${i}
                      result=${state.result}
                      selected=${state.selected === i}
                      onSelect=${(ci) => dispatch({ type: "select", candidate: ci })}
                    />
                  `
                )
              : html`<${EmptyState}>Nobody matches that filter.<//>`}
          </div>
          <${Legend} />
        </section>

        <section aria-label="Teams">
          <div class="teams">
            ${D.teams.map(
              (t, ti) => html`<${TeamCard} key=${ti} team=${t} index=${ti} state=${state} dispatch=${dispatch} />`
            )}
          </div>
        </section>
      </div>
    </div>
  `;
}

function TeamCard({ team, index, state, dispatch }) {
  const [over, setOver] = useState(false);
  const r = state.result;
  const cap = state.capacities[index];

  const members = useMemo(
    () => Array.from(r.rosters[index]).sort((a, b) => E.score(b, index) - E.score(a, index)),
    [r, index]
  );
  const open = cap - members.length;

  return html`
    <article
      class="team ${members.length >= cap ? "is-full" : ""} ${over ? "drop-target" : ""}"
      onDragOver=${(ev) => {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
        setOver(true);
      }}
      onDragLeave=${() => setOver(false)}
      onDrop=${(ev) => {
        ev.preventDefault();
        setOver(false);
        const ci = Number(ev.dataTransfer.getData("text/plain"));
        if (!Number.isNaN(ci)) dispatch({ type: "pin", candidate: ci, team: index });
      }}
    >
      <div class="team-head">
        <div class="row">
          <h3>${team.name}</h3>
          <span class="cap-controls">
            <button
              class="cap-btn"
              aria-label=${`Remove a slot from ${team.name}`}
              disabled=${cap <= members.length}
              onClick=${() => dispatch({ type: "capacity", team: index, delta: -1 })}
            >
              −
            </button>
            <span class="cap">
              ${members.length}/${cap}${cap !== team.capacity ? " *" : ""}
            </span>
            <button
              class="cap-btn"
              aria-label=${`Add a slot to ${team.name}`}
              onClick=${() => dispatch({ type: "capacity", team: index, delta: 1 })}
            >
              +
            </button>
          </span>
        </div>
        <div class="needs">
          needs <b>${team.required.map(pretty).join(", ")}</b>
          ${demand[index] ? ` · ${demand[index]} ranked it 1st` : ""}
        </div>
        <${SlotMeter} capacity=${cap} members=${members} tierOf=${(ci) => r.tier[ci]} />
      </div>
      <div class="members">
        ${members.map(
          (ci) => html`
            <button
              class="member"
              key=${ci}
              aria-selected=${state.selected === ci}
              onClick=${() => dispatch({ type: "select", candidate: ci })}
            >
              <span class="nm">${D.candidates[ci].name}</span>
              <${TierTag} tier=${r.tier[ci]} rank=${r.rank[ci]} />
            </button>
          `
        )}
        ${open > 0 ? html`<div class="empty-slot">${open} open seat${open === 1 ? "" : "s"}</div>` : null}
      </div>
    </article>
  `;
}

/* ========================================================================== */
/* Teams — the hiring manager's view                                          */
/* ========================================================================== */

export function Teams({ state, dispatch }) {
  const [selected, setSelected] = useState(0);
  const r = state.result;
  const team = D.teams[selected];
  const cap = state.capacities[selected];

  const members = useMemo(
    () => Array.from(r.rosters[selected]).sort((a, b) => E.score(b, selected) - E.score(a, selected)),
    [r, selected]
  );

  const wishlistHits = members.filter((ci) => team.wishlist.indexOf(ci) !== -1);

  return html`
    <div class="stack">
      <${Banner} change=${state.lastChange} onDismiss=${() => dispatch({ type: "dismiss" })} />

      <div class="cols" style=${{ gridTemplateColumns: "minmax(0, 260px) minmax(0, 1fr)" }}>
        <section class="panel">
          <div class="panel-head">Teams<span class="count">${D.teams.length}</span></div>
          <div class="pool" style=${{ maxHeight: "560px" }}>
            ${D.teams.map((t, ti) => {
              const filled = r.rosters[ti].size;
              return html`
                <button
                  class="person"
                  key=${ti}
                  aria-selected=${selected === ti}
                  draggable="false"
                  onClick=${() => setSelected(ti)}
                >
                  <span class="stripe ${filled >= state.capacities[ti] ? "tier-ranked" : "tier-fallback"}"></span>
                  <span class="who">
                    <span class="nm">${t.name}</span>
                    <span class="mt">${t.domains.join(", ")}</span>
                  </span>
                  <span class="sc">${filled}/${state.capacities[ti]}</span>
                </button>
              `;
            })}
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            ${team.name}
            <span class="count">${members.length}/${cap} filled</span>
          </div>
          <div class="panel-body">
            <p class="note" style=${{ marginBottom: "12px" }}>
              Wants <b style=${{ color: "var(--ink-2)" }}>${team.required.map(pretty).join(", ")}</b>
              ${team.preferred.length ? `, ideally also ${team.preferred.map(pretty).join(", ")}` : ""}.
              ${demand[selected]} intern${demand[selected] === 1 ? "" : "s"} ranked this team first.
            </p>

            ${members.length
              ? html`
                  <div class="table-wrap">
                    <table class="data">
                      <thead>
                        <tr>
                          <th>Intern</th>
                          <th>Their choice</th>
                          <th>Key skills</th>
                          <th class="num">Fit</th>
                        </tr>
                      </thead>
                      <tbody>
                        ${members.map((ci) => {
                          const c = D.candidates[ci];
                          const matched = c.skills.filter((s) => team.required.indexOf(s) !== -1);
                          return html`
                            <tr key=${ci}>
                              <td>
                                <button
                                  class="linkish"
                                  onClick=${() => dispatch({ type: "select", candidate: ci })}
                                >
                                  ${c.name}
                                </button>
                              </td>
                              <td><${TierTag} tier=${r.tier[ci]} rank=${r.rank[ci]} /></td>
                              <td>
                                ${matched.length
                                  ? matched.map(pretty).join(", ")
                                  : html`<span style=${{ color: "var(--ink-3)" }}>none of the required</span>`}
                              </td>
                              <td class="num">${E.score(ci, selected).toFixed(2)}</td>
                            </tr>
                          `;
                        })}
                      </tbody>
                    </table>
                  </div>
                `
              : html`<${EmptyState}>No one is placed on this team yet.<//>`}

            ${cap - members.length > 0
              ? html`<p class="note" style=${{ marginTop: "10px" }}>
                  ${cap - members.length} seat${cap - members.length === 1 ? "" : "s"} still open.
                </p>`
              : null}

            ${wishlistHits.length
              ? html`<p class="note" style=${{ marginTop: "10px" }}>
                  From the manager's wishlist:
                  <b style=${{ color: "var(--ink-2)" }}>
                    ${wishlistHits.map((ci) => D.candidates[ci].name).join(", ")}
                  </b>
                  ${" "}(${wishlistHits.length} of ${team.wishlist.length} named).
                </p>`
              : team.wishlist.length
              ? html`<p class="note" style=${{ marginTop: "10px" }}>
                  None of the ${team.wishlist.length} people this manager named ended up here —
                  each was placed somewhere they ranked higher, or lost a seat to a stronger fit.
                </p>`
              : null}
          </div>
        </section>
      </div>
    </div>
  `;
}

/* ========================================================================== */
/* Intake — resume in, best-fit teams out                                     */
/* ========================================================================== */

const SAMPLE_RESUME = `Priya Raman
priya.raman@osu.edu | github.com/praman | Columbus, OH

EDUCATION
The Ohio State University — B.S. Computer Science & Engineering, expected 2027

EXPERIENCE
Software Engineering Intern — Acme Corp (Summer 2025)
  Built REST APIs in Python and Go, backed by PostgreSQL.
  Containerized six services with Docker and deployed them on Kubernetes.
  Set up CI/CD with GitHub Actions, cutting deploy time from 25 minutes to 4.

PROJECTS
  Sentiment classifier using PyTorch, trained on 500k reviews.
  Course scheduling tool in TypeScript and React.

INTERESTS
  Interested in backend and infrastructure work, especially platform reliability.`;

export function Intake({ state }) {
  const [text, setText] = useState(SAMPLE_RESUME);
  const parsed = useMemo(() => parseResume(text), [text]);

  // Score the parsed profile against every team. This is advisory only — it
  // says which teams need these skills, not where this person would land,
  // which also depends on capacity and on who else applies.
  const ranked = useMemo(() => {
    const skills = new Set(parsed.skills);
    const interests = new Set(parsed.interests);
    const W = D.weights;

    return D.teams
      .map((t, ti) => {
        const ratio = (have, want) =>
          want.length ? want.filter((w) => have.has(w)).length / want.length : 0;
        const required = ratio(skills, t.required);
        const preferred = ratio(skills, t.preferred);
        const interest = ratio(interests, t.domains);
        const total = W.required * required + W.preferred * preferred + W.interest * interest;

        return {
          index: ti,
          name: t.name,
          total,
          matched: t.required.filter((s) => skills.has(s)),
          missing: t.required.filter((s) => !skills.has(s)),
          bonus: t.preferred.filter((s) => skills.has(s)),
          capacity: state.capacities[ti],
          demand: demand[ti],
        };
      })
      .sort((a, b) => b.total - a.total)
      .slice(0, 6);
  }, [parsed, state.capacities]);

  return html`
    <div class="intake-grid">
      <section class="panel">
        <div class="panel-head">Paste a resume</div>
        <div class="panel-body">
          <label class="section-title" for="resume-text">Resume text</label>
          <textarea
            class="field"
            id="resume-text"
            value=${text}
            onInput=${(e) => setText(e.target.value)}
            spellcheck="false"
          ></textarea>

          <div style=${{ marginTop: "12px" }}>
            <div class="section-title">Skills found</div>
            <div class="pillrow">
              ${parsed.skills.length
                ? parsed.skills.map((s) => html`<span class="pill match" key=${s}>${pretty(s)}</span>`)
                : html`<span class="note">Nothing recognized yet.</span>`}
            </div>
          </div>

          <div style=${{ marginTop: "12px" }}>
            <div class="section-title">Interests inferred</div>
            <div class="pillrow">
              ${parsed.interests.length
                ? parsed.interests.map((s) => html`<span class="pill" key=${s}>${s}</span>`)
                : html`<span class="note">None.</span>`}
            </div>
          </div>

          ${parsed.warnings.length
            ? html`<ul class="warnlist">
                ${parsed.warnings.map((w, i) => html`<li key=${i}>${w}</li>`)}
              </ul>`
            : null}

          <p class="note" style=${{ marginTop: "12px" }}>
            Extraction reads skills and domain language only — never names, schools or employers.
            Preferences are never guessed from resume text; the candidate has to state them.
          </p>
        </div>
      </section>

      <section>
        <div class="panel-head" style=${{ border: 0, paddingLeft: 0 }}>
          Best-fit teams
          <span class="count">${parsed.name || "unnamed candidate"}</span>
        </div>
        ${ranked.map(
          (r, i) => html`
            <div class="fitcard" key=${r.index}>
              <div class="row">
                <h4><span class="rank-badge">${i + 1}</span> ${r.name}</h4>
                <span class="score">${r.total.toFixed(2)}</span>
              </div>
              ${r.matched.length
                ? html`<div class="line">
                    <b>strengths they need</b><br />
                    <span class="pillrow">
                      ${r.matched.map((s) => html`<span class="pill match" key=${s}>${pretty(s)}</span>`)}
                    </span>
                  </div>`
                : null}
              ${r.missing.length
                ? html`<div class="line">
                    <b>gaps</b><br />
                    <span class="pillrow">
                      ${r.missing.map((s) => html`<span class="pill gap" key=${s}>${pretty(s)}</span>`)}
                    </span>
                  </div>`
                : null}
              ${r.bonus.length
                ? html`<div class="line">
                    <b>bonus</b> ${r.bonus.map(pretty).join(", ")}
                  </div>`
                : null}
              <div class="line" style=${{ color: "var(--ink-3)" }}>
                ${r.demand} ranked it 1st · ${r.capacity} slot${r.capacity === 1 ? "" : "s"}
                ${r.capacity ? ` · ${(r.demand / r.capacity).toFixed(1)}x pressure` : ""}
              </div>
            </div>
          `
        )}
        <p class="note" style=${{ marginTop: "12px" }}>
          Fit is not a prediction. A high score means a team needs what this person has; whether
          they land there also depends on capacity and on who else applies.
        </p>
      </section>
    </div>
  `;
}
