"""Every check for kuli. One command, exits non-zero on any failure.

    python tests/run.py

kuli is tier A in the fleet register: it enforces everyone else's rules, so it
obeys them first. That includes the rule that a check which can never fail
proves nothing when it passes — so the ratchet is made to trip on purpose
here, not only to agree.
"""

import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kuli import (  # noqa: E402
    bundle, classify, contract, duties, measures, providers, ratchet,
    redact, review_cost, toolguard, trail,
)

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


# --- the registry ----------------------------------------------------------

GOOD = {"id": "x", "name": "X", "shape": "raw-model",
        "adapter": "openai_compatible", "clearance": "L2"}


def registry(tmp, *entries):
    write(tmp, "providers.json", json.dumps({"providers": list(entries)}))


def with_env(**values):
    """Set environment variables, returning what to restore."""
    before = {k: os.environ.get(k) for k in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return before


def restore_env(before):
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_registry_absent_means_none(tmp):
    equal("no file means no providers", providers.load(tmp), [])
    before = with_env(KULI_PROVIDER=None, CLAUDECODE=None)
    try:
        equal("and the active provider is unknown, not invented",
              providers.active(tmp)["id"], "unknown")
    finally:
        restore_env(before)


def test_registry_refuses_what_it_cannot_trust(tmp):
    for broken, why in (
        ({k: v for k, v in GOOD.items() if k != "clearance"}, "a missing field"),
        (dict(GOOD, clearance="L9"), "a clearance outside the set"),
        (dict(GOOD, shape="something"), "an unknown shape"),
        (dict(GOOD, adapter="magic"), "an unknown adapter"),
    ):
        registry(tmp, broken)
        s_raises = providers.RegistryError
        try:
            providers.load(tmp)
            check("the registry refuses %s" % why, False, "it was accepted")
        except s_raises:
            check("the registry refuses %s" % why, True)

    registry(tmp, GOOD, dict(GOOD, name="Y"))
    try:
        providers.load(tmp)
        check("the registry refuses two providers with one id", False)
    except providers.RegistryError:
        check("the registry refuses two providers with one id", True)


def test_detection(tmp):
    registry(tmp,
             dict(GOOD, id="local", detect={"env": "KULI_LOCAL"}),
             dict(GOOD, id="cloud", clearance="L1",
                  detect={"env": "KULI_CLOUD", "equals": "yes"}))

    before = with_env(KULI_PROVIDER=None, KULI_LOCAL=None, KULI_CLOUD=None)
    try:
        equal("nothing set means unknown", providers.active(tmp)["id"], "unknown")

        with_env(KULI_LOCAL="1")
        equal("an env marker selects its provider",
              providers.active(tmp)["id"], "local")

        with_env(KULI_CLOUD="no")
        equal("a value that does not match does not select",
              providers.active(tmp)["id"], "local")

        with_env(KULI_LOCAL=None, KULI_CLOUD="yes")
        equal("a matching value does", providers.active(tmp)["id"], "cloud")

        with_env(KULI_PROVIDER="local")
        equal("an explicit KULI_PROVIDER beats detection",
              providers.active(tmp)["id"], "local")
    finally:
        restore_env(before)


def test_clearance_comparison():
    local = dict(GOOD, clearance="L2")
    hosted = dict(GOOD, clearance="L1")
    check("L2 may see L2", providers.may_see(local, "L2"))
    check("L2 may see L1", providers.may_see(local, "L1"))
    check("L1 may NOT see L2", not providers.may_see(hosted, "L2"))
    check("nobody may see L3 on a clearance of L2",
          not providers.may_see(local, "L3"))
    check("an unknown provider may see nothing",
          not providers.may_see(providers.UNKNOWN, "L0"))


def test_starter_never_overwrites(tmp):
    providers.write_starter(tmp)
    check("a starter registry loads", len(providers.load(tmp)) == 1)
    try:
        providers.write_starter(tmp)
        check("writing over an existing registry is refused", False)
    except providers.RegistryError:
        check("writing over an existing registry is refused", True)


def test_trail_records_the_registered_provider(tmp):
    registry(tmp, dict(GOOD, id="local", detect={"env": "KULI_LOCAL"},
                       model_env="KULI_MODEL"))
    before = with_env(KULI_PROVIDER=None, KULI_LOCAL="1", KULI_MODEL="qwen-x")
    try:
        entry = trail.append(event(file_path="a.py"), tmp)
        equal("the trail names the provider", entry["actor"]["provider"], "local")
        equal("and the model", entry["actor"]["model"], "qwen-x")
        equal("and its clearance", entry["actor"]["clearance"], "L2")
    finally:
        restore_env(before)


def test_per_provider_rows(tmp):
    registry(tmp, dict(GOOD, id="local", detect={"env": "KULI_LOCAL"}))
    before = with_env(KULI_PROVIDER=None, KULI_LOCAL="1", KULI_MODEL=None)
    try:
        trail.append(event(file_path="a.py"), tmp)
        trail.append(event(tool="Bash", command="ls"), tmp)
    finally:
        restore_env(before)
    rows = trail.per_provider(trail.entries(tmp))
    equal("one row per provider", list(rows), ["local"])
    equal("counting its actions", rows["local"]["actions"], 2)
    equal("and the distinct tools", len(rows["local"]["tools"]), 2)


# --- classification --------------------------------------------------------

RULES = {"classification": {"rules": [
    {"match": "docs/**", "level": "L0"},
    {"match": "business/**", "level": "L2"},
    {"match": "business/public/**", "level": "L0"},
    {"match": "**/.env", "level": "L0"},
]}}


def level(path, config=None):
    return classify.level_of(path, config)


def test_unclassified_is_confidential():
    equal("a path no rule mentions is L2", level("notes.md"), "L2")
    equal("not L0, which would be the convenient default",
          level("src/anything/at/all.py", RULES), "L2")


def test_a_person_may_set_any_level():
    equal("a rule sets the level", level("docs/spec.md", RULES), "L0")
    equal("including confidential", level("business/plan.md", RULES), "L2")
    _, reason = classify.explain("docs/spec.md", RULES)
    check("and the reason names the rule", "docs/**" in reason, reason)


def test_the_more_specific_rule_wins():
    equal("a public folder can be carved out of a confidential one",
          level("business/public/flyer.md", RULES), "L0")
    equal("while its sibling stays confidential",
          level("business/private/deal.md", RULES), "L2")


def test_secrets_can_only_be_raised():
    # The rule says L0. The built-in says secret. Secret wins.
    equal("a built-in secret pattern overrides a rule that lowers it",
          level(".env", RULES), "L3")
    _, reason = classify.explain(".env", RULES)
    check("and says it raised it", "raised it" in reason, reason)

    for path in ("config/.env.production", "app/id_rsa", "deploy/key.pem",
                 "x/.ssh/config", "a/secrets/token.txt", "sa/.aws/credentials"):
        equal("%s is L3 by default" % path, level(path), "L3")


def test_dotfiles_are_not_mangled():
    # `.env` once became `env` through lstrip("./") and stopped matching the
    # pattern written to catch it. A dotfile is the worst thing to fumble.
    equal("a leading ./ is removed as a prefix, not as characters",
          classify.normalise("./.env"), ".env")
    equal("and a bare dotfile is untouched", classify.normalise(".env"), ".env")
    equal("so it is still caught", level("./.env"), "L3")


def test_windows_separators():
    equal("backslashes are compared as forward slashes",
          level("business\\public\\flyer.md", RULES), "L0")


def test_glob_translation():
    check("* does not cross a directory",
          not classify.to_regex("a/*.py").match("a/b/c.py"))
    check("** does", classify.to_regex("a/**").match("a/b/c.py"))
    check("**/ matches at the root too", classify.to_regex("**/x.py").match("x.py"))
    check("? matches one character", classify.to_regex("a?.py").match("ab.py"))


def test_bad_rules_are_refused():
    for broken in ({"match": "a/**"}, {"match": "a/**", "level": "L9"},
                   {"level": "L1"}):
        try:
            classify.level_of("a/b", {"classification": {"rules": [broken]}})
            check("a rule like %r is refused" % broken, False, "it was accepted")
        except classify.ClassificationError:
            check("a rule like %r is refused" % broken, True)


def test_bundle_level_is_the_highest_part():
    equal("the highest wins", classify.highest(["L0", "L2", "L1"]), "L2")
    equal("a secret dominates", classify.highest(["L0", "L3"]), "L3")
    equal("an empty bundle is still L2", classify.highest([]), "L2")
    equal("unknown levels are ignored", classify.highest(["L9", "L1"]), "L1")


# --- the bundle, and the refusal -------------------------------------------

HOSTED = {"id": "hosted", "clearance": "L1"}
LOCAL = {"id": "local", "clearance": "L2"}
TOP = {"id": "top", "clearance": "L3"}
STRANGER = {"id": "stranger", "clearance": None}

SECRET_TEXT = "the quarterly figure nobody outside may read"


def test_a_cleared_bundle_assembles():
    parts = [bundle.Part("docs/a.md", "L0", "public text"),
             bundle.Part("notes.md", "L1", "internal text")]
    built = bundle.assemble(parts, HOSTED)
    equal("the bundle knows its provider", built.provider_id, "hosted")
    equal("and carries every part", len(built.parts), 2)
    equal("its level is the highest part's", built.max_level, "L1")
    check("and its text is the parts joined", "internal text" in built.text())


def test_an_empty_bundle_has_no_level():
    equal("nothing in it means no level", bundle.assemble([], HOSTED).max_level, None)


def test_above_clearance_is_refused():
    part = bundle.Part("business/plan.md", "L2", SECRET_TEXT)
    try:
        bundle.assemble([part], HOSTED)
        check("an L2 part is refused for an L1 provider", False, "it was allowed")
        return
    except bundle.ClearanceError as exc:
        check("an L2 part is refused for an L1 provider", True)
        message = str(exc)

    check("the refusal names the part", "business/plan.md" in message, message)
    check("and both levels", "L2" in message and "L1" in message, message)
    check("and says the content is not downgraded", "not downgraded" in message)
    # An error message is a log line. A log line that quotes confidential text
    # is the leak arriving by another door.
    check("and never quotes the content it refused", SECRET_TEXT not in message)


def test_one_bad_part_refuses_the_whole_bundle():
    parts = [bundle.Part("docs/a.md", "L0"), bundle.Part("business/b.md", "L2")]
    try:
        bundle.assemble(parts, HOSTED)
        check("a single over-level part stops the bundle", False)
    except bundle.ClearanceError:
        check("a single over-level part stops the bundle", True)


def test_secrets_never_enter_a_bundle():
    part = bundle.Part("config/.env", "L3", "API_KEY=xyz")
    for provider in (HOSTED, LOCAL, TOP):
        try:
            bundle.assemble([part], provider)
            check("L3 refused for a provider cleared to %s" % provider["clearance"],
                  False, "it was allowed")
        except bundle.ClearanceError as exc:
            check("L3 refused for a provider cleared to %s" % provider["clearance"],
                  True)
            check("and the reason is the proxy, not the clearance",
                  "proxy" in str(exc), str(exc))


def test_an_unknown_provider_gets_nothing():
    try:
        bundle.assemble([bundle.Part("README.md", "L0")], STRANGER)
        check("a provider with no clearance is refused even L0", False)
    except bundle.ClearanceError:
        check("a provider with no clearance is refused even L0", True)


def test_there_is_no_way_to_soften_it():
    parameters = list(inspect.signature(bundle.assemble).parameters)
    equal("assemble takes only parts and a provider", parameters, ["parts", "provider"])
    check("no parameter offers to truncate, redact or downgrade",
          not any(word in p.lower() for p in parameters
                  for word in ("trunc", "redact", "downgrade", "force", "allow")))
    source = inspect.getsource(bundle)
    # `(?!=)` matters: `part.level ==` is a comparison, not an assignment, and
    # the first version of this check could not tell them apart.
    check("and the module never assigns a part a different level",
          re.search(r"part\.level\s*=(?!=)", source) is None)


def test_a_part_needs_a_real_level():
    try:
        bundle.Part("a.md", "L9")
        check("a part with an invented level is refused", False)
    except bundle.ClearanceError:
        check("a part with an invented level is refused", True)


def test_would_refuse_reads_nothing(tmp):
    write(tmp, "kuli.json", json.dumps(RULES))
    config = json.loads((Path(tmp) / "kuli.json").read_text(encoding="utf-8"))
    paths = ["docs/spec.md", "business/plan.md", ".env"]
    refused = bundle.would_refuse(paths, HOSTED, config)
    equal("two of the three are refused for an L1 provider", len(refused), 2)
    sources = {part.source for part, _ in refused}
    equal("and they are the right two", sources, {"business/plan.md", ".env"})
    equal("none of the paths had to exist",
          [p for p in paths if (Path(tmp) / p).exists()], [])


# --- the return path -------------------------------------------------------

CONFIDENTIAL_TEXT = "the margin on that deal was forty-two per cent"


def result_event(tool="Read", result="", **payload):
    return {"tool_name": tool, "tool_input": payload,
            "tool_response": {"stdout": result}}


def test_a_declared_target_sets_the_level():
    level, reason = toolguard.assess({"file_path": "docs/spec.md"}, "hi", RULES)
    equal("a public file gives a public result", level, "L0")
    check("and the reason names the file", "docs/spec.md" in reason, reason)

    level, _ = toolguard.assess({"file_path": "business/plan.md"}, "hi", RULES)
    equal("a confidential file gives a confidential result", level, "L2")


def test_output_naming_a_file_raises_the_level():
    # grep declares no target. The answer names what it found, which is the
    # only thing that gives it away.
    level, reason = toolguard.assess(
        {"command": "grep -r margin ."},
        "business/plan.md: the margin is 42%", RULES)
    equal("a path in the output raises the level", level, "L2")
    check("and the reason says which path", "business/plan.md" in reason, reason)


def test_a_credential_anywhere_is_l3():
    for text in ("TOKEN=ghp_abcdefghijklmnopqrstuvwxyz012345",
                 "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123",
                 "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"):
        level, _ = toolguard.assess({"file_path": "docs/spec.md"}, text, RULES)
        equal("a credential in the output beats a public source", level, "L3")


def test_ordinary_output_is_internal():
    level, _ = toolguard.assess({"command": "ls"}, "a\nb\nc", RULES)
    equal("output with no declared source defaults to L1", level, "L1")
    level, _ = toolguard.assess({"command": "ls"}, "a\nb\nc",
                                dict(RULES, tool_output_default="L2"))
    equal("a project may make that stricter", level, "L2")


def test_the_withheld_result_is_not_quoted():
    try:
        toolguard.check({"file_path": "business/plan.md"}, CONFIDENTIAL_TEXT,
                        HOSTED, RULES)
        check("a confidential result is withheld from an L1 provider", False)
        return
    except bundle.ClearanceError as exc:
        check("a confidential result is withheld from an L1 provider", True)
        message = str(exc)
    check("the refusal says it is withheld, not trimmed", "withheld" in message)
    check("and never quotes the result", CONFIDENTIAL_TEXT not in message, message)


def test_a_cleared_provider_still_gets_it():
    level, _ = toolguard.check({"file_path": "business/plan.md"},
                               CONFIDENTIAL_TEXT, LOCAL, RULES)
    equal("the local model may have the same result", level, "L2")


def test_a_refusal_is_recorded(tmp):
    write(tmp, "kuli.json", json.dumps(RULES))
    config = json.loads((Path(tmp) / "kuli.json").read_text(encoding="utf-8"))
    event = result_event("Read", CONFIDENTIAL_TEXT, file_path="business/plan.md")

    ok, _, message = toolguard.guard(event, HOSTED, config, tmp)
    check("the result is refused", ok is False)

    records = trail.entries(tmp)
    equal("and one entry was written", len(records), 1)
    equal("marked as a return-path refusal",
          records[0]["event"], "ReturnPathRefused")
    written = (Path(tmp) / trail.TRAIL_DIR).glob("*.jsonl")
    body = "".join(p.read_text(encoding="utf-8") for p in written)
    check("the trail does not hold the withheld text",
          CONFIDENTIAL_TEXT not in body)
    check("but it does hold the reason", "business/plan.md" in message)


def test_an_allowed_result_is_not_recorded_as_refused(tmp):
    event = result_event("Read", "public", file_path="docs/spec.md")
    ok, level, _ = toolguard.guard(event, HOSTED, RULES, tmp)
    check("it is allowed", ok is True)
    equal("at the file's level", level, "L0")
    equal("and nothing was written as a refusal", len(trail.entries(tmp)), 0)


def test_paths_in_text():
    found = toolguard.paths_mentioned("see a/b.md and a/b.md and c/d.py now")
    equal("paths are found and deduplicated", found, ["a/b.md", "c/d.py"])
    equal("prose with no path finds none", toolguard.paths_mentioned("hello"), [])


# --- separation of duties --------------------------------------------------

def git_in(tmp, *args):
    subprocess.run(["git"] + list(args), cwd=tmp, check=True,
                   capture_output=True, text=True)


def a_repo(tmp):
    git_in(tmp, "init", "-q", "-b", "main")
    git_in(tmp, "config", "user.email", "t@example.com")
    git_in(tmp, "config", "user.name", "T")
    write(tmp, "app.py", "x = 1\n")
    write(tmp, "kuli.json", "{}\n")
    git_in(tmp, "add", "-A")
    git_in(tmp, "commit", "-qm", "initial")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp,
                          capture_output=True, text=True).stdout.strip()


