"""Authority, in a form that can only ever be narrowed.

Until now a provider's clearance was looked up from `providers.json` at the
moment it was needed. That answers *what may this provider see* and leaves the
harder question untouched: **what may the thing it spawned see.**

An agent cleared to L1 that starts a sub-task had nothing stopping the
sub-task being handed more than it had. The registry has no notion of a
sub-task, so the lookup simply returned the same clearance again, and a chain
of hops widened silently at every link.

A `Grant` is that authority made into a value. Three properties hold, and all
three are structural rather than advisory:

**There is no `widen`.** The only way to produce a grant from a grant is
`narrow`, which returns the **intersection** of the two. Asking for more than
the parent holds yields the parent's limit, not the request — so a chain of
hops can only ever shrink:

    root ⊇ root.narrow(...) ⊇ root.narrow(...).narrow(...) ⊇ …

This is the shape Google's Agent Mesh enforces on an attenuated credential,
read in `docs/07-orchestrator.md` §2.1, and it is the hole that assessment
found in this project.

**Nothing is permitted by default.** A grant lists what it allows. `"*"` is
how a root grant says *everything*, and it has to be written down. An empty
list permits nothing at all, which is the honest reading of an empty list.

**A grant without a level is cleared for nothing**, including L0 — the same
rule `bundle.py` already applies to an unrecognised provider, now carried by
the value itself rather than re-derived by each caller.

Scope is matched on path boundaries: `docs` covers `docs/a.md` and does not
cover `docsx/a.md`. A prefix test that got that wrong would be a permission
bug dressed as a string comparison.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from .classify import normalise
from .providers import CLEARANCES, clearance_rank

#: How a grant says *everything of this kind*. Never a default.
ANY = "*"


class GrantError(Exception):
    """A grant that cannot be trusted. Never substitute a default."""


def now():
    """UTC, to the second. Expiry is compared as text, so the format is fixed."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_covers(item, allowed):
    """Whether `allowed` covers `item`, on path boundaries rather than prefix."""
    if allowed == ANY:
        return True
    parent = normalise(allowed).rstrip("/")
    child = normalise(item)
    return child == parent or child.startswith(parent + "/")


def _name_covers(item, allowed):
    return allowed == ANY or item == allowed


def _intersect(held, asked, covers):
    """What both allow. `asked` of None means the request adds no limit."""
    if asked is None:
        return tuple(held)
    if ANY in held:
        return tuple(asked)
    return tuple(i for i in asked if any(covers(i, h) for h in held))


def _lower_level(held, asked):
    """The more restrictive of two levels. A request to raise is clamped."""
    if asked is None:
        return held
    if clearance_rank(asked) < clearance_rank(held):
        return asked
    return held


def _earlier(held, asked):
    """The sooner of two expiries. None means no expiry of its own."""
    candidates = [v for v in (held, asked) if v]
    return min(candidates) if candidates else None


def _level_refusal(grant, level):
    if level is None or clearance_rank(grant.level) >= clearance_rank(level):
        return None
    return ("%s is above %s, which holds %s"
            % (level, grant.principal, grant.level or "nothing"))


def _scope_refusal(grant, path):
    if path is None or any(_path_covers(path, s) for s in grant.scope):
        return None
    return "%s is outside the scope of %s" % (path, grant.principal)


def _tool_refusal(grant, tool):
    if tool is None or any(_name_covers(tool, t) for t in grant.tools):
        return None
    return "%s is not a tool %s may call" % (tool, grant.principal)


@dataclass(frozen=True)
class Grant:
    """What one principal may do. Immutable, and narrowable in one direction."""

    principal: str
    level: str = None
    scope: tuple = (ANY,)
    tools: tuple = (ANY,)
    expires: str = None

    def __post_init__(self):
        if not self.principal:
            raise GrantError("a grant with no principal grants nothing to nobody")
        if self.level is not None and self.level not in CLEARANCES:
            raise GrantError("level %r is not one of %s, or None for nothing"
                             % (self.level, ", ".join(CLEARANCES)))

    def narrow(self, level=None, scope=None, tools=None, expires=None):
        """A grant no wider than this one. The only way to make one."""
        return Grant(
            principal=self.principal,
            level=_lower_level(self.level, level),
            scope=_intersect(self.scope, scope, _path_covers),
            tools=_intersect(self.tools, tools, _name_covers),
            expires=_earlier(self.expires, expires),
        )

    def expired(self, moment=None):
        return bool(self.expires) and (moment or now()) >= self.expires

    def refusal(self, level=None, path=None, tool=None, moment=None):
        """Why this is not permitted, or None when it is.

        One reason per call, in the order a person would check them. Split
        into three helpers because the ratchet refused the single function
        that did all of it — see `kuli/paths.py` for the previous occasion.
        """
        if self.expired(moment):
            return "the grant expired at %s" % self.expires
        return (_level_refusal(self, level) or _scope_refusal(self, path)
                or _tool_refusal(self, tool))

    def permits(self, **asked):
        return self.refusal(**asked) is None

    def as_dict(self):
        return {"principal": self.principal, "level": self.level,
                "scope": list(self.scope), "tools": list(self.tools),
                "expires": self.expires}


def from_dict(data):
    """A grant from its recorded form. Refuses anything it does not recognise."""
    if not isinstance(data, dict):
        raise GrantError("a grant must be an object, not %s" % type(data).__name__)
    unknown = set(data) - {"principal", "level", "scope", "tools", "expires"}
    if unknown:
        raise GrantError("a grant carries unknown field(s): %s"
                         % ", ".join(sorted(unknown)))
    return Grant(principal=data.get("principal"), level=data.get("level"),
                 scope=tuple(data.get("scope") or ()),
                 tools=tuple(data.get("tools") or ()),
                 expires=data.get("expires"))


def for_provider(entry):
    """The root grant a registry entry describes — the widest one that exists.

    Deliberately the only place a grant is created from the registry. Every
    other grant in the system descends from one of these by `narrow`, so the
    registry sets the ceiling and nothing below it can exceed it.
    """
    return Grant(principal=entry.get("id") or "unknown",
                 level=entry.get("clearance"))


def coerce(authority):
    """A grant, from a grant or from a registry entry. Never from anything else."""
    if isinstance(authority, Grant):
        return authority
    if isinstance(authority, dict):
        return for_provider(authority)
    raise GrantError("%r is not a grant or a registry entry"
                     % type(authority).__name__)
