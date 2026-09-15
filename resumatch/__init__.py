"""Resumatch — cohort-to-team placement.

Sorts a cohort of interns/new grads into open team slots using candidate
preferences and hiring-manager needs, and explains every individual outcome.

The engine is a pure function over JSON. Start at docs/DECISIONS.md for why
deferred acceptance, README.md for how to run it, and resumatch/intake/ for
how to feed it real data.
"""

from .matching import ALGORITHM_VERSION, match
from .models import Candidate, Cohort, MatchRun, Team

__version__ = "0.1.0"

__all__ = [
    "ALGORITHM_VERSION",
    "Candidate",
    "Cohort",
    "MatchRun",
    "Team",
    "match",
    "__version__",
]
