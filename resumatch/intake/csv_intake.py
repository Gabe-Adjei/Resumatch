"""Spreadsheet / form-export -> Cohort.

Owns: reading the CSV shapes a recruiting team already has — a Google Form
export of intern preferences, and a hiring-manager wishlist sheet.

Deliberately does NOT own: the skill vocabulary (taxonomy.py).

This is the adapter that matters for a real pilot, because the data already
exists in spreadsheets. Nobody is going to re-enter 150 interns into a new
system, and asking them to is how a pilot dies.

EXPECTED COLUMNS
----------------
candidates.csv
    id            required, unique
    name          required
    skills        semicolon- or comma-separated free text
    interests     optional; domain words. Inferred from skills when blank
    preferences   semicolon- or comma-separated TEAM IDS, best first

teams.csv
    id                required, unique
    name              required
    capacity          required, integer
    domain_tags       semicolon- or comma-separated
    required_skills   semicolon- or comma-separated
    preferred_skills  optional
    wishlist          optional; candidate IDS, strongest first

Header matching is case-insensitive and tolerant of spaces and underscores,
because real exports arrive with headers like "Required Skills" and
"open_slots". Unknown columns are ignored rather than fatal — a form export
carries timestamps and email addresses that are none of this tool's business.
"""

from __future__ import annotations

import csv
from typing import Any, Iterable

from ..models import Candidate, Cohort, Team
from ..taxonomy import DOMAINS, extract_interests, normalize_all

# Alternate header spellings seen in real exports, mapped to our field names.
_ALIASES = {
    "candidate_id": "id",
    "student_id": "id",
    "full_name": "name",
    "team_id": "id",
    "team_name": "name",
    "open_slots": "capacity",
    "openings": "capacity",
    "headcount": "capacity",
    "slots": "capacity",
    "ranked_teams": "preferences",
    "team_preferences": "preferences",
    "ranking": "preferences",
    "must_have": "required_skills",
    "required": "required_skills",
    "nice_to_have": "preferred_skills",
    "preferred": "preferred_skills",
    "domains": "domain_tags",
    "domain": "domain_tags",
    "manager_wishlist": "wishlist",
}


def _key(header: str) -> str:
    normalized = header.strip().lower().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(normalized, normalized)


def _row(raw: dict[str, Any]) -> dict[str, str]:
    return {_key(k): (v or "").strip() for k, v in raw.items() if k}


def _split(value: str) -> list[str]:
    """Split a multi-value cell on either separator.

    Semicolons first: skills legitimately contain commas ("Pricing, Risk"), and
    a semicolon-delimited sheet is the safer convention to tell people to use.
    """
    if not value:
        return []
    parts = value.split(";") if ";" in value else value.split(",")
    return [p.strip() for p in parts if p.strip()]


def load_candidates_csv(path: str) -> tuple[list[Candidate], list[str]]:
    """Read candidates. Returns (candidates, warnings)."""
    candidates: list[Candidate] = []
    warnings: list[str] = []
    unknown_terms: set[str] = set()

    with open(path, newline="", encoding="utf-8-sig") as fh:
        for line_no, raw in enumerate(csv.DictReader(fh), start=2):
            row = _row(raw)
            if not row.get("id"):
                warnings.append(f"{path}:{line_no} skipped — no id")
                continue

            skills, unknown = normalize_all(_split(row.get("skills", "")))
            unknown_terms.update(unknown)

            declared = [d.lower() for d in _split(row.get("interests", ""))]
            interests = frozenset(d for d in declared if d in DOMAINS)
            if not interests:
                # Fall back to inferring from the raw text of their skills.
                interests = extract_interests(row.get("skills", ""), skills)

            candidates.append(
                Candidate(
                    id=row["id"],
                    name=row.get("name") or row["id"],
                    skills=skills,
                    interests=interests,
                    ranked_team_ids=tuple(_split(row.get("preferences", ""))),
                )
            )

    if unknown_terms:
        warnings.append(
            f"{len(unknown_terms)} unrecognized skill term(s) dropped: "
            + ", ".join(sorted(unknown_terms)[:12])
            + (" ..." if len(unknown_terms) > 12 else "")
            + " — add them to taxonomy.py so they count"
        )
    return candidates, warnings


def load_teams_csv(path: str) -> tuple[list[Team], list[str]]:
    """Read teams. Returns (teams, warnings)."""
    teams: list[Team] = []
    warnings: list[str] = []
    unknown_terms: set[str] = set()

    with open(path, newline="", encoding="utf-8-sig") as fh:
        for line_no, raw in enumerate(csv.DictReader(fh), start=2):
            row = _row(raw)
            if not row.get("id"):
                warnings.append(f"{path}:{line_no} skipped — no id")
                continue
            try:
                capacity = int(float(row.get("capacity") or 0))
            except ValueError:
                warnings.append(
                    f"{path}:{line_no} team {row['id']} has unreadable capacity "
                    f"{row.get('capacity')!r} — treated as 0"
                )
                capacity = 0

            required, unknown_r = normalize_all(_split(row.get("required_skills", "")))
            preferred, unknown_p = normalize_all(_split(row.get("preferred_skills", "")))
            unknown_terms.update(unknown_r)
            unknown_terms.update(unknown_p)

            tags = frozenset(
                d.lower() for d in _split(row.get("domain_tags", "")) if d.lower() in DOMAINS
            )
            if not required and not preferred:
                warnings.append(
                    f"team {row['id']} lists no recognized skills — it will score every "
                    f"candidate identically and fill on tie-break alone"
                )

            teams.append(
                Team(
                    id=row["id"],
                    name=row.get("name") or row["id"],
                    capacity=capacity,
                    domain_tags=tags,
                    required_skills=required,
                    preferred_skills=preferred,
                    wishlist=tuple(_split(row.get("wishlist", ""))),
                )
            )

    if unknown_terms:
        warnings.append(
            f"{len(unknown_terms)} unrecognized skill term(s) dropped from team "
            f"requirements: " + ", ".join(sorted(unknown_terms)[:12])
            + (" ..." if len(unknown_terms) > 12 else "")
        )
    return teams, warnings


def load_cohort_csv(candidates_path: str, teams_path: str) -> tuple[Cohort, list[str]]:
    """Build a full Cohort from two CSVs, with validation warnings surfaced.

    Validation runs here rather than at match time so a typo'd team id in a
    preference column is caught while someone is still looking at the intake
    step, not after a match has been distributed.
    """
    candidates, cand_warnings = load_candidates_csv(candidates_path)
    teams, team_warnings = load_teams_csv(teams_path)
    cohort = Cohort(candidates=tuple(candidates), teams=tuple(teams))
    return cohort, [*cand_warnings, *team_warnings, *cohort.validate()]


def write_candidates_csv(path: str, candidates: Iterable[Candidate]) -> None:
    """Round-trip helper: export candidates back to the CSV shape above."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "name", "skills", "interests", "preferences"])
        for c in candidates:
            writer.writerow(
                [
                    c.id,
                    c.name,
                    ";".join(sorted(c.skills)),
                    ";".join(sorted(c.interests)),
                    ";".join(c.ranked_team_ids),
                ]
            )


def write_teams_csv(path: str, teams: Iterable[Team]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["id", "name", "capacity", "domain_tags", "required_skills", "preferred_skills", "wishlist"]
        )
        for t in teams:
            writer.writerow(
                [
                    t.id,
                    t.name,
                    t.capacity,
                    ";".join(sorted(t.domain_tags)),
                    ";".join(sorted(t.required_skills)),
                    ";".join(sorted(t.preferred_skills)),
                    ";".join(t.wishlist),
                ]
            )
