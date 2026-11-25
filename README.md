# trunk-kuli

A personal AI assistant that does not belong to any one model provider, and a
harness that keeps the way it works the same when the model underneath changes.

*Kuli* — a worker who carries the load. The name is deliberate: the model is
not the point. The model is whichever one is cheapest and good enough this
month. What stays is the process it has to work under.

---

## Why

Two things break every time you switch model — Claude to a local model, to
Gemini, to DeepSeek, or just one version to the next.

**The assistant forgets who you are.** Your instructions, your corrections,
what it already told you, what it was halfway through: all of it lives inside
one vendor's product.

**The discipline evaporates.** Most "AI engineering process" today is a pile of
prompts — *write the spec first, add tests, follow the standard*. A prompt is a
request, not a guarantee. A different model reads it differently. Nothing stops
work that ignored it.

## The idea

> **A harness is not a prompt. A harness is a set of gates written in ordinary
> code, which the model's output must pass, and which are identical whichever
> model produced it.**

A prompt saying *"always write tests"* is advice. A gate that refuses a change
when a documented acceptance criterion has no test is a rule — a program that
reads files and exits non-zero. The first needs the model's cooperation. The
second does not involve the model at all.

So everything that must survive a model swap lives **outside** the model: in
files, and in checks that run as code.

## The measurement that settles it

