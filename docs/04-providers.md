# Adding providers — architecture

Proposed **26/11/2026**, for review. Nothing here is built yet.

The goal: one cloud provider besides Claude (Grok, Gemini or similar) and one
local model, added **without weakening a single rule already designed**.

---

## 1. The trap this design exists to avoid

The obvious architecture is an interface with `send(messages, tools)` and a
factory that picks one. It takes an afternoon, and it quietly breaks three
rules at once:

- The adapter ends up assembling its own context, so **it decides what the
  provider sees** — and the L2 boundary becomes a thing an adapter is trusted
  not to cross.
- Provider differences leak upward as `if provider == ...`, and
  "model-agnostic" becomes a slogan.
- Everything is attempted everywhere, so a small local model is handed work
  it cannot do, fails for ten minutes, and the harness calls that a model
  problem.

So the architecture below is organised around **what must be impossible**,
not around what must be callable.

---

## 2. Two adapters, not five

Grok, Gemini, DeepSeek, Ollama and llama.cpp all speak the OpenAI
chat-completions shape, natively or through a compatibility endpoint. Claude
has its own Messages API.

> **Write two adapters. Everything else is configuration.**

| Adapter | Speaks | Covers |
|---|---|---|
| `openai_compatible` | `/v1/chat/completions` | Grok, Gemini (compat endpoint), DeepSeek, Ollama, llama.cpp, LM Studio |
| `anthropic` | Messages API | Claude |

A provider is then a row of data — base URL, model name, clearance,
capability manifest — not a new module. Adding DeepSeek later is an entry in
a file.

### 2.1 Two integration shapes, and the difference matters

This is the distinction most designs skip, and it is the one that bites here.

| Shape | What it is | Examples |
|---|---|---|
| **Agent product** | Already has its own loop, tools and permissions. kuli *wraps* it: hooks record, the CLI gates its output. | Claude Code, Cursor |
| **Raw model** | Just an endpoint. kuli supplies the loop, the tools and the limits. | Grok, Gemini, Ollama |

These are not interchangeable, and pretending they are produces a harness
that works in one and is theatre in the other. kuli therefore has **two entry
paths with one contract**: whatever the shape, the run must produce the same
trail entries and pass the same gates. The conformance suite (§7) is what
proves it, and until a shape passes it, it is not supported.

---

## 3. The classification boundary is not the adapter's job

**An adapter must not be able to send what it is not cleared to see.** Trust
is not a mechanism, so the adapter is never given the choice.

```
   brain (classified files)
            │
            ▼
   context assembler ──► Bundle{ max_level, parts[] }
            │                        │
            │   refuses to build a bundle above
            │   the target provider's clearance
            ▼
       adapter  ──►  provider
```

The adapter receives a **bundle**, never a path and never the brain. A bundle
carries the highest level it contains; constructing one for a provider whose
clearance is lower **fails, and does not downgrade the content**. A run that
needs L2 on a hosted provider switches to the local model or stops.

Direction of travel, not v1: run adapter processes where the brain's files
are not readable at all, so the boundary is enforced by the operating system
rather than by code that could have a bug. Worth naming now so the interfaces
do not make it impossible later.

### 3.1 The return path is where the leak actually happens

A provider does not leak by reading its prompt. It leaks by **calling a
tool** — `read_file("business/legal/contract.md")` — and having the result
handed back into its context.

So classification is checked **twice**:

1. **Inbound**: when the bundle is assembled.
2. **Outbound**: on every tool *result*, before it re-enters the provider's
   context.

The second check is the one people forget, and it is the one that matters,
because the model chooses the argument.

### 3.2 Keys are L3, so no adapter holds one

API keys for Grok and Gemini are secrets, and §4.1 of the specification says
no model reads a secret. The adapter therefore sends through an **egress
proxy** that attaches the credential:

- the adapter never sees the key;
- every outbound call passes one place, so the trail is complete by
  construction rather than by the adapter remembering to log;
- the set of reachable endpoints is a list, so a provider adapter cannot
  quietly talk to somewhere else.

### 3.3 The local model's clearance is checked, not promised

The local model is cleared for L2 **because** nothing leaves the machine.
That is a claim, and claims get verified here:

- its endpoint must resolve to loopback;
- its process must have no outbound network allowance;
- the check runs at startup, and a failure drops its clearance to L1 rather
  than disabling it silently.

A local model that can reach the internet is a hosted model with extra steps.

---

## 4. Capabilities are data, and routing is a written rule

Each provider carries a manifest:

