"""The shared skill vocabulary. Every intake path normalizes through here.

Owns: canonical skill names, their aliases, their domains, and free-text
extraction.

Deliberately does NOT own: scoring or matching. This module decides what a
word *means*, never what it is worth.

WHY THIS EXISTS
---------------
This is the module that makes the tool portable between organizations, and it
is easy to underestimate. The matcher compares a candidate's skills against a
team's required skills by set intersection. Set intersection is exact. So:

    manager writes  "React"
    resume says     "ReactJS"
    course catalog  "front-end development"

...are three different strings, and without normalization the matcher scores a
genuinely strong fit as 0.00 and places that person somewhere else entirely.
The failure is silent — no error, just a quietly worse match — which makes it
the most dangerous class of bug in this system.

So both sides of the market MUST pass through `normalize()` or
`extract_skills()`. An intake adapter that writes raw user strings into a
Candidate or Team is broken even if it runs.

PORTING THIS TO A NEW ORG
-------------------------
Replace the contents of SKILL_DEFS. The taxonomy is data, not logic: a product
company's vocabulary is not a bank's (murex, fix protocol, kdb) and neither is
a research lab's (matlab, labview, cuda), but nothing downstream changes. Keep
the shape and the domain tags and the rest of the pipeline is untouched.

The set below is a general software org: backend, data/ML, frontend, infra,
systems, mobile, security.
"""

from __future__ import annotations

import re

# Domain tags are the coarse buckets teams advertise and candidates express
# interest in. They are deliberately few — a candidate can meaningfully say
# "I want to do infra"; they cannot meaningfully rank 200 skill tags.
DOMAINS = (
    "backend",
    "data_ml",
    "frontend",
    "infra",
    "systems",
    "mobile",
    "security",
)

# canonical -> (domain, aliases)
# Aliases are lowercase and matched on token boundaries. Add generously: a
# missing alias is an invisible scoring failure, a spurious one is merely noise.
SKILL_DEFS: dict[str, tuple[str, tuple[str, ...]]] = {
    # backend
    "python": ("backend", ("py", "python3")),
    "java": ("backend", ("java8", "java17", "core java")),
    "go": ("backend", ("golang",)),
    "sql": ("backend", ("postgres", "postgresql", "mysql", "rdbms", "relational databases")),
    "rest_apis": ("backend", ("rest", "restful", "api design", "web services", "grpc")),
    "microservices": ("backend", ("service oriented", "distributed systems")),
    # data / ml
    "machine_learning": ("data_ml", ("ml", "deep learning", "neural networks", "pytorch", "tensorflow")),
    "data_engineering": ("data_ml", ("etl", "spark", "airflow", "data pipelines", "hadoop")),
    "statistics": ("data_ml", ("stats", "statistical modeling", "regression", "probability")),
    "pandas": ("data_ml", ("numpy", "scipy", "dataframes")),
    "nlp": ("data_ml", ("natural language processing", "llm", "transformers")),
    "time_series": ("data_ml", ("forecasting", "arima", "anomaly detection")),
    # frontend
    "javascript": ("frontend", ("js", "es6", "ecmascript")),
    "typescript": ("frontend", ("ts",)),
    "react": ("frontend", ("reactjs", "react.js", "next.js", "nextjs")),
    "css": ("frontend", ("scss", "sass", "tailwind", "styling")),
    "accessibility": ("frontend", ("a11y", "wcag", "screen reader")),
    # infra
    "aws": ("infra", ("amazon web services", "ec2", "s3", "lambda")),
    "kubernetes": ("infra", ("k8s", "container orchestration")),
    "docker": ("infra", ("containers", "containerization")),
    "ci_cd": ("infra", ("ci/cd", "jenkins", "github actions", "continuous integration")),
    "terraform": ("infra", ("iac", "infrastructure as code", "cloudformation")),
    # systems
    "cpp": ("systems", ("c++", "cplusplus", "low latency")),
    "rust": ("systems", ("rustlang", "memory safety", "borrow checker")),
    "concurrency": ("systems", ("multithreading", "threads", "parallelism", "async")),
    "performance": ("systems", ("profiling", "optimization", "benchmarking", "latency tuning")),
    # mobile
    "swift": ("mobile", ("ios", "swiftui", "objective-c")),
    "kotlin": ("mobile", ("android", "jetpack compose")),
    "react_native": ("mobile", ("flutter", "cross platform mobile")),
    # security
    "cryptography": ("security", ("crypto", "encryption", "pki", "tls")),
    "threat_modeling": ("security", ("penetration testing", "pentest", "red team", "appsec")),
    "identity": ("security", ("oauth", "saml", "iam", "authentication", "sso")),
}

ALL_SKILLS: tuple[str, ...] = tuple(SKILL_DEFS)

SKILLS_BY_DOMAIN: dict[str, tuple[str, ...]] = {
    domain: tuple(s for s, (d, _) in SKILL_DEFS.items() if d == domain) for domain in DOMAINS
}

