# CLAUDE.md — trunk-kuli

A personal AI assistant that does not belong to any one model provider, and a
harness that keeps the way it works the same when the model underneath
changes. **Tier A** in the fleet register: it enforces everyone else's rules,
so it obeys them first.

This project works under [its own constitution](CONSTITUTION.md). Everything
below adds to it; nothing below overrides it.

---

## Facts an agent will get wrong by guessing

- **The gates are the product, and they are programs.** Anything enforced only
  by instructions in a prompt does not belong here — it would vanish the
  moment the model changed, which is the one thing this project exists to
  prevent.
- **`kuli` is standard library only.** No dependency, ever. A gate that needs
  installing is a gate somebody skips.
- **The CLI is the authority, not the Claude integration.** CI calls `kuli`;
  hooks and slash commands call the same `kuli`. If the two ever disagree, the
  CLI is right.
- **The JavaScript measures are a heuristic, deliberately.** A real JS parser
  is a dependency. A ratchet compares a measure against itself, so a
  consistent bias cancels — an inaccurate measure is a poor report and a
  perfectly good ratchet. Do not "fix" this by adding a parser.
- **A unit is a function in Python and a file in JavaScript.** Numbers are
  reported per language and are not comparable across them.
- **A gate that cannot judge abstains.** It returns neither pass nor fail and
  exits 2. It must never report success for a question it did not answer.
- **A *permission* that cannot judge refuses.** The opposite of the line above,
  and deliberately. An unrecognised key in `providers.json` or `kuli.json` is
  named and refused, because a misspelt `clearence` that is quietly ignored is
  a permission nobody applied and everybody believed.
- **Authority is narrowed, never widened.** `Grant.narrow` returns the
  intersection and there is no `widen`. The registry sets the ceiling; a
  sub-task gets `parent.narrow(...)` and nothing else can construct one. Do not
  add a path that raises a level, including "just for the owner".
- **The MCP surface (`kuli serve`) is read-only, and stays that way.** It
  returns verdicts. Do not add a tool that writes a baseline, freezes a
  contract, mints a capability or edits a rule file — that would give the thing
  being judged a way to move the bar, which is what this whole project exists
  to prevent. A test reads this module's own source to keep it honest.

## Commands

```bash
python tests/run.py                       # every check — must be green before any commit
python -m kuli.cli measure                # the numbers, as JSON
python -m kuli.cli baseline               # record today's numbers as the line to hold
python -m kuli.cli ratchet                # fail if anything got worse
python -m kuli.cli serve                  # the gates as MCP tools, read-only
python -m kuli.cli review-cost --base REF # fail if the change costs too much to read
```

## Traps

- **Changing a measure changes every baseline.** The numbers in
  `.kuli/baseline.json` are only comparable to numbers produced by the same
  code. Altering how a measure is computed means re-baselining every project
  in the fleet, and saying so.
- **`kuli` is measured by itself.** A refactor here can trip its own ratchet.
  That is the system working; pay for it or record the exception.
- **Never widen `SKIP_DIRS` to make a number look better.** Excluding code
  from measurement is the easiest way to fake a flat line.
- Never rewrite `main` or force-push.
