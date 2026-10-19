"""RT-SPLIT: every entry loads the pinned shared runtime beside it; anything else refuses, never allows.

Each fault is put on a shipped bundle's `scripts/_chock_runtime.py`, and every hook the bundle
wires is run the way its client runs it: guards, gates, the stop check and Stop.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import client_payloads
import pytest
import yaml
from bundle_fixtures import BUNDLE_ID, bundle, hook_commands, make_members, project
from conftest import baseline_policy
from test_fail_closed_payloads import DENIES, _body, _payload, _run
from test_unreadable_stop import STOP_REFUSALS, _clean_stop

from chock.gate import runtime_bundle
from chock.gate.write_gate import STOP_FLAG
from chock.hooks.runtime_vendor import prune_shared_runtime, vendor_runtime
from chock.hooks.stop_check import STOP_CHECK_FLAG
from chock.plugin.bundle_build import CLIENTS, merged_files

SHARED = runtime_bundle.SHARED_FILE
#: A gate's Stop refusal: Cursor's is `followup_message`, as any gate's (test_stop_reentry_wire); exit 2 elsewhere too.
STOP_REFUSES = {**STOP_REFUSALS, "cursor": lambda p: p.returncode == 2 or "followup_message" in _body(p)}


def _rewrite(path: Path, change) -> None:
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")


def _unreadable(path: Path) -> None:
    path.unlink()
    path.mkdir()  # chmod 000 stops no root; a folder in its place is unreadable to everyone


#: How the shared runtime can be wrong. Each must refuse every hook, in the client's own grammar.
FAULTS = {
    "missing": lambda path: path.unlink(),
    "unreadable": _unreadable,
    "edited-one-byte": lambda path: _rewrite(path, lambda t: t + "# edited\n"),
    "crlf-and-edited": lambda path: path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n") + b"# edited\r\n"),
    "edited-and-declaring-the-old-digest": lambda path: _rewrite(
        path, lambda t: t + f"CHOCK_RUNTIME_DIGEST = {runtime_bundle.shared_pin()!r}\n"
    ),
    "import-error": lambda path: _rewrite(path, lambda t: "raise ImportError('broken')\n" + t),
    "syntax-error": lambda path: _rewrite(path, lambda t: t + "\ndef (\n"),
    "not-utf8": lambda path: path.write_bytes(b"\xff\xfe" + path.read_bytes()),
    "exits-clean": lambda path: _rewrite(path, lambda t: "raise SystemExit(0)\n" + t),
}


@pytest.fixture(params=sorted(CLIENTS))
def installed(request, tmp_path: Path) -> tuple[str, Path, Path]:
    client = request.param
    files = merged_files(client, bundle(members := make_members(tmp_path)), members, tmp_path)
    package = client_payloads.write_resolved(tmp_path / "dist" / client / BUNDLE_ID, files)
    return client, package, project(tmp_path)


def _judging(package: Path) -> list[tuple[str, bool]]:
    """(command, whether it serves Stop) for every hook that judges: all but the session-start heartbeat."""
    commands = hook_commands(json.loads(next(package.rglob("hooks.json")).read_text(encoding="utf-8")))
    judging = [c for c in commands if re.search(r" --(?:guard|gate) ", c) or STOP_CHECK_FLAG in c]
    return [(c, c.endswith(f" {STOP_FLAG}")) for c in judging]


def _verdicts(client: str, package: Path, repo: Path, payload: str | None = None) -> list[tuple[str, object, bool]]:
    """(command, process, whether it refused) per judging hook, on an ordinary payload unless one is given."""
    found = []
    for command, stop in _judging(package):
        given = payload if payload is not None else _clean_stop(client, repo) if stop else _payload(client, repo, "ls")
        done = _run(command, repo, given, package)
        refused = STOP_REFUSES[client] if stop else DENIES[CLIENTS[client].agent]
        found.append((command, done, refused(done)))
    assert found, f"{client}: no judging hook"
    return found


def test_every_bundle_ships_the_pinned_shared_runtime_beside_its_entry(installed) -> None:
    client, package, _repo = installed
    entry = package / "scripts" / f"{CLIENTS[client].agent}.py"
    assert entry.with_name(SHARED).read_text(encoding="utf-8") == runtime_bundle.render_shared()
    assert f"_CHOCK_RUNTIME_PIN = {runtime_bundle.shared_pin()!r}\n" in entry.read_text(encoding="utf-8")


def test_the_pin_is_the_sha256_of_the_shared_runtime_s_bytes() -> None:
    text = runtime_bundle.render_shared()
    assert runtime_bundle.shared_pin() == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert "CHOCK_RUNTIME_DIGEST" not in text
    assert not re.search(r"^\s*(?:import|from)\s+(?:chock|agentseam)\b", text, re.MULTILINE)


def test_an_intact_bundle_still_allows_an_ordinary_call(installed) -> None:
    client, package, repo = installed
    for command, done, refused in _verdicts(client, package, repo):
        assert not refused and done.returncode == 0, (client, command, done.stdout, done.stderr)


def test_a_crlf_copy_of_the_shared_runtime_still_loads(installed) -> None:
    """A Windows checkout or text-mode write turns LF into CRLF; the pin is over the LF text, so it must still match."""
    client, package, repo = installed
    path = package / "scripts" / SHARED
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    for command, done, refused in _verdicts(client, package, repo):
        assert not refused and done.returncode == 0, (client, command, done.stdout, done.stderr)


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_a_bad_shared_runtime_refuses_every_hook_and_says_why(installed, fault: str) -> None:
    client, package, repo = installed
    FAULTS[fault](package / "scripts" / SHARED)
    for command, done, refused in _verdicts(client, package, repo):
        assert refused, (client, fault, command, done.returncode, done.stdout, done.stderr)
        assert SHARED in done.stderr and "refusing every call" in done.stderr, (client, fault, done.stderr)


def test_a_missing_shared_runtime_refuses_an_unreadable_payload_in_the_event_s_grammar(installed) -> None:
    client, package, repo = installed
    (package / "scripts" / SHARED).unlink()
    for command, done, refused in _verdicts(client, package, repo, payload="not json"):
        assert refused and SHARED in done.stderr, (client, command, done.returncode, done.stdout, done.stderr)


def test_a_matching_copy_outside_the_entry_s_folder_is_never_loaded(installed, tmp_path: Path, monkeypatch) -> None:
    """The loader reads only its own folder: not the cwd, not PYTHONPATH, whatever that copy's pin says."""
    client, package, repo = installed
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for folder in (repo, elsewhere):
        shutil.copy(package / "scripts" / SHARED, folder / SHARED)
    (package / "scripts" / SHARED).unlink()
    monkeypatch.setenv("PYTHONPATH", str(elsewhere))
    for command, done, refused in _verdicts(client, package, repo):
        assert refused and SHARED in done.stderr, (client, command, done.stdout, done.stderr)


