"""Command-line interface.

Owns: argument parsing, file I/O, and printing.

Deliberately does NOT own: any logic. Every command here is a thin wrapper —
if a behavior only exists in this file, it cannot be tested or reused by the
web UI, so it belongs in a module instead.

    generate   make a synthetic cohort
    intake     build a cohort from CSVs (real data path)
    match      run the matcher
    report     cohort metrics
    explain    why one candidate landed where they did
    roster     who is on one team
    fit        score a resume against every team
    shock      re-run with a team's headcount changed
    diff       compare two runs
    export     write a run out as CSV
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .advise import format_advice, rank_teams_for
from .diff import diff_runs, format_diff, shock_capacity
from .generate import generate_cohort
from .matching import match
from .models import Cohort, MatchRun
from .report import explain_candidate, format_metrics, format_roster, team_roster


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, payload: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def _load_cohort(path: str) -> Cohort:
    return Cohort.from_dict(_read_json(path))


def _load_run(path: str) -> MatchRun:
    return MatchRun.from_dict(_read_json(path))


def _warn(problems: list[str], label: str) -> None:
    if problems:
        print(f"\n{len(problems)} intake warning(s) from {label}:", file=sys.stderr)
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)
        print("", file=sys.stderr)


def cmd_generate(args: argparse.Namespace) -> int:
    cohort = generate_cohort(
        n_candidates=args.candidates, n_teams=args.teams, seed=args.seed
    )
    _warn(cohort.validate(), "generated cohort")
    _write_json(args.output, cohort.to_dict())
    print(
        f"Generated {len(cohort.candidates)} candidates across {len(cohort.teams)} teams "
        f"({cohort.total_capacity} slots, seed {args.seed}) -> {args.output}"
    )
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    from .intake import load_cohort_csv

    cohort, warnings = load_cohort_csv(args.candidates_csv, args.teams_csv)
    _warn(warnings, "CSV intake")
    _write_json(args.output, cohort.to_dict())
    print(
        f"Loaded {len(cohort.candidates)} candidates and {len(cohort.teams)} teams "
        f"({cohort.total_capacity} slots) -> {args.output}"
    )
    return 0


def cmd_match(args: argparse.Namespace) -> int:
    cohort = _load_cohort(args.cohort)
    problems = cohort.validate()
    _warn(problems, args.cohort)
    if any("ranked unknown team" in p for p in problems) and not args.force:
        print(
            "Refusing to match: preferences reference teams that do not exist. "
            "Fix the intake, or pass --force to match anyway.",
            file=sys.stderr,
        )
        return 2

    pins: dict[str, str] = {}
    for spec in args.pin or ():
        if "=" not in spec:
            print(f"Bad --pin {spec!r}; expected CANDIDATE_ID=TEAM_ID", file=sys.stderr)
            return 2
        cid, tid = spec.split("=", 1)
        pins[cid.strip()] = tid.strip()

    try:
        run = match(cohort, seed=args.seed, pins=pins)
    except ValueError as exc:
        print(f"Cannot match: {exc}", file=sys.stderr)
        return 2

    _write_json(args.output, run.to_dict())
    print(format_metrics(run))
    if pins:
        print(f"\n{len(pins)} manual override(s) applied: " + ", ".join(
            f"{c} -> {t}" for c, t in sorted(pins.items())
        ))
    print(f"\nRun written to {args.output}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    print(format_metrics(_load_run(args.run)))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    run = _load_run(args.run)
    try:
        record = explain_candidate(run, args.candidate)
    except KeyError:
        print(f"No candidate {args.candidate!r} in this run.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print("=" * 68)
        print(f"WHY {record['name']} ({record['candidate_id']}) LANDED HERE")
        print(f"run {record['run_id']}  cohort {record['cohort_hash'][:16]}...")
        print("=" * 68)
        print()
        print(record["narrative"])
        print()
        print("They ranked: " + ", ".join(record["ranked_teams"]))
    return 0


def cmd_roster(args: argparse.Namespace) -> int:
    run = _load_run(args.run)
    try:
        print(format_roster(team_roster(run, args.team)))
    except KeyError:
        print(f"No team {args.team!r} in this run.", file=sys.stderr)
        return 1
    return 0


def cmd_fit(args: argparse.Namespace) -> int:
    from .intake import candidate_from_resume

    cohort = _load_cohort(args.cohort)
    with open(args.resume, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    result = candidate_from_resume(text, candidate_id="APPLICANT", name=args.name)
    if result.warnings:
        print("Intake notes:", file=sys.stderr)
        for w in result.warnings:
            print(f"  ! {w}", file=sys.stderr)
        print("", file=sys.stderr)

    rows = rank_teams_for(result.candidate, cohort, top_n=args.top)
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        print(format_advice(result.candidate, rows))
    return 0


def cmd_shock(args: argparse.Namespace) -> int:
    cohort = _load_cohort(args.cohort)
    shocked = shock_capacity(cohort, args.team, args.slots)
    run = match(shocked, seed=args.seed)
    _write_json(args.output, run.to_dict())
    before = cohort.team(args.team).capacity
    after = shocked.team(args.team).capacity
    print(
        f"{cohort.team(args.team).name}: {before} -> {after} slots. "
        f"Re-matched -> {args.output}"
    )
    print()
    print(format_metrics(run))
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    print(format_diff(diff_runs(_load_run(args.run_a), _load_run(args.run_b))))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    import csv

    run = _load_run(args.run)
    if run.cohort is None:
        print("Run has no embedded cohort; cannot export names.", file=sys.stderr)
        return 1

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["candidate_id", "name", "assigned_team", "preference_rank", "tier", "fit_score"]
        )
        for a in run.assignments:
            writer.writerow(
                [
                    a.candidate_id,
                    run.cohort.candidate(a.candidate_id).name,
                    run.cohort.team(a.team_id).name,
                    a.preference_rank or "",
                    a.tier,
                    round(a.fit_score, 3),
                ]
            )
    print(f"Exported {len(run.assignments)} assignments -> {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resumatch",
        description="Cohort-to-team placement with explainable, stable matching.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="create a synthetic cohort")
    p.add_argument("--candidates", type=int, default=150)
    p.add_argument("--teams", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("-o", "--output", default="data/cohort.json")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("intake", help="build a cohort from CSV exports")
    p.add_argument("candidates_csv")
    p.add_argument("teams_csv")
    p.add_argument("-o", "--output", default="data/cohort.json")
    p.set_defaults(func=cmd_intake)

    p = sub.add_parser("match", help="run the matcher")
    p.add_argument("cohort")
    p.add_argument("--seed", type=int, default=0, help="tie-break seed, recorded in the run")
    p.add_argument("--force", action="store_true", help="match despite intake errors")
    p.add_argument(
        "--pin",
        action="append",
        metavar="CANDIDATE=TEAM",
        help="manual override, repeatable: seat this candidate on this team first",
    )
    p.add_argument("-o", "--output", default="data/run.json")
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("report", help="cohort metrics for a run")
    p.add_argument("run")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("explain", help="why one candidate landed where they did")
    p.add_argument("run")
    p.add_argument("--candidate", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("roster", help="who is on one team")
    p.add_argument("run")
    p.add_argument("--team", required=True)
    p.set_defaults(func=cmd_roster)

    p = sub.add_parser("fit", help="score a resume against every team")
    p.add_argument("cohort")
    p.add_argument("--resume", required=True, help="path to a plain-text resume")
    p.add_argument("--name", default=None)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fit)

    p = sub.add_parser("shock", help="change a team's headcount and re-match")
    p.add_argument("cohort")
    p.add_argument("--team", required=True)
    p.add_argument("--slots", type=int, required=True, help="delta, e.g. -3 or +2")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("-o", "--output", default="data/run_b.json")
    p.set_defaults(func=cmd_shock)

    p = sub.add_parser("diff", help="compare two runs")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("export", help="write assignments as CSV")
    p.add_argument("run")
    p.add_argument("-o", "--output", default="data/assignments.csv")
    p.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
