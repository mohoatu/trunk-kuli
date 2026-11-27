# Three agents around one prompt — what of it belongs here

Assessment, **27/11/2026**. Source: the Anthropic Labs write-up *Three Agents
Around One Prompt* (planner, generator, evaluator; six parts; a long-running
app harness). Figures below are as the piece reports them and are not
independently verified.

**Nothing in this document is adopted yet.** Two proposed changes to
[`01-product-spec.md`](01-product-spec.md) are set out in §4 for approval.

---

## 1. Its opening sentence is the same argument this project makes

> *"Asked to grade their own work, agents confidently praise it, even when
> the quality is obviously mediocre."*

That is the thesis of trunk-kuli in different words: the model's own account
of its work is a claim, not evidence. So the question is not whether the
piece is right — it is which of its mechanisms trunk-kuli does not already
have.

## 2. What is already here

| In the piece | Already in trunk-kuli |
|---|---|
| Planner writes a spec before code | The spec-driven loop, and the spec gate (§8) |
| Evaluator attacks the generator's work | Adversarial review (§7) |
| A second opinion that is not the author | Cross-provider review (§7, §5.1) |
| Evaluator clicks the **running app**, not the source | Interface gates judge the **rendered** result (§8.2); proof by execution (§8.5) |
| Hard thresholds fail rather than warn | Every gate refuses rather than warns (constitution 3) |
| One feature per sprint | Review-cost budget pushes the same way from the other end (§8.4) |
| Cost and time measured per run | The capability report (§9), costs deliberately blank until measured |

So roughly two-thirds of it is a restatement of decisions already taken. That
is reassuring rather than disappointing: independent arrival at the same
design is weak evidence the design is right.

## 3. What is genuinely new

### 3.1 "Never sign off on your own work"

The generator self-checks and then hands to QA. trunk-kuli has adversarial
review, but it has **no rule forbidding the producer from being the
accepter** — and that rule is mechanical, not a matter of good behaviour.

The trail already records which provider and session produced each action.
So a gate can refuse an acceptance whose actor matches the actor that
produced the change. Separation of duties, enforced by a program, using data
already being collected.

This is the strongest thing in the piece for this project, because it turns a
convention into a gate.

### 3.2 The sprint contract, agreed before any code

> *"Before each sprint, write contract.md: what gets built, how it is tested.
> The evaluator reviews it. Iterate until both agree on 'done'."*

trunk-kuli has acceptance criteria in documents and design-first for
expensive surfaces (§8.6). It does **not** have a per-increment agreement
**negotiated with the party who will later judge the work, before the work
starts**.

That ordering is the whole value. It removes the oldest failure in automated
quality: the producer writing the tests that its own code will pass. If the
bar is agreed by the reviewer first, passing it means something.

Cheap to implement: a file, and a gate that refuses work on an increment with
no agreed contract.

### 3.3 Graded dimensions

Depth, functionality, visual design, code quality — scored, with a hard floor
that fails the sprint.

The structure is worth having; **the scores are not measurements**. A number
produced by a model is an opinion with a decimal point. Adopting the named
dimensions and the hard floor is consistent with this project; ratcheting
those scores would be ratcheting noise, and is rejected in §5.

## 4. Proposed changes to the specification

Two, both gates rather than instructions, both using data that already
exists.

---

### Proposal A — separation of duties

#### The hole, concretely

Every gate in this project is a deterministic program, so a model cannot talk
one into passing. But it can do something simpler: **change the gate's
settings.**

Today, one actor can, in a single session:

1. write code that raises erosion,
2. watch `kuli ratchet` refuse it,
3. add an exception to `kuli.json` — or widen `skip`, or re-run
   `kuli baseline` — and
4. see the gate go green, and report success.

`CLAUDE.md` already warns about exactly this: *"Never widen `SKIP_DIRS` to
make a number look better."* That warning is **a prompt**. In a project whose
entire thesis is that a prompt is not a guarantee, the one rule protecting
the gates from the thing they judge is currently a prompt.

#### The rule

> **The actor that produced a change may not be the actor that accepts it,
> and may not be the only actor behind a change to the rules themselves.**
>
> Rule files — `kuli.json`, `.kuli/baseline.json`, `providers.json`, CI
> workflows — are refused when the trail shows the same actor both produced
> the work under judgement and relaxed the rule judging it. The refusal is
> recorded.

#### Why it is cheap

The trail already carries provider, model and session on every action. The
gate is a comparison between two fields that are already being written.

#### The obvious objection, and the answer

*He works alone, often with one provider. If a second actor is required,
does everything stop?*

No, because the second actor is allowed to be **the owner**. With one
provider, the rule degrades to: *a change to the rules needs your explicit
approval.* That is not a new burden — the constitution already says only a
person may lower a classification level, and §5.2 already says nothing
irreversible happens without the owner. This extends the same principle from
*data* to *the rules themselves*, which is where it was missing.

---

