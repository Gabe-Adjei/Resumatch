# Resumatch

Sorts a cohort of interns or new grads into open team slots, using what
candidates want and what hiring managers need — and produces a defensible
answer for every single person about why they landed where they did.

No install step. Python 3.11+, standard library only. There is no
`requirements.txt` and you do not need one.

```bash
python3 -m unittest discover tests            # 53 tests, ~0.3s
python3 -m resumatch generate --seed 42 -o data/cohort.json
python3 -m resumatch match data/cohort.json -o data/run.json
python3 -m resumatch report data/run.json
```

---

## 1. The problem

A tech division runs ~150 interns through ~20 teams with open headcount, every
cycle, on a two-week clock. Today that happens in a spreadsheet.

The program manager who owns it is working from three disconnected sources: an
intern preference form, a hiring-manager wishlist doc, and the HR headcount
system. Reconciling them by hand costs 20–30 hours a cycle — and most of that
is not the *first* match. It is redoing the match when a manager's headcount
shifts in week two.

Three things go wrong, and they are the three things this tool exists to fix:

1. **Candidate preference quietly loses to convenience.** It is faster to slot
   someone into whatever team has a seat than to honor their ranked list.
2. **No one can explain an outcome.** When an intern or a manager pushes back,
   there is no answer beyond "that's how it worked out."
3. **Every headcount change restarts the whole thing.** The re-work is manual,
   so it gets rationed, so the result drifts further from what anyone asked for.

The tool has to beat a spreadsheet on all three, not just produce assignments.

---

## 2. Why deferred acceptance

**Read this section before changing anything in `matching.py`.**

This is the Hospital/Residents problem — two sides with preferences, one side
with capacity limits. It was solved in 1962 by Gale and Shapley, and Roth won a
Nobel for it in 2012. It is the mechanism behind the US medical residency
match, which places ~40,000 doctors a year.

We use **candidate-proposing deferred acceptance**. It gives three properties:

### Stability — this is the audit trail

A stable matching contains no *blocking pair*: no (candidate, team) who would
both rather have each other than what they got.

That is not an abstraction, it is the product. When an intern asks "why am I
not on Payments?", the answer is mechanical and checkable:

> Every team you ranked above this one filled its slots with candidates it
> scored higher than you.

`find_blocking_pairs()` verifies this on every run and the count is printed in
the report. Zero is the claim. Nothing else in this codebase earns the word
"defensible."

### Candidate-optimality

Among *all* stable matchings, DA with candidates proposing produces the one
that is simultaneously best for every candidate. This maps directly to the
retention goal: people who get a team they wanted are likelier to take the
return offer.

### Strategy-proofness

Ranking honestly is optimal for candidates — there is no ordering they could
submit that does better than their true preferences. This lets the program tell
a cohort "rank truthfully, it can only help you" and have that be *true*.

**It holds only under one condition, and that condition is fragile.** See §3.

### What we rejected

Maximizing total fit score with min-cost max-flow or the Hungarian algorithm.
It gets a marginally higher aggregate score and it cannot explain a single
individual outcome, because "this arrangement has the best global sum" is not
an answer you can give to a person. `docs/DECISIONS.md` has the full argument.

---

## 3. The one rule that is easy to break

> **A team's score for a candidate must never read that candidate's
> preferences.**

Not their ranked list, not their rank of this team, not "they seem keen."

Strategy-proofness depends on the other side's ranking being independent of
what candidates submitted. The moment a team's score includes "they ranked us
first", candidates gain a reason to misreport, and the promise printed for the
cohort becomes false.

**The failure is silent.** The match still runs. It still reports zero blocking
pairs. It still looks completely defensible. Nothing goes red.

The only thing standing between this codebase and that bug is
`tests/test_scoring.py::test_scores_ignore_candidate_preferences`. Do not
delete it to make a change pass. `scoring.py` carries the same warning at the
top of the file.

---

## 4. Data model

Five types, all in `resumatch/models.py`, all JSON-serializable.

### Candidate

| field | type | notes |
|---|---|---|
| `id` | str | unique |
| `name` | str | display only — never read by scoring (see §9) |
| `skills` | frozenset[str] | **canonical** skill names (see §5) |
| `interests` | frozenset[str] | domain tags |
| `ranked_team_ids` | tuple[str, ...] | strict preference order, best first, usually a *subset* of teams |

Candidates rank ~5 of 20 teams. A team they did not rank is a team they never
proposed to, which is different from a team that rejected them — the
explanation layer keeps those cases apart.

### Team

