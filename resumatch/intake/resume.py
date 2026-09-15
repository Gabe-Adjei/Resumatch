"""Resume text -> Candidate.

Owns: extracting a structured candidate profile from unstructured resume text.

Deliberately does NOT own: the skill vocabulary (taxonomy.py) or any judgment
about whether a candidate is good (scoring.py).

WHAT THIS DOES AND DOES NOT DO
------------------------------
It finds named technologies and domain language. Resumes state their concrete
skills explicitly far more often than not, so keyword-and-alias extraction
over a curated taxonomy recovers most of the usable signal at zero
infrastructure cost.

It will miss skills that are only implied ("rebuilt the checkout flow, cutting
p99 latency by 40%" names no technology). It cannot judge depth — two years of
production Python and one course project both read as `python`. It does not
attempt seniority, quality, or authenticity.

Those are real limits and they are accepted for the MVP, because the matching
result is far more sensitive to *preferences and capacity* than to a marginally
better skill list. The function signature is the seam: swapping in a
model-backed extractor later changes this file and nothing else.

A NOTE ON FAIRNESS
------------------
Extraction reads skills and domain language only. It does not read names,
schools, addresses, dates, or any other field, and the scoring layer never
sees the resume text — only the extracted skill set. Keep it that way. The
moment school or employer prestige enters the profile, the tool stops being a
fit matcher and starts laundering bias behind a fit score.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from ..models import Candidate
from ..taxonomy import describe, extract_interests, extract_skills


@dataclass
class IntakeResult:
    """A parsed candidate plus everything a human should know about the parse.

    `warnings` exists because a silent bad parse is the worst outcome here:
    the match still runs and still looks defensible, it is just quietly wrong
    for that person.
    """

    candidate: Candidate
    matched_skills: tuple[str, ...] = ()
    inferred_interests: tuple[str, ...] = ()
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"{self.candidate.name} ({self.candidate.id})"]
        lines.append(
            "  skills:    "
            + (", ".join(describe(s) for s in sorted(self.matched_skills)) or "(none found)")
        )
        lines.append(
            "  interests: "
            + (", ".join(sorted(self.inferred_interests)) or "(none inferred)")
        )
        for w in self.warnings:
            lines.append(f"  ! {w}")
        return "\n".join(lines)


# A resume's own header line is the most reliable name source, and it is almost
# always the first non-empty line that is short and not contact details.
_CONTACT_HINT = re.compile(r"[@\d]|https?://|linkedin|github", re.IGNORECASE)


def guess_name(text: str, fallback: str = "Unknown Candidate") -> str:
    """Best-effort name from the top of a resume.

    Used only for display. Nothing in scoring or matching reads it — see the
    fairness note above.
    """
    for line in text.splitlines()[:6]:
        stripped = line.strip()
        if not stripped or len(stripped) > 48:
            continue
        if _CONTACT_HINT.search(stripped):
            continue
        words = stripped.split()
        if 1 < len(words) <= 4 and all(w[:1].isalpha() for w in words):
            return stripped.title() if stripped.isupper() else stripped
    return fallback


def candidate_from_resume(
    text: str,
    candidate_id: str,
    name: str | None = None,
    ranked_team_ids: tuple[str, ...] = (),
) -> IntakeResult:
    """Parse one resume into a Candidate.

    `ranked_team_ids` stays a separate argument on purpose. Preferences come
    from the candidate telling us what they want, never from inferring it out
    of a resume. Guessing someone's preferences and then matching them against
    that guess is how a tool quietly stops honoring the thing it promised to
    honor.
    """
    skills = extract_skills(text)
    interests = extract_interests(text, skills)

    warnings: list[str] = []
    if len(text.strip()) < 120:
        warnings.append("resume text is very short — check the file extracted correctly")
    if not skills:
        warnings.append(
            "no recognized skills found — this candidate will score 0.00 against every "
            "team and land via the fallback round. Extend taxonomy.py or check the input."
        )
    elif len(skills) < 3:
        warnings.append(
            f"only {len(skills)} skill(s) recognized — matching will be weakly informed"
        )
    if not ranked_team_ids:
        warnings.append(
            "no ranked team preferences supplied — this candidate can only be placed by "
            "the fallback round, not by their own choices"
        )

    candidate = Candidate(
        id=candidate_id,
        name=name or guess_name(text, fallback=candidate_id),
        skills=skills,
        interests=interests,
        ranked_team_ids=tuple(ranked_team_ids),
    )
    return IntakeResult(
        candidate=candidate,
        matched_skills=tuple(sorted(skills)),
        inferred_interests=tuple(sorted(interests)),
        warnings=warnings,
    )


def candidates_from_directory(
    directory: str, id_prefix: str = "C", extensions: tuple[str, ...] = (".txt", ".md")
) -> list[IntakeResult]:
    """Parse every resume in a folder.

    Plain text only. PDF and DOCX extraction needs a third-party library, and
    this package is deliberately dependency-free — pipe them through your own
    converter first (`pdftotext`, `textutil`) and point this at the output.
    """
    results: list[IntakeResult] = []
    names = sorted(
        f for f in os.listdir(directory) if f.lower().endswith(extensions)
    )
    for i, filename in enumerate(names, start=1):
        path = os.path.join(directory, filename)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        result = candidate_from_resume(
            text,
            candidate_id=f"{id_prefix}{i:03d}",
            name=guess_name(text, fallback=os.path.splitext(filename)[0]),
        )
        result.warnings.insert(0, f"source: {filename}")
        results.append(result)
    return results
