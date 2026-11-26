"""kuli — command line.

    kuli measure              print every measure as JSON
    kuli baseline             record today's measures as the line to hold
    kuli ratchet              fail if any measure got worse
    kuli review-cost --base X fail if the change costs more to read than it
                              should for the criteria it serves

Exit code 0 means pass, 1 means a gate refused, 2 means the gate could not
judge. A gate that cannot judge never reports success.
"""

import argparse
import json
import sys

from . import classify, measures, providers, ratchet, review_cost, trail


def _utf8():
    """The reports contain names from Vietnamese repositories; cp1252 cannot
    print them, and a console error must not look like a failing gate."""
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

    reg = sub.add_parser("providers", help="who may run here, and at what clearance")
    reg.add_argument("--init", action="store_true", help="write a starter registry")
    reg.set_defaults(func=cmd_providers)

    sub.add_parser("report", help="what each provider did"
                   ).set_defaults(func=cmd_report)

    level = sub.add_parser("classify", help="how sensitive a path is, and why")
    level.add_argument("paths", nargs="+")
    level.set_defaults(func=cmd_classify)


ROW = "%-16s %-14s %-18s %-9s %s"


def _print_registry(entries, running):
    print(ROW % ("ID", "CLEARANCE", "SHAPE", "ADAPTER", ""))
    for entry in entries:
        mark = "<- running" if entry["id"] == running["id"] else ""
        print(ROW % (entry["id"], entry["clearance"], entry["shape"],
                     entry["adapter"], mark))
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


def _report_row(name, row):
    print("  %-16s %6d actions  %2d tools  %s .. %s"
          % (name, row["actions"], len(row["tools"]),
             (row["first"] or "")[:10], (row["last"] or "")[:10]))
    print("%22s models: %s" % ("", ", ".join(sorted(row["models"]))))


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
    return 0


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


def build_parser():
    parser = argparse.ArgumentParser(prog="kuli", description=__doc__)
    parser.add_argument("--root", default=".", help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_gates(sub)
    _add_trail(sub)
    return parser


def main(argv=None):
    _utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
