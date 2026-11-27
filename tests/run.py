"""Every check for kuli. One command, exits non-zero on any failure.

    python tests/run.py

kuli is tier A in the fleet register: it enforces everyone else's rules, so it
obeys them first. That includes the rule that a check which can never fail
proves nothing when it passes — so the ratchet is made to trip on purpose
here, not only to agree.
"""

import http.server
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kuli import (  # noqa: E402
    adapters, bundle, capability, classify, contract, duties, gateway, grants,
    mcp, measures, providers, ratchet, redact, review_cost, runner, toolguard,
    tools, trail,
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

#: Carries a loopback endpoint on purpose: since T8, a clearance above L1 is
#: demoted unless the entry can show the model runs on this machine.
GOOD = {"id": "x", "name": "X", "shape": "raw-model",
        "adapter": "openai_compatible", "clearance": "L2",
        "endpoint": "http://127.0.0.1:11434"}


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
    equal("assemble takes only parts and an authority",
          parameters, ["parts", "authority"])
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


WORKFLOW = ".github/workflows/verify.yml"
A_JOB = ("name: verify\njobs:\n  tests:\n    steps:\n"
         "      - run: python tests/run.py\n")


APPROVED = "%s\n\nRules-approved-by: The Owner"


def _commit_all(tmp, files, message):
    for relative, text in files.items():
        write(tmp, relative, text)
    git_in(tmp, "add", "-A")
    git_in(tmp, "commit", "-qm", message)


def _workflow_repo(tmp):
    """A repo whose workflow exists already, so the next diff can remove."""
    base = a_repo(tmp)
    _commit_all(tmp, {WORKFLOW: A_JOB}, APPROVED % "ci")
    return base


def _with_code(tmp, workflow, message):
    """One commit changing the workflow and a work file. Returns the report."""
    base = _workflow_repo(tmp)
    _commit_all(tmp, {WORKFLOW: workflow, "app.py": "x = 2\n"}, message)
    return duties.run(base, tmp)


def test_an_additive_workflow_change_is_excused_from_a1(tmp):
    added = A_JOB + "  docs:\n    steps:\n      - run: make docs\n"
    ok, report = _with_code(tmp, added, APPROVED % "a docs job and a feature")
    check("adding a job alongside code is not refused", ok, report["faults"])
    equal("and both workflow commits are reported as excused, not silent",
          [paths for _, paths in report["excused"]], [[WORKFLOW], [WORKFLOW]])


def test_a_workflow_change_still_needs_a_second_actor(tmp):
    added = A_JOB + "  docs:\n    steps:\n      - run: make docs\n"
    problems = _with_code(tmp, added, "a docs job and a feature")[1]["faults"][0][1]
    check("A2 is never excused",
          any(p.startswith("A2") for p in problems), problems)
    check("but A1 is, for a purely additive change",
          not any(p.startswith("A1") for p in problems), problems)


def test_removing_a_line_from_a_workflow_binds_a1(tmp):
    stripped = "name: verify\njobs:\n  tests:\n    steps:\n"
    ok, report = _with_code(tmp, stripped, APPROVED % "drop the suite")
    check("taking a step out alongside code is still refused", not ok)
    check("and the reason names the removal",
          any("removes lines" in p for p in report["faults"][0][1]),
          report["faults"])


#: Each adds a line, removes none, and switches a gate off.
ADDITIVE_RELAXATIONS = (
    ("    continue-on-error: true\n", "continue-on-error"),
    ("      - run: kuli ratchet || true\n", "|| true"),
    ("    if: false\n", "if: false"),
)


def test_an_additive_relaxation_is_caught_by_name():
    """The hole in the additive rule, closed by the RELAXING list."""
    for marker, label in ADDITIVE_RELAXATIONS:
        each = Path(tempfile.mkdtemp(prefix="kuli-"))
        try:
            faults = _with_code(each, A_JOB + marker, APPROVED % "ci")[1]["faults"]
            problems = faults[0][1] if faults else []
            check("%s is refused though it removes nothing" % label,
                  any(p.startswith("A1") for p in problems), problems)
            check("and the marker is named for %s" % label,
                  any(label in p for p in problems), problems)
        finally:
            shutil.rmtree(each, ignore_errors=True)


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


# --- authority that only narrows ------------------------------------------

CLOUD = {"id": "cloud", "clearance": "L1"}
LOCALP = {"id": "local-llm", "clearance": "L2"}


def test_a_root_grant_is_the_registry_ceiling():
    root = grants.for_provider(LOCALP)
    equal("the root grant takes the registered clearance", root.level, "L2")
    check("and everything is in scope until it is narrowed",
          root.permits(level="L2", path="business/legal/x.md", tool="Read"))
    equal("an unregistered entry grants nothing",
          grants.for_provider({}).level, None)


def test_asking_for_more_gives_less():
    root = grants.for_provider(CLOUD)
    equal("narrowing down lowers the level", root.narrow(level="L0").level, "L0")
    equal("asking above the parent is clamped to the parent",
          root.narrow(level="L3").level, "L1")
    check("there is no widen", not any(
        name for name in dir(root) if "widen" in name or "raise" in name))


def test_a_chain_of_hops_can_only_shrink():
    held = grants.for_provider(LOCALP).narrow(scope=["src", "docs"])
    ranks = [providers.clearance_rank(held.level)]
    for asked in ("L3", "L1", "L2", "L0", "L3"):
        held = held.narrow(level=asked)
        ranks.append(providers.clearance_rank(held.level))
    check("every hop is no wider than the one before",
          all(b <= a for a, b in zip(ranks, ranks[1:])), ranks)
    equal("and five hops ended at the lowest asked", held.level, "L0")


def test_scope_is_an_intersection():
    held = grants.for_provider(LOCALP).narrow(scope=["src"])
    equal("a child scope outside the parent is dropped",
          held.narrow(scope=["business"]).scope, ())
    equal("a child scope inside the parent is kept",
          held.narrow(scope=["src/engine"]).scope, ("src/engine",))
    check("an empty scope permits nothing",
          not held.narrow(scope=[]).permits(path="src/a.py"))


def test_scope_matches_on_path_boundaries():
    held = grants.for_provider(LOCALP).narrow(scope=["docs"])
    check("docs covers docs/a.md", held.permits(path="docs/a.md"))
    check("docs does not cover docsx/a.md", not held.permits(path="docsx/a.md"))
    check("docs covers itself", held.permits(path="docs"))


def test_tools_are_exact():
    held = grants.for_provider(LOCALP).narrow(tools=["Read", "Grep"])
    check("a named tool is allowed", held.permits(tool="Grep"))
    check("an unnamed tool is not", not held.permits(tool="Bash"))
    equal("and narrowing again intersects",
          held.narrow(tools=["Grep", "Bash"]).tools, ("Grep",))


def test_a_grant_without_a_level_is_cleared_for_nothing():
    nobody = grants.Grant(principal="stranger")
    check("not even L0", not nobody.permits(level="L0"))
    check("and the refusal says what it holds",
          "nothing" in nobody.refusal(level="L0"))


def test_expiry_is_part_of_the_grant():
    held = grants.for_provider(LOCALP).narrow(expires="2020-01-01T00:00:00Z")
    check("an expired grant refuses what it would otherwise allow",
          not held.permits(level="L0"))
    equal("and narrowing takes the earlier deadline",
          held.narrow(expires="2030-01-01T00:00:00Z").expires,
          "2020-01-01T00:00:00Z")


def test_a_recorded_grant_round_trips():
    held = grants.for_provider(LOCALP).narrow(scope=["src"], tools=["Read"])
    equal("as_dict and from_dict agree",
          grants.from_dict(held.as_dict()), held)
    for bad, label in (({"principal": "x", "levl": "L1"}, "a misspelt field"),
                       ("not an object", "a string"),
                       ({"principal": "x", "level": "L9"}, "a level outside the set")):
        try:
            grants.from_dict(bad)
            check("%s is refused" % label, False)
        except grants.GrantError:
            check("%s is refused" % label, True)


def test_coerce_takes_a_grant_or_a_registry_entry():
    held = grants.for_provider(CLOUD)
    check("a grant passes through", grants.coerce(held) is held)
    equal("an entry becomes its root grant",
          grants.coerce(CLOUD).principal, "cloud")
    try:
        grants.coerce("cloud")
        check("a bare string is not an authority", False)
    except grants.GrantError:
        check("a bare string is not an authority", True)


def test_a_narrowed_grant_is_what_the_boundary_obeys():
    """The hole docs/07 found: the hop, not the provider."""
    held = grants.for_provider(LOCALP)
    part = bundle.Part(source="business/plan.md", level="L2")
    check("the provider's own ceiling admits it",
          bundle.check_part(part, held))
    try:
        bundle.check_part(part, held.narrow(level="L1"))
        check("the sub-task's narrowed grant refuses it", False)
    except bundle.ClearanceError:
        check("the sub-task's narrowed grant refuses it", True)
    try:
        toolguard.check({"file_path": "business/plan.md"}, "text",
                        held.narrow(level="L1"))
        check("and so does the return path", False)
    except bundle.ClearanceError:
        check("and so does the return path", True)


# --- a capability the agent cannot mint ------------------------------------

KEY = b"k" * 32


def test_a_signed_capability_verifies():
    held = grants.for_provider(LOCALP).narrow(scope=["src"], tools=["Read"])
    token = capability.sign(held, KEY)
    equal("the token carries exactly the grant",
          capability.verify(token, KEY), held)


def _refused(label, call):
    try:
        call()
        check(label, False)
    except capability.CapabilityError as exc:
        check(label, True)
        check("and the refusal does not quote the token",
              "eyJ" not in str(exc) and "kuli1." not in str(exc))


def test_a_capability_cannot_be_forged():
    held = grants.for_provider(CLOUD)
    token = capability.sign(held, KEY)
    version, body, mac = token.split(".")
    better = capability.sign(held.narrow(), b"j" * 32)
    _refused("a token signed with another key is refused",
             lambda: capability.verify(better, KEY))
    _refused("a swapped payload is refused", lambda: capability.verify(
        "%s.%s.%s" % (version, capability._encode(b'{"principal":"cloud",'
                                                  b'"level":"L3","scope":["*"],'
                                                  b'"tools":["*"],'
                                                  b'"expires":null}'), mac), KEY))
    _refused("a token of another shape is refused",
             lambda: capability.verify("v9.a.b", KEY))


def test_every_capability_expires():
    held = grants.for_provider(CLOUD)
    minted = capability.verify(capability.mint(held, KEY, 60), KEY)
    check("mint sets a deadline", bool(minted.expires))
    _refused("a lifetime of zero is refused",
             lambda: capability.mint(held, KEY, 0))
    stale = capability.sign(held.narrow(expires="2020-01-01T00:00:00Z"), KEY)
    _refused("an expired capability is refused",
             lambda: capability.verify(stale, KEY))


def test_the_signing_key_lives_outside_the_repository(tmp):
    inside = write(tmp, "key.txt", "x" * 40)
    _refused("a key file inside the repository is refused",
             lambda: capability.signing_key(tmp, {"KULI_CAPABILITY_KEY_FILE":
                                                  str(inside)}))
    _refused("a short key is refused",
             lambda: capability.signing_key(tmp, {"KULI_CAPABILITY_KEY": "short"}))
    _refused("no key at all is refused", lambda: capability.signing_key(tmp, {}))
    equal("a long key in the environment is accepted",
          capability.signing_key(tmp, {"KULI_CAPABILITY_KEY": "y" * 40}),
          b"y" * 40)


# --- fail closed on a key nobody understands -------------------------------

def test_an_unknown_permission_key_is_refused(tmp):
    cases = (
        ('{"providrs": []}', "an unknown key in the registry document"),
        ('{"providers": [{"id": "a", "name": "a", "shape": "raw-model",'
         ' "adapter": "anthropic", "clearence": "L1"}]}',
         "a misspelt clearance field"),
        ('{"services": [{"name": "mcp://x", "transprot": "local"}]}',
         "an unknown key on a service"),
    )
    for text, label in cases:
        write(tmp, "providers.json", text)
        try:
            providers.registry(tmp)
            check("%s is refused" % label, False)
        except providers.RegistryError as exc:
            check("%s is refused" % label, "unknown key" in str(exc))


def test_an_unknown_config_key_is_refused(tmp):
    write(tmp, "kuli.json", '{"tier": "A", "skipp": ["x"]}')
    try:
        ratchet.load_config(tmp)
        check("a misspelt skip is refused rather than ignored", False)
    except ratchet.ConfigError as exc:
        check("a misspelt skip is refused rather than ignored",
              "skipp" in str(exc))
    check("and this repository's own config still loads",
          ratchet.load_config(ROOT).get("tier") == "A")


# --- the seam --------------------------------------------------------------

LOCAL_SERVICE = ('{"providers": [], "services": [{"name": "mcp://audit",'
                 ' "transport": "local", "target": "scripts/audit.js"}]}')


def test_nothing_resolves_by_default(tmp):
    write(tmp, "providers.json", LOCAL_SERVICE)
    equal("a registered service resolves",
          gateway.resolve("mcp://audit", tmp)["target"], "scripts/audit.js")
    for name, label in (("mcp://other", "an unregistered service"),):
        try:
            gateway.resolve(name, tmp)
            check("%s does not resolve" % label, False)
        except gateway.GatewayError:
            check("%s does not resolve" % label, True)


def test_a_transport_this_build_cannot_honour_is_refused(tmp):
    write(tmp, "providers.json", LOCAL_SERVICE.replace("local", "mesh"))
    try:
        gateway.resolve("mcp://audit", tmp)
        check("a mesh transport is refused rather than faked", False)
    except gateway.GatewayError as exc:
        check("a mesh transport is refused rather than faked",
              "not built" in str(exc))


def test_dispatch_refuses_before_it_calls(tmp):
    write(tmp, "providers.json", LOCAL_SERVICE)
    held = grants.Grant(principal="cloud", level="L1", tools=("mcp://other",))
    called = []
    try:
        gateway.dispatch("mcp://audit", capability.sign(held, KEY), KEY,
                         lambda endpoint: called.append(endpoint), tmp)
        check("a grant that does not name the service refuses", False)
    except gateway.GatewayError:
        check("a grant that does not name the service refuses", True)
    equal("and the call was never made", called, [])


def test_dispatch_judges_what_came_back(tmp):
    write(tmp, "providers.json", LOCAL_SERVICE)
    token = capability.sign(
        grants.Grant(principal="cloud", level="L1", tools=("mcp://audit",)), KEY)
    equal("a permitted call returns its result",
          gateway.dispatch("mcp://audit", token, KEY, lambda e: "fine", tmp),
          "fine")
    try:
        gateway.dispatch("mcp://audit", token, KEY,
                         lambda e: "see business/legal/contract.md", tmp)
        check("a result above the grant is withheld", False)
    except bundle.ClearanceError as exc:
        check("a result above the grant is withheld", True)
        check("and the refusal names the path, not the content",
              "contract.md" in str(exc) and "see business" not in str(exc))


# --- the console gets what it can read -------------------------------------

#: An em dash and Vietnamese diacritics: the two things that came out as
#: mojibake on a Windows console while the stream itself was correct.
AWKWARD = "docs/kế-hoạch—2026.md"


def test_the_cli_prints_what_it_was_given():
    """A report is wrong if the console cannot render it.

    Reconfiguring the stream to UTF-8 was half the job; a Windows console
    still decoding as its legacy code page printed `ΓÇö` for an em dash. This
    runs the CLI as a subprocess so the Windows leg of the matrix is the one
    that would fail, which is the only place the bug existed.
    """
    done = subprocess.run(
        [sys.executable, "-m", "kuli.cli", "classify", AWKWARD],
        cwd=str(ROOT), capture_output=True)
    check("the command succeeds", done.returncode == 0,
          done.stderr[:300].decode("utf-8", errors="replace"))
    text = done.stdout.decode("utf-8", errors="replace")
    check("the path comes back intact", AWKWARD in text, text)
    for mojibake in ("ΓÇö", "â€”", "�"):
        check("and carries no %r" % mojibake, mojibake not in text, text)


# --- a clearance above L1 is shown, not declared ---------------------------

LOOPBACK = ("http://127.0.0.1:11434", "http://localhost:1234",
            "http://[::1]:8080", "http://127.0.0.5:99",
            "http://ollama.localhost:11434", "127.0.0.1:11434")

ELSEWHERE = ("http://10.0.0.4:11434", "https://api.example.com",
             "http://ollama.local:11434", "http://0.0.0.0:11434", "")


def test_what_counts_as_this_machine():
    for url in LOOPBACK:
        check("%s is this machine" % url, providers.is_loopback(url))
    for url in ELSEWHERE:
        check("%r is not" % url, not providers.is_loopback(url))


def test_a_name_that_merely_resolves_here_does_not_count():
    """A DNS answer is not a property of the address."""
    check("ollama.local is refused even though it may point at 127.0.0.1",
          not providers.is_loopback("http://ollama.local:11434"))
    check("while the reserved name is accepted without a lookup",
          providers.is_loopback("http://anything.localhost:11434"))


def test_a_loopback_endpoint_earns_its_clearance():
    level, reason = providers.verified(dict(GOOD, clearance="L2"), {})
    equal("L2 stands for a model on this machine", level, "L2")
    check("and the reason names the host", "127.0.0.1" in reason, reason)


def test_an_endpoint_elsewhere_is_demoted_and_says_so():
    for url, label in ((None, "no endpoint at all"),
                       ("https://api.example.com", "a hosted endpoint")):
        entry = dict(GOOD, clearance="L2", endpoint=url)
        level, reason = providers.verified(entry, {})
        equal("%s is demoted to L1" % label, level, "L1")
        check("and the reason says demoted", "demoted" in reason, reason)
    top, reason = providers.verified(dict(GOOD, clearance="L3", endpoint=None), {})
    equal("L3 is demoted to the ceiling, not one step", top, "L1")


def test_a_low_clearance_is_never_raised():
    for declared in ("L0", "L1"):
        level, reason = providers.verified(
            dict(GOOD, clearance=declared, endpoint="http://127.0.0.1:1"), {})
        equal("%s needs no proof and is left alone" % declared, level, declared)
        check("and nothing was demoted", "demoted" not in reason, reason)


def test_verification_reads_the_endpoint_the_call_will_use():
    """Checking the inline value while calling the environment one is theatre."""
    entry = dict(GOOD, clearance="L2", endpoint="http://127.0.0.1:11434",
                 endpoint_env="KULI_TEST_URL")
    level, _ = providers.verified(entry, {"KULI_TEST_URL": "https://api.example.com"})
    equal("the environment override is what gets verified", level, "L1")
    equal("and the adapter would call the same host",
          adapters.base_url(entry, {"KULI_TEST_URL": "https://api.example.com"}),
          "https://api.example.com")


def test_the_registry_and_the_trail_carry_the_earned_clearance(tmp):
    registry(tmp, dict(GOOD, id="hosted", clearance="L2",
                       endpoint="https://api.example.com",
                       detect={"env": "KULI_HOSTED"}))
    entries = providers.load(tmp, {})
    equal("load returns the earned level", entries[0]["clearance"], "L1")
    equal("and one provider is reported as demoted",
          len(providers.demoted(entries)), 1)

    before = with_env(KULI_PROVIDER=None, KULI_HOSTED="1")
    try:
        entry = trail.append(event(file_path="a.py"), tmp)
        equal("the trail records the earned clearance, not the declared one",
              entry["actor"]["clearance"], "L1")
    finally:
        restore_env(before)


# --- the openai_compatible adapter -----------------------------------------

RAW = {"id": "local-llm", "name": "a local model", "shape": "raw-model",
       "adapter": "openai_compatible", "clearance": "L2", "model": "qwen3:8b"}


def _endpoint(reply="it works", status=200):
    """A real OpenAI-compatible server on a free port.

    A socket rather than a mock, because §8.5 asks for an execution and a
    patched function proves the test agrees with itself.
    """
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            seen.append({"path": self.path,
                         "body": json.loads(self.rfile.read(length) or b"{}"),
                         "auth": self.headers.get("Authorization")})
            payload = json.dumps(
                {"choices": [{"message": {"content": reply}}]}).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % server.server_port, seen, server.shutdown


def test_a_real_endpoint_answers_through_the_adapter():
    url, seen, stop = _endpoint("hello from the model")
    try:
        entry = dict(RAW, endpoint=url)
        parcel = bundle.assemble([bundle.Part("docs/x.md", "L0", "be brief")],
                                 entry)
        equal("the adapter returns the model's text",
              adapters.complete(parcel, entry, "say hi", env={}),
              "hello from the model")
        call = seen[0]
        equal("it posts to the completions path", call["path"],
              adapters.COMPLETIONS)
        equal("the bundle became the system message", call["body"]["messages"][0],
              {"role": "system", "content": "be brief"})
        equal("the prompt became the user message",
              call["body"]["messages"][1]["content"], "say hi")
        equal("and there is no third source of content",
              len(call["body"]["messages"]), 2)
        equal("no key is sent when none is configured", call["auth"], None)
    finally:
        stop()


def test_a_second_endpoint_is_a_config_change(tmp):
    """T7's done-when: the same code path, two rows in providers.json."""
    first, _, stop_one = _endpoint("from the first")
    second, seen, stop_two = _endpoint("from the second")
    try:
        write(tmp, "providers.json", json.dumps({"providers": [
            dict(RAW, id="one", endpoint=first),
            dict(RAW, id="two", endpoint=second, api_key_env="KULI_TEST_KEY")]}))
        answers = [adapters.complete(bundle.assemble([], entry), entry, "hi",
                                     env={"KULI_TEST_KEY": "sk-test"})
                   for entry in providers.load(tmp)]
        equal("both endpoints were reached by one code path",
              answers, ["from the first", "from the second"])
        equal("the key goes in the header of the entry that names it",
              seen[0]["auth"], "Bearer sk-test")
        check("and never into the body",
              "sk-test" not in json.dumps(seen[0]["body"]))
    finally:
        stop_one()
        stop_two()


def test_a_bundle_for_another_provider_is_refused():
    entry = dict(RAW, endpoint="http://127.0.0.1:1")
    elsewhere = bundle.assemble([], dict(RAW, id="someone-else"))
    try:
        adapters.complete(elsewhere, entry, "hi", env={})
        check("a bundle stamped for another provider is refused", False)
    except adapters.AdapterError as exc:
        check("a bundle stamped for another provider is refused", True)
        check("and the refusal names both providers",
              "someone-else" in str(exc) and RAW["id"] in str(exc), str(exc))


def test_the_adapter_cannot_assemble_its_own_context():
    source = inspect.getsource(adapters)
    for forbidden in ("assemble(", "part_for(", "read_text(", "classify"):
        check("the adapter never reaches for %s" % forbidden,
              forbidden not in source)
    check("and it refuses anything that is not already a Bundle",
          "isinstance(parcel, Bundle)" in source)


def test_this_adapter_refuses_work_that_is_not_its_shape():
    wrapped = {"id": "claude-code", "name": "cc", "shape": "agent-product",
               "adapter": "wrapped", "clearance": "L1"}
    parcel = bundle.assemble([], wrapped)
    for entry, label in ((wrapped, "a wrapped adapter"),
                         (dict(wrapped, adapter="openai_compatible"),
                          "an agent-product shape")):
        try:
            adapters.complete(parcel, entry, "hi", env={})
            check("%s is refused" % label, False)
        except adapters.AdapterError:
            check("%s is refused" % label, True)


def test_a_bad_answer_is_a_refusal_that_quotes_nothing():
    url, _, stop = _endpoint("a secret in the body", status=500)
    try:
        entry = dict(RAW, endpoint=url)
        adapters.complete(bundle.assemble([], entry), entry, "hi", env={})
        check("an error status is refused", False)
    except adapters.AdapterError as exc:
        check("an error status is refused", True)
        check("and the response is not quoted",
              "a secret in the body" not in str(exc) and "not quoted" in str(exc))
    finally:
        stop()

    for payload, label in (({}, "no choices"),
                           ({"choices": [{"message": {}}]}, "no content")):
        try:
            adapters.text_from(payload)
            check("an answer with %s is refused" % label, False)
        except adapters.AdapterError:
            check("an answer with %s is refused" % label, True)


def test_the_endpoint_and_model_come_from_configuration():
    entry = dict(RAW, endpoint="http://inline:1/", endpoint_env="KULI_TEST_URL")
    equal("an environment variable wins over the inline value",
          adapters.base_url(entry, {"KULI_TEST_URL": "http://env:2"}),
          "http://env:2")
    equal("and the inline value stands when it is unset",
          adapters.base_url(entry, {}), "http://inline:1")
    for broken, label in ((dict(RAW, endpoint=None), "no endpoint"),
                          (dict(RAW, endpoint="http://x:1", model=None),
                           "no model")):
        try:
            adapters.request_for([{"role": "user", "content": "hi"}], broken,
                                 None, {})
            check("a provider with %s is refused" % label, False)
        except adapters.AdapterError:
            check("a provider with %s is refused" % label, True)


# --- tool calling, and the loop around it ----------------------------------

def _wants(name, arguments, identifier="call_1"):
    """An assistant message asking for one tool, as a model sends it."""
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": identifier, "type": "function",
         "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def _says(text):
    return {"role": "assistant", "content": text}


def _script(*replies):
    """A `talk` that returns each reply in turn, and records what it was sent."""
    seen = []

    def talk(messages, entry, schemas):
        seen.append({"messages": list(messages), "schemas": schemas})
        return replies[min(len(seen) - 1, len(replies) - 1)]

    return talk, seen


def _task(prompt="what is here", context=None):
    return {"prompt": prompt, "context": context or {}}


def _grant_for(allowed=("read_file", "list_files"), level="L1"):
    return grants.Grant(principal="local-llm", level=level, tools=tuple(allowed))


def test_a_tool_schema_is_what_the_model_expects():
    schema = tools.schemas(["read_file"], adapters.tool_schema)[0]
    equal("it is a function tool", schema["type"], "function")
    equal("named for the tool", schema["function"]["name"], "read_file")
    equal("with an object parameter block",
          schema["function"]["parameters"]["type"], "object")
    equal("and the path is required",
          schema["function"]["parameters"]["required"], ["path"])
    equal("an unknown name is not invented",
          tools.schemas(["nonsense"], adapters.tool_schema), [])


def test_tool_calls_are_parsed_or_refused():
    parsed = adapters.tool_calls_in(_wants("read_file", {"path": "a.md"}))
    equal("one call, with its arguments as a mapping",
          parsed, [{"id": "call_1", "name": "read_file",
                    "arguments": {"path": "a.md"}}])
    already = {"tool_calls": [{"id": "x", "function": {
        "name": "read_file", "arguments": {"path": "b.md"}}}]}
    equal("a server that sends an object rather than a string also works",
          adapters.tool_calls_in(already)[0]["arguments"], {"path": "b.md"})
    equal("a message with no calls asks for nothing",
          adapters.tool_calls_in(_says("hello")), [])
    broken = {"tool_calls": [{"id": "x", "function": {
        "name": "read_file", "arguments": "{not json at all"}}]}
    try:
        adapters.tool_calls_in(broken)
        check("arguments that are not JSON are refused", False)
    except adapters.AdapterError as exc:
        check("arguments that are not JSON are refused", True)
        check("and are not quoted back",
              "not json at all" not in str(exc), str(exc))


def test_tools_are_only_sent_when_there_are_some():
    url, seen, stop = _endpoint("fine")
    try:
        entry = dict(RAW, endpoint=url)
        adapters.converse([{"role": "user", "content": "hi"}], entry, None,
                          env={})
        check("a text-only turn sends no tools array", "tools" not in seen[0]["body"])
        adapters.converse([{"role": "user", "content": "hi"}], entry,
                          tools.schemas(None, adapters.tool_schema), env={})
        equal("and a tool turn sends both of them",
              len(seen[1]["body"]["tools"]), 2)
    finally:
        stop()


def test_a_two_tool_task_runs_to_an_answer(tmp):
    write(tmp, "notes.md", "the answer is 41\n")
    write(tmp, "kuli.json", json.dumps(OFFER_CONFIG))
    talk, seen = _script(_wants("list_files", {"prefix": ""}, "a"),
                         _wants("read_file", {"path": "notes.md"}, "b"),
                         _says("the answer is 41"))

    result = runner.run(_task(), dict(RAW, id="local-llm"),
                        _grant_for(level="L2"), tmp, OFFER_CONFIG, talk=talk)
    equal("the loop stops because the model answered",
          result["stopped"], runner.ANSWERED)
    equal("after two tool calls", result["tool_calls"], 2)
    equal("and returns the model's text", result["text"], "the answer is 41")

    answers = [m for m in seen[-1]["messages"] if m.get("role") == "tool"]
    equal("both results went back to the model", len(answers), 2)
    check("the listing named the file", "notes.md" in answers[0]["content"])
    check("and the file's text was handed over",
          "the answer is 41" in answers[1]["content"])


def test_every_call_and_result_is_in_the_trail(tmp):
    write(tmp, "notes.md", "x\n")
    talk, _ = _script(_wants("read_file", {"path": "notes.md"}),
                      _says("done"))
    runner.run(_task(), dict(RAW, id="local-llm"), _grant_for(level="L2"),
               tmp, OFFER_CONFIG, talk=talk)

    records = trail.entries(tmp)
    events = [e["event"] for e in records]
    equal("the turn, the call and its result are all recorded",
          events, ["ModelReply", "PreToolUse", "PostToolUse", "ModelReply"])
    ok, problems = trail.verify(tmp)
    check("and the chain still verifies", ok, problems)
    equal("the loop names the provider it drove, not 'unknown'",
          records[1]["actor"]["provider"], "local-llm")
    check("the result is stored as a fingerprint, not content",
          "sha256" in json.dumps(records[2]["result"]))
    check("and the file's text is nowhere in the trail",
          "x\n" not in json.dumps(records[2]["result"]))


def test_a_payload_may_not_name_its_own_provider(tmp):
    """The event is written by the agent. The registry is not."""
    registry(tmp, dict(GOOD, id="honest", clearance="L2"))
    before = with_env(KULI_PROVIDER=None, CLAUDECODE=None, KULI_LOCAL=None)
    try:
        entry = trail.append({"hook_event_name": "PreToolUse",
                              "tool_name": "Read", "provider": "honest",
                              "model": "something", "clearance": "L3"}, tmp)
    finally:
        restore_env(before)
    equal("a claimed provider is ignored", entry["actor"]["provider"], "unknown")
    equal("so is a claimed model", entry["actor"]["model"], "unknown")
    check("and a claimed clearance cannot be recorded",
          entry["actor"]["clearance"] != "L3", entry["actor"])


def test_the_trail_shape_matches_a_wrapped_products(tmp):
    """T10's done-when: one code path reads both kinds of run."""
    write(tmp, "notes.md", "x\n")
    hooked = trail.append({"hook_event_name": "PreToolUse", "tool_name": "Read",
                           "tool_input": {"file_path": "notes.md"}}, tmp)
    talk, _ = _script(_wants("read_file", {"path": "notes.md"}), _says("done"))
    runner.run(_task(), dict(RAW, id="local-llm"), _grant_for(level="L2"),
               tmp, OFFER_CONFIG, talk=talk)
    ours = [e for e in trail.entries(tmp) if e["event"] == "PreToolUse"][-1]
    equal("the same keys, in the same shape",
          sorted(ours), sorted(hooked))
    equal("including the actor block",
          sorted(ours["actor"]), sorted(hooked["actor"]))


def test_a_refused_tool_is_handed_back_and_the_loop_goes_on(tmp):
    write(tmp, "notes.md", "x\n")
    talk, seen = _script(_wants("read_file", {"path": "business/secret.md"}),
                         _says("I was not allowed"))
    result = runner.run(_task(), dict(RAW, id="local-llm"), _grant_for(),
                        tmp, OFFER_CONFIG, talk=talk)
    equal("the loop still reached an answer", result["stopped"], runner.ANSWERED)
    answer = [m for m in seen[-1]["messages"] if m.get("role") == "tool"][0]
    check("the model is told it was refused",
          answer["content"].startswith("REFUSED:"), answer["content"])
    check("and why", "L2" in answer["content"], answer["content"])
    refusals = [e for e in trail.entries(tmp)
                if "refused" in json.dumps(e.get("result") or {})]
    equal("the refusal is in the trail", len(refusals), 1)


def test_a_tool_the_grant_does_not_name_is_refused(tmp):
    talk, seen = _script(_wants("list_files", {"prefix": ""}), _says("fine"))
    runner.run(_task(), dict(RAW, id="local-llm"),
               _grant_for(allowed=("read_file",), level="L2"), tmp,
               OFFER_CONFIG, talk=talk)
    answer = [m for m in seen[-1]["messages"] if m.get("role") == "tool"][0]
    check("a tool outside the grant is refused by name",
          "list_files is not a tool" in answer["content"], answer["content"])


def test_a_secret_in_the_content_is_caught_even_on_an_allowed_path(tmp):
    """The path said L0. What was in the file did not."""
    write(tmp, "docs/notes.md", "api_key: sk-abcdefghijklmnopqrstuvwxyz\n")
    talk, seen = _script(_wants("read_file", {"path": "docs/notes.md"}),
                         _says("nothing to see"))
    runner.run(_task(), dict(RAW, id="local-llm"), _grant_for(level="L2"),
               tmp, {"classification": {"rules": [
                   {"match": "docs/**", "level": "L0"}]}}, talk=talk)
    answer = [m for m in seen[-1]["messages"] if m.get("role") == "tool"][0]
    check("the return path refuses it", answer["content"].startswith("REFUSED:"))
    check("and the secret never reached the model",
          "sk-abcdefghijklmnopqrstuvwxyz" not in json.dumps(seen[-1]["messages"]))


def test_running_out_of_steps_is_a_stated_stop(tmp):
    write(tmp, "notes.md", "x\n")
    talk, _ = _script(_wants("read_file", {"path": "notes.md"}))
    result = runner.run(_task(), dict(RAW, id="local-llm"),
                        _grant_for(level="L2"), tmp, OFFER_CONFIG, steps=3,
                        talk=talk)
    equal("the loop says why it stopped", result["stopped"], runner.OUT_OF_STEPS)
    equal("after exactly the budget", result["tool_calls"], 3)


def test_nothing_escapes_the_repository(tmp):
    write(tmp, "notes.md", "x\n")
    for path in ("../outside.md", "/etc/passwd", "a/../../b.md"):
        try:
            tools.inside(tmp, path)
            check("%s is refused" % path, False)
        except tools.ToolError:
            check("%s is refused" % path, True)
    equal("while a path inside resolves",
          tools.inside(tmp, "notes.md").name, "notes.md")
    for bad, label in (({"path": "nope.md"}, "a missing file"),
                       ({"prefix": "notes.md"}, "a file asked for as a list")):
        try:
            tools.run("read_file" if "path" in bad else "list_files", bad, tmp)
            check("%s is refused" % label, False)
        except tools.ToolError:
            check("%s is refused" % label, True)
    try:
        tools.run("rm", {}, tmp)
        check("an unknown tool is refused rather than guessed at", False)
    except tools.ToolError:
        check("an unknown tool is refused rather than guessed at", True)


def test_a_listing_is_capped(tmp):
    for index in range(tools.MAX_ENTRIES + 20):
        write(tmp, "many/%03d.md" % index, "x")
    listing = tools.run("list_files", {"prefix": "many"}, tmp)
    equal("a listing cannot be used to page out the repository",
          len(listing.splitlines()), tools.MAX_ENTRIES)


def test_the_loop_refuses_a_bundle_built_for_someone_else(tmp):
    talk, _ = _script(_says("hi"))
    try:
        runner.run(_task(), dict(RAW, id="someone-else"), _grant_for(),
                   tmp, OFFER_CONFIG, talk=talk)
        check("the loop checks the bundle's stamp too", False)
    except adapters.AdapterError:
        check("the loop checks the bundle's stamp too", True)


# --- filter the offer, not only the call -----------------------------------

QUEUE = (
    {"service": "mcp://audit", "paths": ["src/engine.js"]},
    {"service": "mcp://audit", "paths": ["business/legal/contract.md"]},
    {"service": "mcp://deploy", "paths": ["src/engine.js"]},
    {"service": "mcp://audit"},
)

#: src is public, business/legal is confidential. Everything else is L2.
OFFER_CONFIG = {"classification": {"rules": [
    {"match": "src/**", "level": "L0"},
    {"match": "business/legal/**", "level": "L2"},
]}}


def _worker(level="L1", tools=("mcp://audit",)):
    return grants.Grant(principal="cloud", level=level, tools=tuple(tools))


def test_a_queue_is_filtered_before_it_is_shown():
    offered = gateway.offer(QUEUE, _worker(), OFFER_CONFIG)
    equal("only the work this grant can do is offered", len(offered), 2)
    equal("the public path is offered", offered[0]["paths"], ["src/engine.js"])
    check("the confidential one is not",
          all("business/legal/contract.md" not in (t.get("paths") or [])
              for t in offered))
    check("and neither is another service",
          all(t["service"] == "mcp://audit" for t in offered))


def test_every_withholding_says_why():
    reasons = [gateway.withheld(t, _worker(), OFFER_CONFIG) for t in QUEUE]
    check("a confidential path names the level",
          "L2 is above cloud" in (reasons[1] or ""), reasons[1])
    check("an unpermitted service names the tool",
          "mcp://deploy" in (reasons[2] or ""), reasons[2])
    equal("and a permitted task has no reason at all", reasons[0], None)


def test_a_task_is_judged_on_what_it_declares():
    """The known gap, pinned so it is a decision rather than a surprise."""
    bare = {"service": "mcp://audit"}
    equal("a task naming no path passes on its service alone",
          gateway.withheld(bare, _worker(), OFFER_CONFIG), None)
    equal("declaring the path is what gets it judged",
          gateway.withheld(dict(bare, paths=["business/legal/contract.md"]),
                           _worker(), OFFER_CONFIG) is None, False)


def test_offer_and_dispatch_cannot_disagree(tmp):
    write(tmp, "providers.json", LOCAL_SERVICE)
    grant = _worker()
    token = capability.sign(grant, KEY)
    for task in QUEUE:
        if task["service"] != "mcp://audit":
            continue
        permitted = task in gateway.offer(QUEUE, grant, OFFER_CONFIG)
        try:
            gateway.dispatch(task, token, KEY, lambda e: "fine", tmp,
                             OFFER_CONFIG)
            refused = False
        except (gateway.GatewayError, bundle.ClearanceError):
            refused = True
        equal("offered means dispatchable for %s" % (task.get("paths"),),
              permitted, not refused)


def test_an_expired_grant_is_offered_nothing():
    stale = grants.Grant(principal="cloud", level="L2", tools=("mcp://audit",),
                         expires="2020-01-01T00:00:00Z")
    equal("an expired grant sees an empty queue",
          gateway.offer(QUEUE, stale, OFFER_CONFIG), [])


# --- the gates as MCP tools ------------------------------------------------

def _ask(method, params=None, root=None, identifier=1):
    message = {"jsonrpc": "2.0", "method": method}
    if identifier is not None:
        message["id"] = identifier
    if params is not None:
        message["params"] = params
    return mcp.handle(message, str(root or ROOT))


def _text_of(response):
    return response["result"]["content"][0]["text"]


def test_the_handshake():
    result = _ask("initialize", {})["result"]
    equal("the protocol version is stated", result["protocolVersion"],
          mcp.PROTOCOL)
    equal("and the server names itself", result["serverInfo"]["name"], "kuli")
    check("tools are the declared capability", "tools" in result["capabilities"])


def test_every_tool_is_described():
    tools = _ask("tools/list", {})["result"]["tools"]
    equal("one entry per gate", len(tools), len(mcp.TOOLS))
    for tool in tools:
        check("%s has a description" % tool["name"], len(tool["description"]) > 20)
        equal("%s takes an object" % tool["name"],
              tool["inputSchema"]["type"], "object")


def test_the_surface_writes_nothing():
    """An agent may ask whether it would pass. It may not move the bar."""
    source = inspect.getsource(mcp)
    # Call-shaped, so the docstring explaining what is absent does not count
    # as the thing being present.
    for forbidden in ("write_baseline(", "write_starter(", "freeze(",
                      "create(", "write_text(", "mint("):
        check("the MCP surface never calls %s" % forbidden,
              forbidden not in source)
    for absent in ("baseline", "init", "record"):
        check("and exposes no %r tool" % absent, absent not in mcp.HANDLERS)


def test_a_verdict_is_never_an_argument():
    for _, _, schema, _ in mcp.TOOLS:
        for field in schema.get("properties", {}):
            check("no tool accepts %r as input" % field,
                  field not in ("level", "verdict", "ok", "allowance",
                                "clearance", "pass"))


def test_a_gate_answers_through_the_tool():
    text = _text_of(_ask("tools/call", {"name": "ratchet", "arguments": {}}))
    check("the ratchet reports through MCP", text.startswith(mcp.PASS), text)
    reply = _ask("tools/call", {"name": "classify",
                                "arguments": {"paths": [".env", "README.md"]}})
    text = _text_of(reply)
    check("classify names the secret level", "L3" in text and ".env" in text)
    check("and a verdict is not an error", not reply["result"]["isError"])


def test_cannot_judge_is_not_a_pass():
    reply = _ask("tools/call", {"name": "classify", "arguments": {"paths": []}})
    check("nothing to classify is undecided",
          _text_of(reply).startswith(mcp.UNDECIDED))
    check("and it is flagged as an error, not a pass",
          reply["result"]["isError"])
    missing = _ask("tools/call", {"name": "nonsense", "arguments": {}})
    check("an unknown tool is undecided rather than a crash",
          _text_of(missing).startswith(mcp.UNDECIDED))


def test_a_broken_tool_call_does_not_kill_the_server():
    reply = _ask("tools/call", {"name": "contract_check",
                                "arguments": {"slug": "no-such-increment"}})
    check("a missing contract comes back as text", "content" in reply["result"])
    check("and says it could not judge",
          _text_of(reply).startswith(mcp.UNDECIDED), _text_of(reply))


def test_unknown_methods_and_notifications():
    reply = _ask("resources/list", {})
    equal("an unsupported method is a JSON-RPC error",
          reply["error"]["code"], mcp.METHOD_NOT_FOUND)
    equal("a notification gets no response",
          _ask("notifications/initialized", {}, identifier=None), None)


def test_the_offer_tool_takes_a_token_not_a_level(tmp):
    """Authority arrives as a signature, so the caller cannot claim it."""
    schema = dict((name, s) for name, _, s, _ in mcp.TOOLS)["offer"]
    equal("the offer tool requires a token",
          sorted(schema["required"]), ["tasks", "token"])
    check("and never a level", "level" not in schema["properties"])

    token = capability.sign(_worker(level="L0"), KEY)
    reply = mcp.call("offer", {"token": token, "tasks": list(QUEUE)}, str(tmp))
    check("an unsigned environment cannot judge", reply["isError"],
          reply["content"][0]["text"])

    key_file = Path(tmp).parent / "offer.key"
    key_file.write_bytes(KEY + b"0" * 8)
    os.environ["KULI_CAPABILITY_KEY_FILE"] = str(key_file)
    try:
        bad = mcp.call("offer", {"token": token, "tasks": []}, str(tmp))
        check("a token signed with another key is refused, not honoured",
              bad["isError"], bad["content"][0]["text"])
    finally:
        del os.environ["KULI_CAPABILITY_KEY_FILE"]
        key_file.unlink()


def test_a_bad_line_is_skipped_not_fatal(tmp):
    lines = ['not json\n', '\n',
             json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}) + "\n"]
    out = io.StringIO()
    equal("the loop finishes", mcp.serve(str(ROOT), iter(lines), out), 0)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    equal("and only the real request was answered", len(replies), 1)
    equal("with its own id", replies[0]["id"], 7)


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
    test_an_additive_workflow_change_is_excused_from_a1,
    test_a_workflow_change_still_needs_a_second_actor,
    test_removing_a_line_from_a_workflow_binds_a1,

    test_an_unsigned_contract_is_not_ready,
    test_the_producer_may_not_be_the_reviewer,
    test_a_signed_contract_is_ready,
    test_the_bar_cannot_move_after_work_begins,
    test_an_unfrozen_contract_does_not_count,
    test_an_unsigned_contract_cannot_be_frozen,
    test_the_signing_key_lives_outside_the_repository,
    test_an_unknown_permission_key_is_refused,
    test_an_unknown_config_key_is_refused,
    test_nothing_resolves_by_default,
    test_a_transport_this_build_cannot_honour_is_refused,
    test_dispatch_refuses_before_it_calls,
    test_dispatch_judges_what_came_back,
    test_offer_and_dispatch_cannot_disagree,
    test_the_offer_tool_takes_a_token_not_a_level,
    test_a_bad_line_is_skipped_not_fatal,
    test_a_second_endpoint_is_a_config_change,
    test_the_registry_and_the_trail_carry_the_earned_clearance,
    test_a_two_tool_task_runs_to_an_answer,
    test_every_call_and_result_is_in_the_trail,
    test_a_payload_may_not_name_its_own_provider,
    test_the_trail_shape_matches_a_wrapped_products,
    test_a_refused_tool_is_handed_back_and_the_loop_goes_on,
    test_a_tool_the_grant_does_not_name_is_refused,
    test_a_secret_in_the_content_is_caught_even_on_an_allowed_path,
    test_running_out_of_steps_is_a_stated_stop,
    test_nothing_escapes_the_repository,
    test_a_listing_is_capped,
    test_the_loop_refuses_a_bundle_built_for_someone_else,
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
    test_an_additive_relaxation_is_caught_by_name,
    test_the_handshake, test_every_tool_is_described,
    test_the_surface_writes_nothing, test_a_verdict_is_never_an_argument,
    test_a_gate_answers_through_the_tool, test_cannot_judge_is_not_a_pass,
    test_a_broken_tool_call_does_not_kill_the_server,
    test_unknown_methods_and_notifications,
    test_a_queue_is_filtered_before_it_is_shown,
    test_every_withholding_says_why,
    test_a_task_is_judged_on_what_it_declares,
    test_an_expired_grant_is_offered_nothing,
    test_a_tool_schema_is_what_the_model_expects,
    test_tool_calls_are_parsed_or_refused,
    test_tools_are_only_sent_when_there_are_some,
    test_the_cli_prints_what_it_was_given,
    test_what_counts_as_this_machine,
    test_a_name_that_merely_resolves_here_does_not_count,
    test_a_loopback_endpoint_earns_its_clearance,
    test_an_endpoint_elsewhere_is_demoted_and_says_so,
    test_a_low_clearance_is_never_raised,
    test_verification_reads_the_endpoint_the_call_will_use,
    test_a_real_endpoint_answers_through_the_adapter,
    test_a_bundle_for_another_provider_is_refused,
    test_the_adapter_cannot_assemble_its_own_context,
    test_this_adapter_refuses_work_that_is_not_its_shape,
    test_a_bad_answer_is_a_refusal_that_quotes_nothing,
    test_the_endpoint_and_model_come_from_configuration,
    test_a_root_grant_is_the_registry_ceiling,
    test_asking_for_more_gives_less,
    test_a_chain_of_hops_can_only_shrink,
    test_scope_is_an_intersection,
    test_scope_matches_on_path_boundaries,
    test_tools_are_exact,
    test_a_grant_without_a_level_is_cleared_for_nothing,
    test_expiry_is_part_of_the_grant,
    test_a_recorded_grant_round_trips,
    test_coerce_takes_a_grant_or_a_registry_entry,
    test_a_narrowed_grant_is_what_the_boundary_obeys,
    test_a_signed_capability_verifies,
    test_a_capability_cannot_be_forged,
    test_every_capability_expires,
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
