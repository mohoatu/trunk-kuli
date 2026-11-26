"""The registry: which models may run here, and what each is allowed to see.

Written before any second provider exists, because the first thing a registry
has to do is **describe what is already running** — otherwise the design is
shaped around the newcomer and the incumbent becomes a special case.

Three things live here and nowhere else:

**Clearance.** A provider's maximum classification level. Nothing in this file
enforces it; the context assembler will. What this file guarantees is that the
number exists, is valid, and was written down by a person rather than inferred
at runtime.

**Shape.** `agent-product` already has its own loop and tools, and kuli wraps
it. `raw-model` is an endpoint, and kuli supplies the loop. These are not
interchangeable, and code that forgets the difference produces a harness that
works in one and is theatre in the other.

**Detection.** Which provider is running *now* is decided by rules in the
registry file, not by vendor names hard-coded here. Adding a provider must not
mean editing this module.

Nothing is invented. With no registry file, the active provider is `unknown`
and the commands say so — a guessed provider in an audit trail is worse than
an honest gap.
"""

import json
import os
from pathlib import Path

REGISTRY_PATH = Path("providers.json")

#: Lowest to highest. A provider may see its own level and below.
CLEARANCES = ("L0", "L1", "L2", "L3")

SHAPES = ("agent-product", "raw-model")
ADAPTERS = ("wrapped", "openai_compatible", "anthropic")

UNKNOWN = {"id": "unknown", "name": "unknown", "shape": None,
           "adapter": None, "clearance": None, "model": None}


class RegistryError(Exception):
    """A registry that cannot be trusted. Never fall back to a default."""


def path_for(root="."):
    return Path(root) / REGISTRY_PATH


def load(root="."):
    """Every registered provider. An absent file means none, not a default."""
    path = path_for(root)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("providers", [])
    validate(entries)
    return entries


def _check_one(entry, seen):
    for field in ("id", "name", "shape", "adapter", "clearance"):
        if not entry.get(field):
            raise RegistryError("a provider is missing %s: %r" % (field, entry))
    if entry["id"] in seen:
        raise RegistryError("two providers share the id %s" % entry["id"])
    if entry["clearance"] not in CLEARANCES:
        raise RegistryError("%s has clearance %r, not one of %s"
                            % (entry["id"], entry["clearance"], ", ".join(CLEARANCES)))
    if entry["shape"] not in SHAPES:
        raise RegistryError("%s has shape %r" % (entry["id"], entry["shape"]))
    if entry["adapter"] not in ADAPTERS:
        raise RegistryError("%s has adapter %r" % (entry["id"], entry["adapter"]))


def validate(entries):
    """Refuse a registry rather than running with a half-understood one."""
    seen = set()
    for entry in entries:
        _check_one(entry, seen)
        seen.add(entry["id"])
    return entries


def matches(entry):
    """Whether this provider's detection rule fires in this process."""
    rule = entry.get("detect") or {}
    name = rule.get("env")
    if not name:
        return False
    expected = rule.get("equals")
    value = os.environ.get(name)
    if value is None:
        return False
    return True if expected is None else value == expected


def active(root="."):
    """The provider running now, or UNKNOWN.

    An explicit KULI_PROVIDER wins over detection, so a wrapper can always say
    what it is rather than hoping to be recognised.
    """
    entries = load(root)
    chosen = os.environ.get("KULI_PROVIDER")
    for entry in entries:
        if entry["id"] == chosen or (not chosen and matches(entry)):
            return with_model(entry)
    return dict(UNKNOWN)


def with_model(entry):
    """Fill the model name from the environment variable the entry names."""
    resolved = dict(entry)
    variable = entry.get("model_env")
    if variable and os.environ.get(variable):
        resolved["model"] = os.environ[variable]
    resolved.setdefault("model", None)
    return resolved


def clearance_rank(level):
    return CLEARANCES.index(level) if level in CLEARANCES else -1


def may_see(entry, level):
    """Whether a provider is cleared for content at `level`."""
    return clearance_rank(entry.get("clearance")) >= clearance_rank(level)


STARTER = {
    "_comment": "Edit by hand. Clearance is a decision, not a default.",
    "providers": [
        {
            "id": "claude-code",
            "name": "Claude Code",
            "shape": "agent-product",
            "adapter": "wrapped",
            "clearance": "L1",
            "detect": {"env": "CLAUDECODE"},
            "model_env": "KULI_MODEL",
            "capabilities": {
                "tool_calling": True,
                "parallel_tool_calls": True,
                "context_tokens": None,
            },
            "cost_per_mtok": {"in": None, "out": None},
            "good_for": [],
            "not_for": [],
        }
    ],
}


def write_starter(root="."):
    path = path_for(root)
    if path.exists():
        raise RegistryError("%s already exists; edit it rather than replacing it"
                            % path)
    path.write_text(json.dumps(STARTER, indent=2) + "\n", encoding="utf-8")
    return path
