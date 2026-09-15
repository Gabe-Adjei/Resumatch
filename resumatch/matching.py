"""The matching engine: deferred acceptance, fallback placement, verification.

Owns: who ends up where, and the evidence trail for why.

Deliberately does NOT own: how teams rank people (scoring.py) or how any of
this is phrased for a human (report.py).

The algorithm is candidate-proposing Gale-Shapley deferred acceptance with
team capacities — the Hospital/Residents problem, the same mechanism behind
the US medical residency match. Three properties matter here:

  stability          no blocking pair exists. This IS the audit trail: every
                     team you ranked higher filled its slots with people it
                     scored above you. That is checkable, not rhetorical.
  candidate-optimal  among all stable matchings, this is the best one for the
                     candidates simultaneously.
  strategy-proof     honest ranking is optimal for candidates, provided team
                     scoring ignores candidate preferences (see scoring.py).

If you are tempted to replace this with something that maximizes total fit
(min-cost flow, Hungarian): it scores marginally better in aggregate and
cannot explain a single individual outcome. Read docs/DECISIONS.md first.
"""

from __future__ import annotations

import hashlib
from collections import deque
from datetime import datetime, timezone

from .models import (
    TIER_FALLBACK,
    TIER_PINNED,
    TIER_RANKED,
    TIER_TOP_CHOICE,
    Assignment,
    Cohort,
    MatchRun,
    Rejection,
)
from .scoring import SCORING_VERSION, ScoringContext, build_scoring_context

ALGORITHM_VERSION = f"da-v1+{SCORING_VERSION}"


def deferred_acceptance(
    cohort: Cohort, ctx: ScoringContext, pins: dict[str, str] | None = None
) -> tuple[dict[str, set[str]], list[tuple[str, str]]]:
    """Run candidate-proposing DA.

    Returns (rosters, rejection_events) where `rosters` maps team id to the set
    of candidates it holds, and `rejection_events` is every (candidate, team)
    bump that happened, in order.

    Candidates propose down their list; teams hold the best `capacity` proposals
    seen so far and release the rest. A held candidate is never final until the
    run ends — that "tentative hold" is the whole trick, and it is why a late
    proposal from a strong candidate can still displace an earlier one.

    `pins` are manual overrides. They are seated before any proposal happens and
    are never displaced, which reduces the effective capacity everyone else is
    competing for. Note the consequence honestly: the result is stable with
    respect to the *remaining* slots, not the full set. A pinned placement can
    itself be a blocking pair, and `find_blocking_pairs` will report it rather
    than quietly excusing it — a manual override should be visible as what it
    is, not laundered into looking like the algorithm's choice.
    """
    pins = pins or {}
    rosters: dict[str, set[str]] = {t.id: set() for t in cohort.teams}
    capacity = {t.id: t.capacity for t in cohort.teams}
    next_choice: dict[str, int] = {c.id: 0 for c in cohort.candidates}
    rejection_events: list[tuple[str, str]] = []

    for cid, team_id in sorted(pins.items()):
        if team_id not in rosters:
            raise ValueError(f"pinned candidate {cid} -> unknown team {team_id!r}")
        rosters[team_id].add(cid)

    for team_id, seated in rosters.items():
        if len(seated) > capacity[team_id]:
            raise ValueError(
                f"team {team_id} has {len(seated)} pinned candidates but only "
                f"{capacity[team_id]} slot(s)"
            )

    # Only unpinned candidates with a non-empty list participate; the rest go
    # straight to the fallback round. Deterministic queue order keeps runs
    # reproducible.
    free = deque(
        c.id for c in cohort.candidates if c.ranked_team_ids and c.id not in pins
    )

    while free:
        cid = free.popleft()
        prefs = cohort.candidate(cid).ranked_team_ids
        idx = next_choice[cid]
        if idx >= len(prefs):
            continue  # exhausted their list — handled by the fallback round

        team_id = prefs[idx]
        next_choice[cid] = idx + 1

        rosters[team_id].add(cid)
        if len(rosters[team_id]) > capacity[team_id]:
            # Release the worst currently held, by this team's own ranking.
            # Pinned candidates are immovable, so they are excluded from the
            # eviction pool — a manual override that the algorithm could undo
            # on the next proposal would not be an override at all.
            evictable = [c for c in rosters[team_id] if c not in pins]
            # When pins fill a team outright there is nobody to evict, so the
            # proposer is turned away immediately and moves down their list.
            worst = (
                max(evictable, key=lambda c: ctx.rank(team_id, c)) if evictable else cid
            )
            rosters[team_id].remove(worst)
            rejection_events.append((worst, team_id))
            free.append(worst)  # they will propose to their next choice

    return rosters, rejection_events


