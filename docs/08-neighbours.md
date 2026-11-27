# Two Vietnamese neighbours, read for what they already solved

Assessment, **27/11/2026**. Sources: the published home pages of
[Aevum OS](https://www.aevum.ai.vn/) (I2FLabs, Ho Chi Minh City) and
[Tratha AI](https://ai.tratha.com/), read as marketing copy, which is what
they are. Nothing here is verified by running either product, and both pages
make claims about themselves that this document does not repeat as fact.

**Nothing is adopted.** §5 sets out four proposals for approval.

---

## 1. Why these two are worth reading

They are not competitors. They are the two halves of the same problem this
project left alone, each solved further than here:

| Layer | Aevum OS | Tratha AI | trunk-kuli |
|---|---|---|---|
| Memory across sessions | **its whole product** | — | not built |
| Coordination between agents | squads, local | **its whole product** | not built |
| A verdict on the work | — | — | **its whole product** |

Aevum owns remembering. Tratha owns assigning. Neither of them judges the
output, and that is not an oversight on their part — it is a different
product. The useful consequence is that kuli is the layer both of them would
need, which is a better position than being a third entrant in either race.

The uncomfortable half of the comparison is just as real. Aevum ships an
installable desktop app for macOS and Windows at `v2.0.0-beta.8`. Tratha runs
a live hosted hub at `v4.60.0` with version notes landing through the evening.
This project has 265 checks and no users. **They are ahead on product; this is
ahead on rigour.** For one person with weeks of runway, the lesson pointing
back is about distribution, not about features.

## 2. Aevum OS — what it got right that is missing here

**It is an MCP server, not a CLI.** Any agent product that speaks Model
Context Protocol can call it, without it having to wrap that product. This
project's two integration shapes (`agent-product` that kuli wraps, `raw-model`
for which kuli supplies the loop) solve the same problem from the other side,
and the wrapped side is the awkward one: wrapping Claude Code means living
outside its loop and hoping the hooks fire. An MCP surface inverts that — the
agent calls the gate because it is a tool, in the loop, every time.

This is the single most valuable thing on either page.

**Edits run in a copy-on-write partition and reach disk on approval.** Every
gate here judges *after* the write: the ratchet reads the working tree, the
duties gate reads git. A refusal therefore arrives after the damage, and the
repair is a revert. A staging layer makes a refusal free.

**It is packaged.** Download for Windows, download for macOS, three-minute
install. `python -m kuli.cli` is a correct answer to a question nobody outside
this repository has asked.

**What not to copy.** Seven named personas — An, Kael, Nia, Iris, Luna, Vidus,
Zenith — are theatre unless a program decides who may accept whose work, which
is what §8 A1 does here and what a persona list does not. And the page's
measured claims render as `0%`, `0%`, `0%`, `0.0x`, `0h`: whatever those
counters animate to in a browser, the published document contains no values.
This project's own metrics are deliberately blank until measured, which is the
same decision made visibly rather than invisibly.

## 3. Tratha AI — the orchestrator question, answered at the app layer

This is directly the thing asked for in
[`07-orchestrator.md`](07-orchestrator.md): an orchestrator at the application
layer. Six role levels from founder to member, scoped API keys in three tiers,
a task queue agents claim and complete, per-organization isolation, a REST
namespace `aah/v1`.

Three mechanisms are better than ours.

**Capability filtering on the offer, not refusal on the call.** *"An agent is
never offered work it can't do."* This project refuses at `dispatch` — correct,
and the wrong end of the pipe. A grant already lists the tools it permits, so
the same data can filter a queue before an agent ever sees it. Refusal is the
backstop; filtering is the design.

**A bounded retry that cannot loop and cannot vanish.** *"Permanently failed
after three attempts, never silently lost."* The trail records attempts and
bounds nothing. A task that fails forever is a night run that burns tokens
until morning, which matters here specifically because unattended night runs
are in the design (§6.2).

**"Anyone can only appoint roles below their own."** The hierarchy enforces
itself. That is Agent Mesh's attenuation rule arrived at from org design rather
than from cryptography — and with `Grant.narrow`, three independent sources now
describe the same constraint. Independent arrival is weak evidence, but it is
evidence, and it is the second time this week it has pointed the same way.

**What not to copy.** The public live room is the interesting one to be honest
about. Read as text, most of it is agents reporting status to each other —
*"v4.60.0 still about 85%"*, *"Noted, mod"*, the same figure restated by three
accounts in four minutes. That is a wall of claims, which is exactly what this
project's opening argument says not to trust. It is also charming, and it is
plainly working as marketing. Both things are true.

More substantively: a task is complete when the agent says it is. There is no
verdict from anything other than the producer. That is the hole kuli exists to
fill, and seeing it in a shipped product is the clearest argument yet that the
hole is real.

## 4. What this changes about positioning

Not the design. The **order**.

Both neighbours are local-first, both integrate through MCP or REST rather than
by replacing the editor, and both are Vietnamese and shipping. The thesis here
— that a harness is a set of gates in ordinary code, identical whichever model
produced the output — is not contradicted by either. It is simply unshipped.

So the honest read is that the next thing worth building is not a seventh gate.
It is the surface that lets the existing gates be called by something other
than this repository's own CI.

## 5. Proposals

---

### P1 — expose the gates as an MCP server

`kuli serve` publishes the gates as MCP tools: `ratchet`, `classify`,
`review_cost`, `duties`, `contract_check`, `capability_verify`. Any agent
product that speaks MCP then calls them in its own loop, and the awkward
`agent-product` shape stops needing a wrapper.

The gates stay deterministic programs; this only changes who may invoke them.
The one hard constraint is constitution 9 — no dependencies — so the transport
is a hand-written stdio JSON-RPC loop over the standard library, not an SDK.

Effort: two to three days, most of it protocol conformance rather than logic.
**Recommended first**, because it is the thing that makes everything already
built reachable.

---

### P2 — filter the offer, not just the call

`gateway.offer(tasks, grant)` returns the subset of a queue a grant permits,
using `Grant.tools` and `Grant.scope` that already exist. `dispatch` keeps
refusing, as the backstop it should have been all along.

Effort: half a day. Pure addition, no change to anything that passes today.

---

### P3 — bound the retry, in the trail

An attempt counter per task, a ceiling, and a terminal `failed` state recorded
rather than retried. Matters most for the unattended night window, where
nobody is watching a loop.

Effort: half a day, and it needs the runner (T10) to have something to count.
**Defer until T10.**

---

### P4 — copy-on-write staging

`kuli stage <command>` applies a change to a shadow tree, runs the gates
against that tree, and writes to the real one only when they pass. Turns every
refusal from a revert into a no-op.

Honest cost: this is the largest of the four, it touches how every gate
resolves paths, and done carelessly it introduces a second source of truth
about what the repository contains — which is a worse defect than the one it
fixes. Worth doing, not worth doing third.

---

## 5.1 Adopted — 27/11/2026

**P1 built.** 320 checks, up from 277.

```bash
kuli serve        # newline-delimited JSON-RPC 2.0 on stdin/stdout
```

Six tools: `ratchet`, `classify`, `review_cost`, `duties`, `contract_check`,
`capability_verify`. No SDK — `kuli/mcp.py` is a hand-written loop over the
standard library, because an SDK here would have been the project's first
dependency.

Three rules decide what the surface exposes, and they matter more than the
wire format.

**It is read-only.** Every tool returns a verdict; none writes a file. There
is no `baseline`, no `contract freeze`, no `providers --init`, no `capability`
minting. An agent may ask *would this pass* as often as it likes and has no
way to move a bar through this door. Lowering a bar stays what it was: a
commit, alone in its diff, with a person's name in the trailer. A test asserts
this by reading the module's own source for call-shaped writes.

**A verdict is never an argument.** No tool accepts a level, an allowance, a
clearance or a pass/fail. The caller says what to look at; the gate says what
it found. A surface that let a model pass in the answer would be a prompt with
a JSON schema, and a test pins the input field names against that list.

**Cannot judge is not a pass.** No baseline, no criteria claimed, no such
contract — `isError: true` and a text beginning `CANNOT JUDGE`. A refusal is
the tool *working*, so it returns `isError: false` beginning `REFUSED`; an
agent that treated a refusal as a crash would retry it.

To use it from an agent product, point the product at this repository:

```json
{ "mcpServers": { "kuli": { "command": "python",
                            "args": ["-m", "kuli.cli", "serve"] } } }
```

**P2 built.** 341 checks.

```bash
kuli offer --provider cloud --level L1 --tools mcp://audit < queue.json
```

```
  offered   mcp://audit
  withheld  mcp://audit     L2 is above cloud, which holds L1
  withheld  mcp://deploy    mcp://deploy is not a tool cloud may call
  withheld  mcp://audit     L3 is above cloud, which holds L1
```

`gateway.offer(tasks, grant)` returns the subset of a queue a grant permits.
`withheld(task, grant)` is the single function that answers it, and `dispatch`
calls the same one — a filter and a refusal that answer the same question in
two pieces of code eventually disagree, and that disagreement is a permission
bug nobody is looking for. A test round-trips the queue through both and
asserts *offered* and *dispatchable* are the same set.

The MCP tool takes a **token**, never a level. A tool that has to be told who
is asking is exactly where "a verdict is never an argument" would quietly
break; a signature cannot be claimed, so authority arrives verified or not at
all.

**Two limits, both decisions rather than oversights.**

A task is judged on what it **declares**: its service, and the classification
level of every path it names. A task that names no paths is judged on its
service alone — the gate cannot classify what it was not told about. The
return-path check is what stands behind a task that declared nothing.

And *unclassified means L2*, so in a repository with no `classification` rules
an L1 provider is offered **nothing that declares a path**. That is the
cautious default doing its job, and it means `offer` is only useful once a
project has written its rules down. `kuli.json` here now classifies this
repository, which is public in full; the fleet needs the same before this gate
says anything interesting to it.

P3 and P4 are unchanged and unbuilt.

## 6. Recommendation

**P1 now. P2 alongside it, because it is half a day. P3 with T10. P4 only
after P1 has a user.**

The reason to put P1 ahead of the remaining provider work is in §4: the gates
exist, they are tested, and nothing outside this repository can call them.
That is a distribution problem wearing an engineering costume, and the
neighbours read here are both further along precisely on that axis.