```json
{
  "id": "gemini-flash",
  "adapter": "openai_compatible",
  "base_url": "…",
  "clearance": "L1",
  "capabilities": {
    "tool_calling": true,
    "parallel_tool_calls": false,
    "json_mode": true,
    "context_tokens": 1000000,
    "max_output_tokens": 8192
  },
  "cost_per_mtok": { "in": null, "out": null },
  "good_for": ["summarise", "classify", "draft"],
  "not_for": ["multi-step refactor"]
}
```

A task declares what it needs. **A provider whose manifest does not satisfy
the task is not offered the task** — it is not tried and allowed to fail.

This is the honest handling of §3 of the specification: *the floor is the same
everywhere, not the ceiling.* A small local model is not bad, it is
**eligible for less**, and saying so in a manifest is better than discovering
it at two in the morning over ten failed attempts.

Costs are left `null` deliberately. They are filled from the capability
report the conformance runs produce, not from a price list copied from a
website that changes.

---

## 5. Where cross-checking happens

§7 of the specification asks for two providers disagreeing, and this is where
the design gets its payoff: **the two providers must not share a failure
mode.** Two runs of the same model agreeing proves very little.

| Review | Who |
|---|---|
| Cheap and frequent | local model reviews cloud output |
| Expensive and rare | cloud reviews cloud, different vendor |
| Judgement calls | neither — the owner, per §7 |

And the rule that stops it being theatre stands unchanged: **a disagreement
is never settled by models voting.** Mechanical questions go to a gate;
everything else goes to the approval queue.

---

## 6. Everything still passes through the same gates

Nothing above touches the gates, and that is the point:

- `kuli ratchet` and `kuli review-cost` judge the diff; they never learn which
  model produced it.
- The trail records provider and model on every entry, so *"which model wrote
  the code that eroded this module"* becomes answerable — the field is already
  in the schema, currently `unknown`.
- Irreversible actions still need the owner, whichever provider asked.

---

## 7. How a provider is admitted

A provider is not added by writing a config row. It is admitted by **passing
conformance**, and this is the acceptance test:

1. The same task runs through the candidate and through an already-admitted
   provider.
2. Both outputs are judged by the same gates.
3. A deliberate violation is introduced — a criterion with no test, a call to
   a method absent from the installed version, an out-of-scope file — and
   **both must be stopped by the same gate, with the same reason**.
4. The trail from both runs must be complete and chain-verifiable.
5. A classification probe: the provider is asked, through a tool, for content
   above its clearance, and the request **must be refused by the boundary and
   recorded**.

Step 5 is new here and is the one that matters for a multi-provider system.
Steps 3 and 5 are both about the answer being *no*: anyone can look
model-agnostic while everything succeeds.

Output: the provider's row in the **capability report** — what it completed,
how many attempts it needed, which gate stopped it most, and what it cost.

---

## 8. Build order

| # | Step | Why first |
|---|---|---|
| 1 | Capability manifest + registry, with Claude Code described as the one existing provider | Describes what exists before adding to it |
| 2 | Trail records provider and model for real | The field exists and says `unknown`; fix before there is more than one |
| 3 | `openai_compatible` adapter + **local model only** | No key, no egress, no cost — the cheapest place to be wrong |
| 4 | Conformance suite, run against local vs Claude Code | The admission test has to exist before the thing it admits |
| 5 | Egress proxy for credentials | Required before any cloud key exists anywhere |
| 6 | First cloud provider through the proxy | Last, because by then it is a config row |

**The local model comes before the cloud one**, which is the reverse of the
obvious order. It has no key to leak, no bill to run up and no vendor to
blame, so every boundary in §3 can be got wrong cheaply first.

---

## 9. Choosing the cloud provider

Not decided here, and deliberately not from memory: prices, limits and
capabilities move monthly. The selection criteria, in order:

1. **Does it speak the OpenAI-compatible shape?** If yes, it costs a config
   row rather than an adapter.
2. **Does it fail differently from Claude?** The whole value of a second
   opinion is an independent failure mode. Two models trained on similar data
   agreeing is weak evidence.
3. **Tool calling that works under load**, not just in the documentation.
4. **Price per solved task**, measured by conformance — not price per token.

`[OPEN-10]` Which cloud provider, decided against current figures when step 6
is reached.

---

## 10. Open questions

| Ref | Question |
|---|---|
| OPEN-11 | Which local model, and is it strong enough for real L2 work, or only for review and classification? |
| OPEN-12 | When a bundle exceeds a provider's context window — summarise, split the task, or refuse? Summarising silently loses the detail a gate might have needed. |
| OPEN-13 | Is cross-provider review run on every task, or sampled? Every task doubles the cost; sampling means some work is never second-guessed. |
| OPEN-14 | Does the egress proxy run as a separate process from day one, or start as a library the adapter calls? The library is quicker and is trust rather than a boundary. |

OPEN-12 and OPEN-14 shape the interfaces and should be answered before step 3.
