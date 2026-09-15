"""How a team ranks candidates.

Owns: the fit score, its component weights, and the derived preference order
each team holds over the whole cohort.

Deliberately does NOT own: the matching loop, or any tie to what candidates
want.

    ############################################################
    #  A team's score for a candidate MUST NOT read that       #
    #  candidate's preferences. Not their ranked list, not      #
    #  their rank of this team, not "they seem keen."           #
    ############################################################

That rule is what buys strategy-proofness for candidates: under
candidate-proposing deferred acceptance, ranking honestly is optimal *only*
if the other side's ranking is independent of what you submitted. The moment
a team scores "they put us first" as a positive, candidates gain a reason to
misrepresent — and the promise we make to the cohort ("rank truthfully, it
can only help you") becomes false.

It breaks silently: the match still runs and still looks stable. Only
`tests/test_scoring.py::test_scores_ignore_candidate_preferences` catches it.
Do not delete that test to make a change pass.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .models import Candidate, Cohort, Team

SCORING_VERSION = "fit-v1"

# Weights sum to 1.0, so a score is readable as "percent fit" without scaling.
# Required-skill coverage dominates because it is the one signal a hiring
# manager states explicitly and would defend out loud.
W_REQUIRED = 0.45
W_PREFERRED = 0.20
W_INTEREST = 0.20
W_WISHLIST = 0.15

# A manager naming someone is strong evidence, but it decays down the list:
# the fifth name on a wishlist carries less conviction than the first.
WISHLIST_DECAY_PER_POSITION = 0.12
WISHLIST_MIN_MULTIPLIER = 0.40


def _overlap_ratio(have: frozenset[str], want: frozenset[str]) -> float:
    """Fraction of `want` covered by `have`.

    An empty `want` scores 0.0 rather than 1.0 — a team that asked for nothing
    gets no credit for a candidate "matching" nothing. Returning 1.0 here would
    make under-specified teams look like a perfect fit for everyone, which is
    exactly backwards.
    """
    if not want:
        return 0.0
    return len(have & want) / len(want)


def fit_score(candidate: Candidate, team: Team) -> tuple[float, dict[str, float]]:
    """Score this candidate for this team, with the reasoning attached.

    Returns (total, breakdown). The breakdown is carried into the assignment
    record so explanations never have to recompute a score — and so an old run
    stays explainable even after the weights change.
    """
    required = _overlap_ratio(candidate.skills, team.required_skills)
    preferred = _overlap_ratio(candidate.skills, team.preferred_skills)
    interest = _overlap_ratio(candidate.interests, team.domain_tags)

    wishlist = 0.0
    if candidate.id in team.wishlist:
        position = team.wishlist.index(candidate.id)
        multiplier = max(
            WISHLIST_MIN_MULTIPLIER,
            1.0 - WISHLIST_DECAY_PER_POSITION * position,
        )
        wishlist = multiplier

    breakdown = {
        "required_coverage": required,
        "preferred_overlap": preferred,
        "interest_alignment": interest,
        "wishlist_bonus": wishlist,
    }
    total = (
        W_REQUIRED * required
        + W_PREFERRED * preferred
        + W_INTEREST * interest
        + W_WISHLIST * wishlist
    )
    breakdown["total"] = total
    return total, breakdown


def _tiebreak_key(seed: int, team_id: str, candidate_id: str) -> str:
    """Stable pseudo-random ordering for candidates a team scores identically.

    Derived by hashing rather than by shuffling a list, so the key for a given
    (seed, team, candidate) never depends on how many other candidates exist or
    what order they arrived in. Adding one person to the cohort must not
    reshuffle everyone else's tie-breaks.

    Ties are common in practice: managers bucket people ("strong yes / yes /
    maybe") far more often than they strictly rank them, and a coarse rubric
    produces identical scores constantly. Some rule has to break them, and the
    only defensible rule is one that is arbitrary, fixed in advance, and
    recorded — which is why the seed lands in the run record.
    """
    return hashlib.sha256(f"{seed}|{team_id}|{candidate_id}".encode("utf-8")).hexdigest()


@dataclass
class ScoringContext:
    """Precomputed scores and team preference orders for one cohort.

    Built once per run (150 x 20 = 3,000 pairs is nothing) so the matching loop
    can do O(1) lookups instead of rescoring on every proposal.
    """

    seed: int
    scores: dict[tuple[str, str], float]
    breakdowns: dict[tuple[str, str], dict[str, float]]
    team_order: dict[str, tuple[str, ...]]
    team_rank: dict[str, dict[str, int]]

    def score(self, candidate_id: str, team_id: str) -> float:
        return self.scores[(candidate_id, team_id)]

    def breakdown(self, candidate_id: str, team_id: str) -> dict[str, float]:
        return self.breakdowns[(candidate_id, team_id)]

    def rank(self, team_id: str, candidate_id: str) -> int:
        """Position of this candidate in the team's order. Lower is better."""
        return self.team_rank[team_id][candidate_id]

    def prefers(self, team_id: str, challenger_id: str, incumbent_id: str) -> bool:
        """Would this team rather have `challenger` than `incumbent`?"""
        return self.rank(team_id, challenger_id) < self.rank(team_id, incumbent_id)


def build_scoring_context(cohort: Cohort, seed: int) -> ScoringContext:
    """Score every (candidate, team) pair and derive each team's ranking.

    Every team ranks the *entire* cohort, including people who never ranked
    them. That is required for two things beyond the matching itself: the
    fallback round needs an order over candidates who did not apply, and the
    blocking-pair check needs to ask "would this team have preferred that
    person?" about pairs that never interacted.
    """
    scores: dict[tuple[str, str], float] = {}
    breakdowns: dict[tuple[str, str], dict[str, float]] = {}

    for team in cohort.teams:
        for candidate in cohort.candidates:
            total, breakdown = fit_score(candidate, team)
            scores[(candidate.id, team.id)] = total
            breakdowns[(candidate.id, team.id)] = breakdown

    team_order: dict[str, tuple[str, ...]] = {}
    team_rank: dict[str, dict[str, int]] = {}
    for team in cohort.teams:
        ordered = sorted(
            cohort.candidates,
            key=lambda c, t=team: (
                -scores[(c.id, t.id)],
                _tiebreak_key(seed, t.id, c.id),
            ),
        )
        ids = tuple(c.id for c in ordered)
        team_order[team.id] = ids
        team_rank[team.id] = {cid: i for i, cid in enumerate(ids)}

    return ScoringContext(
        seed=seed,
        scores=scores,
        breakdowns=breakdowns,
        team_order=team_order,
        team_rank=team_rank,
    )
