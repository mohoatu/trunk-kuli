"""kuli — command line.

    kuli measure              print every measure as JSON
    kuli baseline             record today's measures as the line to hold
    kuli ratchet              fail if any measure got worse
    kuli review-cost --base X fail if the change costs more to read than it
                              should for the criteria it serves
    kuli grant                what a sub-task would hold, next to its ceiling
    kuli capability           the same grant, signed and with a deadline
    kuli conform              every provider, asked the same forbidden things
    kuli egress               the process that holds the keys, so adapters do not
    kuli report               what each provider did, and what stopped it

Exit code 0 means pass, 1 means a gate refused, 2 means the gate could not
judge. A gate that cannot judge never reports success.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import (
    adapters, bundle, capability, classify, conformance, contract, duties,
    egress, gateway, grants, mcp, measures, providers, ratchet, review_cost,
    runner, toolguard, tools, trail,
)

#: Every refusal that means *this gate could not judge, so nothing passed*.
#: Collected in one place so a permission failure can never be mistaken for a
#: pass by a command that forgot to catch it.
CANNOT_JUDGE = (providers.RegistryError, ratchet.ConfigError,
                classify.ClassificationError, grants.GrantError,
                capability.CapabilityError, gateway.GatewayError,
                adapters.AdapterError, bundle.ClearanceError,
                tools.ToolError, egress.EgressError)


#: What `chcp 65001` sets. Named because the number means nothing on sight.
WINDOWS_UTF8 = 65001


def _windows_console_utf8():
    """Tell the console it is being sent UTF-8, as well as sending it.

    Reconfiguring the stream was only half the job: the stream then emits
    UTF-8 bytes, and a Windows console still decoding them as its legacy code
    page prints `ΓÇö` where an em dash was. Both ends have to agree.

    Failures are swallowed on purpose. There may be no console at all — this
    runs under a pipe in CI and under `kuli serve` — and a report that cannot
    set a code page is still a correct report.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(WINDOWS_UTF8)
        ctypes.windll.kernel32.SetConsoleCP(WINDOWS_UTF8)
    except Exception:  # noqa: BLE001 - see the docstring
        pass


def _utf8():
    """The reports contain names from Vietnamese repositories; cp1252 cannot
    print them, and a console error must not look like a failing gate."""
    _windows_console_utf8()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def cmd_measure(args):
    print(json.dumps(measures.measure(args.root), indent=2, sort_keys=True))
    return 0


def cmd_baseline(args):
    config = ratchet.load_config(args.root)
    current = measures.measure(args.root, config.get("skip", ()))
    path = ratchet.write_baseline(args.root, current)
    print("Baseline written to %s" % path)
    for language, block in sorted(current.items()):
        print("  %-11s %d units, erosion %.3f, verbosity %.1f, duplication %.3f"
              % (language, block["units"], block["erosion"],
                 block["verbosity"], block["duplication"]))
    print("\nFrom here a measure may be held or improved, never loosened.")
    return 0


def _report_trip(record, root):
    print("  %s" % ratchet.describe(record))
    print("      %s" % ratchet.MEANING.get(record["measure"], ""))
    if record["measure"] in ("erosion", "max_complexity"):
        units = (measures.python_units(root) if record["language"] == "python"
                 else measures.javascript_units(root))
        for unit in measures.worst_offenders(units):
            print("      carrying it: %s (complexity %d)"
                  % (unit["name"], unit["complexity"]))


def cmd_ratchet(args):
    ok, report = ratchet.run(args.root)
    if ok is None:
        print(report["error"], file=sys.stderr)
        return 2

    for record in report["excused"]:
        print("excused: %s" % ratchet.describe(record))
        print("      reason: %s" % record["reason"])

    if ok:
        print("Nothing got worse.")
        return 0

    print("The ratchet refused this change.\n")
    for record in report["trips"]:
        _report_trip(record, args.root)
    print("\nThis is not a rejection. Include the refactor that pays for it,")
    print("or record an exception in kuli.json with a reason, which stays")
    print("visible until it is repaid.")
    return 1


def cmd_review_cost(args):
    try:
        ok, report = review_cost.run(args.base, args.root, args.budget)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    if ok is None:
        return 2
    return 0 if ok else 1


def cmd_record(args):
    """Append one action to the trail. Must never block the agent.

    This runs as a hook on every tool call, so two rules govern it: it is
    observe-only, and it swallows its own failures. A recorder that can stop
    work gets switched off, and then there is no record at all.
    """
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    try:
        entry = trail.append(event, args.root)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        print("trail: could not record (%s)" % exc, file=sys.stderr)
        return 0
    if args.verbose:
        print(entry["hash"][:12], entry["tool"], entry.get("target") or "")
    return 0


