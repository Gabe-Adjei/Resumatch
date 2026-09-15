"""Comparing two match runs.

Owns: what changed between run A and run B, and how to phrase it.

Deliberately does NOT own: running the match (matching.py).

WHY THIS IS A HEADLINE FEATURE, NOT A UTILITY
---------------------------------------------
The program manager's single largest time sink is not producing the first
match — it is *redoing* it. A manager loses two slots in week two and the
whole spreadsheet gets reworked by hand, which is where most of the 20-30
hours per cycle actually goes.

Re-running the match is instant, so the expensive part disappears on its own.
What does not disappear is the follow-up question: "so what actually changed?"
Handing someone a fresh 150-row assignment list and asking them to spot the
difference recreates the manual work in a new form. This module answers the
question directly: these four people moved, here is each one's reason, nobody
else was touched.
"""

from __future__ import annotations

from typing import Any

from .models import Cohort, MatchRun, Team


def shock_capacity(cohort: Cohort, team_id: str, delta: int) -> Cohort:
    """Return a copy of the cohort with one team's headcount changed.

    Models the real event: a manager's req gets frozen, or they pick up budget
    for one more. Capacity floors at zero rather than going negative.
    """
    if team_id not in {t.id for t in cohort.teams}:
        raise ValueError(f"unknown team {team_id!r}")

    teams = []
    for t in cohort.teams:
        if t.id == team_id:
            teams.append(
                Team(
                    id=t.id,
                    name=t.name,
                    capacity=max(0, t.capacity + delta),
                    domain_tags=t.domain_tags,
                    required_skills=t.required_skills,
                    preferred_skills=t.preferred_skills,
                    wishlist=t.wishlist,
                )
            )
        else:
            teams.append(t)
    return Cohort(candidates=cohort.candidates, teams=tuple(teams), seed=cohort.seed)


def diff_runs(run_a: MatchRun, run_b: MatchRun) -> dict[str, Any]:
    """What changed from run A to run B.

    A candidate's outcome is compared by preference rank, where lower is
    better and a fallback placement (rank None) is treated as worse than any
    ranked outcome. That ordering is what lets us say "improved" or "worse"
    from the candidate's point of view rather than just "different".
    """
    cohort = run_b.cohort or run_a.cohort
    if cohort is None:
        raise ValueError("neither run embeds a cohort; cannot diff")

    a_by_candidate = {x.candidate_id: x for x in run_a.assignments}
    b_by_candidate = {x.candidate_id: x for x in run_b.assignments}

    def rank_value(assignment) -> float:
        """Lower is better. Unranked/absent sort to the bottom."""
        if assignment is None or assignment.preference_rank is None:
            return float("inf")
        return assignment.preference_rank

    moved: list[dict[str, Any]] = []
    unchanged = 0
    for candidate in cohort.candidates:
        cid = candidate.id
        a = a_by_candidate.get(cid)
        b = b_by_candidate.get(cid)
        a_team = a.team_id if a else None
        b_team = b.team_id if b else None
        if a_team == b_team:
            unchanged += 1
            continue

        before, after = rank_value(a), rank_value(b)
        if after < before:
            direction = "improved"
        elif after > before:
            direction = "worse"
        else:
            direction = "lateral"

        moved.append(
            {
                "candidate_id": cid,
                "name": candidate.name,
                "from_team": cohort.team(a_team).name if a_team else None,
                "to_team": cohort.team(b_team).name if b_team else None,
                "rank_before": a.preference_rank if a else None,
                "rank_after": b.preference_rank if b else None,
                "direction": direction,
            }
        )

    moved.sort(key=lambda m: (m["direction"] != "worse", m["candidate_id"]))

    tracked = (
        "first_choice_pct",
        "top_three_pct",
        "placement_rate_pct",
        "mean_preference_rank",
        "matched_by_fallback",
        "unplaced",
        "blocking_pairs",
    )
    metric_deltas = {}
    for key in tracked:
        before_val = run_a.metrics.get(key)
        after_val = run_b.metrics.get(key)
        if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)):
            metric_deltas[key] = {
                "before": before_val,
                "after": after_val,
                "delta": round(after_val - before_val, 2),
            }

    return {
        "run_a": run_a.run_id,
        "run_b": run_b.run_id,
        "same_inputs": run_a.cohort_hash == run_b.cohort_hash,
        "moved_count": len(moved),
        "unchanged_count": unchanged,
        "improved": sum(1 for m in moved if m["direction"] == "improved"),
        "worse": sum(1 for m in moved if m["direction"] == "worse"),
        "lateral": sum(1 for m in moved if m["direction"] == "lateral"),
        "moved": moved,
        "metric_deltas": metric_deltas,
    }


def format_diff(diff: dict[str, Any]) -> str:
    out: list[str] = []
    out.append("=" * 68)
    out.append(f"DIFF  {diff['run_a']} -> {diff['run_b']}")
    out.append("=" * 68)
    out.append("")
    out.append(
        f"  {diff['moved_count']} candidate(s) moved, "
        f"{diff['unchanged_count']} unaffected"
    )
    out.append(
        f"  {diff['improved']} improved, {diff['worse']} worse, {diff['lateral']} lateral"
    )
    out.append("")

    if diff["moved"]:
        out.append("WHO MOVED")
        for m in diff["moved"]:
            marker = {"worse": "v", "improved": "^", "lateral": "-"}[m["direction"]]
            before = f"#{m['rank_before']}" if m["rank_before"] else "fallback"
            after = f"#{m['rank_after']}" if m["rank_after"] else "fallback"
            out.append(
                f"  {marker} {m['name']:<22} {str(m['from_team'])[:24]:<24} -> "
                f"{str(m['to_team'])[:24]:<24} ({before} -> {after})"
            )
        out.append("")

    out.append("METRICS")
    for key, d in diff["metric_deltas"].items():
        sign = "+" if d["delta"] > 0 else ""
        out.append(f"  {key:<22} {d['before']:>7} -> {d['after']:>7}   ({sign}{d['delta']})")
    return "\n".join(out)
