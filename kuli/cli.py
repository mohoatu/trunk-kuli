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

from . import measures, ratchet, review_cost


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


def build_parser():
    parser = argparse.ArgumentParser(prog="kuli", description=__doc__)
    parser.add_argument("--root", default=".", help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("measure").set_defaults(func=cmd_measure)
    sub.add_parser("baseline").set_defaults(func=cmd_baseline)
    sub.add_parser("ratchet").set_defaults(func=cmd_ratchet)

    cost = sub.add_parser("review-cost")
    cost.add_argument("--base", required=True, help="git ref to compare against")
    cost.add_argument("--budget", type=int, default=120,
                      help="added lines allowed per acceptance criterion")
    cost.set_defaults(func=cmd_review_cost)

    return parser


def main(argv=None):
    _utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