def _print_counts(title, data):
    if not data:
        return
    print("\n  %s" % title)
    for name, count in sorted(data.items(), key=lambda kv: -kv[1]):
        print("    %-28s %d" % (name, count))


def _print_recent(records, limit):
    print("\n  last %d" % limit)
    for entry in records[-limit:]:
        print("    %s  %-14s %s" % (entry["ts"], entry["tool"],
                                    entry.get("target") or ""))


def cmd_trail(args):
    records = trail.entries(args.root, args.since)
    if args.file:
        records = trail.touched(records, args.file)
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
        return 0

    summary = trail.summarise(records)
    print("%d actions recorded" % summary["total"])
    _print_counts("by tool", summary["by_tool"])
    _print_counts("by provider", summary["by_actor"])
    _print_counts("by day", summary["by_day"])
    if args.last:
        _print_recent(records, args.last)
    return 0


def cmd_audit(args):
    ok, problems = trail.verify(args.root)
    count = len(trail.entries(args.root))
    if ok:
        print("%d entries, chain intact." % count)
        return 0
    print("The trail has been altered. %d entries, %d problems:"
          % (count, len(problems)))
    for problem in problems[:20]:
        print("  %s" % problem)
    return 1


def _add_gates(sub):
    sub.add_parser("measure").set_defaults(func=cmd_measure)
    sub.add_parser("baseline").set_defaults(func=cmd_baseline)
    sub.add_parser("ratchet").set_defaults(func=cmd_ratchet)

    cost = sub.add_parser("review-cost")
    cost.add_argument("--base", required=True, help="git ref to compare against")
    cost.add_argument("--budget", type=int, default=120,
                      help="added lines allowed per acceptance criterion")
    cost.set_defaults(func=cmd_review_cost)


def _add_trail(sub):
    record = sub.add_parser("record", help="append one action (hook target)")
    record.add_argument("--verbose", action="store_true")
    record.set_defaults(func=cmd_record)

    show = sub.add_parser("trail", help="what the agents did")
    show.add_argument("--since", help="YYYY-MM-DD")
    show.add_argument("--file", help="only actions whose target mentions this")
    show.add_argument("--last", type=int, default=0, help="also list the last N")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_trail)

    sub.add_parser("audit", help="verify the trail was not altered"
                   ).set_defaults(func=cmd_audit)


def _add_boundary(sub):
    reg = sub.add_parser("providers", help="who may run here, and at what clearance")
    reg.add_argument("--init", action="store_true", help="write a starter registry")
    reg.set_defaults(func=cmd_providers)

    sub.add_parser("report", help="what each provider did, and what stopped it"
                   ).set_defaults(func=cmd_report)

    sub.add_parser("conform", help="every provider, asked the same forbidden "
                                   "things, judged the same way"
                   ).set_defaults(func=cmd_conform)

    out = sub.add_parser("egress", help="the process that holds the keys")
    out.add_argument("--port", type=int, default=egress.DEFAULT_PORT)
    out.set_defaults(func=cmd_egress)

    level = sub.add_parser("classify", help="how sensitive a path is, and why")
    level.add_argument("paths", nargs="+")
    level.set_defaults(func=cmd_classify)

    bun = sub.add_parser("bundle", help="what a provider may be shown")
    bun.add_argument("paths", nargs="+")
    bun.add_argument("--provider", help="registry id; defaults to the active one")
    bun.set_defaults(func=cmd_bundle)

    grd = sub.add_parser("guard", help="judge a tool result on its way back")
    grd.add_argument("--provider", help="registry id; defaults to the active one")
    grd.set_defaults(func=cmd_guard)


def _add_procedure(sub):
    dut = sub.add_parser("duties", help="nobody relaxed the rule judging them")
    dut.add_argument("--base", required=True, help="git ref to compare against")
    dut.set_defaults(func=cmd_duties)

    con = sub.add_parser("contract", help="the bar, agreed before the work")
    con.add_argument("action", choices=("new", "check", "freeze", "verify"))
    con.add_argument("slug", nargs="?")
    con.set_defaults(func=cmd_contract)


ROW = "%-16s %-14s %-18s %-9s %s"


def _print_registry(entries, running):
    print(ROW % ("ID", "CLEARANCE", "SHAPE", "ADAPTER", ""))
    for entry in entries:
        mark = "<- running" if entry["id"] == running["id"] else ""
        print(ROW % (entry["id"], entry["clearance"], entry["shape"],
                     entry["adapter"], mark))
    for entry in providers.demoted(entries):
        print("\n  %s: %s" % (entry["id"], entry["clearance_reason"]))
    if running["id"] == "unknown":
        print("\nNone of them is detected in this process. Actions recorded "
              "now will say 'unknown', which is the honest answer.")