| field | type | notes |
|---|---|---|
| `id` | str | unique |
| `name` | str | |
| `capacity` | int | open slots; **multiple people per team is the normal case** |
| `domain_tags` | frozenset[str] | matched against candidate interests |
| `required_skills` | frozenset[str] | the dominant scoring term |
| `preferred_skills` | frozenset[str] | nice-to-have |
| `wishlist` | tuple[str, ...] | candidate ids the manager named, strongest first |

Managers cannot rank 150 people. `wishlist` is the only place they express an
opinion about a *specific* person; the rest of their preference is inferred
from the skills they asked for.

### Cohort, Assignment, MatchRun

`Cohort` is candidates + teams, and `cohort.content_hash()` is a SHA-256 over
both. That hash plus the seed plus the algorithm version reproduces a run
exactly — it is what lets you trace "the numbers changed" to an input change.

`Assignment` carries `tier` (how they got the seat) and `preference_rank` (how
good it was for them). Those answer different questions; don't collapse them.

`MatchRun` embeds the whole cohort, so a run file explains itself offline.

### Tiers

| tier | meaning |
|---|---|
| `top_choice` | matched to their #1 |
| `ranked` | matched to another team they ranked |
| `fallback` | ranked list exhausted; placed by fit score |
| `pinned` | **a human overrode the algorithm** |
| `unplaced` | no capacity anywhere (only when slots < cohort size) |

### A cohort file

```json
{
  "seed": 42,
  "candidates": [
    {
      "id": "C001",
      "name": "Priya Raman",
      "skills": ["docker", "kubernetes", "python", "sql"],
      "interests": ["backend", "infra"],
      "ranked_team_ids": ["T07", "T02", "T14"]
    }
  ],
  "teams": [
    {
      "id": "T07",
      "name": "Payments Core",
      "capacity": 6,
      "domain_tags": ["backend"],
      "required_skills": ["python", "sql"],
      "preferred_skills": ["kubernetes"],
      "wishlist": ["C001"]
    }
  ]
}
```

---

## 5. The skill taxonomy — read this before writing an intake adapter

`resumatch/taxonomy.py` is the module that makes this portable between
organizations, and it is the easiest one to underestimate.

Scoring compares skills by **set intersection**, which is exact. So:

| source | writes |
|---|---|
| hiring manager | `React` |
| resume | `ReactJS` |
| course catalog | `front-end development` |

Three different strings. Without normalization the matcher scores a genuinely
strong fit as `0.00` and places that person somewhere else. There is no error
and nothing in the output looks wrong — the match is just quietly worse for
that person, for a reason that appears nowhere.

**Every intake path must normalize through `taxonomy.normalize()` or
`taxonomy.extract_skills()`.** An adapter that writes raw user strings into a
`Candidate` or `Team` is broken even though it runs.

`normalize_all()` returns `(recognized, unrecognized)`. Surface the second
half. A recruiter who sees "3 terms not recognized: Murex, KDB, FIX" can get
the taxonomy extended; a recruiter who sees nothing just gets worse matches.

**Porting to a new org:** replace the contents of `SKILL_DEFS`. The taxonomy is
data, not logic. A bank's vocabulary and a university's are different sets;
nothing downstream changes.

---

## 6. Pipeline

```
  intake                    engine                    outputs
  ──────                    ──────                    ───────
  generate.py  ┐
  intake/resume.py ├──→ cohort.json ──→ scoring.py ──→ matching.py ──→ run.json
  intake/csv_intake.py ┘                (team            (deferred        │
  your adapter here                      rankings)        acceptance)     │
                                                                          ├──→ report.py   metrics, explanations, rosters
                                                                          ├──→ diff.py     what changed between two runs
                                                                          └──→ ui/         the drag-and-drop board
```

The engine is a pure function over JSON. It has no idea where a cohort came
from. **That is the whole portability story**: moving to a new organization
means writing one adapter in `resumatch/intake/` and changing nothing else.

An adapter is anything shaped like `load(source) -> Cohort`.

---

## 7. Commands

```bash
# make a synthetic cohort
python3 -m resumatch generate --seed 42 --candidates 150 --teams 20 -o data/cohort.json

# or build one from spreadsheets you already have
python3 -m resumatch intake candidates.csv teams.csv -o data/cohort.json

# match
python3 -m resumatch match data/cohort.json -o data/run.json
python3 -m resumatch match data/cohort.json --pin C042=T07 -o data/run.json

# read the result
python3 -m resumatch report data/run.json
python3 -m resumatch explain data/run.json --candidate C042
python3 -m resumatch roster data/run.json --team T03

# score one resume against every team
python3 -m resumatch fit data/cohort.json --resume examples/sample_resume.txt

# headcount changed in week two
python3 -m resumatch shock data/cohort.json --team T07 --slots -3 -o data/run_b.json
python3 -m resumatch diff data/run.json data/run_b.json

python3 -m resumatch export data/run.json -o data/assignments.csv
```

