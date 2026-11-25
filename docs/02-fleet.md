# The fleet — every project under trunk-kuli's process

Surveyed **24/11/2026** from the working copies on disk, not from memory.

**What "under trunk-kuli" means today.** The harness is specified and not yet
built, so no project is being *driven* by it. What is real now is the
[constitution](../CONSTITUTION.md) — the rules — and this register, which
records for each project which gates already exist and which do not. When the
harness runs, it already has its fleet and knows each project's gaps.

Saying this plainly matters. A register that implied automated control that
does not exist would be exactly the kind of claim the constitution exists to
prevent.

---

## 1. Register

| Project | What it is | Git | Spec | Tests | Traceability gate | Evidence | CI |
|---|---|---|---|---|---|---|---|
| **p2p-lending** | P2P lending designed to Decree 94/2025 | ✅ | ✅ `docs/01–04` | ✅ 308 | ✅ report-only | ✅ | ✅ |
| **migration-verify** | Proving a rewrite kept the business logic | ✅ | ❌ | ✅ 132 + mutation | ❌ | ❌ | ✅ |
| **confluence-table-audit** | Atlassian Forge app, published and sold | ❌ sub-dir | ✅ `docs/` | ✅ 743 + 125 mutations | ❌ | ❌ | ✅ |
| **sizePortal / size-fit** | Universal Size Passport | ✅ | ✅ `docs/brd.md` | ✅ 400 | ❌ | ❌ | ✅ |
| **nhau-di** (Tiên Tửu) | Nine party games on one phone | ✅ | ✅ `docs/` | ✅ 342 | ❌ | ❌ | ✅ |
| **text-to-video** (Videogen) | Vietnamese text → narrated video, self-hosted | ✅ remote | ✅ `docs/` | ⚠️ unsurveyed | ❌ | ❌ | ❌ |
| **aws-migration-poc** | On-premise → AWS, with cutover artefacts | ✅ | ✅ `docs/01–06` | ❌ | ❌ | ❌ | ✅ |
| **trunkle-win-web** | The public site | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **trunk-kuli** | This harness | ❌ | ✅ `docs/01` | ❌ | ❌ | ❌ | ❌ |

`text-to-video` is not on this machine; its row is from its README and is
marked unsurveyed where it could not be checked.

### What the register says

**The discipline is real but uneven.** Four projects carry serious test suites
— 743, 400, 342, 308 — and two of them test their own tests by mutation. That
is far beyond normal. But **only one project has a traceability gate, only one
has evidence, and only one has CI.** The practice has been reinvented per
project instead of carried.

That is precisely the problem trunk-kuli exists to solve, now visible as a
table rather than as an intuition.

---

## 2. Tiers — not every project deserves the same process

Applying nine gates to a static website would be the bureaucracy risk in the
constitution, arriving on day one. So projects are tiered, and the tier decides
what is required.

| Tier | Meaning | Required |
|---|---|---|
| **A — handles money, data or a paying customer** | A defect costs real money or real trust | Everything in the constitution: spec, identifiers, traceability gate, tests, evidence, CI |
| **B — a real product, no money at stake yet** | A defect costs credibility | Spec, tests, a single test command, CI. Traceability gate when the spec has identified criteria |
| **C — supporting material** | A defect is an inconvenience | README with honest status. Nothing else is demanded |

| Project | Tier | Why |
|---|---|---|
| p2p-lending | **A** | Money arithmetic and a regulatory argument; it is the portfolio piece |
| confluence-table-audit | **A** | Published, sold, and customers' data passes through it |
| sizePortal / size-fit | **A** | A live demo in front of grant reviewers, with real brand names on it |
| migration-verify | **B** | Public proof of method; already strong |
| text-to-video | **B** | Private, but the output is shown publicly |
| nhau-di | **B** | Real product, pre-launch |
| aws-migration-poc | **B** | A method artefact; correctness of the argument matters more than coverage |
| trunkle-win-web | **C** | A static site. A link check is the whole of it |
| trunk-kuli | **A** | It enforces everyone else's rules; it must obey them first |

---

## 3. Gaps, in order of risk

Ordered by what it costs to leave each one alone, not by effort.

