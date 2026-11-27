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

### T4 — Classification resolver · M · **done 26/11/2026**
Given a path, return its level: from `kuli.json`, from defaults, and
**unclassified means L2**.

- **Done when:** boundary tests cover each rule, and a path matching no rule
  at all resolves to L2 rather than L0.
- **Depends on:** nothing

### T5 — Bundle, and the assembler that refuses · M · **done 27/11/2026**
A `Bundle` carries parts and the highest level among them. Building one for a
provider whose clearance is lower **raises**; it never drops content.

- **Done when:** a negative test proves an L2 part cannot be placed in a
  bundle destined for an L1 provider, and that the error names the part. No
  code path downgrades anything.
- **Depends on:** T4

### T6 — The return-path check · M · **done 27/11/2026**
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

### T7 — `openai_compatible` adapter, text only · M · **built 27/11/2026, one half unverified**
One call, no tools: messages in, text out.

- **Done when:** it holds a conversation with a local Ollama endpoint, and
  the same code path reaches a second OpenAI-compatible endpoint with only a
  config change.
- **Depends on:** T1, T5

`kuli/adapters.py`, `urllib` only. 367 checks, up from 341, including six
against **real HTTP servers on real sockets** rather than a patched function —
§8.5 asks for an execution, and a mock proves the test agrees with itself.

**The second half of the done-when is proven. The first is not.** There is no
Ollama and no local model on this machine — nothing listening on 11434, 1234,
8080, 5000, 8000 or 3000, and no `ollama` binary. So the adapter has been
exercised against OpenAI-compatible endpoints over HTTP, which is the same
wire contract, and **not** against a real model. That is a gap in the evidence,
not a detail: a real model returns a different content shape when it feels
like it, and this adapter has never been disappointed by one.

To close it:

```bash
ollama serve &
ollama pull qwen3:8b
kuli ask --provider local-llm --prompt "say hello in five words"
```

#### What it does today, run rather than asserted

```
$ kuli ask --provider local-llm --prompt "summarise this in one line" --context CLAUDE.md
model qwen3:8b saw 3584 system char(s) and was asked: summarise this in one line

$ kuli ask --provider local-llm --prompt "what is here" --context .env
.env is L3. No provider may be given a secret in context, including one
cleared to L3; the credential proxy injects it into the request instead.
$ echo $?
2

$ KULI_LOCAL_ENDPOINT=… KULI_LOCAL_MODEL=llama3.2:3b kuli ask --provider local-llm --prompt "which model are you"
model llama3.2:3b saw 0 system char(s) and was asked: which model are you
```

The middle one is the interesting line. The refusal happens in the
**assembler**, before a socket is opened — the adapter never had the choice.

#### Where the adapter sits, which is the point of it

- **It receives a bundle and cannot build one.** No assembler is imported and
  none is called; a test reads the module's own source to keep that true. An
  adapter that assembled its own context would decide what it may see, and the
  classification boundary would be decoration.
- **The bundle must have been stamped for this provider.** `assemble` writes
  the provider id onto the bundle and `complete` refuses a bundle built for
  anyone else — otherwise a bundle assembled for a local model cleared to L2
  could be handed to a hosted one cleared to L1 with every gate passing on the
  way.
- **The key lives in the header and nowhere else.** Read from the environment
  variable the entry names, never in the body, never in the trail, never in an
  error message. A test asserts the key does not appear in the posted JSON.
- **A refusal quotes nothing.** An HTTP error names the status and says the
  response is not quoted, for the same reason a classification error does not
  quote the content it refused.
- **Recording belongs to the runner (T10).** An adapter that writes the record
  of its own call is an agent logging itself.

### T8 — Local clearance is verified, not declared · S · **done 27/11/2026**
Loopback check and no outbound network allowance, at startup.

- **Done when:** a local provider configured with a non-loopback endpoint
  **is demoted to L1 and says so**, rather than being disabled or silently
  trusted.
- **Depends on:** T1, T7

`providers.verified(entry)` returns the clearance an entry has **earned** and
the reason. `load()` applies it, so every consumer — the assembler, the
return-path check, the trail — sees the earned level and not the declared one.
396 checks, up from 367.

The rule: **a clearance above L1 must be shown.** L2 means *only this model
may see confidential content*, which is true only if the model runs here, and
the cheap evidence for that is a loopback endpoint. An entry that cannot show
one is demoted to L1 with a reason, rather than disabled — which would make
the harness unusable — or trusted, which is the failure this exists to
prevent.

Three decisions inside it.

**A name that merely resolves here does not count.** `localhost` and
`*.localhost` are reserved for the loopback interface by RFC 6761, so they
pass without a lookup. Any other name is refused even if it resolves to
127.0.0.1 today: a DNS answer is not a property of the address, and a
clearance that depends on a lookup is one that changes without anybody editing
anything.

**Verification reads the endpoint the call will actually use.** The effective
value comes from `endpoint_env` when that variable is set, so
`providers.setting` is shared with the adapter. Checking the inline endpoint
while the request went to the one in the environment would be theatre, and a
test pins the two to the same host.

**Demotion only lowers.** L0 and L1 need no proof and are returned untouched;
L3 without a loopback endpoint is demoted to the ceiling, L1, not one step.

```
$ kuli providers
ID               CLEARANCE      SHAPE              ADAPTER
local-llm        L1             raw-model          openai_compatible

  local-llm: declared L2, demoted to L1: https://api.example.com is not a
             loopback address
```

