# Constitution

The rules every project under trunk-kuli works by, whichever model is doing
the work. Decided once; not re-argued per task.

A project adopts this by referencing it from its own `CLAUDE.md`:

```markdown
This project works under [trunk-kuli's constitution](../trunk-kuli/CONSTITUTION.md).
Anything below adds to it; nothing below overrides it.
```

Project-specific rules are additions. Where a project needs an exception, the
exception is **written down in that project with its reason**, not taken
silently.

---

## The ten rules

**1. The specification is the authority.**
Where code and the specification disagree, the code is wrong — or the
specification is changed first, deliberately, and the code follows. Never the
reverse order, and never silently.

**2. Every rule is enforced in exactly one place.**
A second place enforcing an existing rule is a defect even when the tests pass,
because it means the boundary has leaked and the rule can now drift.

**3. Refusal over approximation.**
When the system cannot do something correctly, it refuses and says so. It does
not warn, clamp, pick a default, or guess. A low-quality answer that looks like
a confident one is worse than no answer.

**4. A gate is code, not a prompt.**
"Always write tests" is advice. A program that reads the repository and exits
non-zero is a rule. Anything that must survive a change of model is written as
the second kind.

**5. Absences are features.**
What the system must not be able to do is asserted by test, the same as what it
must do. A test that proves a forbidden thing does not exist looks absurd until
someone adds it under deadline pressure.

**6. A check that can never fail proves nothing when it passes.**
Test suites are themselves tested — by mutation, or by being seen to go red at
least once on purpose. A gate nobody has watched fail is not known to work.

**7. Evidence is part of the deliverable.**
Running the tests is not the deliverable; being able to show what was proven
is. Evidence is regenerated in the same change as the code, because stale
evidence is worse than none — it is believed.

**8. Exactness where exactness is possible.**
Money is integer, in the smallest real unit. Reconciliation has no tolerance.
Rounding rules are written down rather than left to whichever line runs last.
Where a tolerance genuinely must exist, it is named, justified, and tested at
its boundary.

**9. Nothing irreversible without a person.**
No sending, publishing, pushing to a default branch, paying, or deleting
without explicit confirmation from the owner. Clearance governs reading;
irreversibility is a separate axis and always needs a human.

**10. Say what is not done.**
Open questions are recorded as open. Gaps are stated plainly in the README.
Defaults are labelled as defaults and never quietly promoted into decisions.

---

## What every project must have

| Artefact | Why |
|---|---|
| `README.md` | What this is, its honest status, and what is missing |
| `CLAUDE.md` | The reference to this constitution, plus the project's own additions and traps |
| `docs/` | The specification. For anything non-trivial: spec, acceptance criteria, model, tasks |
| a single test command | One command that runs everything and exits non-zero on any failure |
| `evidence/` | Generated, and committed |

A project missing one of these is not disqualified — it is **recorded as a gap
in the fleet register**, and closed in order of risk.

---

## Identifiers, and the traceability gate

Acceptance criteria and invariants carry identifiers. Tests claim the
identifiers they prove. A gate parses both and fails in **both** directions:

- a documented requirement with no test is uncovered;
- a test claiming an identifier no document defines is a stale claim.

The second direction is what catches a renamed requirement, and it is the
reason the gate is worth more than a coverage percentage.

The gate is built **early, in report-only mode**, not at the end. A gate added
at the end can only report on what was already written; a gate present from the
start makes the gap visible on every run, and the gap shrinking is the progress
report.

---

## Language

Documents committed to a repository are in **English** unless the project is
deliberately Vietnamese for its audience — `sizePortal` is, because it is
written to be read by Vietnamese merchants and reviewers. Within a file, write
in the language the file is already in.