### CSV intake

Header matching is case-insensitive and tolerant of spaces, underscores and
common alternate spellings (`Open Slots`, `Must Have`, `Student ID`), because
real form exports do not arrive in our preferred shape. Unknown columns are
ignored. Use semicolons to separate multi-value cells — skills legitimately
contain commas.

```
candidates.csv   id, name, skills, interests, preferences
teams.csv        id, name, capacity, domain_tags, required_skills,
                 preferred_skills, wishlist
```

---

## 8. Reading the output

```
INTEGRITY
  blocking pairs           0  <- STABLE
```

The headline. Zero means no intern and no team would both rather have each
other than what they got.

```
NEEDS A HUMAN LOOK (19 placement(s) below 0.05 fit)
```

Placements that got their seat on tie-break rather than on any stated skill
overlap. Legitimate — the team had headcount and the candidate ranked them —
but this is the list to review before the match goes out.

The threshold sits just above zero deliberately. The score distribution is
bimodal, not a gradient: on a representative run 23 placements sit at exactly
`0.00` and the next one up is `0.05`, with the median at `0.60`. Either a
candidate overlaps the team's domain or they don't.

### Expected ranges

| metric | healthy | what it means if it's off |
|---|---|---|
| placement rate | 100% | below means total slots < cohort size |
| first choice | 45–70% | **~99% means the generator's popularity skew isn't biting** — the scenario is unrealistically easy and the demo is misleading |
| top three | 90–98% | |
| blocking pairs | 0 | anything else is a bug, or a manual override (§10) |
| fallback | a handful | zero means the fallback path is dead code and untested |

### Explaining one outcome

`python3 -m resumatch explain data/run.json --candidate C042` prints the answer
to a pushback: which teams turned them down, each team's final cutoff score
versus theirs, and how many candidates it held above them.

Comparisons use each team's **final** cutoff, not whoever happened to be held
when the bump occurred. Mid-run state is an artifact of proposal order, and
using it would explain two identical outcomes differently.

---

## 9. Fairness constraints

These are deliberate and should survive refactors.

- **Scoring reads skills and interests. Nothing else.** Not names, not schools,
  not employers, not dates. The resume parser extracts skills and domain
  language only, and the scoring layer never sees resume text. The moment
  school or employer prestige enters the profile, the tool stops being a fit
  matcher and starts laundering bias behind a fit score.
- **Preferences are never inferred.** `candidate_from_resume()` takes
  `ranked_team_ids` as a separate argument and will not guess them from text,
  even when the resume says "I'd love to join Payments." Guessing what someone
  wants and then matching them against the guess is exactly the failure this
  tool exists to prevent.
- **The wishlist bonus cannot outweigh skills.** A manager naming someone is
  real evidence, capped at 15% of the score. Letting it dominate would make the
  tool a rubber stamp for whoever the manager already met — the bias the
  process is supposed to reduce. There is a test for this.

---

## 10. The frontend (`ui/`)

A four-screen React app in `ui/app.html`. **No build step** — React and `htm`
load as pinned UMD globals from a CDN, and the app's own code is plain ES
modules served alongside it. That keeps the whole thing one shareable link,
which matters more for this project than a bundler would.

| screen | route | whose question it answers |
|---|---|---|
| Overview | `#/` | *Is this cycle in good shape, and what needs my attention?* Metrics, rank distribution, oversubscription, and the review queue. |
| Board | `#/board` | *Move this person — show me what it costs.* Drag-and-drop with live re-matching. |
| Teams | `#/teams` | *Who is on my team, and why them?* The hiring-manager view. |
| Intake | `#/intake` | *Given this resume, where does this person fit?* Paste text, see extracted skills and ranked teams. |

### Module layout

```
app.html        shell: fonts, CDN globals, mount point
  app.js        root component, hash routing, toolbar
  store.js      the reducer — the ONLY place capacities and pins change
  screens.js    the four screens
  drawer.js     per-candidate explanation panel (shared)
  components.js presentational primitives, no state
  taxonomy.js   browser-side skill extraction
  h.js          React + htm bindings
  styles.css    design tokens and component styles
  engine.js     deferred acceptance (see below)
  data.js       generated — cohort + team rankings + vocabulary
```

State lives in one reducer because every screen reads the same match result.
Nothing outside `store.js` mutates capacities or pins, and the match re-runs
exactly once per change.

`ui/board.html` is the earlier single-screen version, kept because it is
dependency-free and useful as a minimal reference. The React app supersedes it.

### Checking it

```bash
node scripts/check_ui_render.js    # every screen mounts and produces markup
```

