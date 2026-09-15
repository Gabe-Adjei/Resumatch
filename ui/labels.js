// Plain language, in one place.
//
// The engine's vocabulary is precise and almost entirely wrong for the person
// using this. "Blocking pair", "tier", "fallback", "mean preference rank" and
// a fit score of 0.35 are all meaningful if you have read the matching
// literature, and noise if you are a recruiter trying to place 150 people
// before Friday.
//
// So: the UI says what a thing means, and the technical term appears only
// where someone would need it to check the work. Every user-facing string
// lives here rather than being scattered through the components, so the
// vocabulary stays consistent and can be reviewed in one sitting.

/** 1 -> "1st", 2 -> "2nd", 23 -> "23rd" */
export function ordinal(n) {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return n + "th";
  return n + (["th", "st", "nd", "rd"][n % 10] || "th");
}

/**
 * How someone got their seat, in words a person would actually say.
 *
 * "fallback" is the engine's word for "their ranked list ran out". Nobody
 * outside the code should ever see it.
 */
export function howPlaced(tier, rank) {
  if (tier === "pinned") return "you moved them";
  if (tier === "unplaced") return "no seat yet";
  if (tier === "fallback") return "best available";
  if (rank === 1) return "1st pick";
  return ordinal(rank) + " pick";
}

/** Short form for a chip or badge, where space is tight. */
export function howPlacedShort(tier, rank) {
  if (tier === "pinned") return "moved";
  if (tier === "unplaced") return "no seat";
  if (tier === "fallback") return "best fit";
  return ordinal(rank);
}

/** A fit score as a percentage. 0.35 -> "35% match" */
export function matchPct(score) {
  return Math.round(score * 100) + "% match";
}

export function matchPctShort(score) {
  return Math.round(score * 100) + "%";
}

/**
 * One sentence describing the whole cohort's state — the first thing anyone
 * reads, and often the only thing they need.
 */
export function headline(metrics) {
  const { placed, cohortSize, firstChoice, unplaced } = metrics;
  if (unplaced) {
    return `${unplaced} intern${unplaced === 1 ? " has" : "s have"} no seat — there are fewer open slots than people.`;
  }
  const pct = Math.round((100 * firstChoice) / cohortSize);
  return `All ${placed} interns have a seat, and ${firstChoice} of them (${pct}%) got their first pick.`;
}

/**
 * The stability claim, in plain words.
 *
 * The technical statement is "zero blocking pairs". What that *means* to a
 * person defending a decision is that no swap exists which both sides would
 * accept — so nobody can point at the result and say it should obviously have
 * gone differently.
 */
export function integrityLine(metrics) {
  if (metrics.blockingPairs === 0) {
    return {
      ok: true,
      short: "Results hold up",
      long:
        "There is no intern and team who would both rather have each other than what " +
        "they got. Every placement can be defended one-to-one.",
    };
  }
  return {
    ok: false,
    short: `${metrics.blockingPairs} could be better off`,
    long:
      `Your manual moves created ${metrics.blockingPairs} case${metrics.blockingPairs === 1 ? "" : "s"} ` +
      "where an intern and a team would both rather have each other. That is the cost of " +
      "overriding — worth knowing before you send this out.",
  };
}

/** Pressure on a team, said as people-per-seat rather than a ratio. */
export function pressure(demandCount, capacity) {
  if (!capacity) return "no open seats";
  const ratio = demandCount / capacity;
  if (ratio <= 1) return "room for everyone who asked";
  return `${ratio.toFixed(1)} interns per seat`;
}

export const REVIEW_EXPLAINER =
  "These interns landed on a team that did not ask for any of their skills. " +
  "It happens when their own picks filled up and this team still had room. " +
  "Nothing is broken — but these are the ones to check with the manager first.";
