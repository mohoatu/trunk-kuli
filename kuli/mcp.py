"""The gates, as tools an agent calls in its own loop.

Everything here is already a program with an exit code, and nothing outside
this repository's CI can reach it. That is the gap
[`08-neighbours.md`](../docs/08-neighbours.md) found by reading two shipped
products: one of them is an MCP server rather than a command, so any agent
that speaks the protocol calls it *in the loop*, every time, instead of being
wrapped by it and hoping a hook fires.

This module is that surface. Newline-delimited JSON-RPC 2.0 over stdin and
stdout, written against the standard library, because constitution 9 says a
gate that needs installing is a gate somebody skips — and an SDK dependency
here would be the first one in the project.

Three rules decide what this exposes, and they matter more than the wire
format.

**It is read-only.** Every tool returns a verdict; none writes a file. There
is no `baseline`, no `contract freeze`, no `providers --init`. An agent may
ask *would this pass* as often as it likes and has no way to move a bar
through this door. Lowering a bar stays what it was: a commit, in its own
diff, with a person's name in the trailer.

**A verdict is never an argument.** No tool accepts a level, a measure, an
allowance or a pass/fail. The caller says what to look at; this says what it
found. A surface that let a model pass in the answer would be a prompt with a
JSON schema.

**Cannot judge is not a pass.** A gate with no baseline, outside a git
repository, or with nothing claimed returns `isError: true` and a text that
begins `CANNOT JUDGE`. A refusal is a normal result and returns `isError:
false` beginning `REFUSED` — because a refusal is the tool working, and an
agent that treats it as a crash will retry it.
"""

import json
import sys

from . import capability, contract, duties, gateway, grants, ratchet, review_cost
from .classify import explain

PROTOCOL = "2024-11-05"
NAME = "kuli"
VERSION = "0.1.0"

PASS, REFUSED, UNDECIDED = "PASS", "REFUSED", "CANNOT JUDGE"

METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


def _ratchet(args, root):
    ok, report = ratchet.run(root)
    if ok is None:
        return UNDECIDED, report["error"]
    if ok:
        return PASS, "No measure got worse."
    return REFUSED, "\n".join(ratchet.describe(t) for t in report["trips"])


def _classify(args, root):
    config = ratchet.load_config(root)
    lines = []
    for path in args.get("paths") or []:
        level, reason = explain(path, config)
        lines.append("%-4s %s — %s" % (level, path, reason))
    if not lines:
        return UNDECIDED, "No paths given, so nothing was classified."
    return PASS, "\n".join(lines)


def _review_cost(args, root):
    ok, report = review_cost.run(args.get("base"), root)
    if ok is None:
        return UNDECIDED, "No acceptance criterion was claimed by this change."
    verdict = PASS if ok else REFUSED
    return verdict, json.dumps(report, indent=2, sort_keys=True)


def _duties(args, root):
    ok, report = duties.run(args.get("base"), root)
    if ok:
        return PASS, "Nobody relaxed a rule that was judging them."
    lines = []
    for record, problems in report["faults"]:
        lines.append(record["commit"])
        lines.extend("    " + problem for problem in problems)
    return REFUSED, "\n".join(lines)


def _contract_check(args, root):
    ok, _, problems = contract.check(args.get("slug"), root)
    if ok:
        return PASS, "Signed by two different actors."
    return REFUSED, "\n".join(problems)


def _capability_verify(args, root):
    key = capability.signing_key(root)
    grant = capability.verify(args.get("token"), key)
    return PASS, json.dumps(grant.as_dict(), indent=2, sort_keys=True)


def _offer(args, root):
    """Which of a queue a capability may work. Takes a token, never a level.

    The authority arrives as a signature rather than as a claim, which is what
    keeps "a verdict is never an argument" true for a tool that has to be told
    who is asking.
    """
    grant = capability.verify(args.get("token"), capability.signing_key(root))
    config = ratchet.load_config(root)
    tasks = args.get("tasks") or []
    verdicts = [(t, gateway.withheld(t, grant, config)) for t in tasks]
    return PASS, json.dumps(
        {"offered": [t for t, why in verdicts if not why],
         "withheld": [{"task": t, "reason": why} for t, why in verdicts if why]},
        indent=2, sort_keys=True)


