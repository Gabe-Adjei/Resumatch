"""Correctness tests for the matching engine.

The stability tests are the important ones. Stability is the product claim —
"no team you ranked higher would have taken you over someone it placed" — and
it is the only claim here that a user could be materially harmed by if it were
false, because it gets repeated to interns as fact.
"""

from __future__ import annotations

import unittest

from resumatch.generate import generate_cohort
from resumatch.matching import (
    deferred_acceptance,
    find_blocking_pairs,
    match,
)
from resumatch.models import TIER_FALLBACK, TIER_PINNED, Candidate, Cohort, Team
from resumatch.scoring import build_scoring_context


def tiny_cohort() -> Cohort:
    """A hand-built case with one known-correct answer.

    Two teams, one slot each, four candidates. Both Ana and Ben want Alpha
    first; Alpha's required skill is `python`, which only Ana has, so Ana takes
    Alpha and Ben falls to Beta. Cara and Dan have nowhere ranked to go and
    must land via the fallback round.
    """
    teams = (
        Team(
            id="ALPHA",
            name="Alpha",
            capacity=1,
            domain_tags=frozenset({"backend"}),
            required_skills=frozenset({"python"}),
        ),
        Team(
            id="BETA",
            name="Beta",
            capacity=3,
            domain_tags=frozenset({"frontend"}),
            required_skills=frozenset({"react"}),
        ),
    )
    candidates = (
        Candidate("A", "Ana", frozenset({"python"}), frozenset({"backend"}), ("ALPHA", "BETA")),
        Candidate("B", "Ben", frozenset({"java"}), frozenset({"backend"}), ("ALPHA", "BETA")),
        Candidate("C", "Cara", frozenset({"react"}), frozenset({"frontend"}), ("BETA",)),
        Candidate("D", "Dan", frozenset({"go"}), frozenset({"backend"}), ()),
    )
    return Cohort(candidates=candidates, teams=teams)


class TestKnownFixture(unittest.TestCase):
    def test_matches_the_hand_computed_answer(self):
        run = match(tiny_cohort(), seed=1)
        placed = {a.candidate_id: a.team_id for a in run.assignments}

        self.assertEqual(placed["A"], "ALPHA", "Ana holds the only python skill Alpha wants")
        self.assertEqual(placed["B"], "BETA", "Ben loses Alpha to Ana and falls to his #2")
        self.assertEqual(placed["C"], "BETA")
        self.assertEqual(placed["D"], "BETA", "Dan ranked nothing; fallback seats him")

    def test_unranked_candidate_is_tagged_as_fallback(self):
        run = match(tiny_cohort(), seed=1)
        dan = run.assignment_for("D")
        self.assertEqual(dan.tier, TIER_FALLBACK)
        self.assertIsNone(dan.preference_rank, "fallback placements have no preference rank")

    def test_rejection_is_recorded_with_a_cutoff(self):
        run = match(tiny_cohort(), seed=1)
        bens = run.rejections_for("B")
        self.assertEqual(len(bens), 1)
        self.assertEqual(bens[0].team_id, "ALPHA")
        self.assertEqual(bens[0].held_above, 1, "exactly one person beat him to it")
        self.assertIsNotNone(bens[0].cutoff_score)


class TestStability(unittest.TestCase):
    """The claim the whole product rests on."""

    def test_no_blocking_pairs_across_many_seeds(self):
        for seed in range(25):
            with self.subTest(seed=seed):
                cohort = generate_cohort(n_candidates=60, n_teams=10, seed=seed)
                run = match(cohort, seed=seed)
                self.assertEqual(
                    run.metrics["blocking_pairs"],
                    0,
                    f"seed {seed} produced an unstable match — some candidate and team "
                    f"would both rather have each other",
                )

    def test_stability_survives_the_fallback_round(self):
        """Fallback placements must not introduce blocking pairs.

        They cannot, and the reason is worth stating: DA only leaves someone
        unmatched after every team they ranked has rejected them, which means
        each of those teams is full of people it ranks higher. The fallback
        round then only fills slots that are still empty — and a team a
        candidate ranked cannot be empty while that candidate is unmatched.
        This test is what stops a future refactor from breaking that.
        """
        for seed in range(15):
            cohort = generate_cohort(n_candidates=80, n_teams=12, seed=seed)
            run = match(cohort, seed=seed)
            fallbacks = [a for a in run.assignments if a.tier == TIER_FALLBACK]
            if not fallbacks:
                continue
            self.assertEqual(run.metrics["blocking_pairs"], 0, f"seed {seed}")

    def test_blocking_pair_detector_actually_detects(self):
        """A verifier that always returns [] would pass every test above."""
        cohort = tiny_cohort()
        ctx = build_scoring_context(cohort, seed=1)
        # Deliberately wrong: Ben takes Alpha even though Ana outranks him and
        # would rather be there. That is a textbook blocking pair.
        sabotaged = {"A": "BETA", "B": "ALPHA", "C": "BETA", "D": "BETA"}
        blocking = find_blocking_pairs(cohort, ctx, sabotaged)
        self.assertIn(("A", "ALPHA"), blocking)


