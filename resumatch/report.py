"""Turning a MatchRun into things a human can act on.

Owns: cohort metrics, per-candidate explanations, team rosters, and the
plain-text rendering of each.

Deliberately does NOT own: any matching decision. Nothing here may change an
assignment — if a number looks wrong, the fix belongs in matching.py or
scoring.py, never in the phrasing.

Two audiences, two outputs:
  - the program manager needs aggregate numbers she can take to leadership
  - an intern or hiring manager pushing back needs one specific answer about
    one specific person, in words, backed by the run record

The per-candidate record is structured data first and prose second. Prose that
cannot be traced back to a field is prose that will eventually be wrong.
"""

from __future__ import annotations

from typing import Any

from .models import (
    TIER_FALLBACK,
    TIER_RANKED,
    TIER_TOP_CHOICE,
    TIER_UNPLACED,
    Cohort,
    MatchRun,
)


# A placement below this fit score got its slot on tie-break rather than on any
# stated skill or interest overlap. That is legitimate — the team had headcount
# and the candidate ranked them — but it is the one category of result a human
# should look at before the match goes out, so it surfaces as a review queue
# rather than staying buried in a 150-row spreadsheet.
#
# Set just above zero on purpose. The score distribution is bimodal, not a
# gradient: on a representative run, 23 placements sit at exactly 0.00 and the
# next one up is at 0.05, with the median at 0.60. Either a candidate overlaps
# with the team's domain or they do not. So the honest cut is "no overlap at
# all", and a threshold in the middle of the empty region would only invent a
# false sense of precision about where the line sits.
LOW_FIT_THRESHOLD = 0.05


def _pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def compute_metrics(
    run: MatchRun,
    cohort: Cohort,
    blocking: list[tuple[str, str]],
    da_placed: set[str],
) -> dict[str, Any]:
    """Cohort-level numbers, including the ones that go to leadership.

    `blocking_pairs` is the headline: zero means no intern and no team would
    both rather have each other than what they got. It is the difference
    between "we think this is fair" and "no better arrangement exists that
    both sides would agree to."
    """
    size = len(cohort.candidates)
    ranked = [a for a in run.assignments if a.preference_rank is not None]
    histogram: dict[int, int] = {}
    for a in ranked:
        histogram[a.preference_rank] = histogram.get(a.preference_rank, 0) + 1

    first_choice = histogram.get(1, 0)
    top_three = sum(n for rank, n in histogram.items() if rank <= 3)
    fallback = sum(1 for a in run.assignments if a.tier == TIER_FALLBACK)

    # Demand vs. capacity: which teams everybody wanted. This is the number
    # that explains why the match looks the way it does, and the one a manager
    # asks about first ("why didn't I get my pick?").
    demand: dict[str, int] = {t.id: 0 for t in cohort.teams}
    for c in cohort.candidates:
        if c.ranked_team_ids:
            demand[c.ranked_team_ids[0]] += 1
    oversubscribed = sorted(
        (
            {
                "team_id": t.id,
                "team_name": t.name,
                "first_choice_demand": demand[t.id],
                "capacity": t.capacity,
                "ratio": round(demand[t.id] / t.capacity, 2) if t.capacity else None,
            }
            for t in cohort.teams
        ),
        key=lambda d: -(d["ratio"] or 0),
    )[:5]

    low_fit = sorted(
        (a for a in run.assignments if a.fit_score < LOW_FIT_THRESHOLD),
        key=lambda a: (a.fit_score, a.candidate_id),
    )

    filled = len(run.assignments)
    return {
        "low_fit_threshold": LOW_FIT_THRESHOLD,
        "low_fit_count": len(low_fit),
        "low_fit_review": [
            {
                "candidate_id": a.candidate_id,
                "name": cohort.candidate(a.candidate_id).name,
                "team_name": cohort.team(a.team_id).name,
                "fit_score": round(a.fit_score, 3),
                "tier": a.tier,
            }
            for a in low_fit[:10]
        ],
        "cohort_size": size,
        "team_count": len(cohort.teams),
        "total_slots": cohort.total_capacity,
        "slots_filled": filled,
        "slots_open": cohort.total_capacity - filled,
        "placed": filled,
        "placement_rate_pct": _pct(filled, size),
        "unplaced": len(run.unplaced),
        "first_choice": first_choice,
        "first_choice_pct": _pct(first_choice, size),
        "top_three": top_three,
        "top_three_pct": _pct(top_three, size),
        "mean_preference_rank": (
            round(sum(a.preference_rank for a in ranked) / len(ranked), 2) if ranked else None
        ),
        "rank_histogram": {str(k): histogram[k] for k in sorted(histogram)},
        "matched_by_preference": len(da_placed),
        "matched_by_fallback": fallback,
        "blocking_pairs": len(blocking),
        "blocking_pair_examples": [list(p) for p in blocking[:5]],
        "total_rejections": len(run.rejections),
        "most_oversubscribed": oversubscribed,
    }