def test_work_alone_is_fine(tmp):
    base = a_repo(tmp)
    write(tmp, "app.py", "x = 2\n")
    git_in(tmp, "commit", "-qam", "a feature")
    ok, report = duties.run(base, tmp)
    check("a commit touching no rule file passes", ok, report)
    equal("and none were touched", report["touching_rules"], 0)


def test_rules_and_work_together_are_refused(tmp):
    base = a_repo(tmp)
    write(tmp, "app.py", "x = 2\n")
    write(tmp, "kuli.json", '{"allowances": {"python": {"erosion": 1}}}\n')
    git_in(tmp, "add", "-A")
    git_in(tmp, "commit", "-qm", "a feature and a tweak")

    ok, report = duties.run(base, tmp)
    check("mixing the rules with the work is refused", not ok)
    problems = report["faults"][0][1]
    check("A1 is named", any(p.startswith("A1") for p in problems), problems)
    check("and it says to split them",
          any("Split them" in p for p in problems), problems)


def test_rules_alone_still_need_a_second_actor(tmp):
    base = a_repo(tmp)
    write(tmp, "kuli.json", '{"allowances": {"python": {"erosion": 1}}}\n')
    git_in(tmp, "commit", "-qam", "relax erosion")

    ok, report = duties.run(base, tmp)
    check("a lone rule change with no approver is refused", not ok)
    problems = report["faults"][0][1]
    check("A2 is named", any(p.startswith("A2") for p in problems), problems)
    check("and A1 is not, since nothing else was touched",
          not any(p.startswith("A1") for p in problems), problems)


