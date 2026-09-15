"""Which teams fit this person? — the single-candidate advisory view.

Owns: scoring one candidate against every open team and explaining the gap.

Deliberately does NOT own: placement. Nothing here assigns anybody. A high
score means "this team wants your skills", not "you will land here" — that
depends on capacity and on who else applied, which only a full match run
knows.

WHY THIS IS SEPARATE FROM MATCHING
----------------------------------
This answers the question a candidate actually has *before* submitting a
ranking: "given what I can do, where would I be strongest?" The secondary
persona — the intern ranking teams somewhat blind — has no visibility into
this today, and ranking blind is what produces the herd behavior where 60% of
a cohort puts the same three famous teams first and most of them lose.

Showing people where they are genuinely strong before they rank is the
cheapest available fix for that, and it improves the match for everyone: more
candidates rank teams that want them, so fewer proposals get rejected.

The honesty constraint: this must never be presented as a prediction. Telling
someone "you're a 92% fit for Payments Core" when Payments Core has 4 slots
and 60 first-choice votes sets up exactly the disappointment the tool exists
to reduce, so `demand_context` carries the competition alongside the fit.
"""

from __future__ import annotations

from typing import Any

from .models import Candidate, Cohort
from .scoring import fit_score
from .taxonomy import describe


def rank_teams_for(
    candidate: Candidate, cohort: Cohort, top_n: int | None = None
) -> list[dict[str, Any]]:
    """Score this candidate against every team, best fit first.

    Includes a gap analysis — which required skills they have and which they
    are missing — because "you scored 0.41" is useless feedback and "you match
    2 of 3 required skills; they also wanted Kubernetes" is actionable.
    """
    first_choice_demand: dict[str, int] = {t.id: 0 for t in cohort.teams}
    for c in cohort.candidates:
        if c.ranked_team_ids:
            first_choice_demand[c.ranked_team_ids[0]] += 1

    rows: list[dict[str, Any]] = []
    for team in cohort.teams:
        score, breakdown = fit_score(candidate, team)
        have = candidate.skills & team.required_skills
        missing = team.required_skills - candidate.skills
        demand = first_choice_demand.get(team.id, 0)
        rows.append(
            {
                "team_id": team.id,
                "team_name": team.name,
                "fit_score": round(score, 3),
                "breakdown": {k: round(v, 3) for k, v in breakdown.items()},
                "required_matched": sorted(describe(s) for s in have),
                "required_missing": sorted(describe(s) for s in missing),
                "preferred_matched": sorted(
                    describe(s) for s in candidate.skills & team.preferred_skills
                ),
                "shared_domains": sorted(candidate.interests & team.domain_tags),
                "on_wishlist": candidate.id in team.wishlist,
                "capacity": team.capacity,
                "demand_context": {
                    "first_choice_demand": demand,
                    "capacity": team.capacity,
                    "ratio": round(demand / team.capacity, 2) if team.capacity else None,
                },
            }
        )

    rows.sort(key=lambda r: (-r["fit_score"], r["team_id"]))
    return rows[:top_n] if top_n else rows


def format_advice(candidate: Candidate, rows: list[dict[str, Any]]) -> str:
    """Render the advisory view for a terminal."""
    out: list[str] = []
    out.append("=" * 68)
    out.append(f"BEST-FIT TEAMS FOR {candidate.name} ({candidate.id})")
    out.append("=" * 68)
    out.append("")
    out.append("  your skills:    " + (", ".join(describe(s) for s in sorted(candidate.skills)) or "(none)"))
    out.append("  your interests: " + (", ".join(sorted(candidate.interests)) or "(none)"))
    out.append("")

    for i, r in enumerate(rows, start=1):
        ratio = r["demand_context"]["ratio"]
        competition = (
            f"{r['demand_context']['first_choice_demand']} first choices / "
            f"{r['capacity']} slots"
            + (f" = {ratio}x" if ratio else "")
        )
        out.append(f"{i}. {r['team_name']}   fit {r['fit_score']:.2f}")
        if r["required_matched"]:
            out.append(f"     strengths they need:  {', '.join(r['required_matched'])}")
        if r["required_missing"]:
            out.append(f"     gaps:                 {', '.join(r['required_missing'])}")
        if r["preferred_matched"]:
            out.append(f"     bonus skills:         {', '.join(r['preferred_matched'])}")
        if r["on_wishlist"]:
            out.append("     the hiring manager named you on their wishlist")
        out.append(f"     competition:          {competition}")
        out.append("")

    out.append(
        "Fit is not a prediction. A high score means a team needs what you have;\n"
        "whether you land there also depends on capacity and who else applies."
    )
    return "\n".join(out)
