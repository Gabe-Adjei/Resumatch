// Deferred acceptance, in the browser.
//
// This is a deliberate second implementation of resumatch/matching.py. It
// exists so that dragging someone onto a team answers instantly and honestly:
// a manual override costs a specific person their seat, and the recruiter
// should see who before they confirm, not after.
//
// The duplication is scoped as tightly as possible. Team preference orders —
// the part with tunable weights and a seeded hash tie-break — are computed in
// Python and shipped in data.js. This file only re-runs the queue mechanics,
// which have no constants to drift.
//
// If you change scoring.py, re-run scripts/export_ui_data.py.

(function (global) {
  "use strict";

  const D = global.RESUMATCH_DATA;
  const W = D.weights;

  // rankOf[t][c] = position of candidate c in team t's ordering. Lower is
  // better. Seeded from the orderings Python computed; rebuilt in place when a
  // candidate is added at runtime (see addCandidate).
  let rankOf = D.order.map(function (order) {
    const inv = [];
    order.forEach(function (candIdx, position) {
      inv[candIdx] = position;
    });
    return inv;
  });

  function overlapRatio(have, want) {
    // An empty requirement scores 0, not 1: a team that asked for nothing
    // must not read as a perfect fit for everyone. Mirrors scoring.py.
    if (!want.length) return 0;
    let hits = 0;
    for (const w of want) if (have.indexOf(w) !== -1) hits++;
    return hits / want.length;
  }

  function fitScore(candIdx, teamIdx) {
    const c = D.candidates[candIdx];
    const t = D.teams[teamIdx];
    const required = overlapRatio(c.skills, t.required);
    const preferred = overlapRatio(c.skills, t.preferred);
    const interest = overlapRatio(c.interests, t.domains);

    let wishlist = 0;
    const position = t.wishlist.indexOf(candIdx);
    if (position !== -1) {
      wishlist = Math.max(W.wishlistFloor, 1 - W.wishlistDecay * position);
    }

    const total =
      W.required * required +
      W.preferred * preferred +
      W.interest * interest +
      W.wishlist * wishlist;

    return { total, required, preferred, interest, wishlist };
  }

  // Scores for the cohort as loaded. Extended when a candidate is added.
  const scoreCache = D.teams.map(function (_, t) {
    return D.candidates.map(function (_, c) {
      return fitScore(c, t).total;
    });
  });

  function score(candIdx, teamIdx) {
    return scoreCache[teamIdx][candIdx];
  }

  /* ------------------------------------------------------------------------
   * Adding a candidate at runtime
   *
   * Team orderings normally come from Python (scoring.py) so the browser
   * cannot disagree with the engine about who ranks where. A candidate added
   * in the browser has no Python-computed position, so the ordering has to be
   * rebuilt here — which means reproducing the seeded tie-break exactly.
   *
   * Python does:  sha256(f"{seed}|{team_id}|{candidate_id}").hexdigest()
   * and sorts by (-score, that digest).
   *
   * `verifyOrders()` below asserts this reproduces Python's ordering for the
   * original cohort. If it ever stops matching, adding a person would quietly
   * reshuffle everyone else — so the check is not optional.
   * --------------------------------------------------------------------- */

  const tiebreak = {}; // "teamIdx:candIdx" -> hex digest

  async function sha256Hex(text) {
    const bytes = new TextEncoder().encode(text);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest))
      .map(function (b) {
        return b.toString(16).padStart(2, "0");
      })
      .join("");
  }

  async function ensureTiebreaks() {
    const jobs = [];
    for (let t = 0; t < D.teams.length; t++) {
      for (let c = 0; c < D.candidates.length; c++) {
        const key = t + ":" + c;
        if (tiebreak[key] !== undefined) continue;
        jobs.push(
          sha256Hex(D.matchSeed + "|" + D.teams[t].id + "|" + D.candidates[c].id).then(
            function (hex) {
              tiebreak[key] = hex;
            }
          )
        );
      }
    }
    await Promise.all(jobs);
  }

  function rebuildOrders() {
    rankOf = D.teams.map(function (_, t) {
      const ids = D.candidates.map(function (_, c) {
        return c;
      });
      ids.sort(function (a, b) {
        const diff = scoreCache[t][b] - scoreCache[t][a];
        if (diff !== 0) return diff;
        return tiebreak[t + ":" + a] < tiebreak[t + ":" + b] ? -1 : 1;
      });
      const inv = [];
      ids.forEach(function (candIdx, position) {
        inv[candIdx] = position;
      });
      D.order[t] = ids;
      return inv;
    });
  }

  /** Does the JS tie-break reproduce Python's ordering? Used by the parity check. */
  async function verifyOrders() {
    const original = D.order.map(function (o) {
      return o.slice();
    });
    await ensureTiebreaks();
    rebuildOrders();
    const mismatches = [];
    for (let t = 0; t < D.teams.length; t++) {
      for (let i = 0; i < original[t].length; i++) {
        if (original[t][i] !== D.order[t][i]) {
          mismatches.push({ team: D.teams[t].id, position: i });
          break;
        }
      }
    }
    return mismatches;
  }

  /**
   * Add a candidate to the cohort and return their index.
   *
   * `candidate` is {id, name, skills[], interests[], prefs[teamIdx]} — the
   * same shape as the entries in data.js.
   */
  async function addCandidate(candidate) {
    if (D.candidates.some((c) => c.id === candidate.id)) {
      throw new Error("a candidate with id " + candidate.id + " is already in the cohort");
    }
    const index = D.candidates.length;
    D.candidates.push(candidate);

    for (let t = 0; t < D.teams.length; t++) {
      scoreCache[t][index] = fitScore(index, t).total;
    }
    await ensureTiebreaks();
    rebuildOrders();
    return index;
  }

  /**
   * Run a full match.
   *
   * @param {number[]} capacities  per-team slot counts (the UI can edit these)
   * @param {Object}   pins        candidateIdx -> teamIdx manual overrides
   * @returns {{assignedTeam:Int32Array, tier:string[], rank:Int32Array,
   *            rejections:Object, unplaced:number[], metrics:Object}}
   */
  function runMatch(capacities, pins) {
    pins = pins || {};
    const nC = D.candidates.length;
    const nT = D.teams.length;

    const pinned = new Set(Object.keys(pins).map(Number));
    const rosters = [];
    for (let t = 0; t < nT; t++) rosters.push(new Set());

    for (const key of Object.keys(pins)) {
      rosters[pins[key]].add(Number(key));
    }

    const nextChoice = new Int32Array(nC);
    const rejectionEvents = [];

    // Deterministic queue order, matching the Python.
    const free = [];
    for (let c = 0; c < nC; c++) {
      if (D.candidates[c].prefs.length && !pinned.has(c)) free.push(c);
    }

    let head = 0;
    while (head < free.length) {
      const c = free[head++];
      const prefs = D.candidates[c].prefs;
      if (nextChoice[c] >= prefs.length) continue;

      const t = prefs[nextChoice[c]++];
      rosters[t].add(c);

      if (rosters[t].size > capacities[t]) {
        // Pinned candidates are immovable — an override the algorithm could
        // undo on the next proposal would not be an override.
        let worst = -1;
        for (const member of rosters[t]) {
          if (pinned.has(member)) continue;
          if (worst === -1 || rankOf[t][member] > rankOf[t][worst]) worst = member;
        }
        if (worst === -1) worst = c; // pins fill the team outright
        rosters[t].delete(worst);
        rejectionEvents.push([worst, t]);
        free.push(worst);
      }
    }

    // ---- fallback round: nobody gets a hard no -----------------------------
    const placedNow = new Set();
    for (let t = 0; t < nT; t++) for (const c of rosters[t]) placedNow.add(c);

    const remaining = capacities.map(function (cap, t) {
      return cap - rosters[t].size;
    });

    const unmatched = [];
    for (let c = 0; c < nC; c++) if (!placedNow.has(c)) unmatched.push(c);

    // Most-constrained first: someone who fits three teams loses far more by
    // going last than someone who fits fifteen.
    function viableCount(c) {
      let n = 0;
      for (let t = 0; t < nT; t++) if (remaining[t] > 0 && score(c, t) > 0) n++;
      return n;
    }
    const viability = {};
    unmatched.forEach(function (c) {
      viability[c] = viableCount(c);
    });
    unmatched.sort(function (a, b) {
      return viability[a] - viability[b] || D.candidates[a].id.localeCompare(D.candidates[b].id);
    });

    const unplaced = [];
    for (const c of unmatched) {
      let best = -1;
      for (let t = 0; t < nT; t++) {
        if (remaining[t] <= 0) continue;
        if (best === -1) {
          best = t;
          continue;
        }
        const better =
          score(c, t) > score(c, best) ||
          (score(c, t) === score(c, best) && rankOf[t][c] < rankOf[best][c]);
        if (better) best = t;
      }
      if (best === -1) {
        unplaced.push(c);
      } else {
        rosters[best].add(c);
        remaining[best]--;
      }
    }

    // ---- package -----------------------------------------------------------
    const assignedTeam = new Int32Array(nC).fill(-1);
    const rank = new Int32Array(nC).fill(-1);
    const tier = new Array(nC).fill("unplaced");

    for (let t = 0; t < nT; t++) {
      for (const c of rosters[t]) {
        assignedTeam[c] = t;
        const prefIdx = D.candidates[c].prefs.indexOf(t);
        rank[c] = prefIdx === -1 ? -1 : prefIdx + 1;
        if (pinned.has(c)) tier[c] = "pinned";
        else if (rank[c] === 1) tier[c] = "top_choice";
        else if (rank[c] > 0) tier[c] = "ranked";
        else tier[c] = "fallback";
      }
    }

    // Rejections scored against each team's FINAL cutoff, not against whoever
    // happened to be held when the bump occurred — mid-run state is an
    // artifact of proposal order and would explain identical outcomes
    // differently.
    const cutoff = [];
    for (let t = 0; t < nT; t++) {
      let lo = null;
      for (const c of rosters[t]) {
        const s = score(c, t);
        if (lo === null || s < lo) lo = s;
      }
      cutoff.push(lo);
    }

    const rejections = {};
    for (const [c, t] of rejectionEvents) {
      let above = 0;
      for (const member of rosters[t]) if (rankOf[t][member] < rankOf[t][c]) above++;
      (rejections[c] = rejections[c] || []).push({
        team: t,
        yourScore: score(c, t),
        cutoff: cutoff[t],
        heldAbove: above,
      });
    }

    return {
      assignedTeam,
      tier,
      rank,
      rejections,
      unplaced,
      rosters,
      metrics: computeMetrics(assignedTeam, tier, rank, unplaced, capacities, rosters),
    };
  }

  function findBlockingPairs(assignedTeam, rosters, capacities) {
    // The integrity check. Written to be obviously correct rather than fast.
    const pairs = [];
    for (let c = 0; c < D.candidates.length; c++) {
      const prefs = D.candidates[c].prefs;
      const current = assignedTeam[c];
      const currentIdx = current === -1 ? prefs.length : prefs.indexOf(current);
      // A candidate placed on a team they never ranked prefers any ranked team.
      const ceiling = currentIdx === -1 ? prefs.length : currentIdx;

      for (let i = 0; i < ceiling; i++) {
        const t = prefs[i];
        if (rosters[t].size < capacities[t]) {
          pairs.push([c, t]);
          continue;
        }
        for (const member of rosters[t]) {
          if (rankOf[t][c] < rankOf[t][member]) {
            pairs.push([c, t]);
            break;
          }
        }
      }
    }
    return pairs;
  }

  const LOW_FIT_THRESHOLD = 0.05;

  function computeMetrics(assignedTeam, tier, rank, unplaced, capacities, rosters) {
    const n = D.candidates.length;
    let first = 0;
    let topThree = 0;
    let rankSum = 0;
    let ranked = 0;
    let fallback = 0;
    let pinnedCount = 0;
    const histogram = {};
    const lowFit = [];

    for (let c = 0; c < n; c++) {
      if (assignedTeam[c] === -1) continue;
      if (tier[c] === "fallback") fallback++;
      if (tier[c] === "pinned") pinnedCount++;
      if (rank[c] > 0) {
        ranked++;
        rankSum += rank[c];
        histogram[rank[c]] = (histogram[rank[c]] || 0) + 1;
        if (rank[c] === 1) first++;
        if (rank[c] <= 3) topThree++;
      }
      if (score(c, assignedTeam[c]) < LOW_FIT_THRESHOLD) lowFit.push(c);
    }

    const blocking = findBlockingPairs(assignedTeam, rosters, capacities);
    const totalSlots = capacities.reduce(function (a, b) {
      return a + b;
    }, 0);
    const placed = n - unplaced.length;

    return {
      cohortSize: n,
      placed,
      unplaced: unplaced.length,
      totalSlots,
      slotsOpen: totalSlots - placed,
      firstChoice: first,
      firstChoicePct: n ? (100 * first) / n : 0,
      topThree,
      topThreePct: n ? (100 * topThree) / n : 0,
      meanRank: ranked ? rankSum / ranked : 0,
      fallback,
      pinned: pinnedCount,
      histogram,
      blockingPairs: blocking.length,
      blockingExamples: blocking.slice(0, 5),
      lowFit,
      lowFitThreshold: LOW_FIT_THRESHOLD,
    };
  }

  /** Who moved between two runs, and in which direction. */
  function diff(before, after) {
    const moved = [];
    for (let c = 0; c < D.candidates.length; c++) {
      const a = before.assignedTeam[c];
      const b = after.assignedTeam[c];
      if (a === b) continue;
      // Lower rank is better; an unranked (fallback) outcome sorts worst.
      const rankA = before.rank[c] > 0 ? before.rank[c] : Infinity;
      const rankB = after.rank[c] > 0 ? after.rank[c] : Infinity;
      moved.push({
        candidate: c,
        from: a,
        to: b,
        rankBefore: before.rank[c],
        rankAfter: after.rank[c],
        direction: rankB < rankA ? "improved" : rankB > rankA ? "worse" : "lateral",
      });
    }
    moved.sort(function (x, y) {
      const order = { worse: 0, lateral: 1, improved: 2 };
      return order[x.direction] - order[y.direction];
    });
    return moved;
  }

  global.RESUMATCH = {
    runMatch,
    diff,
    fitScore,
    score,
    addCandidate,
    verifyOrders,
    LOW_FIT_THRESHOLD,
    get rankOf() {
      return rankOf;
    },
  };
})(window);