def test_an_approved_rule_change_passes(tmp):
    base = a_repo(tmp)
    write(tmp, "kuli.json", '{"allowances": {"python": {"erosion": 1}}}\n')
    git_in(tmp, "commit", "-qam", "relax erosion\n\nRules-approved-by: The Owner")
    ok, _ = duties.run(base, tmp)
    check("a lone, approved rule change passes", ok)


def test_what_counts_as_a_rule_file():
    for path in ("kuli.json", ".kuli/baseline.json", "providers.json",
                 ".github/workflows/verify.yml"):
        check("%s is a rule file" % path, duties.is_rule_file(path))
    for path in ("kuli/measures.py", "README.md", "docs/01.md"):
        check("%s is not" % path, not duties.is_rule_file(path))


# --- the increment contract ------------------------------------------------

def a_contract(tmp, producer="", reviewer="", slug="thing"):
    """A contract on disk, signed as asked. Returns its slug."""
    contract.create(slug, tmp)
    if producer or reviewer:
        path = contract.path_for(slug, tmp)
        text = path.read_text(encoding="utf-8")
        text = text.replace("Producer-signed:", "Producer-signed: " + producer)
        text = text.replace("Reviewer-signed:", "Reviewer-signed: " + reviewer)
        path.write_text(text, encoding="utf-8")
    return slug