def cmd_providers(args):
    if args.init:
        print("Wrote %s" % providers.write_starter(args.root))
        return 0
    try:
        entries = providers.load(args.root)
    except providers.RegistryError as exc:
        print("The registry is not usable: %s" % exc, file=sys.stderr)
        return 2
    if not entries:
        print("No providers registered. Write one with: kuli providers --init")
        return 2
    _print_registry(entries, providers.active(args.root))
    return 0


CAPABILITY_ROW = "  %-16s %6s %6s %7s %9s  %-12s %s"


def _report_row(name, row):
    print("  %-16s %6d actions  %2d tools  %s .. %s"
          % (name, row["actions"], len(row["tools"]),
             (row["first"] or "")[:10], (row["last"] or "")[:10]))
    print("%22s models: %s" % ("", ", ".join(sorted(row["models"]))))


def _capability_table(rows):
    """T14. Cost is printed blank rather than guessed — see trail.capability."""
    print("\n" + CAPABILITY_ROW % ("PROVIDER", "RUNS", "DONE", "TURNS",
                                   "REFUSALS", "WORST GATE", "COST"))
    for name, row in sorted(rows.items()):
        print(CAPABILITY_ROW % (name, row["runs"], row["answered"],
                                row["turns"], row["refusals"],
                                trail.worst_gate(row) or "—",
                                "—" if row["cost_usd"] is None else row["cost_usd"]))
    print("\n  Cost is blank because nothing measures it yet. A blank is a "
          "question; a guess would be read as a measurement.")


def _registered_ids(root):
    try:
        return {e["id"] for e in providers.load(root)}
    except providers.RegistryError:
        return set()


def cmd_report(args):
    records = trail.entries(args.root)
    if not records:
        print("Nothing recorded yet. The trail is empty.")
        return 0
    rows = trail.per_provider(records)
    print("%d actions across %d provider(s)" % (len(records), len(rows)))
    for name, row in sorted(rows.items(), key=lambda kv: -kv[1]["actions"]):
        _report_row(name, row)
    silent = sorted(_registered_ids(args.root) - set(rows))
    if silent:
        print("\n  registered but never seen: %s" % ", ".join(silent))
    _capability_table(trail.capability(records, conformance.gate_of))
    return 0


def _conform_row(row):
    print("\n  %s" % row["probe"])
    for name, verdict in sorted(row["by_provider"].items()):
        mark = "refused" if verdict["right_reason"] else "LET THROUGH"
        print("    %-9s %-16s %s" % (mark, name, verdict["reason"] or "—"))


def cmd_conform(args):
    """T11-T13. Every provider, equalised, asked the same forbidden things."""
    entries = providers.load(args.root)
    ok, report = conformance.run(entries, args.root,
                                 ratchet.load_config(args.root))
    if ok is None:
        print(report["error"], file=sys.stderr)
        return 2

    print("%d provider(s), all narrowed to %s"
          % (len(report["providers"]),
             json.dumps(report["equalised_to"], sort_keys=True)))
    for row in report["rows"]:
        _conform_row(row)

    if ok:
        print("\nEvery provider was stopped by the same gate, for the same "
              "reason, every time.")
        return 0
    for row in report["judged_differently"]:
        print("\n  JUDGED DIFFERENTLY: %s" % row["probe"])
        print("      A gate that answers differently per provider is not a "
              "gate; it is a preference.")
    for row in report["let_through"]:
        print("\n  LET THROUGH or refused for the wrong reason: %s"
              % row["probe"])
    return 1


def cmd_classify(args):
    config = ratchet.load_config(args.root)
    try:
        for target in args.paths:
            level, reason = classify.explain(target, config)
            print("%-4s %-46s %s" % (level, target, reason))
    except classify.ClassificationError as exc:
        print("The classification rules are not usable: %s" % exc, file=sys.stderr)
        return 2
    return 0


def _resolve_provider(args):
    """The named provider, or the one detected. None if the name is unknown."""
    if not args.provider:
        return providers.active(args.root)
    for entry in providers.load(args.root):
        if entry["id"] == args.provider:
            return entry
    return None


def _print_verdicts(paths, refused, config):
    for path in paths:
        mark = "REFUSED" if path in refused else "ok"
        print("  %-8s %-4s %s" % (mark, classify.level_of(path, config), path))
    for why in refused.values():
        print("\n  %s" % why)