| # | Gap | Where | Why it ranks here |
|---|---|---|---|
| ~~1~~ | ~~No CI~~ | ~~Tier A~~ | **Closed 24/11/2026.** See §6. |
| 2 | No traceability gate | confluence-table-audit, size-fit | Both have large suites and written specs, so the gate has something real to check and would likely find drift immediately |
| 3 | No evidence | everything except p2p-lending | Weakest where it is needed most: the sold app and the reviewer-facing demo have no artefact showing what was proven |
| 4 | No single test command | size-fit (8 commands), migration-verify | A process cannot gate what it cannot invoke in one line |
| 5 | No `CLAUDE.md` | aws-migration-poc, trunkle-win-web, confluence-table-audit, trunk-kuli | Each new session rediscovers the project's rules, and sometimes gets them wrong |
| 6 | Not an independent repository | confluence-table-audit | It is sold software living inside another project's tree |
| 7 | No tests | aws-migration-poc | Tier B, and it is an argument rather than a program — lowest risk, listed so it is not mistaken for an oversight |

### The first move — done

See §6. Gap 1 is closed; gap 2 is next.

---

## 4. Adoption order

Not everything at once — the fleet is proof that reinventing per project does
not work, and so is doing nine things per project in one week.

| Step | What | Projects |
|---|---|---|
| ~~1~~ | ~~CI running the existing suite~~ | ~~the three Tier A projects~~ — **done 24/11/2026** |
| 2 | `CLAUDE.md` referencing the constitution | every project missing one |
| 3 | Single test command | size-fit, migration-verify |
| 4 | Traceability gate, report-only | confluence-table-audit, size-fit |
| 5 | Evidence generation | the three Tier A projects |
| 6 | Extract confluence-table-audit into its own repository | that project |

Steps 1–3 are mechanical and can be done without the harness existing. Steps
4–5 are the harness's own first real work, alongside continuing p2p-lending
(spec §10).

---

## 5. What this register does not claim

- It does not claim any project is currently *controlled* by trunk-kuli.
  Nothing is: the harness is a specification.
- Test counts are as reported by each project's own documentation and were not
  re-run during this survey.
- `text-to-video` was surveyed from its README only.

Each of these would have been easy to leave unsaid, which is why the
constitution has a rule about saying what is not done.


---

## 6. What the first run found — 24/11/2026

CI now runs on every push for all three Tier A projects, on **Linux and
Windows**, across two language versions each. Everything is green.

| Repository | Jobs | Covers |
|---|---|---|
| `p2p-lending` | 4 test matrix + 1 | 308 checks; the traceability gate reported separately; a job that fails if a dependency manifest ever appears |
| `size-fit` | 4 + 4 + 2 | size-fit's 8 suites; Table Audit's 743 checks; generated files still match their sources; documented paths still resolve |

**Putting it in front of a clean machine found three things that a laptop
where everything already works cannot find.**

**1. The sold app's dependencies were not locked.** `package-lock.json` was
never committed, because the repository ignores lockfiles wholesale — right
for sizePortal, which has no dependencies and treats that as a feature, wrong
for the one product inside it that does. Until today, the artefact a paying
customer installs was built against whatever versions were newest that day:
not reproducible, not reviewable, and awkward for an app that publishes a
security review of itself. Now locked at `@forge/bridge` 7.0.0 and `esbuild`
0.25.12.

**2. `check-links.py` reports 72 broken references that are not broken.** They
are correct relative paths inside `confluence-table-audit/`, resolved against
the wrong root. The job is scoped to size-fit's own documents and says so.
The nested project's documents are therefore unchecked — recorded as gap 2b.

**3. Both generated files restamp the build date, and the sources carry CRLF.**
A naive "is the generated file current?" check would have gone red every day
for no reason, and a check that cries wolf is a check somebody switches off —
constitution risk 1, arriving on day one. The stamps and line endings are
normalised on both sides; anything else that differs is real drift.

Findings 1 and 2 are the same finding twice: a rule written for sizePortal
turned out to be wrong for the separate product living inside it. **Gap 6 —
extract `confluence-table-audit` into its own repository — moves up the list
on that evidence**, from last to second.


---

## 7. The rest of the fleet — 24/11/2026

Every project that lives on this machine now has CI, and all of it is green.

| Repository | What runs |
|---|---|
| `nhau-di` | 342 checks on Linux and Windows, node 20 and 22; plus a job that fails if a dependency or a lockfile ever appears |
| `trunkle-win-web` | 82 internal links, each one resolved |
| `aws-migration-poc` | Every tracked Python file byte-compiles on 3.10 and 3.13, `run_cutover.py --help` starts, and all 6 document references resolve |