def _build_rejections(
    ctx: ScoringContext,
    rosters: dict[str, set[str]],
    rejection_events: list[tuple[str, str]],
) -> list[Rejection]:
    """Turn raw bumps into explainable records, scored against the FINAL roster.

    The comparison a rejected person sees is against the team's final cutoff,
    not against whoever happened to be held at the instant they were bumped.
    Mid-run state is an artifact of proposal order and would make two people
    with identical outcomes get different-sounding explanations.
    """
    cutoffs: dict[str, float | None] = {}
    for team_id, roster in rosters.items():
        cutoffs[team_id] = (
            min(ctx.score(cid, team_id) for cid in roster) if roster else None
        )

    rejections: list[Rejection] = []
    for cid, team_id in rejection_events:
        roster = rosters[team_id]
        my_rank = ctx.rank(team_id, cid)
        held_above = sum(1 for other in roster if ctx.rank(team_id, other) < my_rank)
        rejections.append(
            Rejection(
                candidate_id=cid,
                team_id=team_id,
                candidate_score=ctx.score(cid, team_id),
                cutoff_score=cutoffs[team_id],
                held_above=held_above,
            )
        )
    return rejections


def fallback_round(
    cohort: Cohort,
    ctx: ScoringContext,
    rosters: dict[str, set[str]],
) -> list[str]:
    """Place candidates whose ranked list ran out. "Nobody gets a hard no."

    Processes the most *constrained* candidates first — those who fit the
    fewest teams at all — rather than first-come or alphabetically. The
    fairness argument: someone whose skills suit three teams loses far more by
    going last than someone who fits fifteen. Going in arbitrary order would
    systematically strand narrow-profile candidates in whatever seat remained.

    Mutates `rosters` in place. Returns the ids of anyone still unplaced, which
    happens only when total capacity is genuinely short of cohort size.
    """
    placed = {cid for roster in rosters.values() for cid in roster}
    unmatched = [c.id for c in cohort.candidates if c.id not in placed]
    remaining = {t.id: t.capacity - len(rosters[t.id]) for t in cohort.teams}

    def viable_count(cid: str) -> int:
        return sum(
            1
            for t in cohort.teams
            if remaining[t.id] > 0 and ctx.score(cid, t.id) > 0
        )

    # Tie-break on id so the ordering is total and reproducible.
    unmatched.sort(key=lambda cid: (viable_count(cid), cid))

    still_unplaced: list[str] = []
    for cid in unmatched:
        open_teams = [t.id for t in cohort.teams if remaining[t.id] > 0]
        if not open_teams:
            still_unplaced.append(cid)
            continue
        best = max(open_teams, key=lambda tid: (ctx.score(cid, tid), -ctx.rank(tid, cid)))
        rosters[best].add(cid)
        remaining[best] -= 1

    return still_unplaced


def find_blocking_pairs(
    cohort: Cohort, ctx: ScoringContext, assignments: dict[str, str]
) -> list[tuple[str, str]]:
    """Every (candidate, team) that would both rather have each other.

    This is the verifier the whole audit story rests on, so it is written to be
    obviously correct rather than fast: O(candidates x ranked teams x capacity).

    A pair blocks when BOTH sides would defect:
      - the candidate ranked `team` above wherever they actually landed
        (a candidate placed on a team they never ranked prefers any ranked team)
      - the team has a free slot, or holds someone it ranks below this candidate

    A team the candidate never ranked can never block: not ranking a team means
    not wanting it, so there is no mutual improvement to find.
    """
    rosters: dict[str, list[str]] = {t.id: [] for t in cohort.teams}
    for cid, tid in assignments.items():
        rosters[tid].append(cid)

    blocking: list[tuple[str, str]] = []
    for candidate in cohort.candidates:
        cid = candidate.id
        current = assignments.get(cid)
        prefs = candidate.ranked_team_ids

        if current is None:
            ceiling = len(prefs)  # unplaced: prefers every team they ranked
        elif current in prefs:
            ceiling = prefs.index(current)
        else:
            ceiling = len(prefs)  # fallback placement: prefers any ranked team

        for team_id in prefs[:ceiling]:
            team = cohort.team(team_id)
            roster = rosters[team_id]
            if len(roster) < team.capacity:
                blocking.append((cid, team_id))
                continue
            if any(ctx.prefers(team_id, cid, member) for member in roster):
                blocking.append((cid, team_id))

    return blocking