def cmd_bundle(args):
    """What this provider would and would not be allowed to see."""
    running = _resolve_provider(args)
    if running is None:
        print("No provider %r in the registry." % args.provider, file=sys.stderr)
        return 2

    config = ratchet.load_config(args.root)
    print("provider %s, cleared to %s"
          % (running["id"], running.get("clearance") or "nothing"))
    refused = dict((part.source, why)
                   for part, why in bundle.would_refuse(args.paths, running, config))
    _print_verdicts(args.paths, refused, config)
    return 1 if refused else 0


def cmd_guard(args):
    """Judge one tool result before it goes back into a context.

    Reads the same payload `record` does, so it can sit on PostToolUse
    alongside it. Exit 1 means the result is withheld.
    """
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print("guard: unreadable payload", file=sys.stderr)
        return 2

    running = _resolve_provider(args)
    if running is None:
        print("No provider %r in the registry." % args.provider, file=sys.stderr)
        return 2

    ok, level, reason = toolguard.guard(
        event, running, ratchet.load_config(args.root), args.root)
    if ok:
        print("allowed (%s) — %s" % (level, reason))
        return 0
    print(reason, file=sys.stderr)
    return 1


def cmd_duties(args):
    try:
        ok, report = duties.run(args.base, args.root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("%d commit(s) since %s, %d touching the rules"
          % (report["commits"], report["base"], report["touching_rules"]))
    for commit, paths in report["excused"]:
        print("  excused %s: %s removes nothing and adds no relaxation"
              % (commit, ", ".join(paths)))
    if ok:
        print("Nobody relaxed a rule that was judging them.")
        return 0
    for record, problems in report["faults"]:
        print("\n  %s" % record["commit"])
        for problem in problems:
            print("      %s" % problem)
    return 1


def _contract_report(results):
    for slug, ok, message in results:
        print("  %-7s %s" % ("ok" if ok else "FAIL", message))


def cmd_contract(args):
    try:
        return _contract_action(args)
    except contract.ContractError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _contract_new(args):
    print("Wrote %s" % contract.create(args.slug, args.root))
    return 0


def _contract_freeze(args):
    print("Frozen: %s" % contract.freeze(args.slug, args.root))
    return 0


def _contract_check(args):
    ok, _, problems = contract.check(args.slug, args.root)
    print("%s is %s" % (args.slug, "signed off" if ok else "not ready"))
    for problem in problems:
        print("      %s" % problem)
    return 0 if ok else 1


def _contract_verify(args):
    if args.slug:
        results = [(args.slug,) + contract.verify(args.slug, args.root)]
    else:
        results = contract.verify_all(args.root)[1]
    _contract_report(results)
    return 0 if all(r[1] for r in results) else 1


CONTRACT_ACTIONS = {"new": _contract_new, "freeze": _contract_freeze,
                    "check": _contract_check, "verify": _contract_verify}


def _contract_action(args):
    return CONTRACT_ACTIONS[args.action](args)


def _narrowing(args):
    """The limits named on the command line, as `narrow` keywords."""
    return {"level": args.level, "scope": args.scope, "tools": args.tools}


def _root_grant(args):
    entry = _resolve_provider(args)
    if entry is None:
        raise grants.GrantError("no provider %r in the registry" % args.provider)
    return grants.for_provider(entry)


def cmd_grant(args):
    """What a sub-task would hold. Shows that asking for more gives less."""
    root = _root_grant(args)
    narrowed = root.narrow(**_narrowing(args))
    print(json.dumps({"root": root.as_dict(), "narrowed": narrowed.as_dict()},
                     indent=2, sort_keys=True))
    return 0


def cmd_capability(args):
    key = capability.signing_key(args.root)
    if args.token:
        print(json.dumps(capability.verify(args.token, key).as_dict(),
                         indent=2, sort_keys=True))
        return 0
    grant = _root_grant(args).narrow(**_narrowing(args))
    print(capability.mint(grant, key, args.ttl))
    return 0


def _context_parts(paths, config):
    """A part per path, levelled by the classifier, carrying the file's text."""
    return [bundle.part_for(path, config, Path(path).read_text(encoding="utf-8"))
            for path in paths or []]


def cmd_ask(args):
    """One completion through a raw-model provider.

    The context goes through the real assembler, so a path above the
    provider's clearance refuses the call rather than being trimmed.
    """
    entry = _resolve_provider(args)
    if entry is None:
        print("No provider %r in the registry." % args.provider, file=sys.stderr)
        return 2
    config = ratchet.load_config(args.root)
    grant = grants.for_provider(entry).narrow(**_narrowing(args))
    parcel = bundle.assemble(_context_parts(args.context, config), grant)
    print(adapters.complete(parcel, entry, args.prompt, timeout=args.timeout))
    return 0


def cmd_run(args):
    """kuli's own loop for a raw model: context in, tools dispatched, recorded."""
    entry = _resolve_provider(args)
    if entry is None:
        print("No provider %r in the registry." % args.provider, file=sys.stderr)
        return 2
    config = ratchet.load_config(args.root)
    grant = grants.for_provider(entry).narrow(**_narrowing(args))
    task = {"prompt": args.prompt,
            "context": dict((path, Path(path).read_text(encoding="utf-8"))
                            for path in args.context or [])}
    result = runner.run(task, entry, grant, args.root, config, args.steps,
                        allowed=args.tools,
                        talk=lambda m, e, s: adapters.converse(
                            m, e, s, timeout=args.timeout))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_egress(args):
    """Hold the credentials here, so the adapter's process never has them."""
    server = egress.build(args.root, args.port)
    print("Egress proxy on http://%s:%d — destinations: %s"
          % (egress.LOOPBACK, args.port, ", ".join(sorted(server.table))))
    print("Point an adapter at %s:%d/to/<destination> and give it no key."
          % (egress.LOOPBACK, args.port))
    server.serve_forever()
    return 0


def cmd_serve(args):
    """Speak MCP on stdin and stdout, so an agent calls the gates itself."""
    return mcp.serve(args.root)


def cmd_offer(args):
    """Which of a queue on stdin this grant may work, and why not for the rest.

    Refusal at the call is the backstop; this is the design. An agent should
    not be shown work it cannot do.
    """
    grant = _root_grant(args).narrow(**_narrowing(args))
    config = ratchet.load_config(args.root)
    for task in json.load(sys.stdin):
        reason = gateway.withheld(task, grant, config)
        print("  %-9s %-24s %s" % ("withheld" if reason else "offered",
                                   gateway.as_task(task).get("service") or "",
                                   reason or ""))
    return 0


#: The flags every authority command shares, because they are all narrowings.
NARROWING_FLAGS = (
    ("--provider", {"help": "registry id; defaults to the active one"}),
    ("--level", {"help": "narrow to this level at most"}),
    ("--scope", {"nargs": "*", "help": "narrow to these paths"}),
    ("--tools", {"nargs": "*", "help": "narrow to these tools"}),
)

AUTHORITY = {
    "grant": ("what a sub-task would hold", cmd_grant),
    "capability": ("a signed, expiring grant", cmd_capability),
    "offer": ("which of a queue on stdin this grant may work", cmd_offer),
}


def _add_model_commands(sub):
    """`ask` is one turn; `run` is the loop. Both take a narrowed grant."""
    for name, helptext, func in (
            ("ask", "one completion through a raw-model provider", cmd_ask),
            ("run", "kuli's own loop for a raw model", cmd_run)):
        cmd = sub.add_parser(name, help=helptext)
        for flag, options in NARROWING_FLAGS:
            cmd.add_argument(flag, **options)
        cmd.add_argument("--prompt", required=True)
        cmd.add_argument("--context", nargs="*", help="paths for the bundle")
        cmd.add_argument("--timeout", type=int, default=adapters.DEFAULT_TIMEOUT)
        if name == "run":
            cmd.add_argument("--steps", type=int, default=runner.DEFAULT_STEPS)
        cmd.set_defaults(func=func)


def _add_authority(sub):
    sub.add_parser("serve", help="expose the gates as MCP tools (read-only)"
                   ).set_defaults(func=cmd_serve)

    made = {}
    for name, (helptext, func) in sorted(AUTHORITY.items()):
        cmd = sub.add_parser(name, help=helptext)
        for flag, options in NARROWING_FLAGS:
            cmd.add_argument(flag, **options)
        cmd.set_defaults(func=func)
        made[name] = cmd

    made["capability"].add_argument("--ttl", type=int, default=900,
                                    help="seconds the capability lives")
    made["capability"].add_argument("--verify", dest="token",
                                    help="read a token instead of issuing one")

    _add_model_commands(sub)


def build_parser():
    parser = argparse.ArgumentParser(prog="kuli", description=__doc__)
    parser.add_argument("--root", default=".", help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_gates(sub)
    _add_trail(sub)
    _add_boundary(sub)
    _add_procedure(sub)
    _add_authority(sub)
    return parser


def main(argv=None):
    _utf8()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CANNOT_JUDGE as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
