"""`chock status --only log` -- read the local gate outcome log."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

from chock.gate.runner import journal
from chock.gatelog_report import _printable, render_groups_md, render_groups_text

LOG_DIR = "log"
LOG_NAME = "gate-events.jsonl"
ROTATED_NAME = "gate-events.1.jsonl"
#: The plugin route's per-agent log under the user's home: `~/.chock/log/<agent>/events.jsonl`.
PLUGIN_LOG_NAME = "events.jsonl"
PLUGIN_ROTATED_NAME = "events.1.jsonl"
ROUTES = ("sync", "plugin")
LEVELS = (journal.LOG_INFO, journal.LOG_DEBUG)
VERDICTS = ("allow", "block", "ask", "warn", "off")
FOLLOW_INTERVAL = 0.5

GROUP_KEYS = ("policy", "rule", "agent", "event")
FORMATS = ("text", "md")
UNKNOWN = "unknown"
TOP_FILES = 3
_SINCE_RANGE = "must be 1 or more days"
#: A gate's `matches` line is `<path>[:<line>]: <label>`; only the path is read, never the label.
_MATCH_PATH_RE = re.compile(r"^(?P<path>[^\s:]+)(?::\d+)?: ")


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _pair(folder: Path, rotated: str, current: str) -> list[Path]:
    return [path for path in (folder / rotated, folder / current) if path.exists()]


def log_files(repo_root: Path, route: str | None = None, home: Path | None = None) -> list[Path]:
    """Every log file on the routes asked for, each rotated file before its current one, skipping absent ones.

    Sync: `<repo>/.chock/log/`. Plugin: `~/.chock/log/<agent>/`, plus the user-scope toggle lines in `~/.chock/log/`.
    """
    files = _pair(Path(repo_root) / ".chock" / LOG_DIR, ROTATED_NAME, LOG_NAME) if route in (None, "sync") else []
    if route in (None, "plugin"):
        base = (home or _home()) / ".chock" / LOG_DIR
        files += _pair(base, ROTATED_NAME, LOG_NAME)
        agents = sorted(path for path in base.glob("*") if path.is_dir()) if base.is_dir() else []
        files += [path for folder in agents for path in _pair(folder, PLUGIN_ROTATED_NAME, PLUGIN_LOG_NAME)]
    return files


def _records(lines: Iterable[str]) -> list[dict[str, Any]]:
    """The readable records among `lines`; a record needs a policy id."""
    found = []
    for line in lines:
        try:
            record = json.loads(line) if line.strip() else None
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("policy_id"):
            found.append(record)
    return found


def record_route(record: dict[str, Any]) -> str:
    """A record's route; one written before routes existed is a sync record."""
    return str(record.get("route") or "sync")


def record_level(record: dict[str, Any]) -> str:
    """A record's level; one written before levels existed gets the level its verdict would earn now."""
    return str(record.get("level") or journal.log_record_level(record))


