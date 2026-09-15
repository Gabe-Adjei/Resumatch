"""Tests for the fit score and the team preference orders it produces.

The test that matters most here is
`TestStrategyProofnessInvariant::test_scores_ignore_candidate_preferences`.
It is the only automated defense against the one change that would silently
break the guarantee we make to the cohort. Read its docstring before touching
scoring.py.
"""

from __future__ import annotations

import unittest

from resumatch.generate import generate_cohort
from resumatch.models import Candidate, Cohort, Team
from resumatch.scoring import (
    W_REQUIRED,
    build_scoring_context,
    fit_score,
)


def team(**kwargs) -> Team:
    base = {
        "id": "T1",
        "name": "Team",
        "capacity": 5,
        "domain_tags": frozenset({"backend"}),
        "required_skills": frozenset({"python", "sql"}),
        "preferred_skills": frozenset({"go"}),
    }
    base.update(kwargs)
    return Team(**base)


def candidate(**kwargs) -> Candidate:
    base = {
        "id": "C1",
        "name": "Person",
        "skills": frozenset({"python"}),
        "interests": frozenset({"backend"}),
        "ranked_team_ids": (),
    }
    base.update(kwargs)
    return Candidate(**base)


class TestFitScore(unittest.TestCase):
    def test_full_match_scores_higher_than_partial(self):
        full = fit_score(candidate(skills=frozenset({"python", "sql"})), team())[0]
        partial = fit_score(candidate(skills=frozenset({"python"})), team())[0]
        self.assertGreater(full, partial)

    def test_no_overlap_scores_zero(self):
        score, breakdown = fit_score(
            candidate(skills=frozenset({"swift"}), interests=frozenset({"mobile"})), team()
        )
        self.assertEqual(score, 0.0)
        self.assertEqual(breakdown["required_coverage"], 0.0)

    def test_required_coverage_is_proportional(self):
        score, breakdown = fit_score(
            candidate(skills=frozenset({"python"}), interests=frozenset()), team()
        )
        self.assertAlmostEqual(breakdown["required_coverage"], 0.5, msg="1 of 2 required")
        self.assertAlmostEqual(score, W_REQUIRED * 0.5)

    def test_breakdown_components_reconstruct_the_total(self):
        c = candidate(skills=frozenset({"python", "sql", "go"}))
        score, b = fit_score(c, team())
        self.assertAlmostEqual(b["total"], score)

    def test_a_team_asking_for_nothing_gets_no_free_credit(self):
        """An under-specified team must not look like a perfect fit for all.

        If empty requirements scored 1.0, a manager who left the skills field
        blank would outrank every team that filled it in honestly, and the
        whole cohort would be drawn toward the laziest intake form.
        """
        score, b = fit_score(
            candidate(interests=frozenset()),
            team(required_skills=frozenset(), preferred_skills=frozenset(), domain_tags=frozenset()),
        )
        self.assertEqual(score, 0.0)
        self.assertEqual(b["required_coverage"], 0.0)

    def test_wishlist_bonus_decays_down_the_list(self):
        first = fit_score(candidate(id="A"), team(wishlist=("A", "B")))[0]
        second = fit_score(candidate(id="B"), team(wishlist=("A", "B")))[0]
        self.assertGreater(first, second, "the manager's top name should count for more")

    def test_wishlist_helps_but_does_not_dominate_skills(self):
        """A named candidate with no skills must not outrank a strong fit.

        A wishlist is real evidence, but letting it override the stated
        requirements turns the tool into a rubber stamp for whoever the manager
        already met — which is the bias the process is supposed to reduce.
        """
        named_but_unskilled = fit_score(
            candidate(id="A", skills=frozenset(), interests=frozenset()),
            team(wishlist=("A",)),
        )[0]
        unnamed_but_strong = fit_score(
            candidate(id="B", skills=frozenset({"python", "sql", "go"})), team(wishlist=("A",))
        )[0]
        self.assertGreater(unnamed_but_strong, named_but_unskilled)


