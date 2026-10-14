"""Run a rendered runtime the way a client does, on the sync route or as a plugin, and read what it logged."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from conftest import init_repo

from chock.gate import runtime_bundle
from chock.gate.runner import journal

AGENT = "claude_code"
POLICY = "p-log"
BLOCKING_GUARD = '#!/usr/bin/env bash\necho "refused here" >&2\nexit 1\n'
ASKING_GUARD = '#!/usr/bin/env bash\necho "confirm the target" >&2\nexit 3\n'
CLEAN_GUARD = "#!/usr/bin/env bash\nexit 0\n"
PLUGIN_VERSION = "1.2.3"
#: Every variable that sets a level; a test names the one it means.
LEVEL_VARS = ("CHOCK_LOG_LEVEL", "CHOCK_GATE_LOG")


def sync_layout(tmp: Path, guard_body: str) -> tuple[Path, Path, Path]:
    """(repo, runtime, guard): the runtime under `.chock/bin/`, the guard where `chock sync` points its hook."""
    repo = tmp / "repo"
    repo.mkdir()
    init_repo(repo)
    runtime = repo / ".chock" / "bin" / f"{AGENT}.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(runtime_bundle.render(AGENT), encoding="utf-8")
    guard = repo / ".agents" / "policies" / POLICY / "implementations" / "guard.sh"
    guard.parent.mkdir(parents=True)
    guard.write_text(guard_body, encoding="utf-8", newline="\n")
    return repo, runtime, guard


def plugin_layout(tmp: Path, guard_body: str) -> tuple[Path, Path, Path]:
    """(repo, runtime, guard): a Claude-format package outside any repository, and a repository to work in."""
    repo = tmp / "repo"
    repo.mkdir()
    init_repo(repo)
    root = tmp / "plugins" / POLICY
    runtime = root / "scripts" / f"{AGENT}.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(runtime_bundle.render(AGENT), encoding="utf-8")
    manifest = root / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": POLICY, "version": PLUGIN_VERSION}), encoding="utf-8")
    guard = root / "scripts" / f"{POLICY}.sh"
    guard.write_text(guard_body, encoding="utf-8", newline="\n")
    return repo, runtime, guard


def payload(repo: Path, command: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "session_id": "s",
            "cwd": str(repo),
        }
    )


def hook_env(home: Path, **levels: str) -> dict[str, str]:
    """The client's environment for the hook: a private home, and only the level variables named."""
    env = {k: v for k, v in os.environ.items() if k not in LEVEL_VARS}
    env.update({"HOME": str(home), "USERPROFILE": str(home), **levels})
    return env


def run_hook(repo: Path, runtime: Path, guard: Path, command: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(runtime), "--guard", str(guard)],
        input=payload(repo, command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=repo,
        env=env,
        timeout=60,
        check=False,
    )


def sync_log(repo: Path) -> Path:
    return repo / ".chock" / "log" / "gate-events.jsonl"


def plugin_log(home: Path) -> Path:
    return home / ".chock" / "log" / AGENT / "events.jsonl"


def settle(path: Path) -> None:
    """Write every tool call still held beside `path`, as the settle window passing would."""
    claims = path.parent / journal.LOG_CLAIMS
    if claims.is_dir():
        past = time.time() - journal.LOG_SETTLE_SECONDS - 1
        for claim in claims.iterdir():
            os.utime(claim, (past, past))
        journal.log_settle(path)


def raw_records(path: Path) -> list[dict]:
    """The lines written so far, held calls left held."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def records(path: Path) -> list[dict]:
    settle(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def settings(folder: Path, **values: object) -> Path:
    """Write one scope's `.chock/chock-log.json` under `folder` (a repository or a home)."""
    path = folder / ".chock" / "chock-log.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values), encoding="utf-8")
    return path
