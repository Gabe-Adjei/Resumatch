"""Intake adapters: everything that turns real-world input into a Cohort.

THIS IS THE SEAM. Read this before integrating a new data source.
====================================================================

The engine (scoring, matching, report, diff) is a pure function over the
dataclasses in models.py. It has no idea where a cohort came from. That is the
entire portability story: moving Resumatch to a new organization means writing
one adapter here and changing nothing else.

Adapters that ship today:

    generate.py         synthetic cohorts from a seed (dev + demo)
    intake/resume.py    resume text -> Candidate
    intake/csv_intake.py    spreadsheet / form export -> Cohort

An adapter is anything with this shape:

    def load(source) -> Cohort

...or, for one side at a time:

    def load_candidates(source) -> list[Candidate]
    def load_teams(source) -> list[Team]

TWO RULES EVERY ADAPTER MUST FOLLOW
-----------------------------------
1. Normalize through taxonomy.py. Never write a raw user-supplied skill string
   into a Candidate or Team. "ReactJS" and "React" are different strings and
   the matcher compares by exact set intersection, so an unnormalized skill
   scores 0.00 against a team that genuinely wanted it. The failure is silent.

2. Report what you dropped. Unknown terms come back from
   `taxonomy.normalize_all()` as a list — surface them. A recruiter seeing
   "3 skills not recognized: Murex, KDB, FIX" can get the taxonomy extended.
   A recruiter seeing nothing just gets worse matches for reasons nobody
   notices.

WHAT AN ADAPTER MUST NOT DO
---------------------------
Adapters must not read or infer candidate preferences when building a Team,
and must not adjust a Team's requirements based on who applied. Team-side data
has to stay independent of candidate-side data or the matching loses its
strategy-proofness guarantee. See the banner in scoring.py.
"""

from __future__ import annotations

from .csv_intake import load_candidates_csv, load_cohort_csv, load_teams_csv
from .resume import IntakeResult, candidate_from_resume, candidates_from_directory

__all__ = [
    "IntakeResult",
    "candidate_from_resume",
    "candidates_from_directory",
    "load_candidates_csv",
    "load_teams_csv",
    "load_cohort_csv",
]