#: The sync route's copy. The plugin roots (`~/.chock/marketplace/...`, `~/.cursor/plugins/local/...`) are pinned in
#: chock-catalog's protect-agent-config suite (tc-1512..tc-1520): this repo's installed copy predates its folder rules.
SYNC_SHARED = f".chock/bin/{SHARED}"
SHELL_WRITES = [
    f"rm {SYNC_SHARED}",
    f"echo x > {SYNC_SHARED}",
    f"cp evil.py {SYNC_SHARED}",
    f"sed -i s/a/b/ {SYNC_SHARED}",
]


def _guard(command: str) -> int:
    guard = baseline_policy("protect-agent-config") / "implementations" / "protect-agent-config.py"
    env = {**os.environ, "CHOCK_RAW_COMMAND": command}
    return subprocess.run([sys.executable, str(guard)], env=env, capture_output=True, check=False).returncode


@pytest.mark.parametrize("command", SHELL_WRITES)
def test_protect_agent_config_refuses_a_shell_write_to_the_sync_route_shared_runtime(command: str) -> None:
    assert _guard(command) == 1, command


def test_protect_agent_config_lets_a_read_of_it_through_and_its_gate_refuses_an_edit() -> None:
    assert _guard(f"cat {SYNC_SHARED}") == 0
    manifest = yaml.safe_load((baseline_policy("protect-agent-config") / "manifest.yaml").read_text(encoding="utf-8"))
    pattern = manifest["hook"]["gate"]["params"]["forbidden_path_regex"]
    assert re.search(pattern, SYNC_SHARED) and re.search(pattern, SYNC_SHARED.replace("/", "\\"))


def test_sync_keeps_the_shared_runtime_while_an_entry_loads_it_and_drops_it_after(tmp_path: Path) -> None:
    bin_dir = tmp_path / ".chock" / "bin"
    vendor_runtime(tmp_path, "claude_code")
    assert (bin_dir / SHARED).read_text(encoding="utf-8") == runtime_bundle.render_shared()
    prune_shared_runtime(tmp_path)
    assert (bin_dir / SHARED).exists()
    (bin_dir / "claude_code.py").unlink()
    prune_shared_runtime(tmp_path)
    assert not (bin_dir / SHARED).exists()
