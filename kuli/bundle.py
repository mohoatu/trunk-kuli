"""What a model is given, and the refusal that keeps it honest.

A **bundle** is the only thing an adapter ever receives. It is not a path, not
a directory, and never the brain itself. It carries its parts and the highest
level among them, and it is built by this module rather than by the adapter —
because an adapter that assembles its own context is an adapter that decides
what it is allowed to see, and trust is not a mechanism.

Three rules, and each one is a refusal rather than an adjustment.

**A bundle above a provider's clearance cannot be built.** Not truncated, not
summarised, not redacted down to size. `assemble` raises, names the part, and
the caller's options are to switch to a cleared provider or to stop. There is
deliberately no parameter that softens this.

**L3 cannot enter a bundle at all.** No clearance admits it, including L3's
own. Secrets are injected into outgoing *requests* by the credential proxy;
they are never placed in a *context*. A model that never sees a secret cannot
leak one, and this is the line where that is true or false.

**A provider with no clearance is refused everything**, including L0. An
unrecognised provider is the one case where being generous costs the most, so
the unknown case fails closed.

The refusal names the part and the two levels. It never contains the content
it refused — an error message is a log line, and a log line that quotes
confidential text is the leak arriving by another door.
"""

from dataclasses import dataclass, field

from .classify import DEFAULT_LEVEL, explain, highest
from .providers import CLEARANCES, clearance_rank

#: No clearance admits this. See the module docstring.
NEVER_IN_CONTEXT = "L3"


class ClearanceError(Exception):
    """A bundle that may not be built. Never downgrade in response to this."""


@dataclass(frozen=True)
class Part:
    """One piece of context: where it came from, how sensitive, and the text."""
    source: str
    level: str
    text: str = ""
    reason: str = ""

    def __post_init__(self):
        if self.level not in CLEARANCES:
            raise ClearanceError("%s has level %r, not one of %s"
                                 % (self.source, self.level, ", ".join(CLEARANCES)))


@dataclass(frozen=True)
class Bundle:
    """Parts, and the highest level among them. Nothing else goes to a model."""
    provider_id: str
    parts: tuple = field(default_factory=tuple)

    @property
    def max_level(self):
        if not self.parts:
            return None
        return highest([p.level for p in self.parts])

    @property
    def sources(self):
        return tuple(p.source for p in self.parts)

    def text(self):
        return "\n\n".join(p.text for p in self.parts)


def _refuse(part, provider):
    raise ClearanceError(
        "%s is %s; provider %r is cleared to %s. "
        "Use a cleared provider or stop — the content is not downgraded."
        % (part.source, part.level, provider.get("id", "unknown"),
           provider.get("clearance") or "nothing")
    )


def check_part(part, provider):
    """Raise unless this provider may be shown this part."""
    if part.level == NEVER_IN_CONTEXT:
        raise ClearanceError(
            "%s is L3. No provider may be given a secret in context, including "
            "one cleared to L3; the credential proxy injects it into the "
            "request instead." % part.source)
    if clearance_rank(provider.get("clearance")) < clearance_rank(part.level):
        _refuse(part, provider)
    return True


def assemble(parts, provider):
    """Build a bundle for this provider, or refuse and say which part."""
    parts = tuple(parts)
    for part in parts:
        check_part(part, provider)
    return Bundle(provider_id=provider.get("id", "unknown"), parts=parts)


def part_for(path, config=None, text=""):
    """A part whose level and reason come from the classifier."""
    level, reason = explain(path, config)
    return Part(source=str(path), level=level, text=text, reason=reason)


def would_refuse(paths, provider, config=None):
    """Which of these paths this provider may not see. Reads nothing."""
    refused = []
    for path in paths:
        part = part_for(path, config)
        try:
            check_part(part, provider)
        except ClearanceError as exc:
            refused.append((part, str(exc)))
    return refused


def level_summary(paths, config=None):
    """How many paths sit at each level — a quick look before assembling."""
    counts = {level: 0 for level in CLEARANCES}
    for path in paths:
        counts[explain(path, config)[0] or DEFAULT_LEVEL] += 1
    return counts