class TestStrategyProofnessInvariant(unittest.TestCase):
    def test_scores_ignore_candidate_preferences(self):
        """A team's score for a candidate must not depend on what that
        candidate ranked.

        WHY THIS TEST EXISTS — do not delete it to make a change pass.

        Candidate-proposing deferred acceptance is strategy-proof for
        candidates only while the other side's ranking is independent of what
        candidates submitted. Adding something like "they ranked us #1, bump
        them up" feels like it honors preference, and it does the opposite: it
        hands candidates a reason to misreport, and it makes the promise we
        print for the cohort — rank honestly, it can only help you — false.

        The failure is invisible at runtime. The match still completes, still
        reports zero blocking pairs, and still looks defensible. This test is
        the only thing that catches it.
        """
        t = team()
        for prefs in ((), ("T1",), ("T9", "T1"), ("T1", "T2", "T3")):
            with self.subTest(prefs=prefs):
                self.assertEqual(
                    fit_score(candidate(ranked_team_ids=prefs), t)[0],
                    fit_score(candidate(ranked_team_ids=()), t)[0],
                    "fit score changed when only the candidate's preferences changed",
                )

    def test_team_ordering_is_unchanged_when_preferences_are_shuffled(self):
        """The same invariant, at the level the matcher actually consumes."""
        cohort = generate_cohort(n_candidates=40, n_teams=8, seed=21)
        baseline = build_scoring_context(cohort, seed=1)

        reversed_prefs = tuple(
            Candidate(
                id=c.id,
                name=c.name,
                skills=c.skills,
                interests=c.interests,
                ranked_team_ids=tuple(reversed(c.ranked_team_ids)),
            )
            for c in cohort.candidates
        )
        shuffled = build_scoring_context(
            Cohort(candidates=reversed_prefs, teams=cohort.teams), seed=1
        )
        self.assertEqual(baseline.team_order, shuffled.team_order)


class TestTieBreaking(unittest.TestCase):
    def test_ties_are_broken_deterministically_for_a_given_seed(self):
        cohort = generate_cohort(n_candidates=30, n_teams=6, seed=4)
        a = build_scoring_context(cohort, seed=7)
        b = build_scoring_context(cohort, seed=7)
        self.assertEqual(a.team_order, b.team_order)

    def test_different_seeds_break_ties_differently(self):
        cohort = generate_cohort(n_candidates=60, n_teams=10, seed=4)
        a = build_scoring_context(cohort, seed=1)
        b = build_scoring_context(cohort, seed=2)
        self.assertNotEqual(a.team_order, b.team_order)

    def test_adding_a_candidate_does_not_reshuffle_existing_tie_breaks(self):
        """Tie-break keys are hashed per (seed, team, candidate), not drawn
        from a shuffle, so one late addition must not reorder everyone else.

        If it did, a single late-arriving intern would silently churn the
        entire match — and nobody would be able to explain why.
        """
        cohort = generate_cohort(n_candidates=30, n_teams=6, seed=4)
        before = build_scoring_context(cohort, seed=3)

        newcomer = Candidate("ZZZ", "Late Arrival", frozenset({"python"}), frozenset(), ())
        after = build_scoring_context(
            Cohort(candidates=cohort.candidates + (newcomer,), teams=cohort.teams), seed=3
        )

        for t in cohort.teams:
            original = list(before.team_order[t.id])
            without_newcomer = [c for c in after.team_order[t.id] if c != "ZZZ"]
            self.assertEqual(original, without_newcomer, f"team {t.id} reshuffled")


class TestScoringContext(unittest.TestCase):
    def test_every_team_ranks_every_candidate(self):
        cohort = generate_cohort(n_candidates=25, n_teams=5, seed=2)
        ctx = build_scoring_context(cohort, seed=0)
        for t in cohort.teams:
            self.assertEqual(len(ctx.team_order[t.id]), len(cohort.candidates))

    def test_ranks_are_ordered_by_descending_score(self):
        cohort = generate_cohort(n_candidates=25, n_teams=5, seed=2)
        ctx = build_scoring_context(cohort, seed=0)
        for t in cohort.teams:
            scores = [ctx.score(cid, t.id) for cid in ctx.team_order[t.id]]
            self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
