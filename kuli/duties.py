"""Separation of duties: nobody relaxes the rule that is judging them.

Every gate here is a deterministic program, so a model cannot argue one into
passing. It can do something simpler: **change the gate's settings.** Write
code that raises erosion, watch the ratchet refuse it, add an exception to
`kuli.json`, and the gate goes green.

`CLAUDE.md` warns against exactly that — *never widen `SKIP_DIRS` to make a
number look better* — and that warning is a prompt. In a project whose whole
claim is that a prompt is not a guarantee, the one rule protecting the gates
from the work they judge cannot be a prompt.

Two rules, both decidable from git alone, so they hold in CI where no trail
and no model are present:

**A1. Rule files and work files may not change in the same commit.** Not
because combining them is immoral, but because a relaxation hidden inside a
hundred-line feature is a relaxation nobody reads. Alone in its own commit,
it is the only thing in the diff.

**A2. A commit that touches rule files carries `Rules-approved-by:`.** That
is the second actor. Working alone with one provider, the second actor is the
owner, and the trailer is where he says so — the same principle as "only a
person may lower a classification level", applied to the rules rather than to
the data.

**One exemption, and the reason it is safe.** CI workflows are the one rule
path that also holds changes which relax nothing — a new docs job, a bumped
action version. For workflows only, A1 is held against a change that **removes
a line** or that **adds one of `RELAXING`**; a purely additive, unremarkable
change is excused and reported rather than refused. A2 is never excused,
because it costs one line and it is where a person says they looked.

The exemption rests on the `RELAXING` list, not on additivity, because
`continue-on-error: true` removes nothing and switches a job off. If a way to
weaken a workflow by adding a line appears that is not on that list, this gate
misses it. That is the known limit, written down rather than discovered later.
"""

import re

from .review_cost import git

#: The files that decide what the gates allow. Changing one of these changes
#: the verdict on everything else.
RULE_FILES = (
    "kuli.json",
    ".kuli/baseline.json",
    "providers.json",
    ".github/workflows/",
)

#: A workflow directory is the one entry above that holds two different kinds
#: of change. "Delete the ratchet step" is a relaxation. "Add a job that
#: builds the docs" is not, and A1 charged both the same price: a commit of
#: its own. So for workflows only, **the diff decides**. A change that removes
#: nothing cannot have taken a gate away, and is excused from A1 — never from
#: A2, which costs one line.
WORKFLOW_DIR = ".github/workflows/"

#: The hole in that rule, closed by name. `continue-on-error: true` removes
#: no line and disables a job, so additivity alone cannot be trusted and this
#: list is what makes the exemption safe rather than convenient.
RELAXING = ("continue-on-error", "|| true", "|| :", "if: false",
            "--no-verify", "--exit-zero", "exit 0")

TRAILER = re.compile(r"^Rules-approved-by:\s*(\S.*)$", re.M)


def is_rule_file(path):
    return any(path == name or path.startswith(name) for name in RULE_FILES)


def removed_count(commit, path, root="."):
    """How many lines this commit took out of one file."""
    out = git(["show", "--numstat", "--format=", commit, "--", path], root)
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) == 3 and fields[1].isdigit():
            return int(fields[1])
    return 0


def added_text(commit, path, root="."):
    out = git(["show", "--format=", "--unified=0", commit, "--", path], root)
    return [line[1:] for line in out.splitlines()
            if line.startswith("+") and not line.startswith("+++")]


def relaxation_in(commit, path, root="."):
    """The first added marker that weakens a gate without removing anything."""
    for line in added_text(commit, path, root):
        lowered = line.lower()
        for marker in RELAXING:
            if marker in lowered:
                return marker
    return None


def binds(commit, path, root="."):
    """Why this rule change binds A1, or None when it is excused."""
    if not path.startswith(WORKFLOW_DIR):
        return "a rule file"
    marker = relaxation_in(commit, path, root)
    if marker:
        return "it adds %r" % marker
    return "it removes lines" if removed_count(commit, path, root) else None


def _split_rules(commit, rules, root="."):
    """The rule changes A1 holds against this commit, and the excused ones."""
    binding, excused = [], []
    for path in rules:
        why = binds(commit, path, root)
        if why:
            binding.append("%s — %s" % (path, why))
        else:
            excused.append(path)
    return binding, excused


def commits_in(base, root="."):
    out = git(["log", "--format=%H", base + "...HEAD"], root)
    return [line.strip() for line in out.splitlines() if line.strip()]


def files_in(commit, root="."):
    out = git(["show", "--name-only", "--format=", commit], root)
    return [line.strip() for line in out.splitlines() if line.strip()]


def message_of(commit, root="."):
    return git(["log", "-1", "--format=%B", commit], root)


def approver(commit, root="."):
    found = TRAILER.search(message_of(commit, root))
    return found.group(1).strip() if found else None


def inspect(commit, root="."):
    """What this commit touched, and who approved it if anyone."""
    files = files_in(commit, root)
    rules = [f for f in files if is_rule_file(f)]
    binding, excused = _split_rules(commit, rules, root)
    return {
        "commit": commit[:12],
        "rule_files": rules,
        "binding": binding,
        "excused": excused,
        "work_files": [f for f in files if not is_rule_file(f)],
        "approved_by": approver(commit, root),
    }


def faults(record):
    """Every rule this commit breaks. Empty means it is fine."""
    if not record["rule_files"]:
        return []
    found = []
    if record["binding"] and record["work_files"]:
        found.append(
            "A1: it changes the rules (%s) and the work they judge (%d other "
            "file(s)) in one commit. Split them, so the relaxation is the only "
            "thing in its own diff."
            % ("; ".join(record["binding"]), len(record["work_files"])))
    if not record["approved_by"]:
        found.append(
            "A2: it changes the rules (%s) with no second actor. Add a "
            "'Rules-approved-by: <name>' trailer to the commit message."
            % ", ".join(record["rule_files"]))
    return found


def _counted(records):
    """The parts of the report that are arithmetic rather than judgement."""
    return {
        "commits": len(records),
        "touching_rules": len([r for r in records if r["rule_files"]]),
        "excused": [(r["commit"], r["excused"]) for r in records if r["excused"]],
    }


def run(base, root="."):
    """Returns (ok, report) for every commit since `base`."""
    records = [inspect(commit, root) for commit in commits_in(base, root)]
    broken = [(r, f) for r, f in ((r, faults(r)) for r in records) if f]
    report = dict(_counted(records), base=base, faults=broken)
    return (not broken), report
