"""The `openai_compatible` adapter: messages in, text out, nothing else.

T7 of [`05-provider-tasks.md`](../docs/05-provider-tasks.md). One call, no
tools. Written against `urllib` from the standard library, because
constitution 9 holds here too and an HTTP client is the easiest dependency in
the world to justify and the hardest to remove.

The point of this module is not that it can call an endpoint. It is **where it
sits**: behind the bundle.

**It receives a bundle and cannot build one.** The only context an adapter
ever sees is a `Bundle`, already assembled and already checked against the
provider's clearance by `bundle.py`. This module imports no assembler and
calls none — a test reads its source to keep that true. An adapter that could
assemble its own context would be an adapter that decides what it may see,
and the whole classification boundary would be decoration.

**The bundle has to have been built for this provider.** `assemble` stamps the
provider id onto the bundle, and `complete` refuses a bundle stamped for
anyone else. Without that check, a bundle assembled for a local model cleared
to L2 could be handed to a hosted one cleared to L1 and every gate would have
passed on the way.

**A second endpoint is a config change, not a code change.** The base URL, the
model name and the API key all come from the registry entry — directly, or
from an environment variable the entry names. Reaching Ollama and reaching a
hosted OpenAI-compatible endpoint are the same code path with two rows in
`providers.json`.

**Nothing here is logged, and the key never leaves the header.** The API key
is read from the environment, placed in `Authorization`, and never put in the
body, the trail or an error message. Refusals name the status and the provider
and do not quote the response, for the same reason the classification errors
do not quote the content they refused.

Recording to the trail belongs to the runner (T10), not here. An adapter that
writes the record of its own call is an agent logging itself.
"""

import json
import os
import urllib.error
import urllib.request

from .bundle import Bundle
from .providers import setting

ADAPTER = "openai_compatible"
SHAPE = "raw-model"
COMPLETIONS = "/v1/chat/completions"
DEFAULT_TIMEOUT = 60


class AdapterError(Exception):
    """A call that will not be made, or an answer that cannot be read."""


def base_url(entry, env=None):
    url = setting(entry, "endpoint", "endpoint_env", env)
    if not url:
        raise AdapterError(
            "provider %r has no endpoint. Set one in providers.json, or name "
            "an environment variable in endpoint_env." % entry.get("id"))
    return url.rstrip("/")


def model_name(entry, env=None):
    name = setting(entry, "model", "model_env", env)
    if not name:
        raise AdapterError("provider %r names no model" % entry.get("id"))
    return name


def api_key(entry, env=None):
    """The key, or None. A local model needs none and must not be given one."""
    env = env if env is not None else os.environ
    return env.get(entry.get("api_key_env")) if entry.get("api_key_env") else None


def messages_from(parcel, prompt):
    """The bundle becomes the system message; the prompt becomes the user one.

    Deliberately the whole mapping. There is no third source of content, so
    there is nowhere for context to arrive that the bundle did not carry.
    """
    text = "\n\n".join(part.text for part in parcel.parts if part.text)
    messages = [{"role": "system", "content": text}] if text else []
    messages.append({"role": "user", "content": prompt})
    return messages


def check(parcel, entry):
    """Refuse a pairing that should never have been attempted."""
    if not isinstance(parcel, Bundle):
        raise AdapterError("an adapter takes a Bundle, not %s. Assemble it "
                           "first, so it is checked." % type(parcel).__name__)
    if entry.get("adapter") != ADAPTER:
        raise AdapterError("provider %r uses adapter %r, not %s"
                           % (entry.get("id"), entry.get("adapter"), ADAPTER))
    if entry.get("shape") != SHAPE:
        raise AdapterError("provider %r has shape %r; %s supplies the loop "
                           "only for %s" % (entry.get("id"), entry.get("shape"),
                                            ADAPTER, SHAPE))
    if parcel.provider_id != entry.get("id"):
        raise AdapterError(
            "this bundle was assembled for %r and is being handed to %r. "
            "Assemble it for the provider that will see it."
            % (parcel.provider_id, entry.get("id")))
    return True


def request_for(parcel, entry, prompt, env=None):
    """The HTTP request, with the key in the header and never in the body."""
    body = json.dumps({"model": model_name(entry, env),
                       "messages": messages_from(parcel, prompt),
                       "stream": False}).encode("utf-8")
    request = urllib.request.Request(base_url(entry, env) + COMPLETIONS,
                                     data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    key = api_key(entry, env)
    if key:
        request.add_header("Authorization", "Bearer " + key)
    return request


def text_from(payload):
    """The one field this adapter wants, or a refusal that quotes nothing."""
    choices = payload.get("choices") or []
    if not choices:
        raise AdapterError("the endpoint returned no choices")
    content = (choices[0].get("message") or {}).get("content")
    if content is None:
        raise AdapterError("the endpoint returned a choice with no content")
    return content


def _fetch(request, timeout, open_url):
    """The round trip. Every failure becomes an AdapterError naming no body."""
    try:
        with open_url(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AdapterError("the endpoint answered %s; the response is not "
                           "quoted here" % exc.code)
    except (urllib.error.URLError, OSError) as exc:
        raise AdapterError("the endpoint could not be reached: %s"
                           % type(exc).__name__)
    except (ValueError, json.JSONDecodeError):
        raise AdapterError("the endpoint answered with something that is not "
                           "JSON")


def complete(parcel, entry, prompt, env=None, timeout=DEFAULT_TIMEOUT,
             open_url=None):
    """One completion. The bundle is the only context that reaches the model."""
    check(parcel, entry)
    request = request_for(parcel, entry, prompt, env)
    return text_from(_fetch(request, timeout, open_url or urllib.request.urlopen))