def read_events(
    repo_root: Path, since_days: int | None = None, *, route: str | None = None, home: Path | None = None
) -> list[dict[str, Any]]:
    """Every readable record on the routes asked for, oldest first."""
    cutoff = None
    if since_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    events: list[dict[str, Any]] = []
    for path in log_files(repo_root, route, home):
        try:
            events += _records(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
    events = [e for e in events if route is None or record_route(e) == route]
    events = [e for e in events if not cutoff or str(e.get("ts", "")) >= cutoff]
    return sorted(events, key=lambda e: str(e.get("ts", "")))


def keep(record: dict[str, Any], args: argparse.Namespace) -> bool:
    """Whether a record passes the `--policy`, `--verdict` and `--level` filters."""
    if args.policy and record.get("policy_id") != args.policy:
        return False
    if args.verdict and record.get("verdict") != args.verdict:
        return False
    return not (args.level == journal.LOG_INFO and record_level(record) != journal.LOG_INFO)


def settings_problems(repo_root: Path) -> list[str]:
    """What is wrong with the log settings in force: an unknown `CHOCK_LOG_LEVEL`, or a bad file in either scope."""
    named = os.environ.get(journal.LOG_LEVEL_ENV, "").strip()
    problems = (
        []
        if not named or named.lower() in journal.LOG_LEVELS
        else [f"{journal.LOG_LEVEL_ENV}={named!r} is not off, info or debug; ignored"]
    )
    for path in journal.log_settings_paths(repo_root):
        problems += journal.log_settings_read(path)[1]
    return problems


def follow(
    paths: Callable[[], list[Path]],
    wanted: Callable[[dict[str, Any]], bool],
    out: TextIO = sys.stdout,
    *,
    polls: int | None = None,
) -> int:
    """Print each new record as one JSON line as it is written, until interrupted (or after `polls` polls)."""
    offsets = {path: path.stat().st_size for path in paths()}
    done = 0
    try:
        while polls is None or done < polls:
            time.sleep(FOLLOW_INTERVAL)
            done += 1
            for path in paths():
                size, start = path.stat().st_size, offsets.get(path, 0)
                start = 0 if size < start else start  # rotated: the current file started again
                with path.open("rb") as fh:
                    fh.seek(start)
                    chunk = fh.read(size - start)
                complete = chunk[: chunk.rfind(b"\n") + 1]
                offsets[path] = start + len(complete)
                for record in _records(complete.decode("utf-8", errors="replace").splitlines()):
                    if wanted(record):
                        print(json.dumps(record), file=out, flush=True)
    except KeyboardInterrupt:
        return 0
    return 0


def summarize(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per (policy, surface) totals, most-active first."""
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for record in events:
        key = (str(record.get("policy_id")), str(record.get("surface") or "unknown"))
        entry = totals.setdefault(
            key,
            {
                "policy_id": key[0],
                "surface": key[1],
                "events": 0,
                "allow": 0,
                "block": 0,
                "ask": 0,
                "warn": 0,
                "would_block": 0,
                "last_block": None,
            },
        )
        entry["events"] += 1
        entry["would_block"] += record.get("would_block") is True
        verdict = record.get("verdict")
        if verdict in ("ask", "warn"):
            entry[verdict] += 1
        elif verdict == "block":
            entry["block"] += 1
            ts = str(record.get("ts") or "")
            if ts > (entry["last_block"] or ""):
                entry["last_block"] = ts
        else:
            entry["allow"] += 1
    return sorted(totals.values(), key=lambda e: (-e["events"], e["policy_id"]))


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _group_names(record: dict[str, Any], by: str) -> list[str]:
    """The groups a record counts toward; a record lacking the field counts under "unknown"."""
    if by == "policy":
        return [str(record["policy_id"])]
    if by == "rule":
        rules = record.get("rules")
        return sorted(rules) if isinstance(rules, dict) and rules else [UNKNOWN]
    return [str(record.get(by) or UNKNOWN)]


def _record_files(record: dict[str, Any]) -> list[str]:
    matches = record.get("matches")
    found = (_MATCH_PATH_RE.match(m) for m in matches if isinstance(m, str)) if isinstance(matches, list) else ()
    return sorted({m.group("path") for m in found if m})


def _new_group(name: str) -> dict[str, Any]:
    return {
        "group": name,
        "events": 0,
        "allow": 0,
        "block": 0,
        "ask": 0,
        "warn": 0,
        "would_block": 0,
        "new_findings": 0,
        "baseline_findings": 0,
        "agents": set(),
        "rules": Counter(),
        "files": Counter(),
    }


def _tally(entry: dict[str, Any], record: dict[str, Any], by: str) -> None:
    """Add one record to a group. Grouped by rule, `new` is that rule's own count; the verdict,
    baseline and file columns stay per record, since the log does not tie them to one rule."""
    entry["events"] += 1
    verdict = record.get("verdict")
    entry[verdict if verdict in ("block", "ask", "warn") else "allow"] += 1
    entry["would_block"] += record.get("would_block") is True
    rules = record.get("rules")
    if by == "rule" and isinstance(rules, dict) and entry["group"] in rules:
        entry["new_findings"] += _count(rules[entry["group"]])
    else:
        entry["new_findings"] += _count(record.get("new_findings"))
    entry["baseline_findings"] += _count(record.get("baseline_findings"))
    if record.get("agent"):
        entry["agents"].add(str(record["agent"]))
    if by != "rule" and isinstance(rules, dict):
        entry["rules"].update({str(k): _count(v) for k, v in rules.items()})
    entry["files"].update(_record_files(record))


def group_events(events: list[dict[str, Any]], by: str) -> list[dict[str, Any]]:
    """Counts per `by` group (policy, rule, agent or event), most-intercepted first.

    Reads only verdicts, counts, ids and the paths in `matches`; a file's contents are never logged.
    """
    groups: dict[str, dict[str, Any]] = {}
    for record in events:
        for name in _group_names(record, by):
            _tally(groups.setdefault(name, _new_group(name)), record, by)
    rows = []
    for entry in groups.values():
        entry["agents"] = sorted(entry["agents"])
        entry["rules"] = dict(entry["rules"].most_common())
        top = sorted(entry["files"].items(), key=lambda item: (-item[1], item[0]))[:TOP_FILES]
        entry["files"] = [{"path": p, "count": n} for p, n in top]
        rows.append(entry)
    return sorted(rows, key=lambda e: (-(e["block"] + e["ask"] + e["warn"]), -e["events"], e["group"]))


def installed_policies(repo_root: Path) -> list[str]:
    """Policy ids present in the repo, from the directory tree rather than the registry."""
    root = Path(repo_root) / ".agents" / "policies"
    if not root.is_dir():
        return []
    return sorted(
        {path.parent.name for path in root.glob("*/manifest.yaml")}
        | {path.parent.name for path in root.glob("*/*/manifest.yaml")}
    )


def render_text(summary: list[dict[str, Any]], silent: list[str]) -> str:
    cols = ("events", "allow", "block", "ask", "warn") + (
        ("would_block",) if any(e["would_block"] for e in summary) else ()
    )
    width = max((len(str(e["policy_id"])) for e in summary), default=0)
    lines = [f"{'policy'.ljust(width)}  {'surface':<13} " + " ".join(f"{c:>6}" for c in cols) + "  last block"]
    for entry in summary:
        cells = " ".join(f"{entry[c]:>{max(len(c), 6)}}" for c in cols)
        lines.append(
            f"{str(entry['policy_id']).ljust(width)}  {entry['surface']:<13} {cells}  {entry['last_block'] or 'never'}"
        )
    lines = lines if summary else ["No gate outcomes recorded yet."]
    if silent:
        lines += ["", f"Never recorded ({len(silent)}): {', '.join(silent)}"]
        lines.append("Advisory policies emit no runtime event, so absence here is not evidence of a gap.")
    return "\n".join(lines)


def positive_days(value: str) -> int:
    """argparse type for `--since`: a whole number of days, 1 or more."""
    days = int(value)
    if days < 1:
        raise argparse.ArgumentTypeError(_SINCE_RANGE)
    return days


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chock status --only log", description="Read the decision log, both routes")
    parser.add_argument("--repo", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--policy", help="Restrict the report to one policy id")
    parser.add_argument("--since", type=positive_days, metavar="DAYS", help="Only records from the last N days")
    parser.add_argument(
        "--route", choices=ROUTES, help="Only the sync route (this repo) or the plugin route (~/.chock)"
    )
    parser.add_argument("--level", choices=LEVELS, help="info: only decisions a policy made; debug: allows too")
    parser.add_argument("--verdict", choices=VERDICTS, help="Only records with this verdict")
    parser.add_argument("--follow", action="store_true", help="Print new records as they are written (Ctrl-C stops)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results")
    parser.add_argument("--by", choices=GROUP_KEYS, help="Group counts by policy, rule, agent or event")
    parser.add_argument("--format", choices=FORMATS, default="text", help="md prints a paste-able markdown summary")
    return parser


def main(argv: list[str] | None = None, *, polls: int | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.json and args.format == "md":
        parser.error("--json and --format md are mutually exclusive")

    repo_root = Path(args.repo).resolve()
    for problem in settings_problems(repo_root):
        print(f"chock: log settings: {problem}", file=sys.stderr)
    if args.follow:
        current = (LOG_NAME, PLUGIN_LOG_NAME)
        return follow(
            lambda: [p for p in log_files(repo_root, args.route) if p.name in current],
            lambda record: keep(record, args) and (args.route is None or record_route(record) == args.route),
            polls=polls,
        )
    events = [e for e in read_events(repo_root, args.since, route=args.route) if keep(e, args)]

    by = args.by or ("policy" if args.format == "md" else None)
    if by:
        rows = group_events(events, by)
        if args.json:
            print(json.dumps({"by": by, "groups": rows, "events": len(events)}, indent=2))
        elif args.format == "md":
            print(render_groups_md(rows, by, args.since))
        else:
            print(_printable(render_groups_text(rows, by)))
        return 0

    summary = summarize(events)
    recorded = {str(e["policy_id"]) for e in summary}
    silent = [p for p in installed_policies(repo_root) if p not in recorded]
    if args.policy:
        silent = [p for p in silent if p == args.policy]

    if args.json:
        print(json.dumps({"summary": summary, "silent": silent, "events": len(events)}, indent=2))
    else:
        print(_printable(render_text(summary, silent)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
