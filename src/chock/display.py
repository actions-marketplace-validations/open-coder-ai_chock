"""Inert text for a person to read: a logged or agent-derived string can move no cursor, colour, link or fake a line.

Only what is shown changes; the log and every machine format keep the value as it was.
"""

from __future__ import annotations

import unicodedata
from typing import Any

#: Control (C0, DEL, C1), surrogate, line/paragraph separator and format (bidi, invisible) characters.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cs", "Zl", "Zp", "Cf"})
#: Format characters that ordinary text needs: ZWNJ and ZWJ join Persian, Indic and emoji sequences.
_KEPT = frozenset({"‌", "‍"})
_NAMED = {"\t": "\\t", "\n": "\\n", "\r": "\\r"}


def _shown(char: str) -> str:
    if char in _KEPT or unicodedata.category(char) not in _UNSAFE_CATEGORIES:
        return char
    code = ord(char)
    if char in _NAMED:
        return _NAMED[char]
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}" if code < 0x10000 else f"\\U{code:08x}"  # noqa: PLR2004


def inert(value: object) -> str:
    """`value` as one line of text, each unsafe character written as a visible escape (ESC as `\\x1b`)."""
    text = str(value)
    return text if text.isprintable() else "".join(map(_shown, text))


def inert_all(value: Any) -> Any:
    """`value` with every string in it, dict keys included, made `inert`."""
    if isinstance(value, dict):
        return {inert_all(key): inert_all(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(inert_all(item) for item in value)
    return inert(value) if isinstance(value, str) else value