OFFER_SCHEMA = {
    "type": "object",
    "properties": {
        "token": {"type": "string", "description": "a kuli1 capability token"},
        "tasks": {"type": "array", "items": {"type": "object"},
                  "description": "queue entries, each with a service and the "
                                 "paths it will touch"},
    },
    "required": ["token", "tasks"],
}


def _paths_schema(description):
    return {"type": "object",
            "properties": {"paths": {"type": "array",
                                     "items": {"type": "string"},
                                     "description": description}},
            "required": ["paths"]}


def _one(name, description):
    return {"type": "object",
            "properties": {name: {"type": "string", "description": description}},
            "required": [name]}


NOTHING = {"type": "object", "properties": {}}

#: Every tool: what it is called, what it answers, what it takes, and the
#: function that decides. No entry writes anything — see the module docstring.
TOOLS = (
    ("ratchet", "Whether any guarded measure got worse than the recorded "
                "baseline. Returns the measures carrying a regression.",
     NOTHING, _ratchet),
    ("classify", "What classification level each path holds, and the rule or "
                 "pattern that decided it.",
     _paths_schema("repository-relative paths to classify"), _classify),
    ("review_cost", "Whether a change costs more to read than the acceptance "
                    "criteria it serves can justify.",
     _one("base", "git ref to compare against"), _review_cost),
    ("duties", "Whether any commit changed the rules and the work they judge "
               "together, or changed the rules with no second actor.",
     _one("base", "git ref to compare against"), _duties),
    ("contract_check", "Whether an increment's contract is signed by two "
                       "different actors.",
     _one("slug", "the increment's contract slug"), _contract_check),
    ("capability_verify", "What grant a capability token carries, or why it is "
                          "refused. Never issues one.",
     _one("token", "a kuli1 capability token"), _capability_verify),
    ("offer", "Which entries in a queue a capability may work, and the reason "
              "each withheld one was not offered.",
     OFFER_SCHEMA, _offer),
)

HANDLERS = dict((name, handler) for name, _, _, handler in TOOLS)


def described():
    return [{"name": name, "description": description, "inputSchema": schema}
            for name, description, schema, _ in TOOLS]


#: Refusals a tool may raise that are the gate answering, not the gate
#: breaking. Anything else is a defect and says so.
EXPECTED = (ratchet.ConfigError, contract.ContractError, grants.GrantError,
            capability.CapabilityError, RuntimeError, ValueError)


def call(name, args, root):
    """Run one tool. Returns the MCP result object for it."""
    handler = HANDLERS.get(name)
    if handler is None:
        return _result(UNDECIDED, "There is no tool called %r." % name)
    try:
        verdict, text = handler(args or {}, root)
    except EXPECTED as exc:
        return _result(UNDECIDED, "%s: %s" % (type(exc).__name__, exc))
    return _result(verdict, text)


def _result(verdict, text):
    return {"content": [{"type": "text", "text": "%s\n%s" % (verdict, text)}],
            "isError": verdict == UNDECIDED}


def _initialize(params, root):
    return {"protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": NAME, "version": VERSION}}


def _list(params, root):
    return {"tools": described()}


def _call(params, root):
    return call((params or {}).get("name"), (params or {}).get("arguments"), root)


METHODS = {"initialize": _initialize, "tools/list": _list, "tools/call": _call}


def handle(message, root="."):
    """One request in, one response out — or None for a notification."""
    identifier = message.get("id")
    method = METHODS.get(message.get("method"))
    if method is None:
        if identifier is None:
            return None
        return _error(identifier, METHOD_NOT_FOUND,
                      "no method %r" % message.get("method"))
    try:
        result = method(message.get("params"), root)
    except Exception as exc:  # noqa: BLE001 - a crash must not kill the server
        return _error(identifier, INTERNAL_ERROR, str(exc))
    if identifier is None:
        return None
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def _error(identifier, code, text):
    return {"jsonrpc": "2.0", "id": identifier,
            "error": {"code": code, "message": text}}


def serve(root=".", stream=None, out=None):
    """Read requests until stdin closes. A bad line is skipped, not fatal."""
    stream = stream or sys.stdin
    out = out or sys.stdout
    for line in stream:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        response = handle(message, root)
        if response is not None:
            out.write(json.dumps(response) + "\n")
            out.flush()
    return 0
