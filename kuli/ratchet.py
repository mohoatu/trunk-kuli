"""The ratchet: a measure may be held or improved, never loosened.

The question is never *is this good code* — no program can answer that. It is
*is this worse than it was*, which is arithmetic.

Two things keep this from becoming the bureaucracy that gets switched off:

**The refactor obligation.** A trip is not a rejection. It names the measure
and the units carrying it, and the change may proceed by including the
refactor that pays for it.

**A spendable budget.** Sometimes a deadline is worth some erosion. An
exception records the amount and the reason and stays visible until repaid.
Debt taken knowingly is engineering; debt taken silently is the thing this
project exists to prevent.
"""

import json
from pathlib import Path

from . import measures

BASELINE_PATH = Path(".kuli/baseline.json")
CONFIG_PATH = Path("kuli.json")

#: Floating-point noise, not drift.
EPSILON = 1e-9


def load_config(root="."):
    path = Path(root) / CONFIG_PATH
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_baseline(root="."):
    path = Path(root) / BASELINE_PATH
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_baseline(root=".", data=None):
    path = Path(root) / BASELINE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def allowance(config, language, measure_name):
    """How much worse a measure may get before the ratchet trips.

    Defaults to zero: the ratchet is strict unless a project says otherwise,
    in writing, in a file somebody had to edit.
    """
    allowances = config.get("allowances", {})
    return float(allowances.get(language, {}).get(measure_name, 0))


def exceptions(config, language):
    return config.get("exceptions", {}).get(language, {})


def compare(baseline, current, config):
    """Every measure that got worse, with by how much and why it is allowed."""
    trips, excused = [], []
    for language, before in sorted(baseline.items()):
        after = current.get(language)
        if after is None:
            continue
        for name in measures.GUARDED:
            if name not in before or name not in after:
                continue
            delta = after[name] - before[name]
            if delta <= allowance(config, language, name) + EPSILON:
                continue
            record = {
                "language": language,
                "measure": name,
                "baseline": before[name],
                "current": after[name],
                "delta": round(delta, 4),
            }
            reason = exceptions(config, language).get(name)
            if reason:
                record["reason"] = reason
                excused.append(record)
            else:
                trips.append(record)
    return trips, excused


def describe(record):
    return "%s / %s: %s -> %s (worse by %s)" % (
        record["language"], record["measure"],
        record["baseline"], record["current"], record["delta"],
    )


MEANING = {
    "erosion": "complexity is concentrating into fewer units — the usual sign "
               "that something was patched instead of restructured",
    "verbosity": "more code per unit of behaviour",
    "duplication": "more repeated lines — something was copied rather than "
                   "extracted",
    "max_complexity": "the worst single unit got worse",
    "max_statements": "the longest unit got longer",
    "max_nesting": "the deepest nesting got deeper",
}


def run(root=".", stream=None):
    """Returns (ok, report). ok is False when a measure got worse unexcused."""
    config = load_config(root)
    baseline = load_baseline(root)
    if baseline is None:
        return None, {"error": "no baseline; run: kuli baseline"}

    current = measures.measure(root, config.get("skip", ()))
    trips, excused = compare(baseline, current, config)
    return (not trips), {
        "current": current,
        "baseline": baseline,
        "trips": trips,
        "excused": excused,
    }
