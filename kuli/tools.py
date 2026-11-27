"""The tools a raw model may be given, and the one thing they all obey.

Two of them, both read-only: `read_file` and `list_files`. Two is the number
T9 asks for and also the number worth having before the loop around them has
been wrong a few times. Nothing here writes, moves, deletes or runs anything —
a model that can edit the repository through a loop this young is a model
whose mistakes are expensive to find.

**Every tool declares the path it will touch**, and the runner checks that
declaration against the grant *before* calling the handler. So a tool cannot
reach a path the grant does not cover, and it cannot reach a level above the
grant's clearance, and neither check lives in the handler — the handler would
then be the thing deciding what it may see.

**Nothing escapes the root.** A path is resolved and refused unless it lands
inside the repository. `../../.ssh/id_rsa` is the first thing a model tries
when it is being helpful about a missing file, and `..` in a string is not a
path traversal the classifier would catch: `.ssh/id_rsa` is L3 by pattern, but
`../../../home/x/notes.md` is nothing the rules mention and would read as L2
and be allowed. The boundary has to be the filesystem, not the glob.
"""

from pathlib import Path

#: Listings are for orientation, not for exfiltration by pagination.
MAX_ENTRIES = 200


class ToolError(Exception):
    """A tool call that will not be made. The model is told, not obeyed."""


def inside(root, path):
    """The resolved path, or a refusal. The root is the boundary."""
    base = Path(root).resolve()
    target = (base / (path or "")).resolve()
    if target != base and base not in target.parents:
        raise ToolError("%s is outside the repository, so it is not read" % path)
    return target


def read_file(arguments, root="."):
    target = inside(root, arguments.get("path"))
    if not target.is_file():
        raise ToolError("%s is not a file" % arguments.get("path"))
    return target.read_text(encoding="utf-8", errors="replace")


def list_files(arguments, root="."):
    target = inside(root, arguments.get("prefix") or "")
    if not target.is_dir():
        raise ToolError("%s is not a directory" % arguments.get("prefix"))
    names = sorted(child.name + ("/" if child.is_dir() else "")
                   for child in target.iterdir())
    return "\n".join(names[:MAX_ENTRIES])


def _declared(arguments, key):
    value = arguments.get(key)
    return [value] if value else []


#: name -> (description, properties, required, handler, which argument names
#: the path the grant is checked against).
CATALOGUE = {
    "read_file": (
        "Read one text file from this repository.",
        {"path": {"type": "string",
                  "description": "repository-relative path"}},
        ("path",), read_file, "path",
    ),
    "list_files": (
        "List the names directly inside one directory of this repository.",
        {"prefix": {"type": "string",
                    "description": "repository-relative directory, or empty "
                                   "for the root"}},
        (), list_files, "prefix",
    ),
}


def schemas(names=None, schema=None):
    """The `tools` array for the chosen tools, in the model's own format."""
    chosen = list(names) if names else sorted(CATALOGUE)
    return [schema(name, CATALOGUE[name][0], CATALOGUE[name][1],
                   CATALOGUE[name][2])
            for name in chosen if name in CATALOGUE]


def paths_declared(name, arguments):
    """The paths this call says it will touch, for the permission check."""
    entry = CATALOGUE.get(name)
    return _declared(arguments, entry[4]) if entry else []


def run(name, arguments, root="."):
    """Call one tool. An unknown name is refused, never guessed at."""
    entry = CATALOGUE.get(name)
    if entry is None:
        raise ToolError("there is no tool called %r" % name)
    return entry[3](arguments or {}, root)
