# A corridor for agents — what Google's Agent Mesh settles, and what it leaves to us

Assessment, **27/11/2026**. Primary source: the
[`google/agentmesh`](https://github.com/google/agentmesh) repository — its
README, `concepts/architecture` and `concepts/authorization`. Read from the
repository rather than from commentary, because three unrelated projects share
the name *AgentMesh* and the secondary write-ups confuse them.

**Nothing here is adopted.** §6 sets out three options for approval.

---

## 1. What it actually is, in one paragraph

Agent Mesh (previously SAM) is **a private network for AI agents**: a control
plane that admits identities and holds policy, routers that make nodes
reachable, and a node process that runs next to each agent and exposes the rest
of the mesh to it as a local MCP server and an OpenAI-compatible `/v1`
endpoint. Services are named, not addressed — `mcp://code-reviewer`,
`inference://vllm-eu`, `a2a://triage` — and policy is written against those
names. Apache-2.0, pre-1.0, and the README says plainly it is *not an officially
supported Google product*.

**It is not an orchestrator, and does not claim to be.** It answers *may this
caller use this service right now*. It says nothing about whether the work that
came back is any good, who was allowed to accept it, or when the bar was set.
Those are the only questions trunk-kuli asks. The two do not compete; one is
the **where**, the other is the **whether**.

## 2. The three ideas in it that are better than ours

### 2.1 Authority that only ever narrows

A holder may append a `TaskAuthorizationRule` block to its own credential
before handing it to a sub-agent. Every appended block must match the request,
so the effective authority is the **intersection**:

> Standing Policy ∩ TAR₁ ∩ … ∩ TARₖ

Appending can never widen. And the appended block is restricted to a single
opaque fact with *zero rules and zero checks* — the holder cannot smuggle
policy logic into its own token.

This is the same shape as our classification rule (*the harness may upgrade a
level alone, never downgrade alone*), but it holds across a **hop**. Ours does
not. trunk-kuli has no answer today for *agent A, cleared to L1, spawns agent B*
— there is no mechanism preventing B from being handed more than A had.

### 2.2 The host has the last word, and a broken rule stops the node

```yaml
attenuation:
  checks:
    - 'check if label("jurisdiction", "eu");'
  policies:
    - 'deny if service("mcp", "db-writer"), group("contractors");'
```

Two properties worth stealing outright. The node hosting a service can add
conditions **beyond** what the control plane granted — so a central policy
mistake cannot open a local door. And *a syntax error in any statement stops
the node at start*, so a malformed rule can never silently weaken it.

Our ratchet does the opposite today: a missing baseline returns an error string
and the gate declines to judge. Deliberate for a measure. Wrong for a
permission.

### 2.3 Facts the caller cannot author

Credential facts (roles, grants, labels, peer id) are written and signed by the
control plane. Request facts (`service`, `method`, `path`, `host`) are written
by the receiving node from what arrived on the wire. **The caller writes
neither.**

Compare ours. `providers.json` holds every clearance, and it is a file in the
repository — readable and writable by exactly the agent whose clearance it
records. `kuli.json` and `.kuli/baseline.json` were in the same position until
yesterday's separation-of-duties gate, which closes it *in git*, after the fact.
Nothing closes it *at the moment of the call*. This is the real hole Agent Mesh
exposes, and it is ours, not theirs.

## 3. What it would cost to run

- Go binaries — control plane, router, node — plus SQLite or PostgreSQL.
- An OIDC identity provider, or operator-minted bootstrap tokens.
- libp2p on the data path; Biscuit tokens; Datalog policy.
- Pre-1.0, with the sandboxed-agent and mobile pieces in preview.

Set against constitution 9 (*vanilla everything; the prototype must survive
being double-clicked from a USB stick*) and against one developer with weeks of
runway, adopting the software now is not a close call. Adopting the **model**
costs almost nothing.

## 4. What it cannot do for us

| Question | Agent Mesh | trunk-kuli |
|---|---|---|
| May this agent reach this tool? | yes | partly (`toolguard`) |
| Did anything get worse? | — | ratchet |
| Was the bar agreed before the work? | — | contract gate |
| Did the producer accept its own work? | — | duties gate |
| Can the model see this file? | by label, at the hop | by classification, in the bundle |
| Is the record of what happened tamper-evident? | — | the hash-chained trail |

Four of six rows are blank on their side. An orchestrator that only answers the
first row is a network, and we would still have to build everything else. So
the question is not *mesh or kuli* — it is **which layer each rule belongs in**.

## 5. Where the corridor belongs

> **Transport and identity are infrastructure. Judgement is not.**

A gate that decides *whether this work is acceptable* must read the diff, the
measures, the contract and the trail. None of that is network-shaped, and
pushing it into a policy engine turns a program that can explain itself into a
Datalog rule that cannot.

A gate that decides *whether this call may happen at all* must sit where the
call does, outside the caller, and refuse before any data moves. That is
network-shaped, and it is where we are currently weakest.

So: **the corridor lives in trunk-kuli; the door lives at the boundary.** The
orchestrator we want is the thing that holds both — it assigns work, and the
work cannot complete without passing the gates nor begin without a credential
it did not mint itself.

## 6. Options

---

### Option 1 — Take the model, not the software

Three changes, all vanilla Python, no new processes.

**1a. Attenuation that only narrows.** A `Grant` object replaces the current
`(principal, max_level, scope)` tuple lookup. `Grant.narrow(**limits)` returns a
grant that is the intersection of itself and the limits; there is no `widen`.
A sub-task receives `parent.narrow(...)` and nothing else can construct one.
Gate: a test that asserts no code path produces a grant whose level exceeds its
parent's.

**1b. A capability the agent cannot mint.** The harness signs a short-lived
token — `hmac.new` from the standard library, key held outside the repository —
carrying `(provider, clearance, scope, expiry)`. `bundle.assemble` and
`toolguard.check` require a valid token rather than reading `providers.json`.
The agent can still *edit* the registry; it cannot produce a signature, so the
edit buys it nothing until a person re-signs. This is §2.3, at a tenth of the
cost.

**1c. A permission gate that refuses rather than abstains.** `kuli.json` and
`providers.json` get a strict parse at load: unknown key, malformed clearance or
missing field raises, and the call fails closed. Measures may abstain;
permissions may not.

Effort: roughly a day, maybe two. Risk: low. It closes the hop and the
self-granting hole, which are the two live ones.

---

### Option 2 — Run a mesh now

`agentmesh-one` on the laptop, local model and each cloud provider published as
`inference://` services, clearance expressed as a signed label, and L2 enforced
by one line of host attenuation:

```yaml
checks:
  - 'check if label("clearance", "local");'
```

Genuinely stronger than anything we can write ourselves: the enforcement is in
a process the agent does not control, on a credential it cannot forge.

Cost: a Go toolchain, a control plane and a database on the critical path, OIDC
or bootstrap tokens to manage, and pre-1.0 software between the owner and his
own files. Also breaks the single property that makes this project
demonstrable — that it runs from a clean checkout with nothing installed.

**Recommend deferring**, with a written trigger: a second machine, a second
person, or anything running unattended off this laptop.

---

### Option 3 — Define the seam, build one side

Write the orchestrator interface so that "same machine, subprocess" and "mesh
node" are two implementations of one small thing:

```
resolve(service_name) -> endpoint      # names, never addresses
present(grant)        -> credential    # locally signed now, Biscuit later
dispatch(task, grant) -> result        # the gates run on the result either way
```

Build the local implementation; leave the mesh one unbuilt and unreferenced.
Cost: one document and one module of perhaps eighty lines. Buys the right to
take Option 2 later without a rewrite, and costs nothing if we never do.

---

## 7. Recommendation

**Option 1 now, Option 3 as its shape, Option 2 deferred behind a written
trigger.**

Option 1 fixes two holes that exist today on one machine. Option 3 costs
roughly nothing and is the difference between a later migration and a later
rewrite. Option 2 is correct engineering for a fleet of machines and premature
for a laptop, and the honest reason to say no to it is runway, not design.

The sentence worth keeping from all of this is theirs, and it is the one our
permission code does not yet obey:

> *A caller writes neither.*

---

## 7.1 Adopted — 27/11/2026

**Option 1 built, Option 3 built on the local side, Option 2 deferred.**
265 checks, up from 202.

```bash
kuli grant --provider cloud --level L0 --scope src      # what a sub-task holds
kuli capability --provider cloud --ttl 300 --level L1   # signed, expiring
kuli capability --verify <token>                        # what a token carries
```

Three modules, no dependencies. `kuli/grants.py` is the grant and `narrow`;
`kuli/capability.py` is `hmac` over a grant, with the key refused if it lives
inside the repository; `kuli/gateway.py` is `resolve` / `present` / `dispatch`,
with the mesh transport deliberately absent and refused by name.

`bundle.check_part` and `toolguard.check` now judge against a **grant** rather
than a registry entry — a registry entry is coerced into the root grant it
describes, so the ceiling still comes from the file and the limit that applies
comes from the hop. §5.1.1 of the specification carries the rule.

Option 2's trigger, written down so it is not a mood: **a second machine, a
second person, or anything running unattended off this laptop.**

### What the gates caught this time

**The ratchet refused `Grant.refusal`** at complexity 11 against a ceiling of
8 — one function answering *why is this not permitted* for level, scope, tools
and expiry at once. Split into three helpers plus the expiry check. Paid with
a refactor, not an exception, which is now four times out of four.

**A test pinned a parameter name**, not the property it meant to pin:
`assemble` takes *two* arguments and offers no way to soften a refusal, which
is the point; it was asserting the second one was called `provider`. Renaming
it to `authority` broke a check that should not have been sensitive to the
name. The check was updated with the rename rather than the rename abandoned —
recorded here because the other reading of that sequence is a test being bent
to fit the code, and the difference is only visible if somebody says which it
was.

---

## 8. Appendix — the duties gate refused the commit that introduced it

For the record, because the alternative is quietly not mentioning it.

```
$ kuli duties --base HEAD~1
1 commit(s) since HEAD~1, 1 touching the rules

  ee767ea8dc24
      A1: it changes the rules (.github/workflows/verify.yml) and the work
          they judge (9 other file(s)) in one commit. Split them, so the
          relaxation is the only thing in its own diff.
      A2: it changes the rules (.github/workflows/verify.yml) with no second
          actor. Add a 'Rules-approved-by: <name>' trailer.
```

`ee767ea` is the commit that *added* `kuli duties`. It necessarily changed a
rule file (the workflow that runs the new gate) alongside the code the gate
judges, and it carried no approval trailer, because the trailer did not exist
yet. The gate is reading its own introduction correctly.

Three things follow.

**The history stands.** The constitution forbids rewriting `main`, and a gate's
first act will not be to make us break a rule to satisfy it. The violation stays
visible here instead.

**The CI job did not fire**, because it ran only on `pull_request` and this went
straight to `main`. That was the gate's real weakness, not the bootstrap: a
rule enforced on one path and not the other is enforced on neither. **Fixed
27/11/2026** — the `procedure` job now runs on push as well, comparing against
`github.event.before` there and against the target branch on a pull request,
falling back to `HEAD~1` on a new branch and abstaining when there is nothing
to compare. The commit that made that change touched only the workflow and
carried a `Rules-approved-by:` trailer, which is the gate's own prescription
followed rather than argued with.

**`.github/workflows/` may be too broad for `RULE_FILES`.** Any commit that adds
a workflow beside code now trips A1 — which is right for a workflow that *relaxes*
a gate and heavy-handed for one that adds an unrelated job. Narrowing it to the
workflows that run gates is possible; leaving it strict is defensible. Not
deciding it silently.
