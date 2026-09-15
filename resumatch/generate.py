"""Synthetic cohort generation.

Owns: producing realistic test cohorts from a seed.

Deliberately does NOT own: anything about the real world. This is one intake
adapter among several (see resumatch/intake/) and nothing downstream knows or
cares that a cohort was synthetic.

THE ONE THING THAT MATTERS HERE
-------------------------------
Popularity skew. If candidate preferences are drawn uniformly at random, the
matching problem becomes trivially easy — almost everyone gets their first
choice, the metrics read ~99%, and the demo is a lie. Real cohorts are not
uniform: a handful of teams (the famous product, the team that presented well
at orientation) collect most of the first-choice votes and run 5-10x
oversubscribed, while several teams get almost no votes at all.

That skew is the entire reason this tool needs to exist. So each team gets a
`prestige` weight, and candidates sample their rankings with probability
proportional to prestige x domain affinity. If you ever see first-choice rates
near 100%, the skew has stopped biting and the generator — not the matcher —
is what to go fix.
"""

from __future__ import annotations

import random

from .models import Candidate, Cohort, Team
from .taxonomy import DOMAINS, SKILLS_BY_DOMAIN

FIRST_NAMES = (
    "Alicia Marcus Priya Devon Sofia Jamal Yuki Elena Omar Hannah Tobias Nia "
    "Raj Clara Andre Mei Lucas Fatima Ivan Sasha Noor Diego Leah Kwame Ingrid "
    "Theo Amara Felix Rosa Dmitri Aisha Caleb Lena Hugo Zara Emeka Sana Victor "
    "Mira Oscar Talia Bruno Naomi Ravi Esme Jonas Kira Paulo Iris Malik"
).split()

LAST_NAMES = (
    "Mora Chen Patel Okafor Rivera Haddad Tanaka Novak Brennan Silva Kowalski "
    "Nguyen Abadi Lindqvist Osei Ferrari Bhatt Mwangi Sorensen Delgado Ivanov "
    "Adeyemi Kaur Volkov Santos Larsen Hassan Duarte Petrov Mensah Ortega "
    "Bakker Rahman Castillo Jensen Aluko Moreau Serrano Kim Fischer"
).split()

# Product areas at a general software org, each mapped to the domains it would
# plausibly hire for. Deliberately generic rather than industry-specific — the
# cohort should read as "a tech division", not as a bank or a named company, so
# the demo does not quietly imply a customer we do not have.
#
# The mapping is not decoration. Drawing a team's domains at random produces
# combinations like "Observability Core — needs css, typescript", which any
# reader with priors about the area immediately clocks as fake. A demo whose
# data is visibly nonsense undermines the result it is trying to show, so team
# names and skill requirements have to agree.
TEAM_AREAS = {
    "Search": ("data_ml", "backend"),
    "Identity": ("security", "backend"),
    "Growth": ("data_ml", "frontend"),
    "Messaging": ("backend", "mobile"),
    "Storage": ("infra", "systems"),
    "Notifications": ("backend", "mobile"),
    "Checkout": ("frontend", "backend"),
    "Media": ("systems", "frontend"),
    "Recommendations": ("data_ml", "backend"),
    "Billing": ("backend", "data_ml"),
    "Observability": ("infra", "systems"),
    "Developer": ("infra", "systems"),
    "Content": ("frontend", "backend"),
    "Commerce": ("backend", "frontend"),
    "Streaming": ("systems", "infra"),
    "Onboarding": ("frontend", "mobile"),
    "Compute": ("infra", "systems"),
    "Payments": ("backend", "security"),
    "Maps": ("data_ml", "mobile"),
    "Accounts": ("security", "backend"),
}

TEAM_PREFIXES = tuple(TEAM_AREAS)

TEAM_SUFFIXES = (
    "Core",
    "Platform",
    "Engineering",
    "Infrastructure",
    "Experience",
    "Services",
    "Tools",
)

# Total slots slightly exceed cohort size: the process is feasible but tight,
# which is what makes the fallback round exercise instead of sitting dead.
CAPACITY_HEADROOM = 1.06

