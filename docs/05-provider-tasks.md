# Adding providers — the work, in small pieces

Breaks down [`04-providers.md`](04-providers.md). Proposed **26/11/2026**.

**How to read a task.** Each has a **done-when** that is observable, its
dependencies, and a size: **S** under half a day, **M** half a day to a day.
Nothing here is L — anything that stays L once started is still two tasks
pretending to be one.

Each phase ships something usable on its own. The order is chosen so that
**every boundary is built and tested before there is anything valuable behind
it** — no key exists until P15, and by then the boundary it protects has been
wrong and fixed several times already, cheaply.

---

## P0 — Describe what already exists

No new capability. This phase only writes down the provider that is already
in use, so the next phases have something to compare against.

### T1 — Provider registry · S · **done 26/11/2026**
`providers.json` plus a loader, and `kuli providers` to list them.

- **Done when:** `kuli providers` prints one row — Claude Code — with its
  clearance, adapter shape (`agent-product`) and capability manifest, read
  from the file rather than hard-coded.
- **Depends on:** nothing

### T2 — The trail records who, for real · S · **done 26/11/2026**
`actor.provider` and `actor.model` currently say `unknown`.

- **Done when:** a recorded entry carries the provider id from the registry,
  and a test asserts the field is never `unknown` when a registry entry
  exists for the running process.
- **Depends on:** T1

### T3 — `kuli report` · S · **done 26/11/2026**
Per-provider totals from the trail: actions, tools used, days active.

- **Done when:** it prints a table with one row per provider, and prints
  nothing but a clear message when the trail is empty.
- **Depends on:** T2

---

## P1 — The boundary, before any provider can use it

Pure logic. No network, no model, no keys. All of it testable in a
temporary directory, which is why it comes before anything that costs money.

### T4 — Classification resolver · M
Given a path, return its level: from `kuli.json`, from defaults, and
**unclassified means L2**.

- **Done when:** boundary tests cover each rule, and a path matching no rule
  at all resolves to L2 rather than L0.
- **Depends on:** nothing

### T5 — Bundle, and the assembler that refuses · M
A `Bundle` carries parts and the highest level among them. Building one for a
provider whose clearance is lower **raises**; it never drops content.

- **Done when:** a negative test proves an L2 part cannot be placed in a
  bundle destined for an L1 provider, and that the error names the part. No
  code path downgrades anything.
- **Depends on:** T4

### T6 — The return-path check · M
Every tool *result* is classified before it re-enters a provider's context.

- **Done when:** a test has an L1 provider request a file resolving to L2
  through a tool, and asserts the result is refused and the refusal recorded
  in the trail. **This is the leak the design exists to stop; it gets its own
  test file.**
- **Depends on:** T4, T2

---

## P2 — The local model, because it is the cheapest place to be wrong

No key, no bill, no vendor. Every boundary above gets exercised against a
real model before one exists that could leak anything.

### T7 — `openai_compatible` adapter, text only · M
One call, no tools: messages in, text out.

- **Done when:** it holds a conversation with a local Ollama endpoint, and
  the same code path reaches a second OpenAI-compatible endpoint with only a
  config change.
- **Depends on:** T1, T5

### T8 — Local clearance is verified, not declared · S
Loopback check and no outbound network allowance, at startup.

- **Done when:** a local provider configured with a non-loopback endpoint
  **is demoted to L1 and says so**, rather than being disabled or silently
  trusted.
- **Depends on:** T1, T7

### T9 — Tool calling · M
Tool definitions out, tool calls back, results in — through T6 on the way
back.

- **Done when:** a local model completes a two-tool task, and every call and
  result appears in the trail.
- **Depends on:** T7, T6

### T10 — The runner · M
kuli's own agent loop for raw models: load context, call, dispatch tools,
record, stop.

- **Done when:** a raw local model completes a small real task end to end,
  and its trail is indistinguishable in shape from a Claude Code run's.
- **Depends on:** T9

---

## P3 — Conformance, the admission test

