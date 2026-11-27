"""The increment contract: the bar, agreed before the work and fixed after.

Ask an agent to add a feature. It writes the code. It writes the tests. The
tests pass. Both came from the same party reading the same request, so if the
reading was wrong the tests encode the wrong expectation exactly as
faithfully as the code does. Green means the two agree with each other; it
does not mean either is right.

That is the migration-verify finding arriving from the other side: both
implementations read the document correctly, and the document was missing a
sentence. Nobody made a mistake and the answer was still wrong.

Adversarial review catches some of this, but it runs afterwards, on work
already built, where a reviewer is under pressure to accept.

So two rules:

**Signed by two, before the work.** The producer writes what will be built
and how it will be judged; the reviewer accepts it. They must not be the same
actor.

**Frozen once work begins.** The contract's digest is recorded, and an
acceptance whose contract changed since is refused. A bar that can be edited
after the result is known is not a bar, and a hash makes that mechanical
rather than a matter of discipline.
"""

import hashlib
import json
import re
from pathlib import Path

from . import paths

CONTRACT_DIR = Path(".kuli/contracts")

SECTIONS = ("What will be built", "How it will be judged")
# `[^\S\n]*` and not `\s*`: `\s` matches a newline, so an unsigned
# "Producer-signed:" swallowed the line below it and reported the reviewer's
# name as the producer's. An empty signature has to read as empty.
PRODUCER = re.compile(r"^Producer-signed:[^\S\n]*(\S.*)$", re.M)
REVIEWER = re.compile(r"^Reviewer-signed:[^\S\n]*(\S.*)$", re.M)

TEMPLATE = """# Contract: %s

## What will be built

<one increment, in plain sentences>

## How it will be judged

<the conditions the reviewer will check, written before the work exists>

Producer-signed:
Reviewer-signed:
"""


class ContractError(Exception):
    """A contract that cannot be relied on. Never proceed past it."""


def path_for(slug, root="."):
    return Path(root) / CONTRACT_DIR / ("%s.md" % slug)


def lock_for(slug, root="."):
    return Path(root) / CONTRACT_DIR / ("%s.lock" % slug)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create(slug, root="."):
    path = path_for(slug, root)
    if path.exists():
        raise ContractError("%s already exists; edit it rather than replacing it"
                            % path)
    paths.ensure_parent(path)
    path.write_text(TEMPLATE % slug, encoding="utf-8")
    return path


def read(slug, root="."):
    path = path_for(slug, root)
    if not path.exists():
        raise ContractError("no contract at %s. Write one: kuli contract new %s"
                            % (path, slug))
    return path.read_text(encoding="utf-8")


def _signature(pattern, text):
    found = pattern.search(text)
    value = found.group(1).strip() if found else ""
    return value or None


def parse(text):
    return {
        "producer": _signature(PRODUCER, text),
        "reviewer": _signature(REVIEWER, text),
        "sections": [s for s in SECTIONS if ("## %s" % s) in text],
        "digest": digest(text),
    }


def complaints(parsed):
    """Everything wrong with this contract. Empty means it is signed and whole."""
    found = []
    for section in SECTIONS:
        if section not in parsed["sections"]:
            found.append("the section '%s' is missing" % section)
    if not parsed["producer"]:
        found.append("Producer-signed is empty")
    if not parsed["reviewer"]:
        found.append("Reviewer-signed is empty")
    if parsed["producer"] and parsed["producer"] == parsed["reviewer"]:
        found.append("producer and reviewer are the same actor (%s); the party "
                     "doing the work may not set its own bar"
                     % parsed["producer"])
    return found


def check(slug, root="."):
    """Is this contract ready to work against? Returns (ok, parsed, problems)."""
    parsed = parse(read(slug, root))
    problems = complaints(parsed)
    return (not problems), parsed, problems


def freeze(slug, root="."):
    """Record the digest. Work starts here; the bar stops moving here."""
    ok, parsed, problems = check(slug, root)
    if not ok:
        raise ContractError("%s is not signed off: %s" % (slug, "; ".join(problems)))
    lock = lock_for(slug, root)
    lock.write_text(json.dumps({"slug": slug, "digest": parsed["digest"],
                                "producer": parsed["producer"],
                                "reviewer": parsed["reviewer"]},
                               indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock


def verify(slug, root="."):
    """Has the bar moved since work began? Returns (ok, message)."""
    lock = lock_for(slug, root)
    if not lock.exists():
        return False, ("%s was never frozen. Run: kuli contract freeze %s "
                       "before starting work." % (slug, slug))
    recorded = json.loads(lock.read_text(encoding="utf-8"))
    current = digest(read(slug, root))
    if current != recorded["digest"]:
        return False, ("%s changed after work began. A bar edited once the "
                       "result is known is not a bar." % slug)
    return True, "%s matches what was agreed (%s)" % (slug, current[:12])


def slugs(root="."):
    directory = Path(root) / CONTRACT_DIR
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))


def verify_all(root="."):
    results = [(slug,) + verify(slug, root) for slug in slugs(root)]
    return all(ok for _, ok, _ in results), results
