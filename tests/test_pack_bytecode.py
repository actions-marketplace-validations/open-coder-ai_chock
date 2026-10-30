"""Bytecode is a build artifact: a pack that ships it is refused, and running a policy's script never writes it."""

from __future__ import annotations

import io
import shutil
import sys
import types
from pathlib import Path

import pytest

from chock.gate import budget, guard_runner, tool_call_gate
from chock.gate.runner import cli
from chock.gate.runner.script import _spawn
from chock.lock import build_lock, pack_bytecode, verify_lock, write_lock
from chock.scaffold.add import IntegrityError, add

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
ID = "demo-pack"
ENV_PROBE = "import os, sys\nsys.exit(0 if os.environ.get('PYTHONDONTWRITEBYTECODE') == '1' else 1)\n"


def _pack(root: Path) -> Path:
    pack = root / ID
    pack.mkdir(parents=True)
    (pack / "manifest.yaml").write_text(f"id: {ID}\n", encoding="utf-8")
    return pack


def _ship_bytecode(pack: Path) -> None:
    (pack / "__pycache__").mkdir()
    (pack / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\x00")
    (pack / "stray.pyo").write_bytes(b"\x00")


def test_bytecode_is_named_by_its_path(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    assert pack_bytecode(pack) == []
    _ship_bytecode(pack)
    assert pack_bytecode(pack) == ["__pycache__/x.cpython-312.pyc", "stray.pyo"]


def test_verify_refuses_an_installed_pack_that_ships_bytecode(tmp_path: Path) -> None:
    _pack(tmp_path / ".agents" / "policies")
    write_lock(build_lock(tmp_path), tmp_path)
    assert verify_lock(tmp_path)[1] == []

    _ship_bytecode(tmp_path / ".agents" / "policies" / ID)
    ok, failures = verify_lock(tmp_path)
    assert not ok
    assert any("ships build artifact __pycache__/x.cpython-312.pyc" in f for f in failures), failures
    assert any("ships build artifact stray.pyo" in f for f in failures), failures


def test_add_refuses_a_catalog_pack_that_ships_bytecode(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    _ship_bytecode(_pack(catalog / "base"))
    repo = tmp_path / "repo"
    (repo / ".agents" / "policies").mkdir(parents=True)

    with pytest.raises(IntegrityError, match=r"build artifact.*__pycache__/x\.cpython-312\.pyc.*stray\.pyo"):
        add(repo, ID, str(catalog), None, force=False)
    assert not (repo / ".agents" / "policies" / ID).exists()


def test_every_way_a_script_is_launched_asks_python_not_to_write_bytecode(tmp_path: Path) -> None:
    assert guard_runner.interpreter_env(sys.executable)["PYTHONDONTWRITEBYTECODE"] == "1"

    probe = tmp_path / "probe.py"
    probe.write_text(ENV_PROBE, encoding="utf-8")
    ctx = types.SimpleNamespace(repo_root=tmp_path)
    assert _spawn(probe, ctx, {}, 30).returncode == 0

    verdict = tool_call_gate._tool_call_script({"params": {"script": probe.name}}, tmp_path, {})
    assert verdict is None, verdict
    assert budget.BYTECODE_OFF == {"PYTHONDONTWRITEBYTECODE": "1"}


def test_a_hook_payload_that_is_not_utf8_exits_2_at_an_agent_event(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"writes": {"a": "\xff\xfe"}}')))
    assert cli.main(["run", "--gate", "gate.json", "--event", "pre-tool-use"]) == 2
    assert "not UTF-8" in capsys.readouterr().err
