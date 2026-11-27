"""A process that holds the credentials, so the adapter does not.

T15 of [`05-provider-tasks.md`](../docs/05-provider-tasks.md). Everything so
far has kept secrets out of a model's *context*. This keeps them out of the
*process that talks to the model*, which is a different and weaker boundary
until something enforces it.

The shape is deliberately dull. A loopback HTTP server, `urllib`, and a table
of destinations read from `providers.json`. An adapter is configured with
`endpoint: http://127.0.0.1:8808/to/anthropic` and **no** `api_key_env`, so
its environment never carries a key, its request body never carries a key,
and a dump of its memory never carries a key. The proxy adds the credential
on the way out.

Four rules.

**A destination is a name, not a URL.** The adapter asks for `/to/anthropic`
and has no say in where that goes. An adapter that could name the host could
name a host of its own choosing, and the allowlist would be a suggestion.

**Deny by default.** A name that is not in the table is refused with 403 and
recorded. There is no pass-through and no default destination.

**The key is read once, at startup, by this process.** If a destination names
an environment variable that is not set, the server refuses to start rather
than starting and failing one request at a time — a proxy that is up but
cannot authenticate looks like an outage somewhere else.

**Both outcomes are recorded.** An allowed call and a refused one are written
to the trail with the destination, the upstream host and the status. The
body is never recorded, in either direction.

What this is not: it is not a security boundary against the adapter, because
both run as the same user on the same machine and nothing stops a determined
process from reading the environment of another. It raises the cost of an
accident — a logged request, a crash dump, a context window — from certain to
unlikely. `[OPEN-14]` asked whether this should be a library instead; a
library would share the address space with the thing it is protecting
secrets from, which is the one property that makes this worth the process.
"""

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import providers, trail

#: Defined in `providers` so that the clearance check can recognise a routed
#: URL as not-local without importing this module.
PREFIX = providers.EGRESS_PREFIX

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8808
TIMEOUT = 120


class EgressError(Exception):
    """A proxy that will not start, or a destination that will not be used."""


def destinations(root="."):
    """The allowlist. An absent table means nothing may leave, not anything."""
    return providers.registry(root).get("egress", {})


def split(path):
    """(destination, the rest of the path) or (None, path) when unaddressed."""
    if not path.startswith(PREFIX):
        return None, path
    rest = path[len(PREFIX):]
    name, _, tail = rest.partition("/")
    return (name or None), "/" + tail


def credentials(table, env):
    """Every destination's key, read once. Missing one is a refusal to start."""
    held = {}
    for name, spec in sorted(table.items()):
        variable = spec.get("key_env")
        if not variable:
            raise EgressError("destination %r names no key_env" % name)
        value = env.get(variable)
        if not value:
            raise EgressError(
                "destination %r needs %s, which is not set. Refusing to start: "
                "a proxy that cannot authenticate looks like an outage "
                "somewhere else." % (name, variable))
        held[name] = value
    return held


def upstream_request(spec, key, tail, body):
    """The outbound request, with the credential added here and only here."""
    request = urllib.request.Request(spec["url"].rstrip("/") + tail,
                                     data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header(spec.get("header") or "authorization", key)
    for name, value in (spec.get("extra") or {}).items():
        request.add_header(name, value)
    return request


def forward(request, open_url=None):
    """Returns (status, body). An upstream failure is a status, not a crash."""
    opener = open_url or urllib.request.urlopen
    try:
        with opener(request, timeout=TIMEOUT) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return 502, json.dumps(
            {"error": "the destination could not be reached: %s"
                      % type(exc).__name__}).encode("utf-8")


def record(root, event, detail, status=None):
    trail.append({"hook_event_name": event, "tool_name": "egress",
                  "tool_input": detail,
                  "tool_response": {"status": status} if status else None},
                 root, stated={"provider": "egress-proxy"})


class Proxy(BaseHTTPRequestHandler):
    """One request: name the destination, or be refused by name."""

    def do_POST(self):
        name, tail = split(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        table = self.server.table
        if name not in table:
            return self._refuse(name, sorted(table))
        status, answer = forward(upstream_request(
            table[name], self.server.keys[name], tail, body))
        record(self.server.root, "EgressAllowed",
               {"destination": name, "url": table[name]["url"], "path": tail},
               status)
        self._send(status, answer)

    def _refuse(self, name, allowed):
        record(self.server.root, "EgressRefused",
               {"destination": name, "path": self.path, "allowed": allowed})
        self._send(403, json.dumps(
            {"error": "%r is not an allowed destination" % name}
        ).encode("utf-8"))

    def _send(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        """Silent on purpose: a request log is where a key leaks."""


def build(root=".", port=DEFAULT_PORT, env=None):
    """A server bound to loopback, or a refusal to start. Does not serve yet."""
    table = destinations(root)
    if not table:
        raise EgressError("no egress table in providers.json; nothing may "
                          "leave, which is the default and not an error")
    server = HTTPServer((LOOPBACK, port), Proxy)
    server.table = table
    server.keys = credentials(table, env if env is not None else os.environ)
    server.root = root
    return server


def serve(root=".", port=DEFAULT_PORT, env=None):
    server = build(root, port, env)
    server.serve_forever()
    return 0
