"""kuli's own loop for a raw model: context in, tools dispatched, record out.

T10 of [`05-provider-tasks.md`](../docs/05-provider-tasks.md). An agent
product brings its own loop and kuli wraps it; a raw model has none, so this
is it. Small on purpose — every gate it uses already exists and is tested, and
the loop's job is to call them in the right order rather than to be clever.

Five decisions, and each is the reason a line of this is where it is.

**The record is written here, not by the model.** Every turn and every tool
call goes through `trail.append` with the *same payload shape a Claude Code
hook sends* — `hook_event_name`, `tool_name`, `tool_input`, `tool_response` —
so `kuli trail`, `kuli audit` and `kuli report` read a local model's run and a
wrapped product's run with one code path. That is T10's done-when, and the
test compares the key sets rather than taking anyone's word.

**A refusal is handed back to the model as the tool result.** Not raised, not
swallowed. The loop has to continue, and the model has to learn that it may
not have the thing — a loop that dies on a refused tool call turns every
boundary into an outage. The refusal text names the path and the levels and
never the content, which is the same rule the assembler follows.

**Permission is checked before the handler runs**, by `gateway.withheld` — the
same function `offer` and `dispatch` use. Three callers, one answer. And the
*result* is checked again by `toolguard`, because the path a model asked for
says nothing about what the file turned out to contain.

**The grant is never widened.** Whatever is passed in is the ceiling for the
whole run. There is no call here that produces a wider one, because
`grants.py` has none.

**The step budget is a stop reason, not a truncation.** Running out is
reported as `out of steps` with the work done so far, which is the honest
version of a loop that stopped. P3 of
[`08-neighbours.md`](../docs/08-neighbours.md) asked for a bound that cannot
loop; this is the loop that would have.
"""

from . import adapters, bundle, gateway, toolguard, tools, trail

DEFAULT_STEPS = 6

#: Why the loop stopped. One of these, always, and never a silence.
ANSWERED, OUT_OF_STEPS = "answered", "out of steps"


def opening(task, grant, config=None):
    """The bundle, assembled and checked, turned into the first messages."""
    parts = [bundle.part_for(path, config, text)
             for path, text in (task.get("context") or {}).items()]
    parcel = bundle.assemble(parts, grant)
    return adapters.messages_from(parcel, task["prompt"]), parcel


def actor_of(entry):
    """What the loop may state about the provider it is driving.

    The loop knows which registry row it is calling, which a hook payload
    does not get to claim — `trail.actor_from` keeps the two apart.
    """
    return {"provider": entry.get("id"), "model": entry.get("model"),
            "clearance": entry.get("clearance")}


def _record(root, event, name, payload, response=None, actor=None):
    """One trail entry, in the shape a hook sends, written outside the model."""
    body = {"hook_event_name": event, "tool_name": name, "tool_input": payload}
    if response is not None:
        body["tool_response"] = response
    return trail.append(body, root, stated=actor)


def _refusal(name, arguments, grant, config):
    """Why this call may not be made, or None. The same answer `offer` gives."""
    return gateway.withheld({"service": name,
                             "paths": tools.paths_declared(name, arguments)},
                            grant, config)


def perform(request, grant, root=".", config=None, actor=None):
    """One tool call: permission, handler, return path. Always returns text."""
    name, arguments = request["name"], request["arguments"]
    _record(root, "PreToolUse", name, arguments, actor=actor)

    refused = _refusal(name, arguments, grant, config)
    if refused:
        return _withhold(root, name, arguments, refused, actor)
    try:
        text = tools.run(name, arguments, root)
    except tools.ToolError as exc:
        return _withhold(root, name, arguments, str(exc), actor)

    try:
        toolguard.check(arguments, text, grant, config)
    except bundle.ClearanceError as exc:
        return _withhold(root, name, arguments, str(exc), actor)

    _record(root, "PostToolUse", name, arguments, text, actor)
    return text


def _withhold(root, name, arguments, reason, actor=None):
    """Record the refusal and give the model the reason, never the content."""
    _record(root, "PostToolUse", name, arguments, {"refused": reason}, actor)
    return "REFUSED: %s" % reason


def _answer(request, text):
    return {"role": "tool", "tool_call_id": request["id"],
            "name": request["name"], "content": text}


def _turn(messages, entry, grant, root, config, schemas, talk):
    """One exchange. Returns (assistant message, the tool answers it caused)."""
    actor = actor_of(entry)
    reply = talk(messages, entry, schemas)
    _record(root, "ModelReply", entry.get("id"), {"model": entry.get("model")},
            reply.get("content") or "", actor)
    requests = adapters.tool_calls_in(reply)
    return reply, [_answer(r, perform(r, grant, root, config, actor))
                   for r in requests]


def run(task, entry, grant, root=".", config=None, steps=DEFAULT_STEPS,
        allowed=None, talk=None):
    """The loop. Returns what happened, including why it stopped."""
    messages, parcel = opening(task, grant, config)
    adapters.check(parcel, entry)
    schemas = tools.schemas(allowed, adapters.tool_schema)
    talk = talk or adapters.converse
    calls = 0

    for _ in range(steps):
        reply, answers = _turn(messages, entry, grant, root, config,
                               schemas, talk)
        messages.append(reply)
        if not answers:
            return _result(ANSWERED, reply.get("content") or "", calls, parcel)
        messages.extend(answers)
        calls += len(answers)

    return _result(OUT_OF_STEPS, "", calls, parcel)


def _result(stopped, text, calls, parcel):
    return {"stopped": stopped, "text": text, "tool_calls": calls,
            "context": list(parcel.sources), "level": parcel.max_level}
