# Product specification — v1

A personal AI assistant that does not belong to any one model provider, and a
harness that keeps the way it works the same when the model underneath changes.

Decisions recorded here were made by the owner on **24/11/2026**. Where
something is still open it is marked `[OPEN]`, not guessed.

---

## 1. The problem

Two things break every time someone switches model — from Claude to a local
model, to Gemini, to DeepSeek, or just from one version to the next.

**The assistant forgets who you are.** Instructions, preferences, corrections,
what it already told you, what it was halfway through — all of it lives inside
one vendor's product.

**The discipline evaporates.** Most "AI engineering process" today is a pile of
prompts: *write the spec first, add tests, follow the standard*. A prompt is a
request, not a guarantee. A different model reads it differently; the same
model reads it differently on a bad day.

> **Can the way an AI assistant works be made independent of which model is
> behind it — and proven so, rather than hoped?**

---

## 2. The thesis

> **A harness is not a prompt. A harness is a set of gates written in ordinary
> code, which the model's output must pass, and which are identical whichever
> model produced it.**

A prompt that says *"always write tests"* is advice. A gate that refuses a
change when a documented acceptance criterion has no test is a rule — a program
that reads files and exits non-zero. The first depends on the model's
cooperation; the second does not involve the model at all.

So everything that must survive a model swap lives **outside** the model: in
files, and in checks that run as code.

### 2.1 The measurement that settles the argument

