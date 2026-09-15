"""Tests for the taxonomy and the intake adapters.

These guard the integration seam. The failure mode they exist to catch is the
quiet one: an unnormalized skill string scores 0.00 against a team that wanted
exactly that skill, the match still runs, and nobody notices that a good
candidate was placed badly for a reason that never appears in any output.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from resumatch.generate import generate_cohort
from resumatch.intake.csv_intake import (
    load_cohort_csv,
    write_candidates_csv,
    write_teams_csv,
)
from resumatch.intake.resume import candidate_from_resume, guess_name
from resumatch.taxonomy import (
    extract_interests,
    extract_skills,
    normalize,
    normalize_all,
)

RESUME = """
Priya Raman
priya.raman@osu.edu | github.com/praman

EXPERIENCE
Software Engineering Intern, Acme Corp
  Built REST APIs in Python and Go, backed by PostgreSQL.
  Containerized services with Docker and deployed on Kubernetes.

PROJECTS
  Sentiment classifier using PyTorch and scikit-learn.

INTERESTS
  Interested in backend and infrastructure work.
"""


class TestNormalization(unittest.TestCase):
    def test_aliases_collapse_to_one_canonical_skill(self):
        for spelling in ("React", "reactjs", "React.js", "REACTJS", "  react  "):
            with self.subTest(spelling=spelling):
                self.assertEqual(normalize(spelling), "react")

    def test_unknown_terms_are_reported_not_silently_kept(self):
        """A dropped term must be visible.

        Passing an unrecognized string through into a Candidate is worse than
        dropping it: it can never match anything, so it produces a worse
        placement with no error anyone can see.
        """
        recognized, unknown = normalize_all(["Python", "Murex", "KDB", "sql"])
        self.assertEqual(recognized, frozenset({"python", "sql"}))
        self.assertEqual(sorted(unknown), ["KDB", "Murex"])

    def test_both_sides_of_the_market_normalize_identically(self):
        """The whole point of the taxonomy.

        A manager typing "ReactJS" and a resume saying "React" must produce the
        same canonical skill, or the set intersection in scoring silently
        misses a genuine match.
        """
        manager_wrote, _ = normalize_all(["ReactJS", "Postgres", "K8s"])
        resume_says = extract_skills("Experienced with React, PostgreSQL and Kubernetes.")
        self.assertEqual(manager_wrote, resume_says)


class TestExtraction(unittest.TestCase):
    def test_pulls_named_technologies_out_of_a_resume(self):
        skills = extract_skills(RESUME)
        for expected in ("python", "go", "sql", "docker", "kubernetes", "rest_apis"):
            self.assertIn(expected, skills)

    def test_punctuation_heavy_skill_names_still_match(self):
        """`\\b` does not work on terms ending in punctuation.

        "c++" is the canonical example: a naive word-boundary pattern never
        matches it, so a whole quant cohort's strongest signal would vanish.
        """
        self.assertIn("cpp", extract_skills("Strong C++ background."))
        self.assertIn("react", extract_skills("Built it in React.js"))

    def test_does_not_match_a_skill_inside_an_unrelated_word(self):
        self.assertNotIn("go", extract_skills("A good algorithm going forward."))
        self.assertNotIn("react", extract_skills("A reactionary position."))

    def test_interests_are_inferred_from_skills_as_well_as_stated(self):
        skills = extract_skills(RESUME)
        interests = extract_interests(RESUME, skills)
        self.assertIn("backend", interests)
        self.assertIn("infra", interests)
        self.assertIn("data_ml", interests, "pytorch implies data/ml even if unstated")

    def test_empty_text_yields_nothing_rather_than_crashing(self):
        self.assertEqual(extract_skills(""), frozenset())
        self.assertEqual(extract_interests(""), frozenset())


class TestResumeIntake(unittest.TestCase):
    def test_parses_a_resume_into_a_usable_candidate(self):
        result = candidate_from_resume(RESUME, candidate_id="C001")
        self.assertEqual(result.candidate.id, "C001")
        self.assertIn("python", result.candidate.skills)
        self.assertIn("backend", result.candidate.interests)

    def test_guesses_the_name_from_the_header(self):
        self.assertEqual(guess_name(RESUME), "Priya Raman")

    def test_skips_contact_lines_when_guessing_a_name(self):
        text = "priya@osu.edu\n614-555-0100\nPriya Raman\n"
        self.assertEqual(guess_name(text), "Priya Raman")

    def test_warns_when_no_skills_are_recognized(self):
        result = candidate_from_resume(
            "A long narrative about leadership and collaboration, " * 8,
            candidate_id="C002",
        )
        self.assertEqual(result.candidate.skills, frozenset())
        self.assertTrue(
            any("no recognized skills" in w for w in result.warnings),
            "a zero-skill parse must warn — it will otherwise place badly in silence",
        )

    def test_warns_when_no_preferences_were_supplied(self):
        result = candidate_from_resume(RESUME, candidate_id="C003")
        self.assertTrue(any("no ranked team preferences" in w for w in result.warnings))

    def test_preferences_are_never_inferred_from_resume_text(self):
        """A resume must not be read as a preference statement.

        Guessing what someone wants and then matching them against the guess
        is precisely the failure the tool exists to prevent.
        """
        text = RESUME + "\nI would love to join the Payments Core team!"
        result = candidate_from_resume(text, candidate_id="C004")
        self.assertEqual(result.candidate.ranked_team_ids, ())


class TestCsvIntake(unittest.TestCase):
    def test_round_trips_a_generated_cohort(self):
        original = generate_cohort(n_candidates=20, n_teams=5, seed=3)
        with tempfile.TemporaryDirectory() as tmp:
            cpath = os.path.join(tmp, "candidates.csv")
            tpath = os.path.join(tmp, "teams.csv")
            write_candidates_csv(cpath, original.candidates)
            write_teams_csv(tpath, original.teams)

            loaded, warnings = load_cohort_csv(cpath, tpath)

        self.assertEqual(
            original.content_hash(),
            loaded.content_hash(),
            "a CSV round trip must not alter the cohort",
        )
        self.assertEqual(warnings, [])

    def test_tolerates_real_world_header_spellings(self):
        with tempfile.TemporaryDirectory() as tmp:
            cpath = os.path.join(tmp, "c.csv")
            tpath = os.path.join(tmp, "t.csv")
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write("Student ID,Full Name,Skills,Team Preferences\n")
                fh.write("S1,Ana Ruiz,Python;PostgreSQL,T1\n")
            with open(tpath, "w", encoding="utf-8") as fh:
                fh.write("Team ID,Team Name,Open Slots,Must Have,Domains\n")
                fh.write("T1,Payments,3,Python;SQL,backend\n")

            cohort, warnings = load_cohort_csv(cpath, tpath)

        self.assertEqual(len(cohort.candidates), 1)
        self.assertEqual(cohort.team("T1").capacity, 3)
        self.assertEqual(cohort.candidate("S1").skills, frozenset({"python", "sql"}))
        self.assertEqual(cohort.candidate("S1").ranked_team_ids, ("T1",))

    def test_unknown_skill_terms_surface_as_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            cpath = os.path.join(tmp, "c.csv")
            tpath = os.path.join(tmp, "t.csv")
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write("id,name,skills,preferences\n")
                fh.write("S1,Ana,Python;Murex;FIX Protocol,T1\n")
            with open(tpath, "w", encoding="utf-8") as fh:
                fh.write("id,name,capacity,required_skills\n")
                fh.write("T1,Payments,3,Python\n")

            _, warnings = load_cohort_csv(cpath, tpath)

        self.assertTrue(any("Murex" in w for w in warnings))

    def test_preferences_referencing_a_missing_team_are_caught_at_intake(self):
        with tempfile.TemporaryDirectory() as tmp:
            cpath = os.path.join(tmp, "c.csv")
            tpath = os.path.join(tmp, "t.csv")
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write("id,name,skills,preferences\n")
                fh.write("S1,Ana,Python,T1;TYPO\n")
            with open(tpath, "w", encoding="utf-8") as fh:
                fh.write("id,name,capacity,required_skills\n")
                fh.write("T1,Payments,3,Python\n")

            _, warnings = load_cohort_csv(cpath, tpath)

        self.assertTrue(any("unknown team" in w for w in warnings))

    def test_a_team_with_no_recognized_requirements_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            cpath = os.path.join(tmp, "c.csv")
            tpath = os.path.join(tmp, "t.csv")
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write("id,name,skills,preferences\n")
                fh.write("S1,Ana,Python,T1\n")
            with open(tpath, "w", encoding="utf-8") as fh:
                fh.write("id,name,capacity,required_skills\n")
                fh.write("T1,Mystery,3,Vibes\n")

            _, warnings = load_cohort_csv(cpath, tpath)

        self.assertTrue(any("no recognized skills" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
