"""`chock status --summary` and `--verify-log`: each takes a few of status's flags and refuses the rest."""

from __future__ import annotations

import argparse
import sys

from chock.gatelog_chain import main as chain_main
from chock.gatelog_summary import main as summary_main


def summary(args: argparse.Namespace) -> int:
    """`--summary`: rates, latency and faults, taking --since, --route and --json only."""
    if any((args.only, args.policy, args.by, args.format, args.level, args.verdict, args.plugin, args.follow)):
        sys.stderr.write("--summary takes --since, --route and --json only\n")
        return 2
    flags = [("--since", args.since), ("--route", args.route)]
    given = [part for flag, value in flags if value is not None for part in (flag, str(value))]
    return int(summary_main(["--repo", args.repo, *given, *(["--json"] if args.json else [])]) or 0)


def verify_log(args: argparse.Namespace) -> int:
    """`--verify-log`: the chain walk, taking --route, --head and --json only."""
    if not args.verify_log:
        sys.stderr.write("--head is read with --verify-log\n")
        return 2
    others = (args.summary, args.only, args.policy, args.since, args.by, args.format, args.level, args.verdict)
    if any((*others, args.plugin, args.follow)):
        sys.stderr.write("--verify-log takes --route, --head and --json only\n")
        return 2
    flags = (("--route", args.route), ("--head", args.head))
    given = [part for flag, value in flags if value for part in (flag, value)]
    return int(chain_main(["--repo", args.repo, *given, *(["--json"] if args.json else [])]) or 0)