def test_an_unsigned_contract_is_not_ready(tmp):
    a_contract(tmp)
    ok, _, problems = contract.check("thing", tmp)
    check("a fresh contract is not ready", not ok)
    # `\\s` matches a newline, so an empty "Producer-signed:" once swallowed
    # the line below and reported the reviewer as the producer.
    check("both signatures are reported empty, not just one",
          len([p for p in problems if "is empty" in p]) == 2, problems)


def test_the_producer_may_not_be_the_reviewer(tmp):
    a_contract(tmp, "claude-code", "claude-code")
    ok, _, problems = contract.check("thing", tmp)
    check("signing both sides is refused", not ok)
    check("and the reason is the point of the rule",
          any("own bar" in p for p in problems), problems)


def test_a_signed_contract_is_ready(tmp):
    a_contract(tmp, "claude-code", "local")
    ok, parsed, problems = contract.check("thing", tmp)
    check("two different signatures are enough", ok, problems)
    equal("the producer is read", parsed["producer"], "claude-code")
    equal("and the reviewer", parsed["reviewer"], "local")


def test_the_bar_cannot_move_after_work_begins(tmp):
    a_contract(tmp, "claude-code", "local")
    contract.freeze("thing", tmp)

    ok, message = contract.verify("thing", tmp)
    check("an untouched contract verifies", ok, message)

    path = contract.path_for("thing", tmp)
    path.write_text(path.read_text(encoding="utf-8").replace(
        "the conditions", "only the easy conditions"), encoding="utf-8")
    ok, message = contract.verify("thing", tmp)
    check("editing it afterwards is caught", not ok)
    check("and the message says why", "is not a bar" in message, message)


