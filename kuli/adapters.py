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
    dialect(entry)
    if entry.get("shape") != SHAPE:
        raise AdapterError("provider %r has shape %r; this module supplies "
                           "the loop only for %s"
                           % (entry.get("id"), entry.get("shape"), SHAPE))
    if parcel.provider_id != entry.get("id"):
        raise AdapterError(
            "this bundle was assembled for %r and is being handed to %r. "
            "Assemble it for the provider that will see it."
            % (parcel.provider_id, entry.get("id")))
    return True


def dialect(entry):
    """How this provider spells a conversation. An unknown one is refused."""
    found = ADAPTERS.get(entry.get("adapter"))
    if found is None:
        raise AdapterError("provider %r uses adapter %r, which this build "
                           "does not speak"
                           % (entry.get("id"), entry.get("adapter")))
    return found


def openai_body(messages, entry, tools=None, env=None):
    payload = {"model": model_name(entry, env), "messages": messages,
               "stream": False}
    if tools:
        payload["tools"] = list(tools)
    return payload


def request_for(messages, entry, tools=None, env=None):
    """The HTTP request, with the key in the header and never in the body."""
    path, shape, _ = dialect(entry)
    payload = (shape or openai_body)(messages, entry, tools, env)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base_url(entry, env) + path,
                                     data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    key = api_key(entry, env)
    if key:
        request.add_header("Authorization", "Bearer " + key)
    return request


def tool_schema(name, description, properties, required=()):
    """One entry for the `tools` array. The model is told, never asked."""
    return {"type": "function",
            "function": {"name": name, "description": description,
                         "parameters": {"type": "object",
                                        "properties": properties,
                                        "required": list(required)}}}


def _arguments(raw):
    """A tool call's arguments, parsed. A model sends them as a string."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        raise AdapterError("the model sent tool arguments that are not JSON; "
                           "they are not quoted here")


def tool_calls_in(message):
    """Every tool call in an assistant message, parsed, or none."""
    found = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        found.append({"id": raw.get("id"), "name": function.get("name"),
                      "arguments": _arguments(function.get("arguments"))})
    return found


def message_from(payload):
    """The assistant message, which may carry text, tool calls or both."""
    choices = payload.get("choices") or []
    if not choices:
        raise AdapterError("the endpoint returned no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AdapterError("the endpoint returned a choice with no message")
    return message


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


def converse(messages, entry, tools=None, env=None, timeout=DEFAULT_TIMEOUT,
             open_url=None):
    """One turn of a conversation. Returns the assistant message.

    The caller owns the message list, because a loop has to append tool
    results to it — but the caller is `runner.py`, which got its opening
    messages from a bundle. Nothing here invents context.
    """
    request = request_for(messages, entry, tools, env)
    payload = _fetch(request, timeout, open_url or urllib.request.urlopen)
    return dialect(entry)[2](payload)


#: T16. The Anthropic Messages API differs from the OpenAI shape in three
#: places and nowhere else that matters here: the path, the system prompt
#: being a field rather than a message, and the answer being a list of
#: content blocks. `max_tokens` is required, so it is named rather than left
#: to a default somebody would have to discover from a 400.
MESSAGES = "/v1/messages"
MAX_TOKENS = 2048


def anthropic_body(messages, entry, tools=None, env=None):
    """The same conversation, in the other vendor's spelling."""
    system = [m["content"] for m in messages if m.get("role") == "system"]
    body = {"model": model_name(entry, env),
            "max_tokens": MAX_TOKENS,
            "messages": [m for m in messages if m.get("role") != "system"]}
    if system:
        body["system"] = "\n\n".join(system)
    if tools:
        body["tools"] = [_anthropic_tool(t) for t in tools]
    return body


def _anthropic_tool(tool):
    function = tool.get("function") or {}
    return {"name": function.get("name"),
            "description": function.get("description"),
            "input_schema": function.get("parameters")}


def anthropic_message(payload):
    """An assistant message in the shape the rest of kuli already speaks.

    Translated here rather than at every call site, so `runner.py` never
    learns that there is more than one vendor. A loop that knows which vendor
    it is talking to is a loop that will eventually behave differently for
    one of them, which is the thing this project exists to prevent.
    """
    blocks = payload.get("content") or []
    text = "".join(_block_text(b) for b in blocks)
    calls = [_block_call(b) for b in blocks if b.get("type") == "tool_use"]
    message = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = calls
    return message


def _block_text(block):
    return (block.get("text") or "") if block.get("type") == "text" else ""


def _block_call(block):
    return {"id": block.get("id"), "type": "function",
            "function": {"name": block.get("name"),
                         "arguments": block.get("input")}}


ADAPTERS = {
    "openai_compatible": (COMPLETIONS, None, message_from),
    "anthropic": (MESSAGES, anthropic_body, anthropic_message),
}


def complete(parcel, entry, prompt, env=None, timeout=DEFAULT_TIMEOUT,
             open_url=None):
    """One completion, text only. The bundle is the only context there is."""
    check(parcel, entry)
    message = converse(messages_from(parcel, prompt), entry, None, env,
                       timeout, open_url)
    content = message.get("content")
    if content is None:
        raise AdapterError("the endpoint returned a message with no text")
    return content
