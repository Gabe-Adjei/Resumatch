// The workspace — one screen.
//
// This replaced a four-tab layout (Overview / Board / Teams / Intake). That
// structure was organised around the data model rather than around the job,
// so it forced you to explore to find out what each tab did, and two of the
// tabs showed the same rosters twice.
//
// The rule now: ONE thing on screen, and everything else is either a filter
// on it or a detail inside it. Three levels, one at a time:
//
//   1. the cohort's state in a sentence, plus anything needing attention
//   2. teams as compact tiles — click one to see who is on it
//   3. click a person for the full explanation (drawer.js)
//
// Nothing is hidden; it is just not all shouted at once. The previous version
// put 150 names and 20 expanded team cards on screen simultaneously, which is
// a wall rather than a board.

import { html, useMemo, useState } from "./h.js";
import { demand, isTouched } from "./store.js";
import { Banner, EmptyState } from "./components.js";
import {
  REVIEW_EXPLAINER,
  headline,
  howPlaced,
  howPlacedShort,
  integrityLine,
  matchPct,
  matchPctShort,
  ordinal,
  pressure,
} from "./labels.js";
import { parseResume, pretty } from "./taxonomy.js";

const D = window.RESUMATCH_DATA;
const E = window.RESUMATCH;

export function Workspace({ state, dispatch }) {
  // `focus` is what the board is currently filtered to. null means everything.
  const [focus, setFocus] = useState(null);
  const [query, setQuery] = useState("");
  const [openTeam, setOpenTeam] = useState(null);
  const [showReport, setShowReport] = useState(false);
  const [showIntake, setShowIntake] = useState(false);

  const m = state.result.metrics;
  const integrity = integrityLine(m);

  const searching = query.trim().length > 0 || focus !== null;
  const matches = useMemo(() => {
    if (!searching) return [];
    const reviewSet = new Set(m.lowFit);
    const q = query.trim().toLowerCase();
    return D.candidates
      .map((_, i) => i)
      .filter((i) => {
        if (focus === "review" && !reviewSet.has(i)) return false;
        if (focus === "first" && state.result.rank[i] !== 1) return false;
        if (focus === "moved" && state.result.tier[i] !== "pinned") return false;
        if (!q) return true;
        const c = D.candidates[i];
        return (
          c.name.toLowerCase().includes(q) ||
          c.id.toLowerCase().includes(q) ||
          c.skills.some((s) => pretty(s).includes(q))
        );
      });
  }, [searching, query, focus, state.result, m.lowFit]);

  function chooseFocus(next) {
    setFocus((current) => (current === next ? null : next));
    setOpenTeam(null);
  }

  return html`
    <div class="stack">
      <section class="status">
        <p class="status-line">${headline(m)}</p>
        <p class="status-sub">
          ${integrity.ok ? "✓ " : "⚠ "}${integrity.long}
        </p>
      </section>

      <${Banner} change=${state.lastChange} onDismiss=${() => dispatch({ type: "dismiss" })} />

      ${m.lowFit.length
        ? html`
            <section class="attention">
              <div>
                <h2>
                  ${m.lowFit.length} intern${m.lowFit.length === 1 ? "" : "s"} worth a second look
                </h2>
                <p>${REVIEW_EXPLAINER}</p>
              </div>
              <button
                class="btn ${focus === "review" ? "" : "primary"}"
                onClick=${() => chooseFocus("review")}
              >
                ${focus === "review" ? "Hide these" : "Show me"}
              </button>
            </section>
          `
        : null}

      <div class="controls">
        <input
          type="search"
          id="workspace-search"
          class="field search"
          placeholder="Search for anyone by name or skill…"
          aria-label="Search the cohort"
          value=${query}
          onInput=${(e) => setQuery(e.target.value)}
        />
        <div class="quick">
          <button
            class="chip"
            aria-pressed=${focus === "first"}
            onClick=${() => chooseFocus("first")}
          >
            Got 1st pick · ${m.firstChoice}
          </button>
          ${m.pinned
            ? html`<button
                class="chip"
                aria-pressed=${focus === "moved"}
                onClick=${() => chooseFocus("moved")}
              >
                You moved · ${m.pinned}
              </button>`
            : null}
          <button class="btn sm" onClick=${() => setShowIntake(true)}>+ Add someone</button>
        </div>
      </div>

      ${searching
        ? html`<${SearchResults}
            indices=${matches}
            state=${state}
            dispatch=${dispatch}
            label=${focus === "review"
              ? "Worth a second look"
              : focus === "first"
              ? "Got their first pick"
              : focus === "moved"
              ? "You moved these"
              : `Matching “${query.trim()}”`}
            onClear=${() => {
              setQuery("");
              setFocus(null);
            }}
          />`
        : null}

      <section>
        <div class="section-bar">
          <h2>Teams</h2>
          <span class="note">
            ${openTeam === null ? "Click a team to see who’s on it" : ""}
          </span>
        </div>
        <div class="tiles">
          ${D.teams.map(
            (t, ti) => html`<${TeamTile}
              key=${ti}
              team=${t}
              index=${ti}
              state=${state}
              dispatch=${dispatch}
              expanded=${openTeam === ti}
              onToggle=${() => setOpenTeam(openTeam === ti ? null : ti)}
              reviewSet=${m.lowFit}
            />`
          )}
        </div>
      </section>

      <section class="panel">
        <button
          class="report-toggle"
          aria-expanded=${showReport}
          onClick=${() => setShowReport(!showReport)}
        >
          <span>${showReport ? "▾" : "▸"} Numbers for your report</span>
          <span class="note">placement rates, team pressure, how it was decided</span>
        </button>
        ${showReport ? html`<${Report} state=${state} />` : null}
      </section>

      ${showIntake ? html`<${IntakePanel} state=${state} onClose=${() => setShowIntake(false)} />` : null}
    </div>
  `;
}

