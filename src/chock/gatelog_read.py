"""Read the decision log on both routes: which files, which records, the filters, and following it live."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

from chock.gate.runner import journal

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