# Phrases that signal interest in a domain without naming a specific skill.
# A resume line like "interested in platform reliability" carries real signal
# that no skill keyword would catch.
DOMAIN_PHRASES: dict[str, tuple[str, ...]] = {
    "backend": ("backend", "back-end", "server side", "api development", "platform engineering"),
    "data_ml": ("data science", "machine learning", "analytics", "artificial intelligence", "ai"),
    "frontend": ("frontend", "front-end", "ui engineering", "user interface", "web development"),
    "infra": ("infrastructure", "devops", "site reliability", "sre", "cloud", "platform reliability"),
    "systems": ("systems programming", "low level", "performance engineering", "compilers", "operating systems"),
    "mobile": ("mobile", "ios development", "android development", "app development"),
    "security": ("security", "cybersecurity", "infosec", "privacy", "application security"),
}


def _boundary_pattern(term: str) -> re.Pattern[str]:
    """Match `term` as a standalone token.

    Plain `\\b` fails on the terms that matter most here — "c++" ends in a
    non-word character, so `\\bc\\+\\+\\b` never matches.

    The two lookarounds are deliberately asymmetric:

      behind  excludes . so that "js" inside "node.js" is not read as a
              standalone token
      ahead   allows . so that a skill ending a sentence still matches

    That second point was a real bug: excluding "." on both sides meant
    "deployed on Kubernetes." and "backed by PostgreSQL." matched nothing,
    because the terms were followed by a full stop. Every resume ends its
    sentences, so most of the vocabulary was quietly unreachable — which is
    precisely the silent-miss failure this module exists to prevent.

    Trailing "." is safe to allow: "react" matching inside "react.js" resolves
    to the same canonical skill anyway.
    """
    escaped = re.escape(term)
    return re.compile(rf"(?<![a-z0-9+#.]){escaped}(?![a-z0-9+#])", re.IGNORECASE)


# Longest-first so "machine learning" is consumed before "learning" could be,
# and multi-word aliases always win over their constituent words.
_LOOKUP: list[tuple[re.Pattern[str], str]] = sorted(
    (
        (_boundary_pattern(term), canonical)
        for canonical, (_, aliases) in SKILL_DEFS.items()
        for term in (canonical, canonical.replace("_", " "), *aliases)
    ),
    key=lambda pair: -len(pair[0].pattern),
)

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, (_domain, _aliases) in SKILL_DEFS.items():
    _ALIAS_TO_CANONICAL[_canonical] = _canonical
    _ALIAS_TO_CANONICAL[_canonical.replace("_", " ")] = _canonical
    for _alias in _aliases:
        _ALIAS_TO_CANONICAL[_alias] = _canonical


def normalize(term: str) -> str | None:
    """Map one user-supplied term to its canonical skill, or None if unknown.

    Returning None rather than passing the raw string through is deliberate:
    an unrecognized skill should be visibly dropped (and reported by intake, so
    someone can add the alias) rather than silently written into a Candidate
    where it can never match anything.
    """
    return _ALIAS_TO_CANONICAL.get(term.strip().lower())


def normalize_all(terms) -> tuple[frozenset[str], list[str]]:
    """Normalize a list of terms. Returns (recognized, unrecognized)."""
    recognized: set[str] = set()
    unrecognized: list[str] = []
    for term in terms:
        canonical = normalize(term)
        if canonical:
            recognized.add(canonical)
        elif term.strip():
            unrecognized.append(term.strip())
    return frozenset(recognized), unrecognized


def extract_skills(text: str) -> frozenset[str]:
    """Pull canonical skills out of free text — a resume, a job blurb, a form.

    Keyword-and-alias matching, not semantic understanding. It reliably finds
    named technologies, which is most of what a resume states explicitly, and
    it will miss skills that are only implied by narrative ("built a system
    that scaled to 10M users"). That ceiling is a known and accepted limit of
    the MVP — see docs/DECISIONS.md. The function signature is the seam: swap
    in a model-backed extractor later and nothing downstream changes.
    """
    found: set[str] = set()
    for pattern, canonical in _LOOKUP:
        if pattern.search(text):
            found.add(canonical)
    return frozenset(found)


def extract_interests(text: str, skills: frozenset[str] | None = None) -> frozenset[str]:
    """Infer domain interests from free text, plus the domains of found skills.

    Someone with five backend skills on their resume is interested in backend
    whether or not they wrote the word, so the domains of extracted skills feed
    in automatically. Explicit phrases ("interested in security") are additive.
    """
    lowered = text.lower()
    interests: set[str] = set()
    for domain, phrases in DOMAIN_PHRASES.items():
        if any(_boundary_pattern(p).search(lowered) for p in phrases):
            interests.add(domain)
    for skill in skills or extract_skills(text):
        interests.add(SKILL_DEFS[skill][0])
    return frozenset(interests)


def domain_of(skill: str) -> str:
    return SKILL_DEFS[skill][0]


def describe(skill: str) -> str:
    """Human-facing label for a canonical skill."""
    return skill.replace("_", " ")