Three decisions worth recording, because each one is a place where more CI
would have been worse CI.

**External links are not checked anywhere.** A third party being briefly down
is not a defect in these repositories, and a job that goes red for someone
else's outage is a job people learn to ignore.

**`aws-migration-poc` gets a deliberately small workflow.** That project is an
argument, not a program: its value is whether the 7Rs reasoning and the
cutover runbook hold up, and no job can judge that. So it checks the two
things a machine honestly can — the code compiles, and the documents point at
files that exist. The second matters more here than elsewhere, because the
documents *are* the deliverable. Its workflow says this about itself rather
than implying a coverage it does not have.

**`nhau-di` keeps the README honest about its own limits.** The workflow
repeats, in its own comment, that `test-ui.mjs` runs in a fake DOM: it catches
a thrown error or a dead timer, not a button nobody can find in a dim bar. A
green badge there is not a playable game.

### Still outstanding

**`text-to-video`** has no CI. It is not on this machine — it is a private
repository that was never cloned here — and it is Java with ffmpeg, Ollama and
ComfyUI around it, so a useful workflow is a larger piece of work than any of
the above. Recorded as an open item rather than quietly left off the table.

### Where the fleet stands

Nine projects. **Eight now have CI**, where this morning one did. Three gaps
remain and their order has changed on the evidence of the day:

| # | Gap | Where |
|---|---|---|
| 1 | Extract the sold app into its own repository | confluence-table-audit — *was gap 6; moved up after two rules written for sizePortal turned out to be wrong for it* |
| 2 | Traceability gate | confluence-table-audit, size-fit |
| 3 | Evidence generation | the Tier A projects |
| 4 | Single test command | size-fit, migration-verify |
| 5 | `CLAUDE.md` referencing the constitution | the projects without one |
| 6 | CI for text-to-video | that project |
| 7 | A test suite for aws-migration-poc | that project, still last on purpose |

---

## 8. The ratchet, across the fleet — 25/11/2026

`kuli` is now wired into every repository that has Python or JavaScript in it.
Each one carries a `kuli.json` saying what is excluded and why, a committed
`.kuli/baseline.json`, and a CI job named **"nothing got worse"**.

| Project | Baseline (erosion / verbosity / duplication) |
|---|---|
| p2p-lending | py 0.317 / 10.7 / 0.064 |
| migration-verify | py 0.338 / 12.2 / 0.070 |
| nhau-di | js 0.404 / 78.2 / 0.092 · py 0.000 / 5.3 / 0.000 |
| aws-migration-poc | py 0.192 / 14.4 / 0.523 |
| size-fit | js 0.305 / 126.4 / 0.163 · py 0.000 / 11.5 / 0.046 |
| confluence-table-audit | js 0.429 / 91.4 / 0.183 · py 0.000 / 5.6 / 0.029 |

**kuli is pinned to tag `v0.1.0` in every workflow.** Changing how a measure
is computed changes every number it has ever produced, so a floating version
would silently invalidate all six baselines at once. Bumping the tag is a
decision, taken together with a re-baseline.

### What was excluded, and what was not

`skip` is the easiest way to fake a flat line, so each entry has a reason:

- **size-fit** excludes `confluence-table-audit` (a separate product, with its
  own baseline), and `embed/` and `data/` — generated bundles that inline
  their own sources. Excluding them moved the JavaScript duplication figure
  from **0.357 to 0.163**: the first number was an artefact of the build, and
  freezing it would have meant defending a wrong number for months.
- **nhau-di** excludes `dist-zalo/`, the bundled build output.
- **migration-verify excludes nothing**, including `legacy-demo/` and
  `cobol-demo/` — deliberately old-style code written to be migrated. It would
  have been easy to exclude them as "not real source". They are measured, and
  the ratchet compares them against themselves.
- **aws-migration-poc excludes nothing** either. Its duplication of **0.523**
  is high and is not a defect: `worker.py` is a faithful port of the Perl
  original, and faithfulness is the entire point of the project.

### The limit of all six numbers

A baseline records where a project **is**, not where it should be. None of
these figures says the code is good. They say that from today it does not get
worse without somebody noticing — which is the only claim the arithmetic
supports.
