"""A person's `chock resume` in process: stdin and stdout read as a terminal and the repository's name is typed."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest import mock

from chock import stop as chock_stop


class _TtyIn(io.StringIO):
    def isatty(self) -> bool:
        return True


class _TtyOut:
    """The real stdout (capsys still reads it), reporting itself a terminal."""

    def __init__(self, stream) -> None:
        self._stream = stream

    def isatty(self) -> bool:
        return True

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def person_resume(repo: Path, typed: str | None = None) -> int:
    """`chock resume --repo <repo>` as a person at a terminal who types `typed` (default: the repository's name)."""
    name = Path(repo).resolve().name if typed is None else typed
    with mock.patch.object(sys, "stdin", _TtyIn(name + "\n")), mock.patch.object(sys, "stdout", _TtyOut(sys.stdout)):
        return chock_stop.resume_main(["--repo", str(repo)])
