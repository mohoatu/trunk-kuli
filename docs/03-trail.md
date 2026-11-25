# The trail — what the agents did, recorded by something that is not them

Built **25/11/2026**. Observe only: nothing here refuses anything.

---

## 1. Why a trail when there are already gates

A gate says yes or no at a boundary. It is a filter. A trail is a **witness**.

They fail differently, which is why both are needed. A gate you never wrote
lets something through in silence — nothing is refused, and nothing is
recorded either. A trail catches it anyway, afterwards, because it was never
deciding anything in the first place; it was only watching.

## 2. The rule the whole design rests on

> **The record is not written by the agent.**

An agent that writes its own log produces a **claim**. The recorder sits
outside the agent, at the tool-call boundary, so what lands in the trail is
what happened rather than what the agent said happened.

This is the same argument as §8.5 of the specification — a claim that
something works must cite an execution — and the same argument as keeping L3
secrets unreadable by any model. A system that asks the agent to be honest
about itself has no answer when it is not.

## 3. Append-only, hash-chained

Every entry carries the digest of the entry before it. Changing one entry
breaks its own digest; removing one breaks the chain at that point. Neither
can be done quietly.

This is the ledger from [`p2p-lending`](https://github.com/mohoatu/p2p-lending),
pointed at agent actions instead of money, and for the same reason: a record
that can be edited without trace is not a record.

```bash
python -m kuli.cli audit
# 3 entries, chain intact.
```

```bash
# after one entry was quietly edited
python -m kuli.cli audit
# The trail has been altered. 3 entries, 1 problems:
#   entry 0: content does not match its digest
```

## 4. Fingerprints, not contents

The trail sees file contents, shell commands and command output. Written down
naively, **the audit log becomes the largest leak in the system** — one file
holding everything every agent ever touched.

So a write is recorded as its path, its size and the SHA-256 of the bytes:

```json
{
  "file_path": "src/app.py",
  "new_string": { "bytes": 5, "lines": 1, "sha256": "1431b986377b…" }
}
```

That answers *who changed what, when, to exactly which bytes* without the
trail becoming a second copy of the codebase. It also keeps the trail at a
level that can live in the repository and be read by anyone reviewing the
work.

Credentials never get even that far. Anything matching a credential shape is
replaced before it is hashed or stored, and the suite checks a real GitHub
token, an OpenAI-style key, a bearer header and a `password =` line against
the written file.

One consequence worth knowing, found while writing the tests: an unbroken
5,000-character token is indistinguishable from an encoded secret, so it is
redacted rather than shortened. The order is deliberate — scrub first, then
truncate.

## 5. Where it lives

Per repository, at `.kuli/trail/YYYY-MM-DD.jsonl` — one JSON object per line.
Greppable, diffable in review, and small, because of §4.

Per repository rather than central, by decision: the trail belongs with the
work it describes, and a reviewer should find it in the same place as the
code it explains.

## 6. Using it

```bash
python -m kuli.cli trail                    # counts by tool, provider and day
python -m kuli.cli trail --last 20          # and the most recent actions
python -m kuli.cli trail --file src/app.py  # who changed this file
python -m kuli.cli trail --since 2026-11-01 --json
python -m kuli.cli audit                    # has the record been altered?
```

## 7. Recording from Claude Code

`kuli record` reads one hook payload on stdin and appends it. Add to
`.claude/settings.json` in the project:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "python -m kuli.cli record", "timeout": 10 } ] }
    ],
    "PostToolUse": [
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "python -m kuli.cli record", "timeout": 10 } ] }
    ]
  }
}
```

**`kuli record` always exits 0 and swallows its own failures.** A recorder
that can stop work is a recorder that gets switched off, and then there is no
record at all. It also accepts a payload it does not recognise rather than
throwing — the suite feeds it a malformed one on purpose.

For other providers, the adapter wraps tool dispatch and calls the same
command. Nothing about the trail is specific to Claude.

## 8. What this does not do, and will not pretend to

- **It refuses nothing.** The corridor comes later, and its rules will be
  written from what this shows rather than from what anyone imagined —
  evidence before policy, the same order as back pressure before forward
  pressure.
- **It only sees agents that run through it.** Open Claude directly, outside
  a project with the hook installed, and nothing is recorded. The corridor
  will bind what it launches; it cannot bind what it never saw.
- **Recording a shell command is not constraining it.** `kuli record` writes
  down `rm -rf`; it does not stop it.
- **Cost and token figures are not recorded yet.** They depend on provider
  responses that the hook payload does not carry.

## 9. The questions it can answer today

- What did agents do, and on which days?
- Which tools, and in what proportion?
- Who changed this specific file?
- Has the record itself been altered?

And the one it cannot answer yet, which is the next piece of work: **what did
it cost, per provider?**
