# Decisions

The longer arguments behind choices that look arbitrary from the code. Each
entry says what we chose, what we gave up, and what would make us revisit.

---

## 1. Deferred acceptance over score maximization

**Chosen:** candidate-proposing Gale–Shapley deferred acceptance with team
capacities (the Hospital/Residents problem).

**Rejected:** min-cost max-flow / Hungarian assignment maximizing total fit.

The flow formulation is genuinely better at the thing it optimizes. It would
produce a slightly higher sum of fit scores across the cohort. We turned it
down anyway, because the sum is not the product.

The product is the answer to one person asking why they landed where they did.
Under max-flow, that answer is "this global arrangement had the highest total
score", which is unfalsifiable from where the person is standing and reads as a
brush-off. Under DA, the answer is local and checkable: *every team you ranked
higher filled its slots with people it scored above you.* You can verify it
against the run record in about thirty seconds.

Max-flow is also manipulable — a candidate can improve their outcome by
misreporting — so we could not honestly tell a cohort to rank truthfully.

**Revisit if:** the requirement changes from "defend each outcome" to "optimize
a measurable cohort-level objective" and nobody needs per-person explanations.
That would be a different product.

---

## 2. Candidate-proposing, not team-proposing

DA is optimal for whichever side proposes. Candidates propose here.

The program's stated goal is return-offer conversion, and the causal story runs
through the candidate: people placed on teams they wanted are likelier to
accept. Teams are comparatively indifferent between two qualified interns;
interns are not indifferent between two teams.

The gap is also small in practice. Both sides get a stable matching; the
candidate-optimal and team-optimal stable matchings usually differ for a
minority of participants. Given a choice of who absorbs that difference, it
should be the side with more at stake and less power in the process.

**Revisit if:** managers begin gaming their requirements because the candidate
side gets the benefit of the doubt. No sign of that; it would show up as
requirement lists suddenly narrowing.

---

## 3. Team preferences are inferred from a rubric

Managers will not rank 150 people. That is not laziness — it is 150 strangers.

So a team's ranking is computed: required-skill coverage (45%), preferred
skills (20%), interest/domain alignment (20%), and a wishlist bonus (15%) for
candidates the manager named directly.

The weights are a judgment call, not a fitted model, and they should be
presented that way. Required coverage dominates because it is the one signal a
manager states explicitly and would defend out loud in a room.

The wishlist is capped at 15% on purpose. It is real evidence — the manager met
this person — but it encodes who happened to be at a career fair, which
correlates with things we do not want to select on. A named candidate with no
relevant skills must not outrank an unnamed strong fit, and
`test_wishlist_helps_but_does_not_dominate_skills` enforces it.

**Revisit when** there is outcome data. With a cycle of return-offer results,
these weights could be fit rather than guessed. Until then, guessing
transparently beats fitting on nothing.

---

## 4. Every candidate is acceptable to every team

There is no minimum score below which a team refuses someone outright.

This is what makes "nobody gets a hard no" true, and it is why placement rate
is 100% whenever there are enough slots. It also means a team can end up with
someone whose stated skills do not overlap its requirements at all — roughly
15% of placements on a representative run.

Real managers would sometimes refuse. We accept the mismatch for the MVP
because the alternative is worse: an acceptability threshold produces
candidates that *no* team will take, and the tool's answer becomes "we could
not place you", which is precisely the outcome the process is supposed to
prevent. Headcount is also frequently use-it-or-lose-it, so "take someone
imperfect" is often the real-world choice anyway.

The mitigation is visibility, not silence: `report.py` surfaces every
sub-`0.05` placement as a review queue, and the per-candidate narrative says
plainly that the skills do not overlap rather than reciting a row of zeroes at
an intern.

**Revisit if** a pilot shows managers rejecting these placements. The seam is
an `acceptability_threshold` in `scoring.py`; the fallback round would need a
genuine "unplaceable" path with an escalation, not a silent failure.

---

## 5. Seeded hash tie-breaking

Teams rank by score, and coarse rubrics produce ties constantly — managers
bucket people ("strong yes / yes / maybe") far more often than they strictly
rank them. Something has to break those ties.

The only defensible rule is one that is arbitrary, fixed in advance, and
recorded. We hash `(seed, team_id, candidate_id)` and sort on the digest. The
seed is stored in the `MatchRun`, so any result reproduces exactly.

Hashing rather than shuffling matters: a hash key for a given triple does not
depend on how many other candidates exist or what order they arrived in. With a
shuffle, one late-arriving intern would silently reorder everyone else's
tie-breaks and churn the whole match, and nobody could explain why.
`test_adding_a_candidate_does_not_reshuffle_existing_tie_breaks` locks this in.

---

## 6. Fallback round ordering

Candidates whose entire ranked list fills up are placed by fit score into
remaining capacity, processed **fewest-viable-options first** — where "viable"
means teams with room that score them above zero.

The fairness argument: someone whose skills suit three teams loses far more by
going last than someone who fits fifteen. Processing in arbitrary or
alphabetical order would systematically strand narrow-profile candidates in
whatever seat was left.

This is greedy, not optimal. A globally optimal assignment of the leftover
people to the leftover slots is a small assignment problem we could solve
exactly. We didn't, because the fallback group is typically 2–8 people out of
150 and the greedy result is nearly always identical.

