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

TRAILER = re.compile(r"^Rules-approved-by:\s*(\S.*)$", re.M)


def is_rule_file(path):
    return any(path == name or path.startswith(name) for name in RULE_FILES)


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
    return {
        "commit": commit[:12],
        "rule_files": rules,
        "work_files": [f for f in files if not is_rule_file(f)],
        "approved_by": approver(commit, root),
    }


def faults(record):
    """Every rule this commit breaks. Empty means it is fine."""
    if not record["rule_files"]:
        return []
    found = []
    if record["work_files"]:
        found.append(
            "A1: it changes the rules (%s) and the work they judge (%d other "
            "file(s)) in one commit. Split them, so the relaxation is the only "
            "thing in its own diff."
            % (", ".join(record["rule_files"]), len(record["work_files"])))
    if not record["approved_by"]:
        found.append(
            "A2: it changes the rules (%s) with no second actor. Add a "
            "'Rules-approved-by: <name>' trailer to the commit message."
            % ", ".join(record["rule_files"]))
    return found


def run(base, root="."):
    """Returns (ok, report) for every commit since `base`."""
    records = [inspect(commit, root) for commit in commits_in(base, root)]
    offences = [(r, faults(r)) for r in records]
    broken = [(r, f) for r, f in offences if f]
    return (not broken), {
        "base": base,
        "commits": len(records),
        "touching_rules": len([r for r in records if r["rule_files"]]),
        "faults": broken,
    }
