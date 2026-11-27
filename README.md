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

### 6. Hand out less than you hold

A clearance in a file answers *what may this model see*. It does not answer
*what may the thing it spawned see* — and that is where authority leaks,
because a lookup returns the same clearance to the parent and the child.

A **grant** is authority as a value, and the only way to make one from another
is `narrow`, which returns the intersection. There is no `widen`, so asking for
more than the parent holds gives the parent's limit:

```bash
python -m kuli.cli grant --provider cloud --level L3 --scope src
```

```
"root":     { "level": "L1", "scope": ["*"] }
"narrowed": { "level": "L1", "scope": ["src"] }     # L3 was asked for
```

The registry sets the **ceiling**; every grant descends from an entry in it by
narrowing. A chain of hops can only shrink.

A grant in a file still has one problem: the file is in the repository, and the
agent whose clearance it records can edit it. So a boundary accepts a
**signature**, not a file:

```bash
export KULI_CAPABILITY_KEY_FILE=~/.kuli/key      # outside the repository
python -m kuli.cli capability --provider cloud --level L1 --ttl 300
python -m kuli.cli capability --verify kuli1.…
```

An agent may still rewrite `providers.json`. It cannot sign the entry it
invented, so the edit buys it nothing until a person signs — and
`signing_key` refuses a key file that lives inside the root it protects, since
a key an agent can read is a key an agent can use. Every capability expires;
one that does not is a permission, which is a different thing.

Permissions also **fail closed**. A measure that cannot judge abstains; a
permission that cannot judge refuses. An unrecognised key in `providers.json`
or `kuli.json` is named and refused rather than ignored, because a misspelt
`clearence` that is silently skipped is a permission nobody applied and
everybody believed.

And a grant filters a queue **before** an agent sees it, rather than only
refusing the call:

```bash
python -m kuli.cli offer --provider cloud --level L1 --tools mcp://audit < queue.json
```

```
  offered   mcp://audit
  withheld  mcp://audit     L2 is above cloud, which holds L1
  withheld  mcp://deploy    mcp://deploy is not a tool cloud may call
  withheld  mcp://audit     L3 is above cloud, which holds L1
```

A queue entry names a service and the paths it will touch. The last one named
a `.env` file, which no clearance admits. `offer` and the
refusal at the call go through one function, so a filter and a refusal cannot
drift into disagreeing — and a task is judged on **what it declares**, so a
task that names no paths is judged on its service alone.

Two things follow from *unclassified means L2*: write your `classification`
rules, or an L1 provider is offered nothing that declares a path.

Why this shape: [`docs/07-orchestrator.md`](docs/07-orchestrator.md), which
reads Google's Agent Mesh against this project and says which layer a corridor
for agents belongs in.

### 7. Let the agent call the gates itself

Everything above is a command. A command runs when CI runs it, or when you
remember to. An agent product has its own loop, and a gate outside that loop
is a gate that fires when somebody remembers.

So the gates are also MCP tools:

```bash
python -m kuli.cli serve     # JSON-RPC 2.0 on stdin/stdout, no dependencies
```

```json
{ "mcpServers": { "kuli": { "command": "python",
                            "args": ["-m", "kuli.cli", "serve"] } } }
```

Six tools — `ratchet`, `classify`, `review_cost`, `duties`, `contract_check`,
`capability_verify` — and three rules about what they are:

**Read-only.** Every tool returns a verdict; none writes a file. No
`baseline`, no `contract freeze`, no minting a capability. An agent can ask
*would this pass* as often as it likes and cannot move a bar through this
door. Lowering a bar stays a commit, alone in its diff, with a person's name
in the trailer.

**A verdict is never an argument.** No tool takes a level, an allowance or a
pass/fail. You say what to look at; it says what it found. Otherwise this
would be a prompt with a JSON schema.

**Cannot judge is not a pass.** `isError: true` with a text beginning
`CANNOT JUDGE`. A refusal is the tool working, so it is `isError: false`
beginning `REFUSED` — an agent that treats a refusal as a crash will retry it.

### 8. Talk to a model through the boundary

A second model joins by being a row in `providers.json`, not by being a branch
in the code. `kuli ask` runs one completion through a `raw-model` provider —
and the context goes through the **real** assembler on the way:

```bash
python -m kuli.cli ask --provider local-llm --context CLAUDE.md \
                       --prompt "summarise this in one line"
```

```
$ python -m kuli.cli ask --provider local-llm --context .env --prompt "what is here"
.env is L3. No provider may be given a secret in context, including one
cleared to L3; the credential proxy injects it into the request instead.
$ echo $?
2
```

That refusal happens in the assembler, before a socket is opened. The adapter
never had the choice — it receives a bundle and has no way to build one, which
is checked by a test that reads the adapter's own source.

Endpoint, model and key all come from the registry entry or from an
environment variable it names, so reaching Ollama and reaching a hosted
OpenAI-compatible endpoint are the same code path with two rows in the file.
The key goes in the `Authorization` header and never into the body, the trail
or an error message.

Honest limit: this has been exercised against OpenAI-compatible endpoints over
real HTTP, and **not yet against a real local model** — see
[`docs/05-provider-tasks.md`](docs/05-provider-tasks.md) T7.

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
| [`docs/04-providers.md`](docs/04-providers.md) | How a second or third model joins without the rules changing: two shapes, two adapters, one registry |
| [`docs/05-provider-tasks.md`](docs/05-provider-tasks.md) | The provider work broken into steps small enough to finish and verify one at a time |
| [`docs/06-three-agent-review.md`](docs/06-three-agent-review.md) | Separation of duties and the increment contract: two gates on the procedure rather than the work |
| [`docs/07-orchestrator.md`](docs/07-orchestrator.md) | Google's Agent Mesh read against this project: which layer a corridor for agents belongs in, and three options |
| [`docs/08-neighbours.md`](docs/08-neighbours.md) | Two Vietnamese products working the adjacent halves of the problem, and the four things worth taking from them |

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
