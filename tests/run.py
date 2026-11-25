"""Every check for kuli. One command, exits non-zero on any failure.

    python tests/run.py

kuli is tier A in the fleet register: it enforces everyone else's rules, so it
obeys them first. That includes the rule that a check which can never fail
proves nothing when it passes — so the ratchet is made to trip on purpose
here, not only to agree.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kuli import measures, ratchet, redact, review_cost, trail  # noqa: E402

RESULTS = []


def configure_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def check(description, condition, detail=None):
    RESULTS.append((description, bool(condition), None if condition else detail))


def equal(description, actual, expected):
    check(description, actual == expected, "expected %r, got %r" % (expected, actual))


def write(root, relative, text):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- the measures ----------------------------------------------------------

SIMPLE = "def a():\n    return 1\n"
BRANCHY = """
def b(x):
    if x:
        for i in range(3):
            if i and x:
                return i
    return 0
"""


def test_python_measures(tmp):
    write(tmp, "simple.py", SIMPLE)
    units = measures.python_units(tmp)
    equal("one function per def", len(units), 1)
    equal("a straight line scores one", units[0]["complexity"], 1)

    write(tmp, "branchy.py", BRANCHY)
    units = {u["name"].split("::")[1]: u for u in measures.python_units(tmp)}
    check("branches raise complexity", units["b"]["complexity"] > 1)
    check("nesting is counted", units["b"]["nesting"] >= 3)
    check("a boolean operator counts as a decision",
          units["b"]["complexity"] >= 5)

    write(tmp, "broken.py", "def (:\n")
    check("a file that will not parse is skipped, not fatal",
          len(measures.python_units(tmp)) == 2)


def test_javascript_measures(tmp):
    write(tmp, "a.js", "function f(x) { if (x) { return 1 } return 2 }\n")
    units = measures.javascript_units(tmp)
    equal("one unit per javascript file", len(units), 1)
    equal("the if is counted", units[0]["complexity"], 2)

    write(tmp, "b.js", '// if if if\nconst s = "if if";\n')
    units = {Path(u["name"]).name: u for u in measures.javascript_units(tmp)}
    equal("keywords in comments and strings do not count",
          units["b.js"]["complexity"], 1)


def test_erosion(tmp):
    equal("fewer than ten units is not a distribution", measures._erosion([5, 5]), 0.0)
    flat = measures._erosion([1] * 100)
    concentrated = measures._erosion([1] * 99 + [900])
    check("erosion is low when complexity is spread", flat < 0.2)
    check("erosion is high when one unit holds it all", concentrated > 0.8)
    check("concentration, not total, is what moves it", concentrated > flat)


def test_duplication(tmp):
    line = "    value = compute_something(argument, other_argument)\n"
    write(tmp, "one.py", "def f():\n" + line)
    write(tmp, "two.py", "def g():\n" + line)
    check("a line repeated across files is duplication",
          measures.duplication(tmp, measures.PY_SUFFIXES) > 0)

    shutil.rmtree(tmp / "one.py", ignore_errors=True)
    (tmp / "one.py").unlink()
    (tmp / "two.py").unlink()
    write(tmp, "short.py", "x = 1\ny = 1\n")
    equal("short lines are not duplication",
          measures.duplication(tmp, measures.PY_SUFFIXES), 0.0)


def test_skips(tmp):
    write(tmp, "node_modules/pkg/index.js", "function f() { if (1) {} }\n")
    write(tmp, ".venv/lib/mod.py", "def f():\n    return 1\n")
    write(tmp, "kept.py", SIMPLE)
    equal("vendored trees are not measured", len(measures.python_units(tmp)), 1)
    equal("node_modules is not measured", len(measures.javascript_units(tmp)), 0)


# --- the ratchet -----------------------------------------------------------

def test_ratchet_holds_and_trips(tmp):
    write(tmp, "src.py", SIMPLE)
    before = measures.measure(tmp)
    ratchet.write_baseline(tmp, before)

    ok, report = ratchet.run(tmp)
    check("an unchanged tree passes", ok is True)
    equal("and reports no trips", len(report["trips"]), 0)

    # Make it worse on purpose. This is the point of the suite: a ratchet
    # nobody has watched trip is not known to work.
    write(tmp, "src.py", SIMPLE + BRANCHY * 3)
    ok, report = ratchet.run(tmp)
    check("a worse tree is refused", ok is False)
    check("and the measure that moved is named", len(report["trips"]) > 0)
    moved = {t["measure"] for t in report["trips"]}
    check("verbosity is among them", "verbosity" in moved or "max_statements" in moved)

    for trip in report["trips"]:
        check("every trip explains itself",
              ratchet.MEANING.get(trip["measure"]) is not None)


def test_ratchet_improvement_passes(tmp):
    write(tmp, "src.py", SIMPLE + BRANCHY * 3)
    ratchet.write_baseline(tmp, measures.measure(tmp))
    write(tmp, "src.py", SIMPLE)
    ok, _ = ratchet.run(tmp)
    check("improving every measure passes", ok is True)


def test_ratchet_exception(tmp):
    write(tmp, "src.py", SIMPLE)
    ratchet.write_baseline(tmp, measures.measure(tmp))
    write(tmp, "src.py", SIMPLE + BRANCHY * 3)

    write(tmp, "kuli.json",
          '{"exceptions": {"python": {"verbosity": "deadline, repay in v2",'
          ' "max_statements": "same", "erosion": "same",'
          ' "max_complexity": "same", "max_nesting": "same",'
          ' "duplication": "same"}}}')
    ok, report = ratchet.run(tmp)
    check("a recorded exception lets it through", ok is True)
    check("and the debt stays visible", len(report["excused"]) > 0)
    check("with the reason attached",
          all("reason" in r for r in report["excused"]))


def test_no_baseline(tmp):
    write(tmp, "src.py", SIMPLE)
    ok, report = ratchet.run(tmp)
    check("with no baseline the gate abstains rather than passing", ok is None)
    check("and says what to do", "baseline" in report["error"])


def test_allowance(tmp):
    write(tmp, "src.py", SIMPLE)
    ratchet.write_baseline(tmp, measures.measure(tmp))
    equal("the default allowance is zero",
          ratchet.allowance({}, "python", "erosion"), 0)
    equal("an allowance is read from config",
          ratchet.allowance({"allowances": {"python": {"erosion": 0.05}}},
                            "python", "erosion"), 0.05)


# --- review cost -----------------------------------------------------------

def test_review_cost_abstains_without_identifiers():
    try:
        ok, report = review_cost.run("HEAD", ROOT, budget=120)
    except RuntimeError as exc:
        # Outside a git repository the gate cannot judge. Abstaining loudly is
        # the correct outcome; the one thing it must never do is pass.
        check("outside git the gate refuses to judge", True)
        check("and says so in one line", "\n" not in str(exc))
        return
    check("with no criteria claimed the gate abstains", ok is None)
    check("and says why, rather than passing silently", "note" in report)


def test_identifier_pattern():
    found = review_cost.IDENTIFIER.findall("fixes A4.4 and I2, see R5 and C2.1")
    equal("identifiers are recognised", found, ["A4.4", "I2", "R5", "C2.1"])
    equal("ordinary words are not", review_cost.IDENTIFIER.findall("A sentence."), [])


# --- redaction -------------------------------------------------------------

SECRETS = [
    "ghp_abcdefghijklmnopqrstuvwxyz012345",
    "sk-abcdefghijklmnopqrstuvwxyz1234",
    "Bearer abcdefghijklmnopqrstuvwxyz0123456789",
    "password = hunter2secret",
]


def test_secrets_never_survive():
    for secret in SECRETS:
        cleaned = redact.scrub("prefix %s suffix" % secret)
        check("a credential is removed: %s" % secret[:12],
              secret not in cleaned, cleaned)
    check("ordinary text is left alone",
          redact.scrub("read the file and return") == "read the file and return")


def test_content_is_fingerprinted_not_stored():
    body = "def f():\n    return 'a very specific line of code'\n"
    detail = redact.clean({"file_path": "src/a.py", "new_string": body})
    check("the path is kept", detail["file_path"] == "src/a.py")
    check("the content is not", body not in json.dumps(detail))
    check("a digest is kept instead", len(detail["new_string"]["sha256"]) == 64)
    equal("and the size", detail["new_string"]["bytes"], len(body.encode()))

    same = redact.clean({"new_string": body})["new_string"]["sha256"]
    equal("the same bytes give the same digest",
          same, detail["new_string"]["sha256"])


def test_long_values_are_shortened():
    # Deliberately not a run of one character: an unbroken 5,000-character
    # token looks exactly like an encoded secret, so scrub() removes it before
    # shorten() ever sees it — which is the right order, and was worth
    # discovering here rather than in the trail.
    long = "the quick brown fox jumps over the lazy dog " * 200
    shortened = redact.shorten(long)
    check("a long value is cut", len(shortened) < 600)
    check("and says how much was dropped", "chars]" in shortened)

    blob = "A" * 5000
    equal("a long unbroken token is treated as a secret, not shortened",
          redact.shorten(blob), redact.REDACTED)


# --- the trail -------------------------------------------------------------

def event(tool="Edit", **kw):
    payload = {"hook_event_name": "PreToolUse", "session_id": "s-1",
               "tool_name": tool, "tool_input": kw}
    return payload


def test_trail_appends_and_chains(tmp):
    first = trail.append(event(file_path="a.py", new_string="x = 1"), tmp)
    second = trail.append(event(tool="Bash", command="ls"), tmp)

    equal("the first entry starts the chain", first["prev"], trail.GENESIS)
    equal("the second points at the first", second["prev"], first["hash"])
    equal("the target is recorded", first["target"], "a.py")
    equal("so is the tool", second["tool"], "Bash")

    records = trail.entries(tmp)
    equal("both were written", len(records), 2)
    ok, problems = trail.verify(tmp)
    check("and the chain verifies", ok, problems)


def test_trail_detects_tampering(tmp):
    trail.append(event(file_path="a.py"), tmp)
    trail.append(event(file_path="b.py"), tmp)

    path = next((Path(tmp) / trail.TRAIL_DIR).glob("*.jsonl"))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[0]["target"] = "innocent.py"
    path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n",
                    encoding="utf-8")

    ok, problems = trail.verify(tmp)
    check("a quietly edited entry is caught", ok is False)
    check("and the entry is named", any("entry 0" in p for p in problems), problems)


def test_trail_removal_is_caught(tmp):
    for name in ("a.py", "b.py", "c.py"):
        trail.append(event(file_path=name), tmp)
    path = next((Path(tmp) / trail.TRAIL_DIR).glob("*.jsonl"))
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")
    ok, _ = trail.verify(tmp)
    check("deleting an entry breaks the chain", ok is False)


def test_trail_never_holds_a_secret(tmp):
    trail.append(event(tool="Bash",
                       command="export TOKEN=%s" % SECRETS[0]), tmp)
    written = next((Path(tmp) / trail.TRAIL_DIR).glob("*.jsonl")).read_text(encoding="utf-8")
    check("a secret in a command never reaches the trail", SECRETS[0] not in written)


def test_trail_queries(tmp):
    trail.append(event(file_path="src/app.py"), tmp)
    trail.append(event(file_path="src/other.py"), tmp)
    trail.append(event(tool="Bash", command="ls"), tmp)

    records = trail.entries(tmp)
    equal("who touched this file", len(trail.touched(records, "src/app.py")), 1)
    summary = trail.summarise(records)
    equal("counted in total", summary["total"], 3)
    equal("and by tool", summary["by_tool"]["Edit"], 2)


def test_trail_survives_an_odd_payload(tmp):
    """A recorder that throws stops the agent. It must not throw."""
    entry = trail.append({"tool_name": "Weird", "tool_input": "not a dict"}, tmp)
    equal("an unexpected payload is still recorded", entry["tool"], "Weird")
    check("with no target invented", entry["target"] is None)
    ok, _ = trail.verify(tmp)
    check("and the chain still verifies", ok)


# --- the suite itself ------------------------------------------------------

def test_cli_runs():
    result = subprocess.run(
        [sys.executable, "-m", "kuli.cli", "measure"],
        cwd=ROOT, capture_output=True, text=True,
    )
    equal("kuli measure exits zero", result.returncode, 0)
    check("and prints json", result.stdout.strip().startswith("{"))


NEEDS_TMP = [
    test_python_measures, test_javascript_measures, test_erosion,
    test_duplication, test_skips, test_ratchet_holds_and_trips,
    test_ratchet_improvement_passes, test_ratchet_exception,
    test_no_baseline, test_allowance,
    test_trail_appends_and_chains, test_trail_detects_tampering,
    test_trail_removal_is_caught, test_trail_never_holds_a_secret,
    test_trail_queries, test_trail_survives_an_odd_payload,
]
NO_TMP = [
    test_review_cost_abstains_without_identifiers, test_identifier_pattern,
    test_cli_runs, test_secrets_never_survive,
    test_content_is_fingerprinted_not_stored, test_long_values_are_shortened,
]


def main():
    configure_stdout()
    for test in NEEDS_TMP:
        tmp = Path(tempfile.mkdtemp(prefix="kuli-"))
        try:
            test(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    for test in NO_TMP:
        test()

    failed = [r for r in RESULTS if not r[1]]
    print("kuli — %d checks, %d passed, %d failed"
          % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for description, _, detail in failed:
        print("  FAIL %s" % description)
        if detail:
            print("       %s" % detail)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
