"""Small filesystem helpers shared by the modules that write files.

One function, extracted because the ratchet noticed four copies of the same
line across `trail`, `ratchet` and `contract` and refused the change that
added the fourth. That is the gate doing its job on a small scale: the line
was harmless, and four copies of a harmless line is how a codebase starts
repeating itself.
"""

from pathlib import Path


def ensure_parent(path):
    """Make sure a file's directory exists, and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
