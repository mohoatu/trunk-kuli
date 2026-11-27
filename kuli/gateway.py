"""The seam: three verbs, so one machine and a mesh are two transports.

Everything in this project so far assumes the agent and the tool are on the
same machine. That assumption is spread across the code rather than written
down anywhere, which is the expensive kind: the day a second machine appears,
every call site has to learn about transports at once.

So the seam is cut now, while there is only one side to it:

    resolve(service)              a name, never an address
    present(grant, …)             authority, signed, with a deadline
    dispatch(service, token, …)   the call, refused before it happens

`docs/07-orchestrator.md` §6 option 3 is the argument for doing this before
there is anything to connect: the local implementation is the one that exists,
the mesh implementation is deliberately absent, and `resolve` refuses a
transport it cannot honour rather than pretending.

**Names, not addresses.** A service is `mcp://chart-audit`, not a port. This is
the one idea from Agent Mesh that costs nothing to adopt and that a policy
written against addresses can never get back: a grant keeps meaning the same
thing when the thing it names moves.

**Deny by default, at both ends.** An unregistered service does not resolve. A
token that does not name the service is refused before the call is made. And
the result is classified on the way back, because the call being permitted
says nothing about what the answer turned out to contain.

**Filter the offer, not only the call.** Refusing at `dispatch` was correct and
the wrong end of the pipe: a queue an agent cannot work is a queue it should
never have been shown. `offer` returns the subset of a queue a grant permits,
and `dispatch` keeps refusing as the backstop it should always have been. Both
go through `withheld`, deliberately — a filter and a refusal that answer the
same question in two pieces of code will eventually disagree, and the
disagreement is a permission bug nobody is looking for.

Read from Tratha AI, which offers an agent only work it is capable of
([`08-neighbours.md`](../docs/08-neighbours.md) §3).

**A task is judged on what it declares.** `withheld` reads `service` and
`paths` from the task. A task that names no paths is judged on its service
alone, which is a real gap rather than a safe default: the gate cannot classify
what it was not told about. Declaring paths is how a task gets judged properly,
and the return-path check in `_check_return` is what stands behind a task that
did not.
"""

from . import capability, providers, toolguard
from .bundle import ClearanceError
from .classify import level_of
from .grants import coerce

#: Transports this build can honour. `mesh` is absent on purpose.
TRANSPORTS = ("local",)


class GatewayError(Exception):
    """A call that will not be attempted. Never downgraded into a warning."""


def services(root="."):
    """Every registered service. An absent registry means none, not any."""
    return providers.registry(root).get("services", [])


def resolve(service, root="."):
    """The endpoint for a name, or a refusal naming what is missing."""
    for entry in services(root):
        if entry.get("name") == service:
            return _endpoint(entry)
    raise GatewayError(
        "%s is not a registered service. Nothing resolves by default; add it "
        "to the services list in providers.json." % service)


def _endpoint(entry):
    transport = entry.get("transport")
    if transport not in TRANSPORTS:
        raise GatewayError(
            "%s asks for transport %r, and this build honours only %s. A mesh "
            "transport is described in docs/07-orchestrator.md and is not built."
            % (entry.get("name"), transport, ", ".join(TRANSPORTS)))
    return dict(entry)


def present(authority, key, seconds=900, **limits):
    """A signed, expiring capability for no more than this authority allows."""
    grant = coerce(authority)
    return capability.mint(grant.narrow(**limits) if limits else grant,
                           key, seconds)


def as_task(what):
    """A task, from a task or from a bare service name."""
    return what if isinstance(what, dict) else {"service": what}


def withheld(task, authority, config=None):
    """Why this authority may not take this task, or None when it may.

    The one place that answers the question, so that `offer` and `dispatch`
    cannot drift apart. A task is judged on what it declares: its service, and
    the classification level of every path it names.
    """
    grant = coerce(authority)
    task = as_task(task)
    service = task.get("service")
    reason = grant.refusal(tool=service) if service else None
    if reason:
        return reason
    for path in task.get("paths") or ():
        reason = grant.refusal(path=path, level=level_of(path, config))
        if reason:
            return reason
    return None


def offer(tasks, authority, config=None):
    """The subset of a queue this authority may work. The rest is not shown."""
    return [task for task in tasks if not withheld(task, authority, config)]


def dispatch(task, token, key, call, root=".", config=None):
    """Verify, resolve, refuse or call, then judge what came back.

    `call` receives the endpoint and returns the result. Injecting it is what
    keeps this module free of any one transport's details — and what lets the
    gates be tested without a network.
    """
    grant = capability.verify(token, key)
    endpoint = resolve(as_task(task).get("service"), root)

    refusal = withheld(task, grant, config)
    if refusal:
        raise GatewayError("the call was not made: %s" % refusal)

    result = call(endpoint)
    _check_return(result, grant, config)
    return result


def _check_return(result, grant, config):
    """The return path, against the grant rather than against the registry."""
    level, reason = toolguard.assess({}, str(result), config)
    refusal = grant.refusal(level=level)
    if refusal:
        raise ClearanceError(
            "the result is withheld, not trimmed: %s (%s)" % (refusal, reason))
    return level
