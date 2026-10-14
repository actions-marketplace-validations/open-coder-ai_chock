"""Stdio JSON-RPC interceptor: one gateway process wraps one downstream MCP server."""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

from chock.gateway import decision
from chock.gateway.gates import FAULT, judge, load_gates, refusal
from chock.gateway.stop import STOP_ACTION, STOP_POLICY, initialize_roots, stop_client, stop_refusal

BLOCKED_CODE = -32000


def _blocked_response(request_id: Any, message: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": BLOCKED_CODE, "message": f"chock gateway refused this call: {message}"},
        }
    )


def _force_utf8(stream: Any) -> None:
    """Best-effort: pin a text stream to UTF-8 with replacement."""
    with contextlib.suppress(AttributeError, ValueError, OSError):
        stream.reconfigure(encoding="utf-8", errors="replace")


class Gateway:
    # Who is calling which server, for the log: the client's `initialize` and the server's answer to it.
    client: str | None = None
    server: str | None = None
    _init_id: Any = None
    # What a stop judges: the client as a stop scope names it, and the folders `initialize` names.
    stop_client: str | None = None
    roots: tuple[str, ...] = ()
    repo_root: Path | None = None

    def __init__(self, repo_root: Path, downstream_argv: list[str]) -> None:
        self.repo_root = Path(repo_root)
        self.gates = load_gates(self.repo_root)
        self.downstream_argv = downstream_argv
        self.process: subprocess.Popen[str] | None = None
        self._out_lock = threading.Lock()
        self._downstream_ended = threading.Event()

    def _write_out(self, line: str, stream: TextIO) -> None:
        with self._out_lock:
            stream.write(line if line.endswith("\n") else line + "\n")
            stream.flush()

    def start_downstream(self, *, pipe_output: bool = True) -> None:
        """Spawn the wrapped server. `pipe_output=False` is for tests that read the"""
        self.process = subprocess.Popen(  # noqa: S603 -- spawning the configured downstream MCP server is the feature
            self.downstream_argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if pipe_output:
            threading.Thread(target=self._pipe_downstream, daemon=True).start()

    def _pipe_downstream(self) -> None:
        assert self.process and self.process.stdout  # noqa: S101 -- start_downstream() always runs first
        for line in self.process.stdout:
            if self.server is None and self._init_id is not None:
                self._note_server(line)
            self._write_out(line, sys.stdout)
        self._downstream_ended.set()
        with contextlib.suppress(OSError, ValueError):
            sys.stdin.close()

    def _note_server(self, line: str) -> None:
        """Take the server's name from its answer to the client's `initialize`."""
        if '"serverInfo"' not in line:
            return
        with contextlib.suppress(ValueError, AttributeError, KeyError, TypeError):
            reply = json.loads(line)
            if isinstance(reply, dict) and reply.get("id") == self._init_id:
                self.server = str(reply["result"]["serverInfo"].get("name") or "") or None

    def _note_initialize(self, item: Any) -> None:
        if isinstance(item, dict) and item.get("method") == "initialize":
            params = item.get("params") if isinstance(item.get("params"), dict) else {}
            info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
            self.client = decision.client_name(info.get("name"))
            self.stop_client = stop_client(info.get("name"))
            self.roots = (*self.roots, *initialize_roots(params))  # a later initialize never drops a root
            self._init_id = item.get("id")

    def _stopped(self) -> list[tuple[str, str, str]]:
        """The repo stop's finding for a tools/call, before any gate; a check that cannot run refuses."""
        try:
            halted = stop_refusal(self.repo_root, list(self.roots), self.stop_client)
        except Exception as exc:  # noqa: BLE001 -- a stop that cannot be checked refuses the call, never allows it
            return [(STOP_POLICY, FAULT, f"chock stop could not be checked ({type(exc).__name__}); refusing")]
        return [(STOP_POLICY, STOP_ACTION, halted)] if halted else []

    def _judge(self, item: Any) -> tuple[list[tuple[str, str, str]], str] | None:
        """(findings, target) for a tools/call request; None for anything else."""
        self._note_initialize(item)
        if not isinstance(item, dict) or item.get("method") != "tools/call":
            return None
        params = item.get("params")
        if not isinstance(params, dict):
            message = "tools/call params is not an object; refusing (fail closed)"
            return [(decision.GATEWAY_POLICY, FAULT, message)], decision.target(self.server, None)
        halted = self._stopped()
        if halted:
            return halted, decision.target(self.server, params.get("name"))
        findings = judge(self.gates, str(params.get("name", "")), params.get("arguments"))
        return findings, decision.target(self.server, params.get("name"))

    def _screen(self, payload: Any) -> tuple[bool, str | None]:
        """(block?, response-to-write). A blocked notification blocks with no response."""
        block, response, _lines = self._decide(payload)
        return block, response

    def _decide(self, payload: Any) -> tuple[bool, str | None, list[dict[str, Any]]]:
        """`_screen`'s answer and the decision-log lines for it."""
        started = time.monotonic()
        items = payload if isinstance(payload, list) else [payload]
        judged = [(item, self._judge(item)) for item in items]
        messages = [refusal(j[0]) if j else None for _, j in judged]
        block = any(m is not None for m in messages)
        context = {"client": self.client, "started": started, "forwarded": not block}
        context["batch"] = block and isinstance(payload, list)
        lines = decision.lines_for([j for _, j in judged if j], context)
        if not block:
            return False, None, lines
        if not isinstance(payload, list):
            has_id = isinstance(payload, dict) and "id" in payload
            return True, (_blocked_response(payload.get("id"), messages[0]) if has_id else None), lines
        errors = []
        for (item, _), msg in zip(judged, messages, strict=True):
            if isinstance(item, dict) and "id" in item:
                reason = msg or "batch refused: another element in this batch was blocked (fail closed)"
                errors.append(json.loads(_blocked_response(item.get("id"), reason)))
        return True, (json.dumps(errors) if errors else None), lines

    def handle_line(self, line: str, out: TextIO) -> bool:
        """Evaluate one client line. Returns True when it was forwarded downstream."""
        lines: list[dict[str, Any]] = []
        try:
            return self._act(line, out, lines)
        finally:
            decision.write(self.repo_root, lines)  # after the verdict is carried out: logging never changes it

    def _act(self, line: str, out: TextIO, lines: list[dict[str, Any]]) -> bool:
        stripped = line.strip()
        if stripped:
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                block, response, lines[:] = self._decide(payload)
                if block:
                    if response is not None:
                        self._write_out(response, out)
                    return False
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(line if line.endswith("\n") else line + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                self._downstream_ended.set()
                return False
        return True

    def serve(self) -> int:
        _force_utf8(sys.stdin)
        _force_utf8(sys.stdout)
        self.start_downstream()
        try:
            for line in sys.stdin:
                if self._downstream_ended.is_set():
                    break
                self.handle_line(line, sys.stdout)
        except (KeyboardInterrupt, BrokenPipeError, OSError, ValueError):
            pass
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        if self.process is not None:
            try:
                return self.process.wait(timeout=5) or 0
            except subprocess.TimeoutExpired:
                self.process.kill()
                return 1
        return 0