def explain_candidate(run: MatchRun, candidate_id: str) -> dict[str, Any]:
    """The full answer to "why did I land here?" for one person.

    Structured fields plus a rendered narrative. Every clause in the narrative
    maps to a field above it, so anyone can check the wording against the run
    record rather than trusting it.
    """
    if run.cohort is None:
        raise ValueError("run has no embedded cohort; cannot explain")

    cohort = run.cohort
    candidate = cohort.candidate(candidate_id)
    assignment = run.assignment_for(candidate_id)
    rejections = sorted(
        run.rejections_for(candidate_id),
        key=lambda r: candidate.ranked_team_ids.index(r.team_id)
        if r.team_id in candidate.ranked_team_ids
        else 999,
    )

    ranked_names = [cohort.team(t).name for t in candidate.ranked_team_ids]
    turned_down = [
        {
            "team_id": r.team_id,
            "team_name": cohort.team(r.team_id).name,
            "your_score": round(r.candidate_score, 3),
            "team_cutoff": None if r.cutoff_score is None else round(r.cutoff_score, 3),
            "candidates_ranked_above_you": r.held_above,
        }
        for r in rejections
    ]

    record: dict[str, Any] = {
        "candidate_id": candidate_id,
        "name": candidate.name,
        "run_id": run.run_id,
        "cohort_hash": run.cohort_hash,
        "ranked_teams": ranked_names,
        "assigned_team_id": assignment.team_id if assignment else None,
        "assigned_team_name": cohort.team(assignment.team_id).name if assignment else None,
        "preference_rank": assignment.preference_rank if assignment else None,
        "tier": assignment.tier if assignment else TIER_UNPLACED,
        "fit_score": round(assignment.fit_score, 3) if assignment else None,
        "fit_breakdown": assignment.fit_breakdown if assignment else {},
        "turned_down_by": turned_down,
    }
    record["narrative"] = _narrate(record)
    return record


def _narrate(rec: dict[str, Any]) -> str:
    """Render the structured explanation as plain English.

    Deliberately avoids hedging language. The candidate is owed a direct
    account, and every claim here is backed by a field in `rec`.
    """
    name = rec["name"]
    tier = rec["tier"]
    team = rec["assigned_team_name"]
    lines: list[str] = []

    if tier == TIER_TOP_CHOICE:
        lines.append(f"{name} was matched to {team} — their first choice.")
    elif tier == TIER_RANKED:
        rank = rec["preference_rank"]
        lines.append(f"{name} was matched to {team}, their #{rank} choice.")
    elif tier == TIER_FALLBACK:
        count = len(rec["ranked_teams"])
        lines.append(
            f"{name} was placed on {team}. None of the {count} team(s) they ranked had a "
            f"slot left once every team had filled its headcount."
        )
    else:
        lines.append(
            f"{name} could not be placed: every team was at capacity. "
            f"This means the cohort is larger than total open headcount."
        )

    if rec["turned_down_by"]:
        lines.append("")
        lines.append("Teams ranked higher that could not take them:")
        for t in rec["turned_down_by"]:
            cutoff = t["team_cutoff"]
            detail = (
                f"fit {t['your_score']:.2f} vs. a cutoff of {cutoff:.2f}"
                if cutoff is not None
                else f"fit {t['your_score']:.2f}"
            )
            lines.append(
                f"  - {t['team_name']}: filled its slots with "
                f"{t['candidates_ranked_above_you']} candidate(s) it scored above them "
                f"({detail})."
            )

    if rec["fit_breakdown"]:
        b = rec["fit_breakdown"]
        lines.append("")
        if not rec["fit_score"]:
            # Be direct about this rather than reciting a row of zeroes. It
            # happens legitimately — the team had headcount left and this
            # candidate ranked them — but a recruiter forwarding "0% of
            # required skills, 0% interest alignment" to an intern is handing
            # them an insult instead of an explanation.
            lines.append(
                f"On paper their skills do not overlap with {team}'s stated requirements. "
                f"They landed there because they ranked it and it still had headcount when "
                f"their higher choices filled. Worth a conversation with the manager before "
                f"this one is final."
            )
        else:
            parts = [
                f"{b.get('required_coverage', 0):.0%} of required skills",
                f"{b.get('preferred_overlap', 0):.0%} of preferred skills",
                f"{b.get('interest_alignment', 0):.0%} interest alignment",
            ]
            if b.get("wishlist_bonus"):
                parts.append("named on the manager's wishlist")
            lines.append(
                f"Fit with {team}: " + ", ".join(parts) + f" (score {rec['fit_score']:.2f})."
            )

    if tier in (TIER_TOP_CHOICE, TIER_RANKED, TIER_FALLBACK):
        lines.append("")
        lines.append(
            "No team they ranked above this one would have taken them over someone it "
            "actually placed. That is what makes this result stable."
        )

    return "\n".join(lines)