class TestCapacityAndCoverage(unittest.TestCase):
    def test_capacity_is_never_exceeded(self):
        cohort = generate_cohort(n_candidates=150, n_teams=20, seed=3)
        run = match(cohort, seed=3)
        counts: dict[str, int] = {}
        for a in run.assignments:
            counts[a.team_id] = counts.get(a.team_id, 0) + 1
        for team in cohort.teams:
            self.assertLessEqual(counts.get(team.id, 0), team.capacity, team.id)

    def test_nobody_is_assigned_twice(self):
        run = match(generate_cohort(n_candidates=100, n_teams=15, seed=5), seed=5)
        ids = [a.candidate_id for a in run.assignments]
        self.assertEqual(len(ids), len(set(ids)))

    def test_everyone_is_placed_when_slots_suffice(self):
        cohort = generate_cohort(n_candidates=100, n_teams=15, seed=11)
        self.assertGreaterEqual(cohort.total_capacity, len(cohort.candidates))
        run = match(cohort, seed=11)
        self.assertEqual(len(run.unplaced), 0)
        self.assertEqual(len(run.assignments), len(cohort.candidates))

    def test_shortage_leaves_people_unplaced_rather_than_overfilling(self):
        """Under-capacity must fail visibly, not by quietly overfilling a team."""
        teams = (Team(id="T1", name="Only", capacity=2, required_skills=frozenset({"python"})),)
        candidates = tuple(
            Candidate(f"C{i}", f"Person {i}", frozenset({"python"}), frozenset(), ("T1",))
            for i in range(5)
        )
        run = match(Cohort(candidates=candidates, teams=teams), seed=0)
        self.assertEqual(len(run.assignments), 2)
        self.assertEqual(len(run.unplaced), 3)


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_same_output(self):
        cohort = generate_cohort(n_candidates=80, n_teams=12, seed=9)
        a = match(cohort, seed=4, timestamp="fixed")
        b = match(cohort, seed=4, timestamp="fixed")
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_seed_changes_tie_breaks_but_not_validity(self):
        cohort = generate_cohort(n_candidates=80, n_teams=12, seed=9)
        a = match(cohort, seed=1, timestamp="fixed")
        b = match(cohort, seed=2, timestamp="fixed")
        self.assertNotEqual(a.run_id, b.run_id, "the seed must be part of run identity")
        self.assertEqual(a.metrics["blocking_pairs"], 0)
        self.assertEqual(b.metrics["blocking_pairs"], 0)

    def test_run_id_tracks_the_inputs(self):
        cohort = generate_cohort(n_candidates=40, n_teams=8, seed=2)
        self.assertEqual(
            match(cohort, seed=0, timestamp="x").run_id,
            match(cohort, seed=0, timestamp="y").run_id,
            "run id must depend on inputs, not on wall-clock time",
        )