### Proposal B — the increment contract

#### The hole, concretely

Ask an agent to "add the payment export". It writes the code. It writes the
tests. The tests pass.

Both were written by the same party, from the same reading of the request —
so if the reading was wrong, the tests encode the wrong expectation just as
faithfully as the code does. Green means the two agree with each other. It
does not mean either is right.

This is the finding from
[migration-verify](https://github.com/mohoatu/migration-verify), arriving
from the other direction: both implementations read the document correctly,
and the document was missing a sentence. Nobody made a mistake, and the
result was still wrong.

Adversarial review (§7) catches some of this, but it runs **afterwards**,
against work already built — and a reviewer looking at finished code is
under pressure to accept it.

#### The rule

> **Before work starts on an increment, a contract states what will be built
> and how it will be judged. The producer writes it; the reviewer accepts it;
> work is refused until both have signed.**
>
> **The contract is fixed once work begins.** Its hash is recorded in the
> trail at the moment work starts, and a gate refuses an acceptance whose
> contract changed afterwards.

#### The second sentence is the one that matters

A bar that can be edited after seeing the result is not a bar. Recording the
hash makes that mechanical rather than a matter of discipline: the contract
either matches what was agreed, or the acceptance is refused.

#### Why it is cheap

One markdown file per increment and one hash comparison. No new
infrastructure.

#### The obvious objection, and the answer

*Does every one-line fix now need a negotiated contract?*

No. It scales by the same test already used for tiers and for design-first
(§8.6): **how expensive is it to be wrong.** A contract is required for a
Tier A project, or for any increment touching an expensive surface. A typo
fix needs nothing. A gate that demands ceremony for trivia is a gate that
gets switched off, and that failure mode is recorded as risk 1.

---

## 5. What is deliberately not adopted

**Three fixed agent roles as a mandated loop.** trunk-kuli does not own the
loop for agent products — Claude Code has its own, and wrapping it is the
whole point of the two-shapes distinction (§2.1 of `04-providers.md`).
Planner, generator and evaluator will be the **default roles of the runner**
built in T10, for raw models, and a field in the registry. They will not be
imposed on a wrapped product, because that would be a rule trunk-kuli cannot
actually enforce there, and an unenforceable rule is a prompt.

**Model-produced scores as ratchet measures.** A ratchet compares a number
against itself and must therefore be deterministic. Cyclomatic complexity on
the same source gives the same answer forever; a model's "visual design: 7"
does not. Scores may be reported and may fail a hard floor; they may not
become a ratchet.

**The implied economics.** The piece reports $9 for twenty solo minutes
against $200 for a six-hour harnessed run — later $124.70 in a second
version. Three agents cost roughly three times one. That is a real price and
this document is not going to quietly leave it out: the gate approach is
cheaper per *correct* result and more expensive per attempt, and which of
those matters depends on whether being wrong is expensive. Which is the same
test used to decide tiers in the fleet register.

## 6. Recommendation

Adopt **A** and **B**.

Everything built so far judges **the work**. These two judge **the
procedure** — who was allowed to say yes, and when the bar was set. Those are
the two ways a correct-looking gate produces a wrong answer, and neither is
caught by any gate currently in the system.

A is the more urgent of the two: without it, the rules protecting the work
are themselves unprotected, and the only thing standing between a failing
ratchet and a green one is a sentence in `CLAUDE.md` asking nicely.

Defer the three agent roles to T10, where there is a loop to put them in.


---

## 7. Adopted — 27/11/2026

Both proposals are built. 202 checks, up from 173.

```bash
kuli duties --base origin/main    # A1 and A2, decidable from git alone
kuli contract new <slug>          # the bar, before the work
kuli contract check <slug>        # two signatures, two different actors
kuli contract freeze <slug>       # work starts; the digest is recorded
kuli contract verify              # has any bar moved since?
```

Both run in CI on pull requests.

**A is decidable from git alone**, with no trail and no model, which is what
lets it hold in CI. Two rules: the rules and the work they judge may not
change in one commit, and a commit touching the rules carries
`Rules-approved-by:`.

**B is a markdown file and a hash.** `freeze` is the moment work begins;
after it, any edit to the contract fails `verify`.

### What the gates caught while being written

**A regex that could not see an empty signature.** `^Producer-signed:\s*(\S.*)$`
— `\s` matches a newline, so an unsigned `Producer-signed:` swallowed the
line below it and reported the *reviewer's* name as the producer. The first
test run said one signature was missing when both were. Now `[^\S\n]*`.

**Four copies of one harmless line.** Adding the contract module put a fourth
`path.parent.mkdir(parents=True, exist_ok=True)` into the tree and the
duplication ratchet refused the change. The line was harmless; four copies of
a harmless line is how a codebase starts repeating itself. Extracted to
`kuli/paths.py`, which exists only because a gate insisted.

That second one is the ratchet working at a scale too small for anyone to
have bothered about by hand, which is the entire argument for having it.