def team_roster(run: MatchRun, team_id: str) -> dict[str, Any]:
    """Who ended up on one team, and how each of them got there.

    Exists because "wait, who's on my team again?" is a recurring email thread
    in the manual process, and answering it should cost nobody any time.
    """
    if run.cohort is None:
        raise ValueError("run has no embedded cohort; cannot build roster")

    cohort = run.cohort
    team = cohort.team(team_id)
    members = [a for a in run.assignments if a.team_id == team_id]
    members.sort(key=lambda a: (-a.fit_score, a.candidate_id))

    return {
        "team_id": team_id,
        "team_name": team.name,
        "capacity": team.capacity,
        "filled": len(members),
        "open_slots": team.capacity - len(members),
        "wishlist_hits": [
            cohort.candidate(a.candidate_id).name
            for a in members
            if a.candidate_id in team.wishlist
        ],
        "members": [
            {
                "candidate_id": a.candidate_id,
                "name": cohort.candidate(a.candidate_id).name,
                "fit_score": round(a.fit_score, 3),
                "tier": a.tier,
                "their_preference_rank": a.preference_rank,
            }
            for a in members
        ],
    }


def format_metrics(run: MatchRun) -> str:
    """Human-readable cohort summary for the terminal."""
    m = run.metrics
    out: list[str] = []
    out.append("=" * 68)
    out.append(f"MATCH RUN {run.run_id}   {run.timestamp}")
    out.append(f"algorithm {run.algorithm_version}   seed {run.seed}")
    out.append(f"cohort    {run.cohort_hash[:16]}...")
    out.append("=" * 68)
    out.append("")
    out.append(
        f"  {m['cohort_size']} candidates -> {m['team_count']} teams "
        f"({m['total_slots']} slots)"
    )
    out.append("")
    out.append("PLACEMENT")
    out.append(
        f"  placed                {m['placed']:>4}  ({m['placement_rate_pct']}%)"
    )
    out.append(f"  first choice          {m['first_choice']:>4}  ({m['first_choice_pct']}%)")
    out.append(f"  top three             {m['top_three']:>4}  ({m['top_three_pct']}%)")
    out.append(f"  mean preference rank  {m['mean_preference_rank']:>4}")
    out.append(f"  placed via fallback   {m['matched_by_fallback']:>4}")
    out.append(f"  unplaced              {m['unplaced']:>4}")
    out.append(f"  slots left open       {m['slots_open']:>4}")
    out.append("")
    out.append("PREFERENCE RANK ACHIEVED")
    hist = m["rank_histogram"]
    peak = max(hist.values()) if hist else 1
    for rank in sorted(hist, key=int):
        count = hist[rank]
        bar = "#" * max(1, round(40 * count / peak))
        out.append(f"  choice #{rank:<3} {count:>4}  {bar}")
    if m["matched_by_fallback"]:
        count = m["matched_by_fallback"]
        bar = "." * max(1, round(40 * count / peak))
        out.append(f"  fallback   {count:>4}  {bar}")
    out.append("")
    out.append("INTEGRITY")
    blocking = m["blocking_pairs"]
    verdict = "STABLE" if blocking == 0 else "UNSTABLE"
    out.append(f"  blocking pairs        {blocking:>4}  <- {verdict}")
    if blocking:
        for pair in m["blocking_pair_examples"]:
            out.append(f"      {pair[0]} would swap to {pair[1]}")
    else:
        out.append(
            "  No candidate and team would both rather have each other than what"
        )
        out.append("  they were assigned. Every outcome is individually defensible.")
    out.append(f"  rejections recorded   {m['total_rejections']:>4}")
    out.append("")

    if m.get("low_fit_count"):
        out.append(
            f"NEEDS A HUMAN LOOK ({m['low_fit_count']} placement(s) below "
            f"{m['low_fit_threshold']:.2f} fit)"
        )
        out.append("  These got their slot on tie-break, not on stated skill overlap.")
        for r in m["low_fit_review"]:
            out.append(f"  {r['name']:<24} -> {r['team_name'][:28]:<28} fit {r['fit_score']:.2f}")
        if m["low_fit_count"] > len(m["low_fit_review"]):
            out.append(f"  ... and {m['low_fit_count'] - len(m['low_fit_review'])} more")
        out.append("")

    out.append("MOST OVERSUBSCRIBED (first choices per open slot)")
    for d in m["most_oversubscribed"]:
        out.append(
            f"  {d['team_name'][:34]:<34} {d['first_choice_demand']:>3} want / "
            f"{d['capacity']:>2} slots  = {d['ratio']}x"
        )
    return "\n".join(out)


def format_roster(roster: dict[str, Any]) -> str:
    out: list[str] = []
    out.append(f"{roster['team_name']}  ({roster['filled']}/{roster['capacity']} filled)")
    out.append("-" * 68)
    for m in roster["members"]:
        rank = (
            f"their #{m['their_preference_rank']} choice"
            if m["their_preference_rank"]
            else "fallback placement"
        )
        out.append(f"  {m['name']:<24} fit {m['fit_score']:.2f}   {rank}")
    if roster["open_slots"]:
        out.append(f"  ({roster['open_slots']} slot(s) still open)")
    if roster["wishlist_hits"]:
        out.append("")
        out.append("  From your wishlist: " + ", ".join(roster["wishlist_hits"]))
    return "\n".join(out)
