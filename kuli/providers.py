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

import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY_PATH = Path("providers.json")

#: A clearance above this must be **shown**, not declared. L1 is what an
#: endpoint nobody has verified is worth: it may be anywhere, so treat it as
#: somewhere else. See T8 in docs/05-provider-tasks.md.
UNVERIFIED_CEILING = "L1"

#: Names that mean this machine without a DNS lookup.
LOOPBACK_NAMES = ("localhost",)

#: Lowest to highest. A provider may see its own level and below.
CLEARANCES = ("L0", "L1", "L2", "L3")

SHAPES = ("agent-product", "raw-model")
ADAPTERS = ("wrapped", "openai_compatible", "anthropic")

UNKNOWN = {"id": "unknown", "name": "unknown", "shape": None,
           "adapter": None, "clearance": None, "model": None}

#: Keys this version understands. Anything else is refused rather than
#: ignored: a misspelt `clearence` that is silently skipped is a permission
#: nobody applied and everybody believed. A measure may abstain when it cannot
#: judge; a permission may not.
DOCUMENT_KEYS = ("_comment", "providers", "services")
ENTRY_KEYS = ("id", "name", "shape", "adapter", "clearance", "detect",
              "model", "model_env", "endpoint", "endpoint_env", "api_key_env",
              "capabilities", "cost_per_mtok", "good_for", "not_for")
SERVICE_KEYS = ("name", "transport", "target", "note")


class RegistryError(Exception):
    """A registry that cannot be trusted. Never fall back to a default."""


def path_for(root="."):
    return Path(root) / REGISTRY_PATH


def _only(where, data, allowed):
    """Refuse a key this version does not understand, naming it."""
    extra = sorted(set(data) - set(allowed))
    if extra:
        raise RegistryError("%s carries unknown key(s): %s. Fail closed rather "
                            "than ignore a permission field."
                            % (where, ", ".join(extra)))


def registry(root="."):
    """The whole validated document. An absent file is an empty one."""
    path = path_for(root)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RegistryError("%s must hold an object" % path)
    _only(str(path), data, DOCUMENT_KEYS)
    validate(data.get("providers", []))
    for service in data.get("services", []):
        _only("service %r" % service.get("name"), service, SERVICE_KEYS)
    return data


def setting(entry, direct, variable, env=None):
    """A setting, from the environment variable the entry names or inline.

    Here rather than in the adapter because **verification has to read the
    same value the call will use.** If clearance were checked against the
    inline endpoint while the request went to the one in the environment, the
    check would be decoration.
    """
    env = env if env is not None else os.environ
    name = entry.get(variable)
    found = env.get(name) if name else None
    return found or entry.get(direct)


def host_of(url):
    text = url or ""
    parsed = urlsplit(text if "//" in text else "//" + text)
    return (parsed.hostname or "").lower()


def is_loopback(url):
    """Whether this endpoint is certainly on this machine.

    An IP literal is decided arithmetically. `localhost` and `*.localhost` are
    reserved for the loopback interface by RFC 6761, so they count. **Any other
    name does not**, even one that resolves to 127.0.0.1 today: a DNS answer is
    not a property of the address, and a clearance that depends on a lookup is
    a clearance that changes without anybody editing anything.
    """
    host = host_of(url)
    if not host:
        return False
    if host in LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def verified(entry, env=None):
    """The clearance this entry has earned, and why. Never raises one.

    L2 means *only this model may see confidential content*, which is true
    only if the model runs here. The cheap evidence for that is a loopback
    endpoint. A provider that cannot show one is **demoted and says so**,
    rather than being disabled, which would make the harness unusable, or
    silently trusted, which is the failure this exists to prevent.

    Half of T8 is here. The other half — that the process has no outbound
    network allowance — cannot be checked from inside it and waits for the
    egress proxy in T15.
    """
    declared = entry.get("clearance")
    if clearance_rank(declared) <= clearance_rank(UNVERIFIED_CEILING):
        return declared, "declared %s, which needs no proof" % declared
    url = setting(entry, "endpoint", "endpoint_env", env)
    if is_loopback(url):
        return declared, ("%s stands: %s is on this machine"
                          % (declared, host_of(url)))
    return UNVERIFIED_CEILING, (
        "declared %s, demoted to %s: %s is not a loopback address"
        % (declared, UNVERIFIED_CEILING, url or "no endpoint is configured"))


def as_verified(entries, env=None):
    """Each entry as it will actually behave: earned clearance, real model.

    `with_model` is applied here rather than left to each caller, because the
    first time it was not, the adapter read the model from the environment and
    the trail read it from the file — so a run against `qwen3:4b` was recorded
    as `qwen3:8b`. An audit record naming a different model than the one that
    answered is worse than no record: it is a confident wrong answer to the
    only question the trail exists to settle.
    """
    resolved = []
    for entry in entries:
        entry.update(with_model(entry, env))
        entry["clearance"], entry["clearance_reason"] = verified(entry, env)
        resolved.append(entry)
    return resolved


def demoted(entries):
    return [e for e in entries if "demoted" in (e.get("clearance_reason") or "")]


def load(root=".", env=None):
    """Every registered provider, at the clearance each has earned."""
    return as_verified(registry(root).get("providers", []), env)


def _check_one(entry, seen):
    _only("provider %r" % entry.get("id"), entry, ENTRY_KEYS)
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
            return entry
    return dict(UNKNOWN)


def with_model(entry, env=None):
    """Fill the model name from the environment variable the entry names."""
    resolved = dict(entry)
    resolved["model"] = setting(entry, "model", "model_env", env)
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