def match(
    cohort: Cohort,
    seed: int = 0,
    timestamp: str | None = None,
    pins: dict[str, str] | None = None,
) -> MatchRun:
    """Run a full match and package it as an auditable MatchRun.

    `cohort_hash` + `seed` + `algorithm_version` + `pins` reproduce this output
    exactly; that is the audit claim, and it is why the seed is a recorded
    input rather than an implementation detail.

    `pins` maps candidate id -> team id for manual overrides: the recruiter
    dragging someone onto a specific team. Pinned people are seated first and
    consume that team's capacity, then deferred acceptance runs over whatever
    is left.

    An override is a legitimate act — the recruiter knows things the data does
    not — but it is never free. Every pin takes a slot that DA would have given
    to someone else, so the cost lands on a specific person, and the run
    records exactly who. That is the number to put in front of someone before
    they confirm a drag, not after.
    """
    ctx = build_scoring_context(cohort, seed)

    rosters, rejection_events = deferred_acceptance(cohort, ctx, pins=pins)
    da_placed = {cid for roster in rosters.values() for cid in roster}
    rejections = _build_rejections(ctx, rosters, rejection_events)
    unplaced = fallback_round(cohort, ctx, rosters)

    assignments: list[Assignment] = []
    assignment_map: dict[str, str] = {}
    for team_id, roster in rosters.items():
        for cid in roster:
            prefs = cohort.candidate(cid).ranked_team_ids
            rank = prefs.index(team_id) + 1 if team_id in prefs else None
            if pins and cid in pins:
                # A pin outranks every other label. Someone asking why this
                # person is here deserves "a human placed them", even when the
                # pin happens to agree with what the algorithm would have done.
                tier = TIER_PINNED
            elif rank == 1:
                tier = TIER_TOP_CHOICE
            elif rank is not None:
                tier = TIER_RANKED
            else:
                tier = TIER_FALLBACK
            assignments.append(
                Assignment(
                    candidate_id=cid,
                    team_id=team_id,
                    tier=tier,
                    fit_score=ctx.score(cid, team_id),
                    preference_rank=rank,
                    fit_breakdown=ctx.breakdown(cid, team_id),
                )
            )
            assignment_map[cid] = team_id

    assignments.sort(key=lambda a: a.candidate_id)

    # Stability is checked over the final matching, fallback placements
    # included — see docs/DECISIONS.md for why that is still sound.
    blocking = find_blocking_pairs(cohort, ctx, assignment_map)

    from .report import compute_metrics  # local import: report.py reads matching

    cohort_hash = cohort.content_hash()
    pin_repr = ",".join(f"{k}={v}" for k, v in sorted((pins or {}).items()))
    run_id = hashlib.sha256(
        f"{cohort_hash}|{seed}|{ALGORITHM_VERSION}|{pin_repr}".encode()
    ).hexdigest()[:12]

    run = MatchRun(
        run_id=run_id,
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        seed=seed,
        cohort_hash=cohort_hash,
        algorithm_version=ALGORITHM_VERSION,
        assignments=tuple(assignments),
        unplaced=tuple(sorted(unplaced)),
        rejections=tuple(
            sorted(rejections, key=lambda r: (r.candidate_id, r.team_id))
        ),
        pins=dict(pins or {}),
        cohort=cohort,
    )
    run.metrics = compute_metrics(run, cohort, blocking, da_placed)
    return run
