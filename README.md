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

## Documents

| Document | What it covers |
|---|---|
| [`CONSTITUTION.md`](CONSTITUTION.md) | The ten rules every project under trunk-kuli works by, whichever model is doing the work |
| [`docs/01-product-spec.md`](docs/01-product-spec.md) | Problem, thesis, the two halves, the gates, how portability is proven, scope, metrics, risks, open questions |
| [`docs/02-fleet.md`](docs/02-fleet.md) | Every existing project, which gates it already has, its tier, and its gaps in order of risk |

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

Specification written. Implementation not started. Six open questions are
recorded rather than guessed; two of them shape the architecture and are
answered before any code.

## Where it comes from

The gates are not hypothetical. The two-directional traceability gate exists in
[p2p-lending](https://github.com/mohoatu/p2p-lending) and caught a real defect
in its first week. The argument that a check which can never fail proves
nothing when it passes comes from
[migration-verify](https://github.com/mohoatu/migration-verify), where the test
suite is itself tested by deliberate mutation.

This project is those ideas taken out of one repository and made to work
anywhere, under any model.