[SlopCodeBench](https://arxiv.org/abs/2603.24755) measured what happens when
agents repeatedly extend their own earlier work: the best agent passed 14.8%
of checkpoints, structural erosion rose in 77% of trajectories and verbosity
in 75.5%, and against 473 open-source Python repositories the agent code was
2.3× more verbose and 2.0× more eroded.

And the finding this project turns on:

> *"Explicit quality guidance reduces initial verbosity and erosion by up to a
> third, **without affecting degradation rates**."*

Telling a model to write good code moves the starting point and does nothing
to the rate of decay. **A prompt changes the intercept; only something
measuring the trend can change the slope.**

So alongside the gates that judge one change, there are **ratchet gates** that
measure the repository and refuse anything that makes it worse — and when a
change would worsen a measure, it may proceed by including the refactor that
pays for it. That is the direct counter to the documented behaviour: an agent
left alone patches rather than restructures, because patching passes the test
and restructuring was never asked for.

These are the first two gates built, because they are the two that nothing
else already does. See [Using it](#using-it).

## What this claims, and what it does not

- **It guarantees that work which breaks the process does not get through.**
  Same gates, same refusals, any provider.
- **It does not guarantee that every model does good work.** A weaker model
  fails the gates more often, loops, or stalls — visible and measurable, which
  is the point, but not quality by decree.

The promise is that **the floor is the same everywhere**. Not the ceiling.

## Two halves

**A portable brain, held locally and classified.** Memory, timers, inbox and
outbox as plain files, every one of them carrying a level. A hosted provider
may see public and internal material; confidential material is readable only
by the local model; **secrets are readable by no model at all** — a credential
proxy injects them, so a model that never sees a secret cannot leak one.
Unclassified defaults to confidential, and only a human may ever lower a level.

**Portable discipline.** Nine gates — spec, traceability, test, current-API,
standard, absence, scope, classification, evidence — each a program, none of
them a prompt.

The current-API gate is the one worth describing. The requirement is that the
model must not write code from the stale API it remembers from training, and
"check the documentation first" is a prompt, so it is not enough. The
mechanical form of the rule is: **every external symbol the code calls must
exist in the version of the dependency that is actually installed.** That needs
no honesty from the model — a remembered method that no longer exists is simply
absent from the package, and absence is checkable.

## Running while you sleep

Sensitive work needs a password and a one-time code, which needs you present;
running continuously means working while you are not. Rather than weakening
either, the work is split: **unattended runs overnight** touch public and
internal material only, and anything needing you is queued and presented as one
batch at **10:00 and 16:00** — two short interruptions at known times, not a
trickle of prompts all day.

## How the claim is proven

A conformance suite runs the same task through several providers, then
introduces a deliberate violation and asserts **every provider is stopped by
the same gate, for the same reason**.

That last part is the real test. Anyone can call a tool model-agnostic while
all their models happen to succeed. Agreement matters when the answer is *no*.

## Using it

No installation and no dependencies. Python 3.10 or newer, standard library
only — copy or clone the `kuli/` package next to your project, or add this
repository as a sibling and call it by path.

```bash
python -m kuli.cli --help
```

### 1. See where you stand

```bash
python -m kuli.cli --root ../my-project measure
```

```json
{
  "python": {
    "duplication": 0.0643,
    "erosion": 0.3168,
    "max_complexity": 17,
    "max_nesting": 4,
    "max_statements": 60,
    "units": 79,
    "verbosity": 10.684
  }
}
```

Read them as: **erosion** is the share of all complexity held by the worst
tenth of units — concentration, not total. **verbosity** is statements per
unit. **duplication** is the share of substantial lines that appear more than
once. A *unit* is a function in Python and a file in JavaScript, so the two
languages are reported separately and are not comparable to each other.

### 2. Draw the line

```bash
python -m kuli.cli --root ../my-project baseline
```

```
Baseline written to ../my-project/.kuli/baseline.json
  python      52 units, erosion 0.266, verbosity 6.6, duplication 0.082

From here a measure may be held or improved, never loosened.
```

Commit `.kuli/baseline.json`. Baseline **after** deciding what to exclude —
freezing a wrong number and then defending it is worse than having none.

### 3. Hold it

```bash
python -m kuli.cli --root ../my-project ratchet
```

Nothing got worse, exit 0. Something did, exit 1 — and it names what, and who
is carrying it:

```
The ratchet refused this change.

  python / erosion: 0.2657 -> 0.2866 (worse by 0.0209)
      complexity is concentrating into fewer units — the usual sign that
      something was patched instead of restructured
      carrying it: kuli/measures.py::_deliberately_awful (complexity 14)
      carrying it: kuli/measures.py::duplication (complexity 8)
  python / max_complexity: 8 -> 14 (worse by 6)
      the worst single unit got worse
  python / max_nesting: 5 -> 7 (worse by 2)
      the deepest nesting got deeper

This is not a rejection. Include the refactor that pays for it,
or record an exception in kuli.json with a reason, which stays
visible until it is repaid.
```

That output is from a real run: a deliberately awful function was added to
this repository to check the ratchet goes red, then removed.

### 4. Keep changes readable

```bash
python -m kuli.cli review-cost --base origin/main --budget 120
```

Slop defined as an asymmetry — work that costs far less to produce than to
review. That is a ratio, so it is measurable: added lines per acceptance
criterion the change claims to serve. Generated files are excluded; a
thousand lines serving one criterion is slop by arithmetic, whatever it
contains.

When a change claims no criteria the gate **abstains and says so**:

```json
{
  "identifiers": [],
  "note": "No acceptance-criterion identifiers found in this change. This gate
           abstains rather than guessing a verdict it cannot support."
}
```

### 5. See what the agents did

A gate says yes or no at a boundary. A **trail** is a witness — and the two
fail differently: a gate you never wrote lets something through in silence,
while a trail catches it anyway, afterwards.

The rule the design rests on: **the record is not written by the agent.** An
agent logging itself produces a claim; the recorder sits outside it, at the
tool-call boundary, so the trail holds what happened rather than what the
agent said happened.

```bash
python -m kuli.cli trail --last 20          # counts by tool, provider, day
python -m kuli.cli trail --file src/app.py  # who changed this file
python -m kuli.cli audit                    # has the record been altered?
```

Append-only and hash-chained, so an entry cannot be edited or removed
quietly:

```
The trail has been altered. 3 entries, 1 problems:
  entry 0: content does not match its digest
```

And it stores **fingerprints, not contents** — a write is recorded as its
path, size and SHA-256. That answers who changed what, when, to exactly which
bytes, without the audit log becoming the largest leak in the system.
Credentials are removed before anything is hashed.

It records; it refuses nothing. See [`docs/03-trail.md`](docs/03-trail.md),
including what it deliberately cannot do.

### Exit codes

| Code | Meaning |
|---|---|
| **0** | The gate passed |
| **1** | The gate refused |
| **2** | The gate could **not judge** — no baseline, not a git repository, no criteria claimed |

Two is not a pass. A gate that cannot answer a question must never report
success for it.

### Configuration — `kuli.json`

Optional, at the project root. Everything defaults to strict.

```json
{
  "tier": "A",
  "skip": ["embed", "vendor"],
  "allowances": { "python": { "verbosity": 0.5 } },
  "exceptions": {
    "javascript": { "duplication": "generated bundle inlines the engine; see #42" }
  }
}
```

- **`skip`** — directories left out of measurement. Use it for generated
  bundles and vendored code, and for nothing else: excluding real source is
  the easiest way to fake a flat line.
- **`allowances`** — how much a measure may drift before the ratchet trips.
  Defaults to zero.
- **`exceptions`** — a measure allowed to get worse, **with a reason**. The
  debt is printed on every run until it is repaid. Debt taken knowingly is
  engineering; debt taken silently is what this project exists to prevent.

### In CI

```yaml
- name: nothing got worse
  run: python -m kuli.cli ratchet
```

The CLI is the authority. Editor and agent integrations call this same
command rather than reimplementing it — which is what stops the gates
disappearing when the model changes.

## Documents

| Document | What it covers |
|---|---|
| [`CONSTITUTION.md`](CONSTITUTION.md) | The ten rules every project under trunk-kuli works by, whichever model is doing the work |
| [`docs/01-product-spec.md`](docs/01-product-spec.md) | Problem, thesis, the two halves, the gates, how portability is proven, scope, metrics, risks, open questions |
| [`docs/02-fleet.md`](docs/02-fleet.md) | Every existing project, which gates it already has, its tier, and its gaps in order of risk |
| [`docs/03-trail.md`](docs/03-trail.md) | The audit trail: what the agents did, recorded by something that is not them |

## The first real workload

The harness exists so its owner can build later products with it, so its first
job is real product work rather than a demo: continuing
[p2p-lending](https://github.com/mohoatu/p2p-lending) from Phase 3 under
trunk-kuli. That project already has a specification, identified acceptance
criteria, a working traceability gate and committed evidence — so any
regression in discipline shows up immediately against 308 checks that already
pass.

It is finished when its owner would rather build the next thing through it than
without it. Nothing else counts as done.

## Status

**Built and running: the two ratchet gates, and the audit trail.** `measure`,
`baseline`, `ratchet`, `review-cost`, `record`, `trail` and `audit`, covering
Python and JavaScript. 69 checks on Linux and Windows across Python 3.10 and
3.13, and the suite makes the ratchet trip and the trail detect tampering on
purpose rather than only watching them agree — a check nobody has seen go red
is not known to work. kuli is measured by its own ratchet in its own CI, and
paid for the trail with a refactor when adding it tripped that ratchet.

**Specified, not yet built:** the classified local brain, the credential
proxy, provider adapters, the other seven gates, the night/approval-window
split, cross-provider review, the conformance suite, and the corridor — rules
that actually refuse an agent's action rather than only recording it.

Nine open questions are recorded rather than guessed; two of them shape the
architecture and are answered before more code.

### Honest limits of what is built

- **The JavaScript measures are a heuristic**, not a parser — a real JS parser
  would be a dependency, and that is a trade this project does not make. The
  numbers are wrong in detail and consistent over time, and a ratchet compares
  a measure against itself, so the bias cancels. An inaccurate measure is a
  poor report and a perfectly good ratchet.
- **Nesting is not measured for JavaScript** and is reported as zero.
- **`review-cost` needs identified acceptance criteria** (`A4.4`, `I2`, `R5`)
  in the diff or commit messages. Without them it abstains.
- **Java, Go and other languages are not measured at all.**
- **The trail only sees agents that run through it.** Open a model directly,
  outside a project with the hook installed, and nothing is recorded.
- **Recording a command is not constraining it.** The trail writes down
  `rm -rf`; it does not stop it.
- **Cost and token figures are not recorded yet.**

## Where it comes from

The gates are not hypothetical. The two-directional traceability gate exists in
[p2p-lending](https://github.com/mohoatu/p2p-lending) and caught a real defect
in its first week. The argument that a check which can never fail proves
nothing when it passes comes from
[migration-verify](https://github.com/mohoatu/migration-verify), where the test
suite is itself tested by deliberate mutation.

This project is those ideas taken out of one repository and made to work
anywhere, under any model.
