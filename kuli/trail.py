"""The trail: what the agents actually did, recorded by something that is not them.

An agent writing its own log produces a **claim**. This recorder sits outside
the agent, at the tool-call boundary, so it records what happened rather than
what the agent says happened — the same reason §8.5 requires an execution
rather than an assertion, and the same reason secrets are never readable by
the model.

**Append-only, hash-chained.** Each entry carries the digest of the one before
it, so an entry cannot be altered or removed without breaking every digest
after it. This is the ledger from `p2p-lending`, pointed at agent actions
instead of money, and for the same reason: a record that can be quietly edited
is not a record.

**Observe only.** Nothing here refuses anything. The corridor comes later, and
its rules will be written from what this shows rather than from what anyone
imagined — back pressure before forward pressure, evidence before policy.

Stored per repository at `.kuli/trail/YYYY-MM-DD.jsonl`, one JSON object per
line: readable with `grep`, diffable in review, and small because the trail
holds fingerprints rather than contents.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import paths, providers, redact

TRAIL_DIR = Path(".kuli/trail")
HEAD_FILE = TRAIL_DIR / "HEAD"
GENESIS = "0" * 64


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def day_file(root, stamp=None):
    stamp = stamp or now()
    return Path(root) / TRAIL_DIR / ("%s.jsonl" % stamp[:10])


def digest(entry, previous):
    """Hash of this entry's content plus the previous digest."""
    payload = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((previous + payload).encode("utf-8")).hexdigest()


def read_head(root):
    path = Path(root) / HEAD_FILE
    if not path.exists():
        return GENESIS
    return path.read_text(encoding="utf-8").strip() or GENESIS


def write_head(root, value):
    path = paths.ensure_parent(Path(root) / HEAD_FILE)
    path.write_text(value + "\n", encoding="utf-8")


def first(event, keys, env=None, default="unknown"):
    """The first of `keys` the event actually carries, then the environment.

    Hook payloads differ between providers and between versions of the same
    provider, so every field here is looked up under several names rather
    than assumed.
    """
    for key in keys:
        if event.get(key):
            return event[key]
    if env and os.environ.get(env):
        return os.environ[env]
    return default


def running_provider(root="."):
    try:
        return providers.active(root)
    except (providers.RegistryError, ValueError):
        return dict(providers.UNKNOWN)


#: The fields only kuli's own code may state. See `actor_from`.
STATED = ("provider", "model", "clearance")


def actor_from(event, root=".", stated=None):
    """Who did it, as far as the boundary can tell.

    The provider, model and clearance come from the registry, **not from the
    event** — the event is written by the agent and the registry is not. An
    earlier version read `event["provider"]` first, which contradicted this
    docstring and let a payload name a provider, and therefore a clearance,
    of its own choosing.

    `stated` is the exception, and it is narrow: kuli's own loop (`runner.py`)
    knows which registry entry it is driving, and the refusal recorder knows
    which provider it just refused. Both are kuli calling itself, not an agent
    describing itself. Nothing arriving from a hook payload can set these.

    With no registry the answer is `unknown`, recorded honestly rather than
    guessed from whatever is in the environment.
    """
    found = running_provider(root)
    actor = {
        "provider": found["id"],
        "model": found.get("model") or "unknown",
        "clearance": found.get("clearance"),
        "session": first(event, ("session_id", "session")),
        "run": first(event, ("run",), "KULI_RUN"),
    }
    for field in STATED:
        if stated and stated.get(field):
            actor[field] = stated[field]
    return actor


#: Where a tool names the thing it is acting on.
TARGET_KEYS = ("file_path", "path", "notebook_path", "url", "command")


def payload_of(event):
    found = first(event, ("tool_input", "input"), default={})
    return found if isinstance(found, dict) else {}


def target_from(event):
    """The thing acted on, when the tool names one."""
    payload = payload_of(event)
    name = first(payload, TARGET_KEYS, default=None)
    return redact.shorten(str(name)) if name else None