[SlopCodeBench](https://arxiv.org/abs/2603.24755) (Orlanski et al., 2026) is
the first benchmark to measure what happens when agents repeatedly extend
**their own earlier work** — 36 problems, 196 checkpoints, 15 agents.

- No agent solved any problem end to end. The best passed **14.8%** of
  checkpoints.
- **Structural erosion rose in 77% of trajectories; verbosity in 75.5%.**
- Against 473 open-source Python repositories, agent code was **2.3× more
  verbose and 2.0× more eroded** — and the human repositories degraded less
  often, and by smaller margins, across their git histories.

And the sentence this whole project turns on:

> *"Explicit quality guidance reduces initial verbosity and erosion by up to a
> third, **without affecting degradation rates**."*

Telling a model to write good code moves the starting point and does nothing
to the rate of decay. **A prompt changes the intercept; only something
measuring the trend can change the slope.**

That is the thesis above, measured by someone else. It also exposes a hole in
the first draft of this document: every gate in §8 judges **one change**. A
codebase can pass all of them on every commit and still rot — each patch
locally reasonable, abstractions never revisited, complexity concentrating.
§8.3 is the answer to that.

---

## 3. What is claimed, and what is not

- **Work that breaks the process does not get through.** Same gates, same
  refusals, any provider.
- **Not every model does good work.** A weaker model fails the gates more
  often, loops, or stalls — visible and measurable, but not quality by decree.

**The floor is the same everywhere. Not the ceiling.**

---

## 4. The second brain is local, and classified

### 4.1 Four levels

Data is classified into four levels. **The harness assigns the level** from
security practice; the owner reviews and adjusts, and his adjustment wins.

| Level | Name | Examples | Who may read it |
|---|---|---|---|
| **L0** | public | open-source repositories, published documents, the CV | any provider |
| **L1** | internal | drafts, plans, work notes, the job tracker, meeting prep | any provider, hosted included |
| **L2** | confidential | client data, contracts, unpublished product specs, financial figures, anything under NDA | **local model only** |
| **L3** | secret | credentials, tokens, API keys, identity documents, bank details | **no model, ever** |

L3 is not "local only". It is **not readable by any model at all**, including
the local one. Secrets are held by a credential proxy outside the agent: the
agent issues a request without credentials and the proxy injects them before
forwarding. A model that never sees a secret cannot leak one.

### 4.2 Classification is itself a gated act

- Every file in the brain carries a level. **Unclassified means L2** — the
  cautious default, not the convenient one.
- The harness proposes a level with its reason recorded. The owner can change
  it; the change is logged with a timestamp.
- **Downgrading** a level (L2 → L1, say) always requires the owner. The harness
  may upgrade on its own; it may never relax on its own.
- A classification decision is never made by the model being granted access.

### 4.3 The hosted-model boundary

A hosted provider's context may contain **L0 and L1 only**. This is enforced by
a gate that inspects what is about to be sent, not by instructing the model to
behave. A run that needs L2 data and is on a hosted provider does not downgrade
the data — it **switches to the local model or stops**.

---

## 5. Permissions

### 5.1 Hierarchical now, function-scoped later

v1 is **hierarchical**: a principal gets a clearance level, and may read
anything at or below it. The policy is nevertheless expressed from day one as:

```
(principal, max_level, scope)
```

with `scope` defaulting to `*`. Function-scoped permissions
("the release agent may read L2 **but only under `src/`**") are then added by
populating a field that already exists, rather than by changing the model. This
is the only concession v1 makes to a future requirement, and it costs one
column.

| Principal | Max level | Scope (v1) |
|---|---|---|
| hosted provider | L1 | `*` |
| local model | L2 | `*` |
| credential proxy | L3 | `*` |
| the owner | L3 | `*` |

### 5.1.1 Authority only narrows, and the agent cannot mint it

Two properties added **27/11/2026**, from reading Google's Agent Mesh against
this project ([`07-orchestrator.md`](07-orchestrator.md)). Both close holes that
the table above does not describe.

**A grant is a value, and the only way to make one from another is
`narrow`.** `narrow` returns the *intersection*, so a request for more than the
parent holds yields the parent's limit:

> root ⊇ root.narrow(…) ⊇ root.narrow(…).narrow(…) ⊇ …

There is no `widen`. This is what makes a hop safe: an agent cleared to L1 that
starts a sub-task cannot hand the sub-task more than it has, because no call
exists that would produce such a grant. The registry sets the **ceiling**; every
grant in the system descends from a registry entry by narrowing. `"*"` is how a
grant says *everything*, and it has to be written down — an empty list permits
nothing, which is the honest reading of an empty list.

**A boundary accepts a signature, not a file.** `providers.json` records the
clearance decision; it does not enforce it, because it is a file in the
repository that the agent whose clearance it records can edit. A **capability**
is that grant signed with a key kept outside the repository, carrying an
expiry, verified in constant time. An agent may still rewrite the registry; it
cannot sign the entry it invented, so the edit buys it nothing until a person
signs. The separation-of-duties gate (§8, A1/A2) catches the same thing in git,
*after* the commit; this catches it at the moment of the call.

Every capability expires. A capability with no expiry is a permission, and the
difference is the whole point.

### 5.1.2 Permissions fail closed

A measure that cannot judge abstains (`CLAUDE.md`). A permission that cannot
judge **refuses**. So `providers.json` and `kuli.json` are parsed strictly: a
key this version does not understand is named and refused rather than ignored,
because a misspelt `clearence` that is silently skipped is a permission nobody
applied and everybody believed.

### 5.2 Irreversible actions

The harness prepares; a person confirms. It never sends mail, pushes to a
default branch, publishes, or spends money on its own — regardless of
clearance. Clearance governs **reading**; irreversibility is a separate axis
and always needs the owner.

---

## 6. Running continuously, with the owner asleep

The owner's two requirements pull against each other: sensitive work needs a
password and a one-time code, which needs the owner present; running
continuously means working while he is not. The resolution is to **split the
work by whether it needs him**, not to weaken either requirement.

### 6.1 Three kinds of run

| Kind | When | May touch | Ends by |
|---|---|---|---|
| **Night run** | overnight, unattended | L0, L1 | finishing, or queueing an approval and stopping |
| **Approval window** | **10:00** and **16:00** | up to L3, during an unlocked session | the owner closing it, or timeout |
| **Interactive** | whenever the owner is there | up to L3 | the conversation |

A night run that reaches something it may not do alone performs a **deferred
stop**: it saves the session mid-call, writes a request into the approval
queue, and ends. It does not block, and it does not improvise a way around.

### 6.2 The approval window

At 10:00 and 16:00 the queued requests are presented **as one batch**. The
owner unlocks once with password and OTP; the unlock opens a time-boxed session
during which the queued actions run; then it re-locks.

- A batch, not a trickle. Two interruptions a day, at known times.
- **Shown, not described.** A person reads a diagram, a table or a screenshot
  far faster than a thousand lines of diff, and the windows are the one place
  where the owner's attention is the scarce resource. Each item leads with
  what changed in a form that can be taken in at a glance — a before/after
  table, a rendered screenshot, a diagram of the states that moved — and the
  diff sits underneath for when he wants it. Items are ordered by risk, not
  by the order they arrived.
- The window closes on a timer `[OPEN-1: how long]` even if the owner walks
  away, and anything unapproved returns to the queue.
- One unlock covers the batch in front of him. It does not persist to the next
  window.
- Requests expire `[OPEN-2: after how long]` so a stale approval is never
  executed against a world that has moved on.

### 6.3 Forward pressure, and the speed limit

Everything in §8 is **back pressure** — what stops bad work reaching a human.
A factory also needs **forward pressure**: what pushes work in without being
asked. Here that is the always-on half — a timer that fires, a failing check
that files its own fix, a queued request.

The two have to be designed against each other, and the rule is one line:

> **Forward pressure may never exceed what back pressure and the owner can
> absorb.**

The failure mode is specific and easy to walk into: automation that admits
work faster than the gates and the two approval windows can clear it. The
queue grows, the owner starts approving in bulk to catch up, and approving in
bulk is the same thing as not reviewing. Industry reporting on agentic
pipelines already describes exactly this — a large share of changes merged
with no review at all.

So intake is throttled by the bottleneck, which is **the owner's two windows**:

- A cap on how many items may be queued for one window. Over the cap, intake
  stops admitting new work rather than letting the queue grow.
- Night work is admitted only if the gates can judge it without him.
- A rising queue is treated as a signal that too much is being admitted, not
  as a reason to approve faster.

### 6.4 Where it runs

**v1 runs on the owner's machine**, which means runs happen only while the
machine is on and the app is open; a missed run happens at next launch. Cloud
comes later, and the design must not assume a machine that is always awake:
every run begins by asking *what is now due?* rather than *what was scheduled
for this minute?*

---

## 7. Two models arguing, and who settles it

Both forms of cross-checking are used, because they catch different things.

**Cross-provider.** The same task goes to two different providers. Their
failure modes are independent, so agreement is evidence and disagreement is a
signal. This also exercises the model-agnostic claim on every task rather than
only in the conformance suite.

**Adversarial review.** One model produces; a second model attacks the result
against a **fixed written checklist** — specification conformance, security,
error handling, test coverage, use of current APIs. The checklist is a file in
the repository, not something the reviewing model invents.

### Nobody accepts their own work, and nobody moves their own bar

Two rules sit underneath the review above, because a reviewer is no use if
the party being reviewed can change the rules or the bar.

**Separation of duties.** The actor that produced a change may not be the
actor that accepts it, and may not be the only actor behind a change to the
rules themselves — `kuli.json`, the baseline, the registry, CI. With a single
provider the second actor is the owner, which is the same principle as "only
a person may lower a classification level", applied to the rules rather than
the data. §8.3's `CLAUDE.md` warning against widening an exclusion was a
prompt until this existed.

**The increment contract.** Before work starts, a contract states what will
be built and how it will be judged; the producer writes it and the reviewer
accepts it. Its digest is recorded when work begins, and an acceptance whose
contract changed afterwards is refused. A bar that can be edited once the
result is known is not a bar.

The contract matters most where tests are written by the same party as the
code: both come from one reading of the request, so if the reading was wrong
the test encodes the error as faithfully as the code. Green then means the
two agree with each other, not that either is right.

### The rule that keeps this from being theatre

> **A disagreement is never settled by models voting.**

Every disagreement is routed to one of two places:

- **A gate**, when the question has a mechanical answer: does the test pass?
  does that symbol exist in the installed version? is the file in scope? The
  gate decides, and no model's opinion is consulted.
- **The owner**, when the question is a judgement call. It goes into the
  approval queue with both positions stated in one paragraph each.

Every disagreement and its resolution is recorded, because the record is what
later shows which provider is worth paying for.

---

## 8. The gates

Each gate is a program. It reads the repository, decides, exits zero or
non-zero. No model takes part in the decision.

| Gate | Refuses when |
|---|---|
| **Spec gate** | A change has no corresponding entry in the specification |
| **Traceability gate** | A documented acceptance criterion has no test — **or** a test claims a requirement the documents no longer define |
| **Test gate** | The suite is red, or a new code path arrived with no test |
| **Current-API gate** | See §8.1 |
| **Standard gate** | Formatting, linting and naming rules fail |
| **Absence gate** | A forbidden symbol, dependency or pattern appeared |
| **Scope gate** | Files were touched that the agreed plan did not name |
| **Classification gate** | Content above a principal's clearance was about to enter its context |
| **Separation of duties** | The rules and the work they judge changed together, or the rules changed with no second actor |
| **Contract gate** | An increment has no contract signed by two actors, or its contract changed after work began |
| **Capability gate** | A call presents no valid signature for the authority it claims, or the grant has expired |
| **Evidence gate** | `evidence/` is older than the code it claims to describe |

Each gate is reachable two ways: as a command, which is how CI runs it, and as
an **MCP tool**, which is how an agent product runs it inside its own loop. The
second surface is read-only and returns verdicts only — it issues nothing,
writes nothing, and accepts no verdict as an argument. See
[`08-neighbours.md`](08-neighbours.md) §5.1; the reason it exists is that a
gate outside the agent's loop is a gate that fires when somebody remembers.

### 8.1 The current-API gate

The requirement is: **the model must not write code from the stale API it
remembers from training.** Asking it to "check the docs first" is a prompt, so
it is not enough. The mechanical form of the rule is:

> **Every external symbol the code calls must exist in the version of the
> dependency that is actually installed.**

The gate resolves each import to its installed distribution and version, checks
that every attribute, function signature and endpoint used is present there,
and fails on anything it cannot find — a hallucinated method, a function
removed two majors ago, an argument that no longer exists. It also fails on
symbols the installed version marks deprecated.

This needs no honesty from the model. A remembered API that no longer exists is
simply absent from the installed package, and absence is checkable.

**Not in v1:** blocking dependencies that are end-of-life or carry a known CVE.
That is a different gate against a different data source, and the owner scoped
v1 to the stale-API problem. `[OPEN-3: add a vulnerability gate in v2?]`

### 8.2 Interface gates

trunk-kuli has no interface of its own (§11), but **the products it builds
do**, and interface quality has to survive a model swap exactly as code quality
does. So the harness carries a second set of gates that apply whenever the work
produces a user interface.

The difficulty is that most of what makes an interface good is a judgement
call. The response is the same as everywhere else here: separate what a program
can decide from what it cannot, and never pretend the second is the first.

#### The doctrine the review argues from

A review needs a position to argue from, or two models simply take turns being
agreeable. The position adopted here is Apple's, reduced to the four parts that
can actually be used as instructions:

1. **Clarity.** Text legible at every size, the purpose of each control
   obvious without explanation.
2. **Deference.** The content is the interface. Decoration that competes with
   content loses.
3. **Depth.** Hierarchy and motion carry meaning; they are not ornament.
4. **Subtraction.** The hardest part, and the one usually skipped: a good
   design is mostly a list of things that were left out. One primary action per
   screen, few settings, strong defaults instead of preferences.

Point 4 is made procedural rather than aspirational: **every interface review
must state what was removed**, not only what was added. A review that proposes
only additions is incomplete and is returned.

**Mechanical — a gate decides, no model consulted:**

| Gate | Refuses when |
|---|---|
| **Accessibility** | Contrast below the threshold, an input without a label, an element unreachable by keyboard, a broken focus order, a touch target under the minimum size |
| **Breakpoints** | The page overflows, clips or collapses at any declared viewport width |
| **Design tokens** | A colour, spacing or type size was hard-coded instead of taken from the design system |
| **States** | An interactive component ships without its loading, empty and error states defined |
| **Copy hygiene** | Placeholder text, lorem ipsum, a `TODO`, or a term on the banned-vocabulary list survived into the interface |
| **Visual regression** | The rendered result changed against the approved baseline in a way the plan did not ask for |
| **Budget** | Bundle size or first-render time exceeded the stated budget |
| **One primary action** | A screen declares more than one primary action, so the user is asked to choose between two emphasised things |
| **Settings budget** | The number of user-facing preferences exceeds the cap. Adding one requires a written reason — a setting is usually a decision the designer declined to make |
| **Platform components** | A control was hand-built where the platform provides a standard one |
| **Text scaling** | The layout breaks when text is enlarged to the accessibility maximum |
| **No dead ends** | An error or empty state offers the user no next action |

**Judgement — the debate, then a person:**

Reviewing the source of an interface is not reviewing the interface. So the
adversarial review in §7 works on the **rendered result**: the harness renders
the page headlessly at each declared viewport, captures screenshots, and gives
those to a second provider to attack against the four points of the doctrine
above — is it clear, does it defer to the content, does the hierarchy mean
something, and **what should come out**.

Disagreements route exactly as §7 says: to a gate where the question is
mechanical, to the owner where it is taste. Two models agreeing that a screen
looks fine is not evidence, and is never recorded as approval.

**And the limit, stated plainly:** none of this establishes that a real person
can use the thing. A checklist catches a contrast failure; it does not catch a
screen that is confusing. That is answered by watching someone use it, and by
nothing else. The harness records interface approval as *passed the gates and
survived review* — never as *good*.

---

### 8.3 Ratchet gates — the codebase may not get worse

Every gate so far asks *is this change correct?* None asks *is the codebase
in worse shape than last week?* — and §2.1 is the evidence that this is where
agents actually fail. They pass the checkpoint and erode the code doing it.

A ratchet gate measures a property of the whole repository and **refuses any
change that makes the number worse.** It can be held, or improved. It cannot
be loosened by the thing being measured.

| Measure | What it catches |
|---|---|
| **Structural erosion** — how concentrated complexity is, rather than its total | The patch bolted onto the one function that already does too much |
| **Verbosity** — code volume per unit of behaviour | Three near-identical handlers where one parameterised handler belongs |
| **Duplication** | Copy-paste instead of extraction |
| **Longest function, deepest nesting, widest signature** | Local rot that totals hide |
| **Public surface area** | Exports that only ever grow |
| **Dependency count** | Reaching for a library instead of thinking |

Two rules make this work rather than merely exist:

**The refactor obligation.** When a change would worsen a measure, the change
is not rejected outright — it is returned with the measure named, and it may
proceed only by including the refactor that pays for it. This is the direct
counter to the documented behaviour: an agent left alone patches rather than
restructures, because patching passes the test and restructuring is not asked
for. Here it is asked for, by a program.

**The budget is spendable, with a receipt.** Sometimes a deadline is worth
some erosion. A measure may be worsened by an explicit, owner-approved
exception that records the amount and the reason, and the debt appears in
`evidence/` until it is repaid. Debt taken knowingly is engineering; debt
taken silently is the thing this project exists to prevent.

**Baselines are per project**, taken when the project joins the fleet. The
question is never *is this good code* — which no program can answer — but
*is this worse than it was*, which is arithmetic.

### 8.4 The review-cost gate — slop, defined as an asymmetry

The useful definition of slop is not "bad code". It is:

> **Work that costs far less to produce than it costs to review.**

That definition is a ratio, and a ratio can be measured. Generating a
thousand-line change now costs almost nothing; reading one costs exactly what
it always did. So the gate sets a **review budget** and refuses changes that
blow through it:

- Diff size out of proportion to the acceptance criteria it satisfies. A
  thousand lines serving one criterion is slop by arithmetic, whatever it
  contains.
- A change that mixes unrelated concerns, when it could have been separated.
- Generated or boilerplate volume submitted for human review at all.

A change over budget is **split, not waved through**. The owner's attention is
the scarcest resource in this system (§6.3), and this is the gate that
protects it.

There is a compounding reason to care. Slop replicates: the next run reads
this repository as its context, so a bloated module teaches the next model
what normal looks like here. Which is also why `evidence/` and the memory
files are **pruned, not only appended** — a note that is no longer true is not
neutral, it is a bad example with a long life.

### 8.5 Proof by execution, not by claim

An agent reporting that something works is an opinion. The harness gives it
the means to find out — run the program, call the endpoint, drive the browser,
take the screenshot — and then requires the result.

> **A claim that something works must cite an execution. No execution, no
> claim.**

Evidence carries the command, its exit code and its output. "Should work",
"this will handle", "the logic is correct" are not accepted in place of a run,
and the gate looks for the citation rather than for the model's confidence.

### 8.6 Design-first where change is expensive

Not every decision deserves a design step, and demanding one everywhere is how
a process becomes bureaucracy. What decides is **how painful the decision is
to reverse.**

| Cost of change | What is required before code |
|---|---|
| **Cheap** — copy, styling, an internal helper | Nothing. Build it. |
| **Expensive** — database schema, public API shape, data format, auth and permission boundaries, anything already released | A written design, cross-reviewed by a second provider (§7), approved before implementation begins |

A change touching an expensive surface is **refused when no approved design
exists for it**. The list of expensive surfaces is a file in each project, not
a judgement made fresh each time — because the moment it is a judgement, a
model in a hurry will make it.

Generation is minutes; being wrong about a schema is weeks. The asymmetry is
the whole argument.

---

## 9. How portability is proven, not asserted

A **conformance suite**. Given one task specification and at least two
providers:

1. Run the identical task through each provider.
2. Assert every provider's output is judged by the **same gates**.
3. Introduce a deliberate violation — a criterion with no test, a call to a
   method that does not exist in the installed version, an out-of-scope file —
   and assert **every provider is stopped by the same gate, with the same
   reason**.
4. Record which providers completed the task, how many attempts each needed,
   and which gate stopped them most.

Step 3 is the real test: anyone can call a tool model-agnostic while all their
models happen to succeed. Agreement matters when the answer is *no*.

Step 4 produces a **capability report per model** — which cheap model is good
enough for which kind of work, and what it costs in retries.

---

## 10. The first real workload

The harness exists so the owner can build his later products with it, so its
first job is real product work, not a demo: **continue
[`p2p-lending`](https://github.com/mohoatu/p2p-lending) from Phase 3 under
trunk-kuli.**

That project already has a specification, acceptance criteria with identifiers,
a working traceability gate and committed evidence — so it can be driven by the
harness on day one, and any regression in discipline is immediately visible
against 308 checks that already pass.

The harness is finished when the owner would rather build the next thing
through it than without it. Nothing else counts as done.

---

## 11. Scope

### In scope for v1

- The classified file layout and a library to read and write it
- The four levels, the policy table, and the classification gate
- A credential proxy for L3
- Provider adapters: one hosted, one local, and one further hosted
- The nine gates in §8, the interface gates in §8.2, the ratchet gates in
  §8.3, and the review-cost, execution and design-first gates in §8.4–8.6
- Night runs, the two approval windows, and the approval queue
- Cross-provider and adversarial review, with disagreements routed per §7
- The conformance suite
- `evidence/` generated per run

### Out of scope for v1, by decision

- Cloud hosting. v1 runs on the owner's machine (§6.3).
- Function-scoped permissions — prepared for, not built (§5.1).
- A vulnerability/EOL dependency gate (§8.1).
- **A user interface for trunk-kuli itself.** Its own interface is the file
  system and the terminal. This is not a contradiction of §8.2: the interface
  gates exist for the products it builds, not for itself.
- Automatic failover between providers mid-task. Switching provider is a
  decision, not something that happens silently while work is in flight.
- Any irreversible action taken unattended (§5.2).

---

## 12. Metrics

| Metric | Why |
|---|---|
| Gate agreement across providers | **Target 100%.** The core claim; less falsifies it. |
| Classification leaks — L2+ content reaching a hosted provider | **Target zero.** Any occurrence is an incident, not a bug. |
| Tasks completed overnight with no human unblocking | Whether the night/approval split actually works |
| Approval batch size, and time the owner spends per window | Watched to keep **small**; two short windows was the whole point |
| Attempts per completed task, per model | What a cheaper model really costs |
| **Erosion and verbosity, per project, over time** | The measure SlopCodeBench says rises in ~3 of 4 agent trajectories. A flat line here is the clearest evidence the harness works at all. |
| Ratchet exceptions outstanding, and how long each has been open | Debt taken knowingly is fine; debt never repaid is the old failure wearing a receipt |
| Review budget breaches per week | Whether the factory is producing work faster than it can be read |
| Escaped defects — passed every gate and still wrong | The honest measure of whether these are the right gates |
| Disagreements settled by a gate vs by the owner | A rising share going to the owner means the gates are too weak |

**Not metrics:** number of gates, providers supported, tokens processed. All
rise without anything improving.

---

## 13. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Gates become bureaucracy and get switched off | Every gate must name a real defect it has caught; one that never fires is deleted |
| 2 | The approval windows fill up and become a chore | Batch size is a tracked metric; a growing queue means too much was classified too high, or the agent is asking for too much |
| 3 | Classification is wrong in the unsafe direction | Unclassified defaults to L2; the harness may upgrade alone but never downgrade alone |
| 4 | "Debate" becomes two models agreeing politely and proving nothing | Disagreements are routed to gates or the owner, never to a vote; the disagreement rate is recorded, and a rate near zero is itself suspicious |
| 5 | Escaped defects give false confidence | Mutation testing **on the gates themselves** — a gate must be provably able to fail |
| 6 | Local model too weak for real L2 work | Measured by the capability report, not assumed. If it cannot, the honest outcome is that L2 work is interactive-only. |
| 7 | The project becomes a toy with one user | §10: it must earn its place on real product work |
| 8 | Ratchet gates make every change a refactor argument and work stops | Measures are few and baselined per project; the exception path (§8.3) exists precisely so a deadline does not require disabling the gate |
| 9 | Forward pressure outruns the owner and the queue is approved in bulk | Intake is capped by window capacity (§6.3); approving in bulk is not reviewing, and queue length is a tracked metric |

Risk 5 is the argument from `migration-verify`: a check that can never say no
proves nothing when it says yes.

---

## 14. Open questions

| Ref | Question | Blocks |
|---|---|---|
| OPEN-1 | How long does an unlocked approval window stay open? | §6.2 |
| OPEN-2 | How long before a queued approval request expires? | §6.2 |
| OPEN-3 | Does v2 add a CVE / end-of-life dependency gate? | §8.1 |
| OPEN-4 | Which local model, and is it strong enough for L2 work? | §4, §12 |
| OPEN-5 | Do the gates run during a task or only at the end? During corrects faster; at the end is simpler and harder to game. | architecture |
| OPEN-6 | After N failed attempts at a gate: stop, ask, or escalate to a stronger model? Escalation is attractive and hides that the cheap model never worked. | architecture |
| OPEN-7 | Which erosion and verbosity measures exactly — SlopCodeBench's own definitions, or simpler proxies that are cheaper to compute per change? | §8.3 |
| OPEN-8 | What is the review budget, in diff lines per acceptance criterion? | §8.4 |
| OPEN-9 | Does the ratchet apply per change, or to a rolling window? Per change is strict and may block legitimate large work; a window is kinder and easier to game. | §8.3 |

OPEN-5 and OPEN-6 shape the architecture and are answered before any code.