def test_an_unfrozen_contract_does_not_count(tmp):
    a_contract(tmp, "claude-code", "local")
    ok, message = contract.verify("thing", tmp)
    check("never frozen is not the same as unchanged", not ok)
    check("and it says what to run", "freeze" in message, message)


def test_an_unsigned_contract_cannot_be_frozen(tmp):
    a_contract(tmp)
    try:
        contract.freeze("thing", tmp)
        check("freezing an unsigned contract is refused", False)
    except contract.ContractError:
        check("freezing an unsigned contract is refused", True)


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
    test_registry_absent_means_none, test_registry_refuses_what_it_cannot_trust,
    test_detection, test_starter_never_overwrites,
    test_trail_records_the_registered_provider, test_per_provider_rows,
    test_would_refuse_reads_nothing, test_a_refusal_is_recorded,
    test_an_allowed_result_is_not_recorded_as_refused,
    test_work_alone_is_fine, test_rules_and_work_together_are_refused,
    test_rules_alone_still_need_a_second_actor,
    test_an_approved_rule_change_passes,
    test_an_unsigned_contract_is_not_ready,
    test_the_producer_may_not_be_the_reviewer,
    test_a_signed_contract_is_ready,
    test_the_bar_cannot_move_after_work_begins,
    test_an_unfrozen_contract_does_not_count,
    test_an_unsigned_contract_cannot_be_frozen,
]
NO_TMP = [
    test_review_cost_abstains_without_identifiers, test_identifier_pattern,
    test_cli_runs, test_secrets_never_survive,
    test_content_is_fingerprinted_not_stored, test_long_values_are_shortened,
    test_clearance_comparison,
    test_unclassified_is_confidential, test_a_person_may_set_any_level,
    test_the_more_specific_rule_wins, test_secrets_can_only_be_raised,
    test_dotfiles_are_not_mangled, test_windows_separators,
    test_glob_translation, test_bad_rules_are_refused,
    test_bundle_level_is_the_highest_part,
    test_a_cleared_bundle_assembles, test_an_empty_bundle_has_no_level,
    test_above_clearance_is_refused, test_one_bad_part_refuses_the_whole_bundle,
    test_secrets_never_enter_a_bundle, test_an_unknown_provider_gets_nothing,
    test_there_is_no_way_to_soften_it, test_a_part_needs_a_real_level,
    test_a_declared_target_sets_the_level,
    test_output_naming_a_file_raises_the_level,
    test_a_credential_anywhere_is_l3, test_ordinary_output_is_internal,
    test_the_withheld_result_is_not_quoted,
    test_a_cleared_provider_still_gets_it, test_paths_in_text,
    test_what_counts_as_a_rule_file,
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
