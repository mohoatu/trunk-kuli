"""A capability the agent can read, copy and delete — and cannot mint.

`providers.json` records each provider's clearance, and it is a file in the
repository. The agent whose clearance it records can edit it. Yesterday's
separation-of-duties gate catches that **in git**, after the commit; nothing
caught it at the moment of the call.

Agent Mesh closes the same hole by having the control plane sign the facts and
the receiving node verify them, so that *a caller writes neither* the authority
it claims nor the request it is judged on. That needs a control plane. This
module buys the same property with `hmac` from the standard library.

The registry stays where it is and keeps doing what it does: it is the written
record of a decision, and it sets the ceiling. What changes is that a
**signed grant** — not the file — is what a boundary accepts. An agent may
still rewrite `providers.json`; it cannot produce a signature for the entry it
invented, so the edit buys it nothing until a person signs.

Three decisions worth stating.

**The key lives outside the repository.** `signing_key` refuses a key file
inside the root it is protecting, because a secret an agent can read is a
secret an agent can sign with, and then this module is theatre.

**Every token expires.** A capability with no expiry is a permission, and the
difference is the whole point. `mint` requires a lifetime.

**Verification is constant-time and fails closed.** A malformed token, an
unknown version, a bad signature and an expired grant are one outcome:
refusal, with a reason that does not quote the token.
"""

import base64
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from . import grants

VERSION = "kuli1"
KEY_ENV = "KULI_CAPABILITY_KEY"
KEY_FILE_ENV = "KULI_CAPABILITY_KEY_FILE"

#: Shorter than this is not a key, it is a password somebody will guess.
MIN_KEY_BYTES = 32


class CapabilityError(Exception):
    """A capability that cannot be trusted. There is no partial acceptance."""


def _encode(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(text):
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _from_file(path, root):
    target = Path(path).expanduser()
    inside = Path(root).resolve()
    if target.resolve() == inside or inside in target.resolve().parents:
        raise CapabilityError(
            "%s is inside %s. A signing key an agent can read is a signing key "
            "an agent can use; keep it outside the repository." % (target, inside))
    if not target.exists():
        raise CapabilityError("%s names %s, which does not exist"
                              % (KEY_FILE_ENV, target))
    return target.read_bytes().strip()


def signing_key(root=".", env=None):
    """The key, from the environment or a file outside the repository."""
    env = env if env is not None else os.environ
    if env.get(KEY_FILE_ENV):
        raw = _from_file(env[KEY_FILE_ENV], root)
    elif env.get(KEY_ENV):
        raw = env[KEY_ENV].encode("utf-8")
    else:
        raise CapabilityError(
            "no signing key. Set %s to a key of at least %d bytes, or %s to a "
            "file holding one, outside this repository."
            % (KEY_ENV, MIN_KEY_BYTES, KEY_FILE_ENV))
    if len(raw) < MIN_KEY_BYTES:
        raise CapabilityError("the signing key is %d bytes; %d is the minimum"
                              % (len(raw), MIN_KEY_BYTES))
    return raw


def _payload(grant):
    return json.dumps(grant.as_dict(), sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _mac(body, key):
    return hmac.new(key, body, sha256).digest()


def sign(grant, key):
    """A token for exactly this grant. Changing one field invalidates it."""
    body = _encode(_payload(grant))
    signed = ("%s.%s" % (VERSION, body)).encode("ascii")
    return "%s.%s.%s" % (VERSION, body, _encode(_mac(signed, key)))


def mint(grant, key, seconds, moment=None):
    """A token that expires. There is no call that produces one that does not."""
    if not seconds or seconds <= 0:
        raise CapabilityError("a capability needs a lifetime; %r is not one"
                              % (seconds,))
    return sign(grant.narrow(expires=_deadline(seconds, moment)), key)


def _deadline(seconds, moment=None):
    start = moment or datetime.now(timezone.utc)
    return (start + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split(token):
    parts = str(token).split(".")
    if len(parts) != 3 or parts[0] != VERSION:
        raise CapabilityError("not a %s capability" % VERSION)
    return parts


def verify(token, key, moment=None):
    """The grant this token carries, or a refusal. Never a partial grant."""
    version, body, mac = _split(token)
    expected = _mac(("%s.%s" % (version, body)).encode("ascii"), key)
    if not hmac.compare_digest(_encode(expected), mac):
        raise CapabilityError("the signature does not match; the grant is refused")
    try:
        grant = grants.from_dict(json.loads(_decode(body)))
    except (ValueError, grants.GrantError) as exc:
        raise CapabilityError("the grant inside the token is unusable: %s" % exc)
    if grant.expired(moment):
        raise CapabilityError("this capability expired at %s" % grant.expires)
    return grant