**Revisit if** the fallback group regularly exceeds ~15% of a cohort. At that
size the approximation starts to matter, and it also signals something more
important: preference lists are too short, and the fix is upstream in intake.

---

## 7. Stability holds across the fallback round

Worth writing down because it looks like it shouldn't.

Fallback candidates are placed on teams they never ranked, which sounds like it
should create blocking pairs. It doesn't, and the reason is structural: DA only
leaves someone unmatched after *every* team they ranked has rejected them,
which means each of those teams is full of candidates it ranks higher. The
fallback round then fills only slots that are still empty — and a team a
candidate ranked cannot be empty while that candidate is unmatched.

So blocking pairs remain zero. `test_stability_survives_the_fallback_round`
guards it, and `test_blocking_pair_detector_actually_detects` makes sure the
verifier isn't just returning an empty list.

**Manual pins are the genuine exception.** A pinned candidate occupies a seat
regardless of ranking, so a pin *can* create a blocking pair — and the UI
reports it as such rather than excusing it. An override should be visible as a
human decision, not laundered into looking like the algorithm's choice.

---

## 8. A second matcher in JavaScript

`ui/engine.js` reimplements deferred acceptance for the browser.

Two implementations of the same algorithm drift, and this drift would be
invisible — both versions would keep producing plausible, stable-looking
matches that quietly disagree about where real people go. That is a bad thing
to accept on purpose, so it needs justification.

The justification is the interaction. A drag onto a team has to answer *who
does this displace* immediately. Round-tripping to a Python process would mean
a server, deployment, and latency on the one interaction that has to feel
instant — and the reason the override UI exists at all is to make the cost of
an override visible at the moment of the decision.

Two things contain the risk:

1. **Only the mechanism is duplicated.** Team preference orders — the part with
   tunable weights and a seeded SHA-256 tie-break — are computed by
   `scoring.py` and shipped in `ui/data.js`. They never change in response to
   anything the UI can do (capacity edits and pins do not alter how a team
   ranks people). The browser re-runs only the queue loop, which has no
   constants to drift.
2. **`scripts/check_ui_parity.js`** asserts placement-for-placement agreement
   against a Python run. It currently reports 150/150 identical.

**Revisit if** the UI ever needs to change scoring, which would mean weights
living in two places. At that point it needs a real backend.

---

## 9. Keyword resume extraction

`intake/resume.py` matches canonical skills and their aliases against resume
text. No model, no dependencies.

It finds named technologies reliably, which is most of what a resume states
explicitly. It misses implied skills ("rebuilt the checkout flow, cut p99
latency 40%" names no technology) and cannot judge depth — two years of
production Python and one course project both read as `python`.

Accepted, because the match result is far more sensitive to preferences and
capacity than to a marginally better skill list. Moving someone's fit score
from 0.55 to 0.60 rarely changes where they land; whether their first-choice
team has a seat always does.

The signature is the seam. A model-backed extractor returning
`frozenset[canonical_skill]` drops in without touching anything downstream.

**The alias list is the real maintenance burden.** A missing alias is an
invisible scoring failure — `normalize()` returns `None`, the skill is dropped,
and the candidate scores lower for a reason that appears nowhere. Add aliases
generously; a spurious one is merely noise.

---

## 10. Extraction reads skills, never identity

The parser reads skills and domain language. Not names, schools, employers, or
dates. The scoring layer never sees resume text at all — only the extracted
skill set.

`Candidate.name` exists for display and is not read by any scoring path.

This is a constraint, not an omission. School and employer prestige are exactly
the signals that would make fit scores look more "accurate" while encoding who
had access to what. A tool that ranks people for placement and reads their
school is laundering bias behind a fit score, and it would be doing it at
scale, on people at the start of their careers.

Related: preferences are never inferred from resume text, even when it says
"I'd love to join Payments." Guessing what someone wants and then matching them
against the guess is the precise failure this tool exists to prevent.

---

## 11. Generator realism is a correctness concern

`PRESTIGE_ALPHA = 2.6` and `UNIVERSAL_SKILLS` are tuned constants, not
decoration, and both were tuned against observed failures.

At `alpha = 1.6`, one team pulled 39% of the cohort's first choices and the
first-choice rate collapsed to 29% — skewed past realism, which misleads in the
opposite direction from no skew at all. With uniform preferences, nearly
everyone gets their first choice and the metrics read ~99%.

Without `UNIVERSAL_SKILLS`, generated cohorts are siloed by domain and 35% of
placements score exactly `0.00`, because a data candidate has literally nothing
in common with a frontend team. Real programs overlap — Python and SQL appear
on backend, data and infra requirements alike.

A generator that makes the problem look easy produces a demo that is a lie, and
a matcher tuned against it would be tuned against fiction. Current settings
land at 60–75% first choice and 90–99% top three, which is where a real
oversubscribed cohort sits.

---

## 12. Positioning: prior art exists in adjacent domains

The claim "no purpose-built tool exists" holds for *this stage* — one-time
cohort placement. Internal-mobility platforms (Gloat, Fuel50) target existing
employees moving roles years in, which is a different problem with different
data.

But NRMP-style matching software and school-choice assignment systems are well
established and use the same mechanism. Anyone technical evaluating this will
know that.

Lead with it rather than get caught by it. "We are applying a Nobel-winning
mechanism, proven at 40,000-doctor scale, to a stage that is still run on
spreadsheets" is a stronger position than "nobody has done this" — which is
both weaker and, stated broadly, not true.