class TestStrategyProofness(unittest.TestCase):
    """Candidates must not be able to gain by misreporting.

    This is the promise made to the cohort — "rank honestly, it can only help
    you" — so it needs a test rather than an assurance.
    """

    def test_truncating_your_list_never_improves_your_outcome(self):
        cohort = generate_cohort(n_candidates=60, n_teams=10, seed=13)
        baseline = match(cohort, seed=13)

        for candidate in cohort.candidates[:20]:
            if len(candidate.ranked_team_ids) < 2:
                continue
            honest = baseline.assignment_for(candidate.id)
            honest_rank = honest.preference_rank if honest else None

            # Drop their last choice and re-run — a classic manipulation.
            truncated = Candidate(
                id=candidate.id,
                name=candidate.name,
                skills=candidate.skills,
                interests=candidate.interests,
                ranked_team_ids=candidate.ranked_team_ids[:-1],
            )
            others = tuple(c for c in cohort.candidates if c.id != candidate.id)
            gamed = match(
                Cohort(candidates=others + (truncated,), teams=cohort.teams), seed=13
            )
            got = gamed.assignment_for(candidate.id)
            gamed_rank = got.preference_rank if got else None

            if honest_rank is not None and gamed_rank is not None:
                with self.subTest(candidate=candidate.id):
                    self.assertGreaterEqual(
                        gamed_rank,
                        honest_rank,
                        f"{candidate.id} improved from #{honest_rank} to #{gamed_rank} by "
                        f"truncating their list — the match is manipulable",
                    )


class TestPinning(unittest.TestCase):
    """Manual overrides: the recruiter dragging someone onto a team."""

    def test_a_pinned_candidate_lands_where_they_were_put(self):
        cohort = generate_cohort(n_candidates=60, n_teams=10, seed=6)
        target = cohort.teams[3].id
        pinned = cohort.candidates[0].id
        run = match(cohort, seed=6, pins={pinned: target})

        assignment = run.assignment_for(pinned)
        self.assertEqual(assignment.team_id, target)
        self.assertEqual(assignment.tier, TIER_PINNED)
        self.assertEqual(run.pins, {pinned: target})

    def test_pinning_still_respects_capacity(self):
        cohort = generate_cohort(n_candidates=60, n_teams=10, seed=6)
        run = match(cohort, seed=6, pins={cohort.candidates[0].id: cohort.teams[3].id})
        counts: dict[str, int] = {}
        for a in run.assignments:
            counts[a.team_id] = counts.get(a.team_id, 0) + 1
        for team in cohort.teams:
            self.assertLessEqual(counts.get(team.id, 0), team.capacity, team.id)

    def test_pinning_beyond_capacity_is_rejected_loudly(self):
        teams = (Team(id="T1", name="Small", capacity=1),)
        candidates = (
            Candidate("A", "A", frozenset(), frozenset(), ("T1",)),
            Candidate("B", "B", frozenset(), frozenset(), ("T1",)),
        )
        with self.assertRaises(ValueError):
            match(Cohort(candidates=candidates, teams=teams), pins={"A": "T1", "B": "T1"})

    def test_pinning_to_an_unknown_team_is_rejected(self):
        with self.assertRaises(ValueError):
            match(tiny_cohort(), pins={"A": "NOPE"})

    def test_everyone_still_gets_placed_around_a_pin(self):
        cohort = generate_cohort(n_candidates=60, n_teams=10, seed=8)
        run = match(cohort, seed=8, pins={cohort.candidates[2].id: cohort.teams[1].id})
        self.assertEqual(len(run.assignments), len(cohort.candidates))
        self.assertEqual(len(run.unplaced), 0)


class TestDeferredAcceptanceInternals(unittest.TestCase):
    def test_a_late_strong_proposal_displaces_an_earlier_weak_one(self):
        """The tentative-hold property, stated as a test.

        Both candidates want T1, which has one slot. The weaker one proposes
        first and is held. If holds were final on arrival, queue order would
        decide the slot and the weaker candidate would keep it. Because holds
        are tentative, the stronger later proposal takes it and the weaker one
        is released to their next choice.
        """
        teams = (
            Team(id="T1", name="One", capacity=1, required_skills=frozenset({"python"})),
            Team(id="T2", name="Two", capacity=1, required_skills=frozenset({"go"})),
        )
        # Queue order follows cohort order, so `weak` proposes first.
        weak = Candidate("W", "Weak", frozenset({"go"}), frozenset(), ("T1", "T2"))
        strong = Candidate("S", "Strong", frozenset({"python"}), frozenset(), ("T1", "T2"))
        cohort = Cohort(candidates=(weak, strong), teams=teams)
        ctx = build_scoring_context(cohort, seed=0)
        rosters, rejection_events = deferred_acceptance(cohort, ctx)

        self.assertIn("S", rosters["T1"], "T1 wanted python; the later proposal wins the slot")
        self.assertIn("W", rosters["T2"], "the displaced candidate falls to their next choice")
        self.assertIn(("W", "T1"), rejection_events, "the displacement must be recorded")


if __name__ == "__main__":
    unittest.main()