# Shape of the team-popularity distribution. Lower = more extreme skew.
#
# Tuned against what a real cohort looks like: the most-wanted team should draw
# roughly 12-18% of first choices and run 4-6x oversubscribed. At alpha=1.6 one
# team pulled 39% of the cohort and first-choice rate collapsed to 29% — skewed
# past the point of realism, which is just as misleading as no skew at all.
# Raise it toward 3.5 for a gentler cycle, drop it toward 2.0 for a brutal one.
PRESTIGE_ALPHA = 2.6

# How strongly a candidate's own fit pulls their ranking away from pure
# prestige-chasing. At 0 everyone ranks the same famous teams; higher values
# mean candidates self-select toward teams that actually want their skills.
# Real applicants do both — they chase the famous team AND apply where they
# fit — so neither term should dominate completely.
AFFINITY_WEIGHT = 4.0
SKILL_FIT_WEIGHT = 0.8

# Skills that cross domain boundaries. Without these, a generated cohort is
# unrealistically siloed: a data candidate has literally nothing in common with
# a frontend team, so any cross-domain placement scores exactly 0.00 and a
# third of the cohort ends up in the review queue.
#
# Real programs do not look like that. Python is on backend, data and infra
# reqs alike; SQL is on nearly everything. Modelling that overlap is what makes
# the fit scores mean anything.
UNIVERSAL_SKILLS = ("python", "sql", "javascript", "ci_cd", "docker", "rest_apis")
P_CANDIDATE_HAS_UNIVERSAL = 0.75
P_TEAM_WANTS_UNIVERSAL = 0.55


def _weighted_sample(rng: random.Random, options: list[str], weights: list[float], k: int) -> list[str]:
    """Sample k distinct items with probability proportional to weight.

    `random.choices` samples with replacement, which would let a candidate rank
    the same team twice. This draws without replacement instead.
    """
    chosen: list[str] = []
    pool = list(options)
    pool_weights = list(weights)
    for _ in range(min(k, len(pool))):
        total = sum(pool_weights)
        if total <= 0:
            break
        pick = rng.uniform(0, total)
        running = 0.0
        for i, w in enumerate(pool_weights):
            running += w
            if running >= pick:
                chosen.append(pool.pop(i))
                pool_weights.pop(i)
                break
    return chosen


