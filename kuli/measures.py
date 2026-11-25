"""The numbers a ratchet turns on.

Implements the two forms of degradation SlopCodeBench measures (arXiv
2603.24755): **structural erosion**, meaning complexity concentrating into a
few places rather than its total, and **verbosity**, meaning code volume per
unit of behaviour.

Why concentration and not total complexity: a growing program is allowed to
contain more decisions. What a healthy one does not do is pile them into the
same handful of functions while the rest stay thin. Total complexity rises
with any honest feature; concentration only rises when nobody refactors.

**A unit is a function in Python and a file in JavaScript.** Python has `ast`
in the standard library; JavaScript does not, and a real JS parser is a
dependency this project will not take. So the JavaScript numbers come from a
token scan after comments and strings are removed, which is a heuristic and
is wrong in detail — it cannot see a function boundary reliably.

That is acceptable here, and the reason is worth stating: **a ratchet compares
a measure against itself.** It never asks whether the number is correct in
absolute terms, only whether today's number is worse than the baseline's.
A systematic bias that is present on both sides cancels. An inaccurate measure
is a poor report and a perfectly good ratchet.
"""

import ast
import os
import re
from pathlib import Path

PY_SUFFIXES = (".py",)
JS_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx")

#: Directories that are never anybody's work.
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "dist", "build", "evidence", ".kuli", ".idea", ".vscode",
}

#: A line has to be long enough to be worth calling duplication. Short lines
#: repeat for honest reasons — a closing brace, a `return None`.
MIN_DUPLICATE_LINE = 24

#: Erosion is the share of complexity held by the worst tenth of units.
TOP_SHARE = 0.10


def iter_source_files(root, suffixes, extra_skip=()):
    """Every source file under `root`, skipping generated and vendored trees.

    The walk prunes directories as it goes rather than listing everything and
    filtering afterwards. That is not a micro-optimisation: `.venv` and
    `node_modules` hold tens of thousands of files, and enumerating them took
    longer than every measure in this module put together.
    """
    skip = SKIP_DIRS | set(extra_skip)
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in skip)
        for name in sorted(files):
            if name.endswith(suffixes):
                yield Path(current) / name


def read(path):
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


# --- Python ----------------------------------------------------------------

_BRANCHING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
              ast.IfExp, ast.Assert)

_NESTING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith,
            ast.Try)


def _complexity(node):
    """Decision points inside one function. One is the floor: straight line."""
    score = 1
    for child in ast.walk(node):
        if isinstance(child, _BRANCHING):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            score += 1 + len(child.ifs)
        elif hasattr(ast, "match_case") and isinstance(child, ast.match_case):
            score += 1
    return score


def _nesting(node, depth=0):
    deepest = depth
    for child in ast.iter_child_nodes(node):
        step = depth + 1 if isinstance(child, _NESTING) else depth
        deepest = max(deepest, _nesting(child, step))
    return deepest


def _statements(node):
    return sum(1 for child in ast.walk(node) if isinstance(child, ast.stmt)) - 1


def python_units(root, extra_skip=()):
    """One record per function: its complexity, statements and nesting."""
    units = []
    for path in iter_source_files(root, PY_SUFFIXES, extra_skip):
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            units.append({
                "name": "%s::%s" % (path.as_posix(), node.name),
                "complexity": _complexity(node),
                "statements": _statements(node),
                "nesting": _nesting(node),
            })
    return units


# --- JavaScript ------------------------------------------------------------

_JS_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_JS_STRINGS = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", re.S)
_JS_DECISIONS = re.compile(
    r"\b(if|for|while|case|catch)\b|&&|\|\||\?\?|\?(?!\.)"
)
_JS_FUNCTIONS = re.compile(r"\bfunction\b|=>")


def _js_strip(text):
    """Remove comments and string bodies so keywords inside them do not count."""
    text = _JS_COMMENTS.sub(" ", text)
    return _JS_STRINGS.sub('""', text)


def javascript_units(root, extra_skip=()):
    """One record per file. See the module docstring on why not per function."""
    units = []
    for path in iter_source_files(root, JS_SUFFIXES, extra_skip):
        code = _js_strip(read(path))
        lines = [line for line in code.splitlines() if line.strip()]
        functions = len(_JS_FUNCTIONS.findall(code))
        units.append({
            "name": path.as_posix(),
            "complexity": 1 + len(_JS_DECISIONS.findall(code)),
            "statements": len(lines),
            "nesting": 0,  # not measurable without a parser; held at zero
            "functions": functions,
        })
    return units


# --- shared arithmetic -----------------------------------------------------

def _erosion(values):
    """Share of the total held by the worst tenth. 0 is flat, 1 is one unit."""
    total = sum(values)
    if total <= 0 or len(values) < 10:
        return 0.0
    count = max(1, int(round(len(values) * TOP_SHARE)))
    worst = sorted(values, reverse=True)[:count]
    return round(sum(worst) / total, 4)


def countable(line):
    """Whether a line is substantial enough that repeating it means something."""
    stripped = line.strip()
    if len(stripped) < MIN_DUPLICATE_LINE:
        return None
    if stripped.startswith(("#", "//", "*")):
        return None
    return stripped


def duplication(root, suffixes, extra_skip=()):
    """Share of substantial lines that appear more than once in the tree."""
    seen = {}
    for path in iter_source_files(root, suffixes, extra_skip):
        for line in read(path).splitlines():
            stripped = countable(line)
            if stripped:
                seen[stripped] = seen.get(stripped, 0) + 1
    if not seen:
        return 0.0
    repeated = sum(count for count in seen.values() if count > 1)
    return round(repeated / sum(seen.values()), 4)


def summarise(units, duplication_ratio):
    """Turn a list of unit records into the numbers a ratchet compares."""
    if not units:
        return None
    complexities = [u["complexity"] for u in units]
    statements = [u["statements"] for u in units]
    return {
        "units": len(units),
        "erosion": _erosion(complexities),
        "verbosity": round(sum(statements) / len(units), 3),
        "duplication": duplication_ratio,
        "max_complexity": max(complexities),
        "max_statements": max(statements),
        "max_nesting": max(u["nesting"] for u in units),
    }


def measure(root=".", extra_skip=()):
    """Every measure, per language. Languages with no source are omitted."""
    result = {}
    python = summarise(python_units(root, extra_skip),
                       duplication(root, PY_SUFFIXES, extra_skip))
    if python:
        result["python"] = python
    javascript = summarise(javascript_units(root, extra_skip),
                           duplication(root, JS_SUFFIXES, extra_skip))
    if javascript:
        result["javascript"] = javascript
    return result


#: Measures where a larger number is worse. Everything the ratchet guards is
#: here; `units` is recorded but never guarded, because a project is allowed
#: to grow.
GUARDED = ("erosion", "verbosity", "duplication", "max_complexity",
           "max_statements", "max_nesting")


def worst_offenders(units, key="complexity", limit=5):
    """The units carrying the most of `key` — what to show when a ratchet trips."""
    return sorted(units, key=lambda u: u[key], reverse=True)[:limit]