`node --check` parses the modules but cannot catch the two things that actually
break this app, both of which fail as a blank page: a malformed `htm` template,
and React prop handling. The render check server-renders all four screens and
the drawer, and asserts that `class` reaches the DOM. It needs React's UMD
builds in `.vendor/` and prints the fetch commands if they're missing — it
skips cleanly rather than failing when they aren't there.

### Overrides

Drag anyone onto a team to override the algorithm; adjust any team's headcount
with `+` / `−`; click anyone for their full explanation.

Every change immediately reports **what it cost** — how many other people
moved, how many got a worse outcome, and their names. An override is a
legitimate act, because the recruiter knows things the data doesn't. It is
never free, and the person paying for it should be visible before the decision
is confirmed, not after.

**Manual overrides can create blocking pairs, and the board says so** rather
than excusing them. If you pin someone into a seat a stronger candidate wanted,
the integrity reading goes from `STABLE` to `n blocking`. That is correct
behavior: a human override should be visible as what it is, not laundered into
looking like the algorithm's choice.

### The duplication you need to know about

`ui/engine.js` is a **second implementation** of deferred acceptance, so the
app can answer a drag instantly with no server.

Two copies of an algorithm drift, and this drift would be invisible — both
would keep producing plausible, stable-looking matches that disagree about
where real people go. Two things contain it:

1. **Only the mechanism is duplicated.** Team preference orders — the part with
   tunable weights and a seeded SHA-256 tie-break — are computed by
   `scoring.py` and baked into `ui/data.js`. They never change in response to
   anything the UI can do. The browser only re-runs the queue loop, which has
   no constants to drift.
2. **A parity check.** After changing `matching.py`, `scoring.py` or
   `engine.js`:

```bash
python3 scripts/export_ui_data.py
node scripts/check_ui_parity.js      # must print PARITY OK
```

The same containment applies to the skill taxonomy. `ui/taxonomy.js` repeats
the extraction *regex* but not the *vocabulary* — aliases, domains and phrases
all ship in `data.js` from `taxonomy.py`. A skill added in Python but missing
in the browser would silently score a real fit as zero on the intake screen
and nowhere else, which is close to impossible to notice.

---

## 11. Synthetic data

`generate.py` produces seeded cohorts. One design decision in it matters more
than the rest:

**Popularity skew.** If candidate preferences are drawn uniformly at random,
almost everyone gets their first choice, the metrics read ~99%, and the demo is
a lie. Real cohorts are not uniform — a few teams collect most of the
first-choice votes and run 4–6x oversubscribed, which is the entire reason this
tool needs to exist.

Each team gets a `prestige` weight drawn from a Pareto distribution
(`PRESTIGE_ALPHA = 2.6`, tuned — at 1.6 one team pulled 39% of the cohort and
first-choice collapsed to 29%, skewed past realism). Candidates sample their
rankings by prestige × domain affinity.

`UNIVERSAL_SKILLS` exists for the same reason: without cross-domain skills like
Python and SQL, generated cohorts are unrealistically siloed and a third of all
placements score exactly `0.00`.

---

## 12. Glossary

**Deferred acceptance (DA)** — candidates propose to teams in preference order;
teams hold the best proposals seen so far and release the rest. Holds stay
tentative until the run ends, which is why a late strong proposal can displace
an earlier weak one.

**Blocking pair** — a (candidate, team) who would both rather have each other
than what they got. Their existence means the match is improvable for both
sides simultaneously.

**Stable** — no blocking pairs exist.

**Capacity** — a team's open slots. Multiple people per team is the normal case.

**Cutoff score** — the fit score of the weakest candidate a team ultimately
kept. What a rejected candidate's score is compared against.

**Tier** — how someone got their seat (algorithmic, fallback, or human
override), as opposed to how good it was for them (`preference_rank`).

**Pin** — a manual override seating a specific person on a specific team.

---

## 13. Scope

**In:** the matching engine, explanations, metrics, run diffing, CSV and resume
intake, synthetic data, the browser board.

**Not in:** a database, authentication, multi-user editing, live HR system
connectors, multi-cycle history, PDF/DOCX resume parsing (convert to text
first — `pdftotext`, `textutil`).

All of those attach without touching the engine, which is a pure function over
JSON.

### Known limits

- **Resume extraction is keyword-and-alias matching**, not comprehension. It
  finds named technologies reliably. It misses skills that are only implied
  ("rebuilt the checkout flow, cut p99 latency 40%" names no technology) and it
  cannot judge depth — two years of production Python and one course project
  both read as `python`. The function signature is the seam; a model-backed
  extractor drops in without touching anything downstream.
- **Every candidate is acceptable to every team.** No team can refuse someone
  outright, which is what keeps "nobody gets a hard no" true. Real managers
  sometimes would. See `docs/DECISIONS.md`.
- **Synthetic data only.** No pilot has run against real candidates.
