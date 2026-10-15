"""GAP-6: `chock gateway run` writes one decision-log line per allowed call and per refusing policy."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from test_mcp_gateway_proxy import _FAKE_AWS_KEY

_TIMEOUT = 30

# Answers `initialize` with its serverInfo and echoes every other method, so a forwarded call is visible.
_SERVER = textwrap.dedent(
    """
    import json, sys
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("method") == "initialize":
            result = {"serverInfo": {"name": "notes", "version": "1"}}
        else:
            result = {"echo": req.get("method")}
        print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": result}), flush=True)
    """
)


def _gate(repo: Path, policy: str, spec: dict) -> None:
    folder = repo / ".chock" / "compiled" / policy / "mcp-gateway"
    folder.mkdir(parents=True)
    (folder / "gateway-gate.json").write_text(json.dumps(spec), encoding="utf-8")


def _regex_gate(repo: Path, policy: str, pattern: str = r"AKIA[A-Z0-9]{16}", action: str = "block") -> None:
    _gate(repo, policy, {"kind": "content_regex", "action": action, "params": {"content_pattern": pattern}})


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ("CHOCK_LOG_LEVEL", "CHOCK_GATE_LOG"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "repo"
    (root / ".chock" / "compiled").mkdir(parents=True)
    return root


def _call(request_id: int, tool: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


def _run(repo: Path, requests: list) -> list:
    """Drive the real entry point: initialize, wait for the server's answer, then one request per reply."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "chock.gateway", "run", "--repo", str(repo), "--", sys.executable, "-c", _SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin and proc.stdout
    replies = []
    init = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"clientInfo": {"name": "Claude Code"}}}
    for request in [init, *requests]:
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        replies.append(json.loads(proc.stdout.readline()))
    proc.stdin.close()
    proc.wait(timeout=_TIMEOUT)
    proc.stdout.close()
    assert proc.stderr
    proc.stderr.close()
    return replies[1:]


def _log_path(repo: Path) -> Path:
    return repo / ".chock" / "log" / "gate-events.jsonl"


def _log(repo: Path) -> list[dict]:
    return [json.loads(line) for line in _log_path(repo).read_text(encoding="utf-8").splitlines()]


def test_an_allowed_call_writes_one_info_line_with_no_policy(repo):
    _regex_gate(repo, "no-secrets")
    [reply] = _run(repo, [_call(1, "write_note", {"text": "hello"})])
    assert reply["result"]["echo"] == "tools/call"
    [line] = _log(repo)
    assert (line["verdict"], line["level"], line["reason"]) == ("allow", "info", "no-rule")
    assert "policy_id" not in line and "call" not in line
    assert line["target"] == "notes/write_note"
    assert line["actor"] == "agent:claudecode" and line["client"] == "claudecode"
    assert (line["route"], line["agent"], line["surface"], line["event"]) == (
        "sync",
        "mcp-gateway",
        "mcp-gateway",
        "tool_use",
    )
    assert line["can_ask"] is False and isinstance(line["duration_ms"], int)
    if os.name != "nt":
        assert stat.S_IMODE(_log_path(repo).stat().st_mode) == 0o600


def test_a_refusal_writes_one_line_per_refusing_policy(repo):
    _regex_gate(repo, "no-secrets")
    _regex_gate(repo, "no-aws-keys")
    _regex_gate(repo, "quiet", pattern="^never$")
    [reply] = _run(repo, [_call(1, "write_note", {"text": _FAKE_AWS_KEY})])
    assert reply["error"]["code"] == -32000
    lines = _log(repo)
    assert sorted(line["policy_id"] for line in lines) == ["no-aws-keys", "no-secrets"]
    assert {(line["verdict"], line["reason"], line["level"]) for line in lines} == {("block", "gate-block", "info")}
    assert {line["target"] for line in lines} == {"notes/write_note"}


def test_an_ask_is_refused_and_logged_as_a_block(repo):
    _regex_gate(repo, "asks", pattern="deploy", action="ask")
    [reply] = _run(repo, [_call(1, "run", {"cmd": "deploy"})])
    assert "error" in reply
    [line] = _log(repo)
    assert (line["policy_id"], line["verdict"], line["reason"]) == ("asks", "block", "gate-ask")


def test_a_gate_that_errors_fails_closed_and_logs_a_fault(repo):
    _regex_gate(repo, "broken", pattern="(")  # not a regex: the gate cannot run
    garbled = repo / ".chock" / "compiled" / "garbled" / "mcp-gateway"
    garbled.mkdir(parents=True)
    (garbled / "gateway-gate.json").write_text("{", encoding="utf-8")
    bad_params = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": 5}
    replies = _run(repo, [_call(1, "write_note", {"text": "hello"}), bad_params])
    assert all(reply["error"]["code"] == -32000 for reply in replies)
    lines = _log(repo)
    assert {(line["policy_id"], line["verdict"], line["reason"]) for line in lines} == {
        ("broken", "block", "fault"),
        ("garbled", "block", "fault"),
        ("mcp-gateway", "block", "fault"),
    }
    assert [line["target"] for line in lines if line["policy_id"] == "mcp-gateway"] == ["notes/-"]


def test_a_log_that_cannot_be_written_changes_no_verdict(repo):
    _regex_gate(repo, "no-secrets")
    (repo / ".chock" / "log").write_text("not a folder", encoding="utf-8")
    refused, allowed = _run(repo, [_call(1, "w", {"text": _FAKE_AWS_KEY}), _call(2, "w", {"text": "hello"})])
    assert refused["error"]["code"] == -32000 and "no-secrets" in refused["error"]["message"]
    assert allowed["result"]["echo"] == "tools/call"
    assert (repo / ".chock" / "log").read_text(encoding="utf-8") == "not a folder"


def test_a_secret_in_the_arguments_never_reaches_the_log(repo):
    _regex_gate(repo, "no-secrets")
    _regex_gate(repo, "warns", pattern="(?i)akia", action="warn")
    _run(
        repo,
        [
            _call(1, "write_note", {"text": _FAKE_AWS_KEY}),  # refused
            _call(2, "write_note", {"nested": [{"key": _FAKE_AWS_KEY.lower()}]}),  # warned, then allowed
            _call(3, f"leak_{_FAKE_AWS_KEY}", {"text": "hi"}),  # a secret in the tool name is redacted
        ],
    )
    text = _log_path(repo).read_text(encoding="utf-8")
    assert _FAKE_AWS_KEY not in text and _FAKE_AWS_KEY.lower() not in text
    lines = _log(repo)
    assert [(line["verdict"], line.get("policy_id")) for line in lines] == [
        ("block", "no-secrets"),
        ("warn", "warns"),
        ("warn", "warns"),
        ("allow", None),
        ("allow", None),
    ]
    assert lines[-1]["target"] == "notes/leak_[redacted]"


def test_a_batch_logs_the_sibling_it_refused(repo):
    _regex_gate(repo, "no-secrets")
    [reply] = _run(repo, [[_call(1, "a", {"text": _FAKE_AWS_KEY}), _call(2, "b", {"text": "ok"})]])
    assert {r["id"] for r in reply} == {1, 2}
    assert {(line["target"], line["policy_id"], line["reason"]) for line in _log(repo)} == {
        ("notes/a", "no-secrets", "gate-block"),
        ("notes/b", "mcp-gateway", "batch"),
    }


def test_the_target_is_capped_at_128_characters(repo):
    _run(repo, [_call(1, "t" * 300, {})])
    [line] = _log(repo)
    assert len(line["target"]) == 128 and line["target"].startswith("notes/ttt")