/* -------------------------------------------------------------------------- */
/* Search / filter results                                                    */
/* -------------------------------------------------------------------------- */

function SearchResults({ indices, state, dispatch, label, onClear }) {
  return html`
    <section class="panel">
      <div class="panel-head">
        ${label}
        <span class="count">
          ${indices.length} ${indices.length === 1 ? "person" : "people"}
          <button class="btn sm" style=${{ marginLeft: "8px" }} onClick=${onClear}>Clear</button>
        </span>
      </div>
      ${indices.length
        ? html`<div class="result-list">
            ${indices.slice(0, 40).map(
              (i) => html`<${PersonLine} key=${i} index=${i} state=${state} dispatch=${dispatch} />`
            )}
            ${indices.length > 40
              ? html`<p class="note" style=${{ padding: "10px 12px" }}>
                  Showing the first 40 of ${indices.length}. Narrow the search to see the rest.
                </p>`
              : null}
          </div>`
        : html`<${EmptyState}>Nobody matches that.<//>`}
    </section>
  `;
}

/** One person, draggable onto any team tile. */
function PersonLine({ index, state, dispatch }) {
  const c = D.candidates[index];
  const r = state.result;
  const t = r.assignedTeam[index];

  return html`
    <div
      class="pline"
      draggable="true"
      onDragStart=${(ev) => {
        ev.dataTransfer.setData("text/plain", String(index));
        ev.dataTransfer.effectAllowed = "move";
        ev.currentTarget.classList.add("dragging");
      }}
      onDragEnd=${(ev) => ev.currentTarget.classList.remove("dragging")}
    >
      <span class="grip" aria-hidden="true">⠿</span>
      <button class="pline-main" onClick=${() => dispatch({ type: "select", candidate: index })}>
        <span class="nm">${c.name}</span>
        <span class="mt">
          ${t === -1 ? "No seat yet" : D.teams[t].name} ·
          ${howPlaced(r.tier[index], r.rank[index])}
          ${t === -1 ? "" : " · " + matchPct(E.score(index, t))}
        </span>
      </button>
    </div>
  `;
}

/* -------------------------------------------------------------------------- */
/* Team tiles                                                                 */
/* -------------------------------------------------------------------------- */

function TeamTile({ team, index, state, dispatch, expanded, onToggle, reviewSet }) {
  const [over, setOver] = useState(false);
  const r = state.result;
  const cap = state.capacities[index];

  const members = useMemo(
    () => Array.from(r.rosters[index]).sort((a, b) => E.score(b, index) - E.score(a, index)),
    [r, index]
  );

  const open = cap - members.length;
  const needsReview = members.filter((ci) => reviewSet.includes(ci)).length;
  const fillPct = cap ? Math.min(100, (100 * members.length) / cap) : 0;

  return html`
    <article
      class="tile ${expanded ? "expanded" : ""} ${over ? "drop-target" : ""}"
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
      <button class="tile-head" onClick=${onToggle} aria-expanded=${expanded}>
        <span class="tile-top">
          <span class="tile-name">${team.name}</span>
          <span class="tile-count">${members.length}/${cap}</span>
        </span>
        <span class="fill">
          <span class="fill-bar" style=${{ width: fillPct + "%" }}></span>
        </span>
        <span class="tile-sub">
          ${open > 0
            ? `${open} seat${open === 1 ? "" : "s"} open`
            : "full"}
          ${needsReview ? html`<span class="flag">${needsReview} to check</span>` : null}
        </span>
      </button>

      ${expanded
        ? html`
            <div class="tile-body">
              <p class="note tile-needs">
                Looking for <b>${team.required.map(pretty).join(", ")}</b> ·
                ${pressure(demand[index], cap)}
              </p>

              <div class="roster">
                ${members.length
                  ? members.map(
                      (ci) => html`
                        <button
                          class="rmember"
                          key=${ci}
                          onClick=${() => dispatch({ type: "select", candidate: ci })}
                        >
                          <span class="nm">${D.candidates[ci].name}</span>
                          <span class="meta">
                            <span class="how">${howPlacedShort(r.tier[ci], r.rank[ci])}</span>
                            <span class="pct">${matchPctShort(E.score(ci, index))}</span>
                          </span>
                        </button>
                      `
                    )
                  : html`<p class="note" style=${{ padding: "6px 2px" }}>Nobody here yet.</p>`}
              </div>

              <div class="tile-actions">
                <span class="note">Open seats</span>
                <span class="cap-controls">
                  <button
                    class="cap-btn"
                    aria-label=${`Remove a seat from ${team.name}`}
                    disabled=${cap <= members.length}
                    onClick=${(ev) => {
                      ev.stopPropagation();
                      dispatch({ type: "capacity", team: index, delta: -1 });
                    }}
                  >
                    −
                  </button>
                  <span class="cap">${cap}</span>
                  <button
                    class="cap-btn"
                    aria-label=${`Add a seat to ${team.name}`}
                    onClick=${(ev) => {
                      ev.stopPropagation();
                      dispatch({ type: "capacity", team: index, delta: 1 });
                    }}
                  >
                    +
                  </button>
                </span>
              </div>
            </div>
          `
        : null}
    </article>
  `;
}

/* -------------------------------------------------------------------------- */
/* Report — the numbers, kept out of the way until asked for                  */
/* -------------------------------------------------------------------------- */

function Report({ state }) {
  const m = state.result.metrics;
  const integrity = integrityLine(m);

  const ranks = Object.keys(m.histogram)
    .map(Number)
    .sort((a, b) => a - b);
  const peak = Math.max(1, ...ranks.map((k) => m.histogram[k]), m.fallback);

  const pressureRows = D.teams
    .map((t, i) => ({
      name: t.name,
      demand: demand[i],
      capacity: state.capacities[i],
      ratio: state.capacities[i] ? demand[i] / state.capacities[i] : 0,
    }))
    .sort((a, b) => b.ratio - a.ratio)
    .slice(0, 6);

  return html`
    <div class="panel-body report">
      <div class="report-grid">
        <div>
          <h3 class="section-title">Which pick everyone got</h3>
          <div class="hist">
            ${ranks.map(
              (k) => html`
                <div class="hist-row" key=${k}>
                  <span>${ordinal(k)} pick</span>
                  <span class="hist-track">
                    <span
                      class="hist-fill ${k === 1 ? "tier-top_choice" : "tier-ranked"}"
                      style=${{ width: (100 * m.histogram[k]) / peak + "%" }}
                    ></span>
                  </span>
                  <span class="n">${m.histogram[k]}</span>
                </div>
              `
            )}
            ${m.fallback
              ? html`<div class="hist-row">
                  <span>best available</span>
                  <span class="hist-track">
                    <span class="hist-fill tier-fallback" style=${{ width: (100 * m.fallback) / peak + "%" }}></span>
                  </span>
                  <span class="n">${m.fallback}</span>
                </div>`
              : null}
          </div>
          <p class="note" style=${{ marginTop: "8px" }}>
            ${m.topThree} of ${m.cohortSize} (${m.topThreePct.toFixed(0)}%) got one of their top
            three picks.
          </p>
        </div>

        <div>
          <h3 class="section-title">Teams under the most pressure</h3>
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr>
                  <th>Team</th>
                  <th class="num">Wanted it</th>
                  <th class="num">Seats</th>
                </tr>
              </thead>
              <tbody>
                ${pressureRows.map(
                  (row) => html`
                    <tr key=${row.name}>
                      <td class="name">${row.name}</td>
                      <td class="num">${row.demand}</td>
                      <td class="num">${row.capacity}</td>
                    </tr>
                  `
                )}
              </tbody>
            </table>
          </div>
          <p class="note" style=${{ marginTop: "8px" }}>
            More people wanting a team than it has seats is the main reason someone does not get
            their first pick.
          </p>
        </div>
      </div>

      <div class="report-foot ${integrity.ok ? "" : "warn"}">
        <b>${integrity.short}.</b> ${integrity.long}
        <span class="note">
          Technically: ${m.blockingPairs} blocking pairs under candidate-proposing deferred
          acceptance (Gale–Shapley). Cohort ${D.cohortHash.slice(0, 12)}.
        </span>
      </div>
    </div>
  `;
}

/* -------------------------------------------------------------------------- */
/* Intake — a panel, not a destination                                        */
/* -------------------------------------------------------------------------- */

const SAMPLE_RESUME = `Priya Raman
priya.raman@osu.edu | github.com/praman | Columbus, OH

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

function IntakePanel({ state, onClose }) {
  const [text, setText] = useState(SAMPLE_RESUME);
  const parsed = useMemo(() => parseResume(text), [text]);

  const ranked = useMemo(() => {
    const skills = new Set(parsed.skills);
    const interests = new Set(parsed.interests);
    const W = D.weights;
    const ratio = (have, want) =>
      want.length ? want.filter((w) => have.has(w)).length / want.length : 0;

    return D.teams
      .map((t, ti) => {
        const required = ratio(skills, t.required);
        const total =
          W.required * required +
          W.preferred * ratio(skills, t.preferred) +
          W.interest * ratio(interests, t.domains);
        return {
          index: ti,
          name: t.name,
          total,
          matched: t.required.filter((s) => skills.has(s)),
          missing: t.required.filter((s) => !skills.has(s)),
          capacity: state.capacities[ti],
          demand: demand[ti],
        };
      })
      .sort((a, b) => b.total - a.total)
      .slice(0, 5);
  }, [parsed, state.capacities]);

  return html`
    <div class="overlay">
      <div class="scrim open" onClick=${onClose}></div>
      <div class="sheet" role="dialog" aria-label="Add someone">
        <div class="drawer-head">
          <div>
            <h2>Where would this person fit?</h2>
            <div class="id">Paste a resume — we read the skills, not the name or school</div>
          </div>
          <button class="btn sm" onClick=${onClose}>Close</button>
        </div>

        <div class="sheet-body">
          <div class="sheet-cols">
            <div>
              <label class="section-title" for="resume-text">Resume text</label>
              <textarea
                class="field"
                id="resume-text"
                value=${text}
                onInput=${(e) => setText(e.target.value)}
                spellcheck="false"
              ></textarea>

              <div class="section-title" style=${{ marginTop: "12px" }}>Skills we found</div>
              <div class="pillrow">
                ${parsed.skills.length
                  ? parsed.skills.map((s) => html`<span class="pill match" key=${s}>${pretty(s)}</span>`)
                  : html`<span class="note">Nothing recognized yet.</span>`}
              </div>

              ${parsed.warnings.length
                ? html`<ul class="warnlist">
                    ${parsed.warnings.map((w, i) => html`<li key=${i}>${w}</li>`)}
                  </ul>`
                : null}
            </div>

            <div>
              <div class="section-title">Best matches</div>
              ${ranked.map(
                (row, i) => html`
                  <div class="fitcard" key=${row.index}>
                    <div class="row">
                      <h4><span class="rank-badge">${i + 1}</span> ${row.name}</h4>
                      <span class="score">${Math.round(row.total * 100)}%</span>
                    </div>
                    ${row.matched.length
                      ? html`<div class="line">
                          <b>has what they need</b><br />
                          <span class="pillrow">
                            ${row.matched.map((s) => html`<span class="pill match" key=${s}>${pretty(s)}</span>`)}
                          </span>
                        </div>`
                      : null}
                    ${row.missing.length
                      ? html`<div class="line">
                          <b>missing</b><br />
                          <span class="pillrow">
                            ${row.missing.map((s) => html`<span class="pill gap" key=${s}>${pretty(s)}</span>`)}
                          </span>
                        </div>`
                      : null}
                    <div class="line" style=${{ color: "var(--ink-3)" }}>
                      ${row.capacity} seat${row.capacity === 1 ? "" : "s"} ·
                      ${pressure(row.demand, row.capacity)}
                    </div>
                  </div>
                `
              )}
              <p class="note" style=${{ marginTop: "10px" }}>
                This shows which teams need these skills. Whether someone lands there also depends
                on how many seats are left and who else applied.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}