def build(event, root=".", stated=None):
    """Turn a raw hook payload into the entry that will be appended."""
    body = {
        "ts": now(),
        "event": first(event, ("hook_event_name", "event")),
        "tool": first(event, ("tool_name", "tool")),
        "actor": actor_from(event, root, stated),
        "target": target_from(event),
        "cwd": redact.shorten(str(first(event, ("cwd",), default=root))),
        "detail": redact.clean(payload_of(event)),
    }
    response = first(event, ("tool_response", "result"), default=None)
    if response is not None:
        body["result"] = redact.clean(_as_content(response))
    return body


def _as_content(response):
    """A bare tool result is **content**, so name it as one.

    `redact.clean` fingerprints a value whose key is in `CONTENT_FIELDS` and
    merely shortens anything else. A plain string arriving as the whole
    response used to land in the second case, so up to `MAX_STRING` characters
    of a file a tool had just read were written into the trail verbatim. The
    runner (T10) made that systematic: its tools return file text.

    Wrapping it under `output` puts it where it belonged — stored as a size
    and a digest, never as the bytes.
    """
    return response if isinstance(response, dict) else {"output": response}


def append(event, root=".", stated=None):
    """Record one action. Returns the written entry.

    `stated` is only for kuli's own code naming the provider it is driving;
    see `actor_from`.
    """
    previous = read_head(root)
    body = build(event, root, stated)
    body["prev"] = previous
    body["hash"] = digest(body, previous)

    path = paths.ensure_parent(day_file(root, body["ts"]))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(body, sort_keys=True) + "\n")
    write_head(root, body["hash"])
    return body


def entries(root=".", since=None):
    """Every entry, oldest first. `since` is a YYYY-MM-DD prefix."""
    directory = Path(root) / TRAIL_DIR
    if not directory.exists():
        return []
    found = []
    for path in sorted(directory.glob("*.jsonl")):
        if since and path.stem < since:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                found.append(json.loads(line))
    return found


def verify(root="."):
    """Walk the chain. Returns (ok, problems)."""
    problems = []
    previous = GENESIS
    for index, entry in enumerate(entries(root)):
        stated = entry.get("hash")
        body = {k: v for k, v in entry.items() if k != "hash"}
        if entry.get("prev") != previous:
            problems.append("entry %d: expected prev %s, found %s"
                            % (index, previous[:12], str(entry.get("prev"))[:12]))
        if digest(body, entry.get("prev", "")) != stated:
            problems.append("entry %d: content does not match its digest" % index)
        previous = stated or previous
    return (not problems), problems


def summarise(records):
    """Counts a person actually asks for: by tool, by actor, by day."""
    by_tool, by_actor, by_day = {}, {}, {}
    for entry in records:
        by_tool[entry.get("tool")] = by_tool.get(entry.get("tool"), 0) + 1
        who = entry.get("actor", {}).get("provider", "unknown")
        by_actor[who] = by_actor.get(who, 0) + 1
        day = entry.get("ts", "")[:10]
        by_day[day] = by_day.get(day, 0) + 1
    return {"total": len(records), "by_tool": by_tool,
            "by_actor": by_actor, "by_day": by_day}


def per_provider(records):
    """One row per provider seen in the trail: what it did, and when."""
    rows = {}
    for entry in records:
        actor = entry.get("actor", {})
        row = rows.setdefault(actor.get("provider", "unknown"), {
            "actions": 0, "tools": set(), "models": set(),
            "first": None, "last": None,
        })
        row["actions"] += 1
        row["tools"].add(entry.get("tool"))
        row["models"].add(actor.get("model") or "unknown")
        stamp = entry.get("ts", "")
        row["first"] = min(row["first"] or stamp, stamp)
        row["last"] = max(row["last"] or stamp, stamp)
    return rows


def touched(records, needle):
    """Every entry whose target mentions `needle` — who changed this file."""
    return [e for e in records if needle in (e.get("target") or "")]
