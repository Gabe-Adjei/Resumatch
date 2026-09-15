"""Core data types for Resumatch.

Owns: the shapes every other module reads and writes, their JSON
(de)serialization, and the input hash that makes a match run auditable.

Deliberately does NOT own: scoring, matching, or any notion of what a "good"
assignment looks like. This module is pure structure — if you find yourself
adding a weight or a threshold here, it belongs in scoring.py instead.

All collection fields serialize as *sorted* lists. That is not cosmetic: the
cohort hash is computed over the serialized form, so stable ordering is what
makes "same inputs produce the same hash" true.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# Assignment tiers. `tier` answers "how did this person get here?", which is a
# different question from `preference_rank` ("how good was it for them?").
TIER_TOP_CHOICE = "top_choice"  # matched to their #1 ranked team
TIER_RANKED = "ranked"  # matched to some other team they ranked
TIER_FALLBACK = "fallback"  # ranked list exhausted; placed by fit score
TIER_PINNED = "pinned"  # a human overrode the algorithm and seated them here
TIER_UNPLACED = "unplaced"  # no capacity anywhere — should be rare/zero


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no incidental whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Candidate:
    """One intern/new-grad awaiting placement.

    `ranked_team_ids` is a strict preference order over a *subset* of teams —
    real candidates rank ~5 of ~20. Teams they did not rank are teams they
    never proposed to, which is materially different from teams that rejected
    them, and the explanation layer keeps those cases distinct.
    """

    id: str
    name: str
    skills: frozenset[str] = frozenset()
    interests: frozenset[str] = frozenset()
    ranked_team_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "skills": sorted(self.skills),
            "interests": sorted(self.interests),
            "ranked_team_ids": list(self.ranked_team_ids),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Candidate:
        return cls(
            id=d["id"],
            name=d["name"],
            skills=frozenset(d.get("skills", ())),
            interests=frozenset(d.get("interests", ())),
            ranked_team_ids=tuple(d.get("ranked_team_ids", ())),
        )


@dataclass(frozen=True)
class Team:
    """A team with open headcount.

    `wishlist` holds candidate ids the hiring manager named directly — people
    they met at a career fair or in an interview loop. It is an ordered list,
    strongest first, and it is the only place a manager expresses an opinion
    about a *specific* person. Everything else about their preferences is
    inferred from the skills they asked for.
    """

    id: str
    name: str
    capacity: int
    domain_tags: frozenset[str] = frozenset()
    required_skills: frozenset[str] = frozenset()
    preferred_skills: frozenset[str] = frozenset()
    wishlist: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "capacity": self.capacity,
            "domain_tags": sorted(self.domain_tags),
            "required_skills": sorted(self.required_skills),
            "preferred_skills": sorted(self.preferred_skills),
            "wishlist": list(self.wishlist),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Team:
        return cls(
            id=d["id"],
            name=d["name"],
            capacity=int(d["capacity"]),
            domain_tags=frozenset(d.get("domain_tags", ())),
            required_skills=frozenset(d.get("required_skills", ())),
            preferred_skills=frozenset(d.get("preferred_skills", ())),
            wishlist=tuple(d.get("wishlist", ())),
        )


@dataclass
class Cohort:
    """Everything the matcher needs: one placement cycle's inputs.

    `seed` here is *generation* provenance (which synthetic cohort this is),
    not the matching tie-break seed — that lives on MatchRun, because it is a
    parameter of the run rather than a property of the inputs.
    """

    candidates: tuple[Candidate, ...]
    teams: tuple[Team, ...]
    seed: int | None = None
    _by_candidate: dict[str, Candidate] = field(init=False, repr=False, default_factory=dict)
    _by_team: dict[str, Team] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.candidates = tuple(self.candidates)
        self.teams = tuple(self.teams)
        self._by_candidate = {c.id: c for c in self.candidates}
        self._by_team = {t.id: t for t in self.teams}
        if len(self._by_candidate) != len(self.candidates):
            raise ValueError("duplicate candidate ids in cohort")
        if len(self._by_team) != len(self.teams):
            raise ValueError("duplicate team ids in cohort")

    def candidate(self, candidate_id: str) -> Candidate:
        return self._by_candidate[candidate_id]

    def team(self, team_id: str) -> Team:
        return self._by_team[team_id]

    @property
    def total_capacity(self) -> int:
        return sum(t.capacity for t in self.teams)

    def validate(self) -> list[str]:
        """Return human-readable problems with the inputs. Empty list == clean.

        Called by the CLI before matching so bad intake data fails loudly with
        a fixable message, rather than silently producing a defensible-looking
        match built on a typo'd team id.
        """
        problems: list[str] = []
        for c in self.candidates:
            for tid in c.ranked_team_ids:
                if tid not in self._by_team:
                    problems.append(f"candidate {c.id} ranked unknown team {tid!r}")
            if len(set(c.ranked_team_ids)) != len(c.ranked_team_ids):
                problems.append(f"candidate {c.id} ranked the same team twice")
        for t in self.teams:
            if t.capacity < 0:
                problems.append(f"team {t.id} has negative capacity")
            for cid in t.wishlist:
                if cid not in self._by_candidate:
                    problems.append(f"team {t.id} wishlisted unknown candidate {cid!r}")
        if self.total_capacity < len(self.candidates):
            problems.append(
                f"only {self.total_capacity} slots for {len(self.candidates)} candidates "
                f"— {len(self.candidates) - self.total_capacity} cannot be placed"
            )
        return problems

    def content_hash(self) -> str:
        """SHA-256 over the candidates and teams that determine the match.

        Excludes the generation seed on purpose: two cohorts with identical
        people and teams should hash identically regardless of how they were
        produced. This is the value that ties a run to its exact inputs, so
        "the numbers moved" is always traceable to an input change.
        """
        payload = canonical_json(
            {
                "candidates": [c.to_dict() for c in self.candidates],
                "teams": [t.to_dict() for t in self.teams],
            }
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "candidates": [c.to_dict() for c in self.candidates],
            "teams": [t.to_dict() for t in self.teams],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Cohort:
        return cls(
            candidates=tuple(Candidate.from_dict(x) for x in d["candidates"]),
            teams=tuple(Team.from_dict(x) for x in d["teams"]),
            seed=d.get("seed"),
        )


@dataclass(frozen=True)
class Assignment:
    """One placement, carrying enough context to explain itself.

    `fit_breakdown` is captured at assignment time rather than recomputed on
    demand, so an explanation months later reflects the scoring rules as they
    were when the run happened — not as they are now.
    """

    candidate_id: str
    team_id: str
    tier: str
    fit_score: float
    preference_rank: int | None = None  # 1-based; None when unranked (fallback)
    fit_breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "team_id": self.team_id,
            "tier": self.tier,
            "fit_score": round(self.fit_score, 6),
            "preference_rank": self.preference_rank,
            "fit_breakdown": {k: round(v, 6) for k, v in sorted(self.fit_breakdown.items())},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Assignment:
        return cls(
            candidate_id=d["candidate_id"],
            team_id=d["team_id"],
            tier=d["tier"],
            fit_score=d["fit_score"],
            preference_rank=d.get("preference_rank"),
            fit_breakdown=dict(d.get("fit_breakdown", {})),
        )


@dataclass(frozen=True)
class Rejection:
    """A team that held this candidate and later let them go.

    This is the record that answers a pushback. `cutoff_score` is the score of
    the weakest candidate the team ultimately kept, so the comparison shown to
    a person is against the final roster — not against whoever happened to be
    held at the moment they were bumped, which would be confusing and would
    change depending on proposal order.
    """

    candidate_id: str
    team_id: str
    candidate_score: float
    cutoff_score: float | None = None
    held_above: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "team_id": self.team_id,
            "candidate_score": round(self.candidate_score, 6),
            "cutoff_score": None if self.cutoff_score is None else round(self.cutoff_score, 6),
            "held_above": self.held_above,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Rejection:
        return cls(
            candidate_id=d["candidate_id"],
            team_id=d["team_id"],
            candidate_score=d["candidate_score"],
            cutoff_score=d.get("cutoff_score"),
            held_above=d.get("held_above", 0),
        )


@dataclass
class MatchRun:
    """The immutable result of one match, including how to reproduce it.

    `cohort_hash` + `seed` + `algorithm_version` together are sufficient to
    regenerate this exact output. That triple is the audit claim.
    """

    run_id: str
    timestamp: str
    seed: int
    cohort_hash: str
    algorithm_version: str
    assignments: tuple[Assignment, ...] = ()
    unplaced: tuple[str, ...] = ()
    rejections: tuple[Rejection, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    # Manual overrides applied to this run: candidate id -> team id. Recorded
    # because "a human put them there" is a materially different answer to
    # "why did I land here?" than "the algorithm did", and the explanation
    # must never blur the two.
    pins: dict[str, str] = field(default_factory=dict)
    cohort: Cohort | None = None  # embedded so a run file explains itself offline

    def assignment_for(self, candidate_id: str) -> Assignment | None:
        for a in self.assignments:
            if a.candidate_id == candidate_id:
                return a
        return None

    def rejections_for(self, candidate_id: str) -> list[Rejection]:
        return [r for r in self.rejections if r.candidate_id == candidate_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "seed": self.seed,
            "cohort_hash": self.cohort_hash,
            "algorithm_version": self.algorithm_version,
            "assignments": [a.to_dict() for a in self.assignments],
            "unplaced": list(self.unplaced),
            "rejections": [r.to_dict() for r in self.rejections],
            "metrics": self.metrics,
            "pins": dict(sorted(self.pins.items())),
            "cohort": self.cohort.to_dict() if self.cohort else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MatchRun:
        return cls(
            run_id=d["run_id"],
            timestamp=d["timestamp"],
            seed=d["seed"],
            cohort_hash=d["cohort_hash"],
            algorithm_version=d.get("algorithm_version", "unknown"),
            assignments=tuple(Assignment.from_dict(x) for x in d.get("assignments", ())),
            unplaced=tuple(d.get("unplaced", ())),
            rejections=tuple(Rejection.from_dict(x) for x in d.get("rejections", ())),
            metrics=dict(d.get("metrics", {})),
            pins=dict(d.get("pins", {})),
            cohort=Cohort.from_dict(d["cohort"]) if d.get("cohort") else None,
        )