### T11 — Run one task through two providers · M
- **Done when:** the same task goes to Claude Code and to the local model,
  and both outputs are judged by the same gates with the verdicts recorded
  side by side.
- **Depends on:** T10

### T12 — The deliberate violations · M
Three cases: a criterion with no test, a call to a method absent from the
installed version, a file outside the agreed scope.

- **Done when:** **both providers are stopped by the same gate, with the same
  reason**, for all three — and the test fails loudly if they are stopped by
  different gates.
- **Depends on:** T11

### T13 — The classification probe · S
Ask each provider, through a tool, for content above its clearance.

- **Done when:** the boundary refuses it, the refusal is in the trail, and
  the content never appears in any recorded context.
- **Depends on:** T11, T6

### T14 — The capability report · S
- **Done when:** one table — per provider: tasks completed, attempts each
  needed, which gate stopped it most, cost where known. **Costs stay blank
  rather than guessed.**
- **Depends on:** T12

---

## P4 — The first cloud provider

Only now, when nothing above has needed a key.

### T15 — Egress proxy · M
A separate process holding credentials, with an endpoint allowlist.

- **Done when:** the adapter completes a cloud call **without the key being
  present anywhere in its process**, a call to an endpoint not on the list is
  refused, and both appear in the trail.
- **Depends on:** T7
- **Note:** `[OPEN-14]` asks whether this starts as a library instead. A
  library is faster and is trust rather than a boundary; the done-when above
  assumes the process, and should be renegotiated rather than quietly
  relaxed.

### T16 — Admit one cloud provider · S
A config row, then conformance.

- **Done when:** the provider passes T12 and T13 unchanged, and appears in
  the capability report. **If it needs a change to a gate in order to pass,
  it is not admitted** — that would mean the gate was provider-specific, and
  the whole claim with it.
- **Depends on:** T14, T15

---

## Order, and what it costs to reorder

```
T1 ─ T2 ─ T3
 │    └──────────────┐
 └─ T5 ◄─ T4 ─► T6 ◄─┘
      └─ T7 ─ T8
           └─ T9 ─ T10 ─ T11 ─ T12 ─ T14 ─ T16
                            └─ T13        T15 ─┘
```

P1 before P2 is the one that must not be swapped. Building the adapter first
and the boundary afterwards means the boundary is designed around what the
adapter already does — which is how an adapter ends up deciding what it is
allowed to see.

## Not in this list, on purpose

- **Choosing the cloud provider.** `[OPEN-10]`, decided at T16 against the
  figures of that week, not from memory now.
- **A second cloud provider.** After T16 it is a config row; if it is not,
  something in T1–T15 was done wrong and that is the thing to fix.
- **Cost recording.** It needs response fields the hook payload does not
  carry; it belongs with T14 and is listed there as blank-not-guessed.


---

## P0 as built — 26/11/2026

Three commands: `kuli providers`, `kuli providers --init`, `kuli report`.
94 checks, up from 69.

**Detection rules are data, not code.** Which provider is running is decided
by rules written in `providers.json` — an environment marker, optionally with
a required value. Adding a provider must never mean editing a module, and
`kuli/providers.py` contains no vendor name anywhere.

**The registry refuses rather than repairs.** A missing field, a clearance
outside L0–L3, an unknown shape or adapter, two providers sharing an id: each
raises. There is no default registry and no fallback entry, so an absent file
means *no providers*, and the active provider is `unknown`. A guessed
provider in an audit trail is worse than an honest gap, and the command says
so in those words.

**`shape` is recorded from the start** — `agent-product` for Claude Code,
`raw-model` for what comes next — because the two need different handling and
a field added later is a field half the rows are missing.

**The trail takes the provider from the registry, not from the event.** The
event is written by the agent; the registry is not. Entries now carry
provider, model and the clearance that was in force, so *"which model wrote
the code that eroded this module"* became answerable today rather than at
T16.

Adding this tripped kuli's own ratchet on verbosity — paid for by splitting
`cmd_providers` and `cmd_report`, not by an exception.

**Next:** T4 — the classification resolver. Pure logic, no network, no model.
