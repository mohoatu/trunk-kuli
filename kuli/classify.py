"""What level a file is, and why.

Nothing here enforces anything. It answers one question — *how sensitive is
this path* — and the context assembler and the return-path check will act on
the answer. Keeping the answer in one small, pure module is the point: a
classification decided in three places is a classification that disagrees
with itself.

Three rules govern the result, and the order matters.

**1. Unclassified means L2.** Not L0. The default has to be the cautious one,
because the file nobody thought about is exactly the file nobody checked.

**2. A person may set any level.** Rules live in `kuli.json`, written by hand.
That is what makes a downgrade a human act: there is no path by which the
harness lowers a level on its own.

**3. The built-in secret patterns may only raise it.** A `.env` file is L3
whatever a rule says. The harness is allowed to be more careful than it was
told; it is never allowed to be less.

Where two hand-written rules both match, the **more specific** one wins —
counted by how much of the pattern is literal — so a public folder can be
carved out of a confidential one. Ties go to the higher level.
"""

import re
from pathlib import PurePosixPath

from .providers import CLEARANCES, clearance_rank

DEFAULT_LEVEL = "L2"

#: Patterns that force L3 regardless of configuration. These are not a
#: complete list of every secret in the world; they are the ones common
#: enough that forgetting them once is likely.
SECRET_PATTERNS = (
    "**/.env", "**/.env.*", "**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx",
    "**/id_rsa", "**/id_ed25519", "**/.git-credentials", "**/.npmrc",
    "**/credentials", "**/credentials.json", "**/service-account*.json",
    "**/.aws/**", "**/.ssh/**", "**/secrets/**",
)


class ClassificationError(Exception):
    """A rule that cannot be trusted. Never guess past it."""


def to_regex(pattern):
    """Translate a glob to a regex. `**` crosses directories, `*` does not."""
    out, index = [], 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif char == "*":
            out.append("[^/]*")
            index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(char))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def normalise(path):
    """Compare on forward slashes, relative, without a leading `./`.

    The leading `./` is removed as a prefix, not with `lstrip("./")`: that
    strips a *set* of characters, so `.env` became `env` and stopped matching
    the secret pattern that exists to catch it. A dotfile is exactly the kind
    of path this module must never fumble.
    """
    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return PurePosixPath(text).as_posix()


def specificity(pattern):
    """How much of the pattern is literal. More literal wins."""
    return len(re.sub(r"[*?]", "", pattern))


def rules_from(config):
    """Validate and return the hand-written rules."""
    rules = (config.get("classification") or {}).get("rules") or []
    for rule in rules:
        if not rule.get("match"):
            raise ClassificationError("a classification rule has no match: %r" % rule)
        if rule.get("level") not in CLEARANCES:
            raise ClassificationError(
                "rule %r has level %r, not one of %s"
                % (rule["match"], rule.get("level"), ", ".join(CLEARANCES)))
    return rules


def _best_rule(path, rules):
    """The most specific matching rule; ties go to the higher level."""
    best = None
    for rule in rules:
        if not to_regex(rule["match"]).match(path):
            continue
        key = (specificity(rule["match"]), clearance_rank(rule["level"]))
        if best is None or key > best[0]:
            best = (key, rule)
    return best[1] if best else None


def _secret_match(path):
    for pattern in SECRET_PATTERNS:
        if to_regex(pattern).match(path):
            return pattern
    return None


def explain(path, config=None):
    """Return (level, reason). The reason is recorded, not just the level."""
    target = normalise(path)
    rules = rules_from(config or {})

    rule = _best_rule(target, rules)
    if rule:
        level, reason = rule["level"], "rule %r in kuli.json" % rule["match"]
    else:
        level, reason = DEFAULT_LEVEL, "no rule matches; unclassified means L2"

    secret = _secret_match(target)
    if secret and clearance_rank("L3") > clearance_rank(level):
        return "L3", "built-in secret pattern %r raised it from %s" % (secret, level)
    return level, reason


def level_of(path, config=None):
    return explain(path, config)[0]


def highest(levels):
    """The level a bundle carries: the highest of its parts."""
    ranked = [l for l in levels if l in CLEARANCES]
    if not ranked:
        return DEFAULT_LEVEL
    return max(ranked, key=clearance_rank)
