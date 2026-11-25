"""What may be written into the trail, and what may not.

The trail will see file contents, shell commands and API responses. Written
down naively, **the audit log becomes the largest leak in the system** — one
file holding everything every agent ever touched.

So the rule is: **the trail records fingerprints, not contents.**

A file write is recorded as its path, its size and the SHA-256 of what was
written. That answers who changed what, when, and to exactly which bytes —
without the trail becoming a second copy of the codebase. It also keeps the
trail itself at a level that can live in the repository and be read by anyone
reviewing the work.

Secrets never reach even that far: patterns that look like credentials are
replaced before anything is hashed or stored.
"""

import hashlib
import re

#: Replaced wherever they appear, before anything else happens.
SECRET_PATTERNS = (
    re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*", re.I),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*[=:]\s*\S{6,}"),
    re.compile(r"\b[A-Za-z0-9+/]{60,}={0,2}\b"),  # long base64-ish blobs
)

REDACTED = "[redacted]"

#: Long enough to be useful in a report, short enough not to become storage.
MAX_STRING = 400


def scrub(text):
    """Remove anything that looks like a credential."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def fingerprint(text):
    """What is stored instead of content: size and an exact digest."""
    data = text.encode("utf-8", "replace")
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "lines": text.count("\n") + 1 if text else 0,
    }


def shorten(text):
    """Keep a readable head, say how much was dropped, never store the rest."""
    text = scrub(text)
    if len(text) <= MAX_STRING:
        return text
    return "%s… [+%d chars]" % (text[:MAX_STRING], len(text) - MAX_STRING)


#: Fields whose value is content rather than description. These are
#: fingerprinted, never stored.
CONTENT_FIELDS = ("content", "new_string", "old_string", "file_text", "text",
                  "body", "stdout", "stderr", "output")


def clean_value(key, value):
    if isinstance(value, str) and key in CONTENT_FIELDS:
        return fingerprint(value)
    if isinstance(value, str):
        return shorten(value)
    if isinstance(value, dict):
        return clean(value)
    if isinstance(value, list):
        return [clean_value(key, item) for item in value[:20]]
    return value


def clean(mapping):
    """A dict safe to append to the trail."""
    if not isinstance(mapping, dict):
        return {"value": clean_value("", mapping)}
    return {str(k): clean_value(str(k), v) for k, v in mapping.items()}
