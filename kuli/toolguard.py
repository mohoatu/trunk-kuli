"""The return path: what a tool hands back, before it re-enters a context.

A model does not leak by reading its prompt. It leaks by **calling a tool** —
`read_file("business/legal/contract.md")` — and having the answer placed back
in front of it. The outbound check in `bundle.py` never sees that, because
the model chose the argument after the bundle was built.

So classification happens twice, and this is the second time.

Four rules decide a result's level, highest wins:

1. **Anything shaped like a credential makes it L3**, whatever its origin.
2. **A path named in the tool's input** gives the result that path's level.
   This is the exact case and the common one.
3. **A path mentioned in the output** raises it to that path's level — which
   is how `grep -r thing business/` gets caught, since the command declares
   no target but the answer names what it found.
4. Otherwise the result is **internal**, not confidential.

Rule 4 is the weak one and is written down as a decision rather than left
implicit. Tool output with no identifiable source is not a classified
artefact: it was produced inside the owner's environment, and defaulting it
to L2 would refuse every `ls` to a hosted provider, which is how a gate earns
being switched off. The protection against being wrong about it is rules 1
and 3, not the default. `tool_output_default` in `kuli.json` moves it for a
project that wants to be stricter.
"""

import re

from . import trail
from .bundle import ClearanceError
from .classify import explain
from .providers import clearance_rank
from .redact import SECRET_PATTERNS

DEFAULT_RESULT_LEVEL = "L1"

#: Where a tool declares what it is acting on.
TARGET_KEYS = ("file_path", "path", "notebook_path")

#: Something that looks like a path inside a blob of output.
PATH_IN_TEXT = re.compile(r"[\w.\-/]+/[\w.\-]+\.\w{1,6}")

#: Looking at more than this much output is not worth the time; rule 1 runs
#: over all of it regardless, because a credential anywhere is a credential.
SCAN_PATHS_LIMIT = 20000


def contains_secret(text):
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def declared_target(payload):
    if not isinstance(payload, dict):
        return None
    for key in TARGET_KEYS:
        if payload.get(key):
            return str(payload[key])
    return None


def paths_mentioned(text):
    """Paths that appear in the output itself, deduplicated, in order."""
    seen, found = set(), []
    for match in PATH_IN_TEXT.findall(text[:SCAN_PATHS_LIMIT]):
        if match not in seen:
            seen.add(match)
            found.append(match)
    return found


def _raise_from_paths(text, config, level, reason):
    """Rule 3: a path named in the output can only raise the level."""
    for candidate in paths_mentioned(text):
        found, _ = explain(candidate, config)
        if clearance_rank(found) > clearance_rank(level):
            level = found
            reason = "the output names %s, which is %s" % (candidate, found)
    return level, reason


def assess(payload, text, config=None):
    """Return (level, reason) for a tool result. Never reveals the text."""
    if contains_secret(text):
        return "L3", "the result contains something shaped like a credential"

    target = declared_target(payload)
    if target:
        level, _ = explain(target, config)
        reason = "the tool was given %s, which is %s" % (target, level)
    else:
        level = (config or {}).get("tool_output_default", DEFAULT_RESULT_LEVEL)
        reason = "no source declared; tool output defaults to %s" % level

    return _raise_from_paths(text, config, level, reason)


def check(payload, text, provider, config=None):
    """Raise unless this result may be shown to this provider."""
    level, reason = assess(payload, text, config)
    if clearance_rank(provider.get("clearance")) < clearance_rank(level):
        raise ClearanceError(
            "a %s result may not go back to %r, cleared to %s: %s. "
            "The result is withheld, not trimmed."
            % (level, provider.get("id", "unknown"),
               provider.get("clearance") or "nothing", reason))
    return level, reason


def guard(event, provider, config=None, root="."):
    """Check a tool result and record the refusal. Returns (ok, level, reason).

    A refusal that leaves no trace is indistinguishable from a result that
    never existed, so it is written to the trail before it is raised.
    """
    payload = event.get("tool_input") or event.get("input") or {}
    text = _result_text(event)
    try:
        level, reason = check(payload, text, provider, config)
    except ClearanceError as exc:
        _record_refusal(event, provider, str(exc), root)
        return False, None, str(exc)
    return True, level, reason


def _result_text(event):
    found = event.get("tool_response") or event.get("result") or ""
    if isinstance(found, dict):
        parts = [str(v) for v in found.values() if isinstance(v, (str, int, float))]
        return "\n".join(parts)
    return str(found)


def _record_refusal(event, provider, message, root):
    trail.append({
        "event": "ReturnPathRefused",
        "tool": event.get("tool_name") or event.get("tool") or "unknown",
        "session_id": event.get("session_id"),
        "provider": provider.get("id"),
        "input": event.get("tool_input") or event.get("input") or {},
        "result": {"refused": message},
    }, root)
