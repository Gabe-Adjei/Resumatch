// Shared presentational components.
//
// Nothing here touches state or the engine — everything arrives as props. The
// screens own behaviour; these own how it looks.

import { html } from "./h.js";
import { TIER_LABEL } from "./store.js";
import { pretty } from "./taxonomy.js";

const D = window.RESUMATCH_DATA;
const E = window.RESUMATCH;

/** One instrument reading. */
export function Reading({ label, value, detail, variant }) {
  return html`
    <div class="reading ${variant || ""}">
      <div class="k">${label}</div>
      <div class="v">${value}</div>
      <div class="d">${detail}</div>
    </div>
  `;
}

/** A movement indicator, only shown once something has been changed. */
export function Delta({ now, was, digits = 1, fallback }) {
  if (was === undefined || was === null) return fallback || null;
  const d = now - was;
  if (Math.abs(d) < 0.05) return html`<span class="d">no change</span>`;
  return html`<span class="delta ${d > 0 ? "up" : "down"}">
    ${(d > 0 ? "+" : "") + d.toFixed(digits)}
  </span>`;
}

export function TierTag({ tier, rank }) {
  return html`<span class="tag tier-${tier}">${rank > 0 ? "#" + rank : TIER_LABEL[tier]}</span>`;
}

export function SkillPill({ skill, state }) {
  return html`<span class="pill ${state || ""}">${pretty(skill)}</span>`;
}

/** A team's seats, one cell each. Fullness reads as shape before number. */
export function SlotMeter({ capacity, members, tierOf }) {
  const slots = [];
  for (let s = 0; s < capacity; s++) {
    const who = members[s];
    const cls = who === undefined ? "" : tierOf(who) === "pinned" ? "pinned" : "filled";
    slots.push(html`<span class="slot ${cls}" key=${s}></span>`);
  }
  return html`<div class="meter">${slots}</div>`;
}

export function Banner({ change, onDismiss }) {
  if (!change) return null;

  const moved = change.moved || [];
  const worse = moved.filter((m) => m.direction === "worse");
  const improved = moved.filter((m) => m.direction === "improved");

  let detail = "";
  if (change.info) {
    detail = "";
  } else if (!moved.length) {
    detail = " Nobody else was affected.";
  } else {
    const names = worse.slice(0, 3).map((m) => D.candidates[m.candidate].name);
    detail =
      ` ${moved.length} other placement${moved.length === 1 ? "" : "s"} shifted` +
      (worse.length
        ? ` — <strong>${worse.length}</strong> got a worse outcome` +
          (names.length
            ? ` (${names.join(", ")}${worse.length > names.length ? ", …" : ""})`
            : "")
        : "") +
      (improved.length ? `, ${improved.length} improved` : "") +
      ".";
  }

  return html`
    <div class="banner ${change.info ? "info" : ""}">
      <div
        class="msg"
        dangerouslySetInnerHTML=${{ __html: change.headline + detail }}
      ></div>
      <button class="btn sm" onClick=${onDismiss}>Dismiss</button>
    </div>
  `;
}

/** Horizontal distribution of preference ranks achieved. */
export function Histogram({ histogram, fallback, total }) {
  const keys = Object.keys(histogram)
    .map(Number)
    .sort((a, b) => a - b);
  const counts = keys.map((k) => histogram[k]).concat(fallback ? [fallback] : []);
  const peak = Math.max(1, ...counts);

  const rows = keys.map((k) => {
    const n = histogram[k];
    return html`
      <div class="hist-row" key=${k}>
        <span>choice #${k}</span>
        <span class="hist-track">
          <span
            class="hist-fill ${k === 1 ? "tier-top_choice" : "tier-ranked"}"
            style=${{ width: (100 * n) / peak + "%" }}
          ></span>
        </span>
        <span class="n">${n}</span>
      </div>
    `;
  });

  if (fallback) {
    rows.push(html`
      <div class="hist-row" key="fb">
        <span>fallback</span>
        <span class="hist-track">
          <span class="hist-fill tier-fallback" style=${{ width: (100 * fallback) / peak + "%" }}></span>
        </span>
        <span class="n">${fallback}</span>
      </div>
    `);
  }

  return html`
    <div class="hist">
      ${rows}
      <p class="note" style=${{ marginTop: "6px" }}>
        Out of ${total} interns. Lower is better — "choice #1" means they got the team they
        ranked first.
      </p>
    </div>
  `;
}

export function Legend() {
  return html`
    <div class="legend">
      <span><i class="tier-top_choice"></i>1st choice</span>
      <span><i class="tier-ranked"></i>Ranked</span>
      <span><i class="tier-fallback"></i>Fallback</span>
      <span><i class="tier-pinned"></i>Manual</span>
    </div>
  `;
}

/** One row in the candidate pool. Draggable onto a team. */
export function PersonRow({ index, result, selected, onSelect }) {
  const c = D.candidates[index];
  const t = result.assignedTeam[index];
  const tier = result.tier[index];

  return html`
    <button
      class="person"
      draggable="true"
      aria-selected=${selected}
      onClick=${() => onSelect(index)}
      onDragStart=${(ev) => {
        ev.dataTransfer.setData("text/plain", String(index));
        ev.dataTransfer.effectAllowed = "move";
        ev.currentTarget.classList.add("dragging");
      }}
      onDragEnd=${(ev) => ev.currentTarget.classList.remove("dragging")}
    >
      <span class="stripe tier-${tier}"></span>
      <span class="who">
        <span class="nm">${c.name}</span>
        <span class="mt">
          ${t === -1 ? "Not placed" : D.teams[t].name} ·
          ${result.rank[index] > 0 ? "#" + result.rank[index] : TIER_LABEL[tier]}
        </span>
      </span>
      <span class="sc">${t === -1 ? "—" : E.score(index, t).toFixed(2)}</span>
    </button>
  `;
}

export function FilterChips({ options, value, onChange }) {
  return html`
    <div class="filters" role="group" aria-label="Filter by placement outcome">
      ${options.map(
        ([key, label]) => html`
          <button
            class="chip"
            key=${key}
            aria-pressed=${value === key}
            onClick=${() => onChange(key)}
          >
            ${label}
          </button>
        `
      )}
    </div>
  `;
}

export function EmptyState({ children }) {
  return html`<div class="empty-state">${children}</div>`;
}
