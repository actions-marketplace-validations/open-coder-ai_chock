"""GAP-6b: `chock gateway run` refuses every tools/call while a `chock stop` reaches it, and logs it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_mcp_gateway_log import _SERVER, _call, _log

from chock.gateway.stop import initialize_roots, stop_client

_TIMEOUT = 30
_LIST = {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ("CHOCK_LOG_LEVEL", "CHOCK_GATE_LOG"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "repo"
    (root / ".chock" / "compiled").mkdir(parents=True)
    (root / ".git").mkdir()
    return root


def _stop(repo: Path, scope: str = "all") -> None:
    (repo / ".chock" / "stop.json").write_text(json.dumps({"scope": scope, "reason": "audit"}), encoding="utf-8")


def _run(repo: Path, requests: list, init_params: dict | None = None) -> list:
    """Drive the real entry point from a folder outside the repo: initialize, then one request per reply."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "chock.gateway", "run", "--repo", str(repo), "--", sys.executable, "-c", _SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=repo.parent,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    params = {"clientInfo": {"name": "claude-code"}, **(init_params or {})}
    replies = []
    for request in [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": params}, *requests]:
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        replies.append(json.loads(proc.stdout.readline()))
    proc.stdin.close()
    proc.wait(timeout=_TIMEOUT)
    proc.stdout.close()
    proc.stderr.close()
    return replies


def _stopped_lines(repo: Path) -> list[dict]:
    return [line for line in _log(repo) if line.get("reason") == "stopped"]


def test_a_stopped_call_is_refused_and_logged_but_initialize_and_tools_list_pass(repo):
    _stop(repo)
    init, listed, called = _run(repo, [_LIST, _call(1, "write_note", {"text": "hi"})])
    assert init["result"]["serverInfo"]["name"] == "notes"
    assert listed["result"]["echo"] == "tools/list"
    assert called["error"]["code"] == -32000
    assert "stopped: audit" in called["error"]["message"]
    [line] = _log(repo)
    assert (line["policy_id"], line["verdict"], line["reason"]) == ("chock-stop", "block", "stopped")
    assert line["target"] == "notes/write_note" and line["agent"] == "mcp-gateway"


def test_after_resume_the_call_is_forwarded(repo):
    _stop(repo)
    (repo / ".chock" / "stop.json").unlink()
    _init, called = _run(repo, [_call(1, "write_note", {"text": "hi"})])
    assert called["result"]["echo"] == "tools/call"
    assert not _stopped_lines(repo)


@pytest.mark.parametrize("content", ["{not json", json.dumps({"scope": "no such scope!"})])
def test_an_unreadable_stop_refuses(repo, content):
    (repo / ".chock" / "stop.json").write_text(content, encoding="utf-8")
    _init, called = _run(repo, [_call(1, "write_note", {"text": "hi"})])
    assert "error" in called
    assert len(_stopped_lines(repo)) == 1


def test_a_stop_file_that_cannot_be_opened_refuses(repo):
    (repo / ".chock" / "stop.json").mkdir()
    _init, called = _run(repo, [_call(1, "write_note", {"text": "hi"})])
    assert "error" in called
    assert len(_stopped_lines(repo)) == 1


def test_a_stop_scoped_to_another_client_allows(repo):
    _stop(repo, "codex_cli")
    _init, called = _run(repo, [_call(1, "write_note", {"text": "hi"})])
    assert called["result"]["echo"] == "tools/call"


def test_a_stop_scoped_to_this_client_refuses(repo):
    _stop(repo, "claude_code")
    _init, called = _run(repo, [_call(1, "write_note", {"text": "hi"})])
    assert "error" in called


def test_a_client_no_vendor_names_is_reached_by_a_scoped_stop(repo):
    _stop(repo, "codex_cli")
    _init, called = _run(repo, [_call(1, "t", {})], {"clientInfo": {"name": "Some Editor"}})
    assert "error" in called


def test_a_stop_in_a_root_initialize_names_refuses(repo, tmp_path):
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    (other / ".chock").mkdir()
    _stop(other)
    for params in ({"roots": [{"uri": other.as_uri()}]}, {"workspaceFolders": [{"uri": other.as_uri(), "name": "o"}]}):
        _init, called = _run(repo, [_call(1, "t", {})], params)
        assert "error" in called
    assert len(_stopped_lines(repo)) == 2


def test_stop_client_and_roots_parse():
    assert stop_client("claude-code") == "claude_code"
    assert stop_client("codex-mcp-client") == "codex"
    assert stop_client("Visual Studio Code") is None
    assert stop_client(5) is None
    assert initialize_roots({"roots": [{"uri": "file:///a%20b"}, "/c", {"uri": "https://x"}, 3]}) == ["/a b", "/c"]
    assert initialize_roots(None) == []


def test_a_stop_check_that_raises_refuses(monkeypatch, tmp_path):
    from chock.gateway import proxy

    def broken(*_args):
        raise OSError

    monkeypatch.setattr(proxy, "stop_refusal", broken)
    gw = proxy.Gateway(tmp_path, [])
    block, response = gw._screen(_call(1, "t", {}))
    assert block is True and response is not None and "could not be checked" in response