**Half of T8, honestly.** *No outbound network allowance* cannot be checked
from inside the process — a loopback endpoint says where the request goes, not
where the model forwards it. That half waits for the egress proxy in T15, and
until then L2 here means *addressed to this machine*, which is weaker than
*cannot leave it*.

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

---

## T4 as built — 26/11/2026

`kuli classify <path>...` answers how sensitive a path is **and why**. The
reason is printed, not just the level, because the constitution says a
proposed level is recorded with its reason.

124 checks, up from 94.

Three rules, and the order is the design:

**Unclassified means L2.** Not L0. The file nobody thought about is exactly
the file nobody checked.

**A person may set any level**, through rules in `kuli.json`. That is what
makes a downgrade a human act — there is no path by which the harness lowers
a level on its own. Where two rules match, the **more specific** wins, so a
public folder can be carved out of a confidential one.

**Built-in secret patterns may only raise it.** A rule saying `.env` is L0 is
overruled; `.env` is L3. The harness may be more careful than it was told and
never less — constitution 3, in one line of code.

### A bug worth recording

`.env` was not being caught. `normalise()` used `lstrip("./")`, which strips a
*set of characters* rather than a prefix — so `.env` became `env` and stopped
matching the pattern written to catch it. A dotfile is the worst possible
thing for this module to fumble, and it fumbled the most common one.

Found by running the command on real paths rather than on the paths the tests
had been written around. `test_dotfiles_are_not_mangled` now pins it.


---

## T5 as built — 27/11/2026

`kuli bundle --provider <id> <path>...` shows what a provider would and would
not be allowed to see. 149 checks, up from 124.

```
provider claude-code, cleared to L1
  ok       L0   docs/spec.md
  REFUSED  L2   business/plan.md
  REFUSED  L3   .env

  business/plan.md is L2; provider 'claude-code' is cleared to L1.
  Use a cleared provider or stop — the content is not downgraded.

  .env is L3. No provider may be given a secret in context, including one
  cleared to L3; the credential proxy injects it into the request instead.
```

Three refusals, and each is a refusal rather than an adjustment.

**A bundle above clearance cannot be built.** Not truncated, not summarised,
not redacted down to size. A test reads `assemble`'s signature and asserts it
takes nothing but parts and a provider — no `force`, no `allow`, no
`truncate`. A door with a handle on it is not a wall.

**L3 cannot enter a bundle at all**, including for a provider cleared to L3.
Secrets go into outgoing *requests* via the proxy, never into a *context*.
That line is where "a model that never sees a secret cannot leak one" is
either true or false.

**A provider with no clearance is refused everything, including L0.** The
unknown case fails closed, because an unrecognised provider is exactly where
generosity costs most.

### Two things the tests caught

**The refusal must not quote what it refused.** An error message is a log
line, and a log line containing confidential text is the leak arriving by
another door. There is a test that puts distinctive text in a refused part
and asserts it appears nowhere in the message.

**`part.level ==` is not an assignment.** The test asserting the module never
lowers a level searched for the substring `part.level =`, which `part.level
==` contains — so it failed on a comparison. Now a regex with `(?!=)`. A
check that cannot tell a comparison from an assignment was not checking what
it claimed to.

Adding this tripped the ratchet twice — `cmd_bundle` at complexity 12, then
`_add_trail` at 21 statements. Both paid with a split.

**Next:** T6 — the return-path check. Every tool *result* classified again
before it re-enters a context. The leak people forget.

---

## T6 as built — 27/11/2026

`kuli guard` reads the same payload `record` does, so it sits on PostToolUse
beside it. Exit 1 means the result is withheld. **173 checks**, up from 149.

```
$ echo '{"tool_name":"Bash","tool_input":{"command":"grep -r margin ."},
         "tool_response":{"stdout":"business/plan.md: the margin is 42%"}}' \
  | kuli guard --provider claude-code

a L2 result may not go back to 'claude-code', cleared to L1: the output names
business/plan.md, which is L2. The result is withheld, not trimmed.
```

Four rules decide a result's level, highest wins:

1. **Anything shaped like a credential is L3**, whatever its origin — so a
   secret printed by `env` is caught even though `env` reads no file.
2. **A path named in the tool's input** gives the result that path's level.
   The exact case, and the common one.
3. **A path mentioned in the output** raises it. This is the one that earns
   its keep: `grep -r thing business/` declares no target, and the answer
   naming what it found is the only thing that gives it away.
4. Otherwise the result is **internal**, not confidential.

### Rule 4 is the weak one, and it is written down as such

Tool output with no identifiable source is not a classified artefact — it was
produced inside the owner's environment. Defaulting it to L2 would refuse
every `ls` to a hosted provider, which is precisely how a gate earns being
switched off (constitution risk 1). The protection against being wrong here
is rules 1 and 3, not the default, and `tool_output_default` in `kuli.json`
moves it for a project that wants to be stricter.

Saying which of four rules is the soft one seemed better than letting someone
discover it.

### A refusal that leaves no trace never happened

Every withheld result is written to the trail as `ReturnPathRefused` before
the refusal is raised — and a test asserts the withheld text appears neither
in the message nor in the trail. The record holds *that* something was
refused and *why*, never the thing itself.

**Next:** T7 — the `openai_compatible` adapter, text only, against a local
model. The first time any of this faces something that is not a test.