def generate_cohort(
    n_candidates: int = 150,
    n_teams: int = 20,
    seed: int = 42,
) -> Cohort:
    """Build a seeded synthetic cohort. Same seed always yields the same cohort."""
    rng = random.Random(seed)

    # ---- teams -------------------------------------------------------------
    used_names: set[str] = set()
    teams: list[Team] = []
    prestige: dict[str, float] = {}

    slots_remaining = int(n_candidates * CAPACITY_HEADROOM)
    for i in range(n_teams):
        while True:
            prefix = rng.choice(TEAM_PREFIXES)
            name = f"{prefix} {rng.choice(TEAM_SUFFIXES)}"
            if name not in used_names:
                used_names.add(name)
                break

        # Domains come from the team's product area, not from the whole set, so
        # requirements match the name on the card.
        area = TEAM_AREAS[prefix]
        tags = {rng.choice(area)}
        if rng.random() < 0.35:
            tags.add(area[1] if len(area) > 1 else area[0])

        skill_pool = sorted({s for d in tags for s in SKILLS_BY_DOMAIN[d]})
        rng.shuffle(skill_pool)
        required = set(skill_pool[: rng.randint(2, 3)])
        if rng.random() < P_TEAM_WANTS_UNIVERSAL:
            required.add(rng.choice(UNIVERSAL_SKILLS))
        remaining_pool = [s for s in skill_pool if s not in required]
        preferred = frozenset(remaining_pool[: rng.randint(1, 3)])
        required = frozenset(required)

        # Distribute remaining slots so the totals land near the headroom
        # target rather than drifting — the last team should not absorb the
        # rounding error and end up with 40 openings.
        teams_left = n_teams - i
        avg = max(1, round(slots_remaining / teams_left))
        capacity = max(2, min(14, rng.randint(max(2, avg - 3), avg + 3)))
        capacity = min(capacity, max(1, slots_remaining - (teams_left - 1)))
        slots_remaining -= capacity

        team_id = f"T{i + 1:02d}"
        # Pareto-ish: a few teams are far more wanted than the rest. The shape
        # parameter is tuned, not arbitrary — see PRESTIGE_ALPHA.
        prestige[team_id] = round(rng.paretovariate(PRESTIGE_ALPHA), 3)
        teams.append(
            Team(
                id=team_id,
                name=name,
                capacity=capacity,
                domain_tags=frozenset(tags),
                required_skills=required,
                preferred_skills=preferred,
            )
        )

    # ---- candidates --------------------------------------------------------
    candidates: list[Candidate] = []
    # Names must be unique. With 50 first x 40 last names and 150 draws, random
    # pairing collides several times per cohort by the birthday paradox — and a
    # review screen showing the same person moving to two different teams reads
    # as a bug even when the ids are distinct.
    used_person_names: set[str] = set()
    for i in range(n_candidates):
        cid = f"C{i + 1:03d}"
        for _ in range(60):
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in used_person_names:
                break
        else:
            # Exhausted the name space (very large cohorts) — disambiguate.
            name = f"{name} ({cid})"
        used_person_names.add(name)

        domains = [rng.choice(DOMAINS)]
        if rng.random() < 0.45:
            second = rng.choice(DOMAINS)
            if second not in domains:
                domains.append(second)

        skill_pool = sorted({s for d in domains for s in SKILLS_BY_DOMAIN[d]})
        rng.shuffle(skill_pool)
        skills = set(skill_pool[: rng.randint(3, 6)])
        if rng.random() < P_CANDIDATE_HAS_UNIVERSAL:
            skills.update(rng.sample(UNIVERSAL_SKILLS, k=rng.randint(1, 2)))
        skills = frozenset(skills)

        interests = set(domains)
        if rng.random() < 0.25:
            interests.add(rng.choice(DOMAINS))

        candidates.append(
            Candidate(
                id=cid,
                name=name,
                skills=skills,
                interests=frozenset(interests),
                ranked_team_ids=(),  # filled below, once teams exist
            )
        )

    # ---- preference lists --------------------------------------------------
    # Weight = prestige x domain affinity. Prestige is the dominant term, which
    # is what creates the oversubscription pathology; affinity keeps the lists
    # from being identical across the whole cohort.
    ranked: list[Candidate] = []
    for candidate in candidates:
        options = [t.id for t in teams]
        weights = []
        for team in teams:
            affinity = len(candidate.interests & team.domain_tags) / max(1, len(team.domain_tags))
            skill_fit = len(candidate.skills & (team.required_skills | team.preferred_skills))
            weights.append(
                prestige[team.id]
                * (1.0 + AFFINITY_WEIGHT * affinity + SKILL_FIT_WEIGHT * skill_fit)
            )

        list_length = rng.randint(3, 7)
        picks = _weighted_sample(rng, options, weights, list_length)
        ranked.append(
            Candidate(
                id=candidate.id,
                name=candidate.name,
                skills=candidate.skills,
                interests=candidate.interests,
                ranked_team_ids=tuple(picks),
            )
        )

    # ---- manager wishlists -------------------------------------------------
    # Managers name people they actually met, so wishlists skew toward genuine
    # strong fits but are not simply "the top 5 by score" — that would make the
    # wishlist signal redundant with the skill score and teach us nothing.
    from .scoring import fit_score

    final_teams: list[Team] = []
    for team in teams:
        scored = sorted(
            ranked,
            key=lambda c, t=team: -fit_score(c, t)[0],
        )
        shortlist = scored[:20]
        picked = rng.sample(shortlist, k=min(5, len(shortlist)))
        final_teams.append(
            Team(
                id=team.id,
                name=team.name,
                capacity=team.capacity,
                domain_tags=team.domain_tags,
                required_skills=team.required_skills,
                preferred_skills=team.preferred_skills,
                wishlist=tuple(c.id for c in picked),
            )
        )

    return Cohort(candidates=tuple(ranked), teams=tuple(final_teams), seed=seed)
