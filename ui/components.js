// Shared presentational components.
//
// Nothing here touches state or the engine — everything arrives as props.
//
// This file used to be much larger. When the four-tab layout collapsed into a
// single workspace, most of its pieces (stat readings, tier tags, slot meters,
// filter chips, the histogram) either moved inline to their one remaining use
// or were dropped with the screens that needed them. What survived is what is
// genuinely shared.

import { html } from "./h.js";

const D = window.RESUMATCH_DATA;

/**
 * The line that appears after a change, saying what it cost.
 *
 * This is the point of the override flow: a recruiter moving someone is a
 * legitimate act, but it takes a seat from a specific person, and they should
 * see who without having to go looking.
 */
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
      ` That shifted ${moved.length} other ${moved.length === 1 ? "person" : "people"}` +
      (worse.length
        ? ` — ${worse.length} ended up worse off` +
          (names.length
            ? ` (${names.join(", ")}${worse.length > names.length ? ", and others" : ""})`
            : "")
        : "") +
      (improved.length ? `, ${improved.length} better off` : "") +
      ".";
  }

  return html`
    <div class="banner ${change.info ? "info" : ""}">
      <div class="msg" dangerouslySetInnerHTML=${{ __html: change.headline + detail }}></div>
      <button class="btn sm" onClick=${onDismiss}>Dismiss</button>
    </div>
  `;
}

export function EmptyState({ children }) {
  return html`<div class="empty-state">${children}</div>`;
}
