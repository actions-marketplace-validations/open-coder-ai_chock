"""The files an `apply_patch` call (Codex, Copilot CLI) would leave behind, for a gate that judges whole files.

Codex CLI writes files with one tool, apply_patch, whose only argument is the patch text in
`tool_input.command`: no path, no content. Copilot CLI's apply_patch hands the same grammar to
a Claude-format hook as the bare `tool_input` string (or under `input`/`patch`). The write gate therefore had nothing to judge before
the write, and Codex was checked only at the turn's end. The patch format is Codex's own,
documented grammar::

    *** Begin Patch
    *** Add File: <path>          lines follow, each prefixed "+"
    *** Delete File: <path>
    *** Update File: <path>
    *** Move to: <new path>       optional
    @@ <optional anchor line>
     context / -removed / +added  lines of one hunk
    *** End of File               optional: the hunk ends the file
    *** End Patch

The patch is read by Codex's own state machine (codex-rs apply-patch: streaming_parser.rs),
so a marker is a marker only where Codex reads one; a patch Codex would not parse raises
ValueError, which refuses the call. Each added or updated file is rebuilt as Codex would
leave it (file_update.rs, seek_sequence.rs, text_file.rs), from the file on disk as earlier
operations in the same call leave it, with paths taken from the agent's working directory.
A hunk that cannot be placed leaves that file out, as the call itself would fail; the turn's
end judges whatever lands. Extracted into the vendored runtime, so stdlib-only.
"""

from __future__ import annotations

import os
from pathlib import Path

_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_ADD = "*** Add File: "
_DELETE = "*** Delete File: "
_UPDATE = "*** Update File: "
_MOVE = "*** Move to: "
_EOF = "*** End of File"
_ENVIRONMENT = "*** Environment ID:"
_HUNK = "@@"
_HUNK_ANCHOR = "@@ "
_OPS = (("add", _ADD), ("delete", _DELETE), ("update", _UPDATE))
#: Where the patch sits in `tool_input`: Codex's `command`; Copilot CLI's `input` or `patch`, else the bare string.
_PATCH_KEYS = ("command", "input", "patch")
#: Rust's char::is_whitespace, which Codex's trim() uses; str.strip() would also strip \x1c-\x1f.
_PATCH_SPACE = "\t\n\x0b\x0c\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
#: seek_sequence's last pass: typographic punctuation and odd spaces read as their ASCII form.
_PATCH_ASCII = str.maketrans(
    dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-")
    | dict.fromkeys("\u2018\u2019\u201a\u201b", "'")
    | dict.fromkeys("\u201c\u201d\u201e\u201f", '"')
    | dict.fromkeys("\xa0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000", " ")
)
_PATCH_ENDINGS = ("\r\n", "\r", "\n")


def patch_text(event):
    """The text an apply_patch call carries, from its first Begin marker on; None when it has none."""
    raw = getattr(event, "raw", None)
    tool_input = raw.get("tool_input") if isinstance(raw, dict) else None
    command = tool_input if isinstance(tool_input, str) else None
    for key in _PATCH_KEYS if isinstance(tool_input, dict) else ():
        if tool_input.get(key) is not None:
            command = tool_input[key]
            break
    if isinstance(command, list):
        command = "\n".join(part for part in command if isinstance(part, str))
    start = command.find(_BEGIN) if isinstance(command, str) else -1
    return command[start:] if start >= 0 else None


def _patch_refuse(number, line, why):
    message = f"the apply_patch text does not parse at line {number} ({line[:80]!r}): {why}"
    raise ValueError(message)


def _patch_header(state, text):
    """Open a file operation or end the patch when `text` is a header; False when it is not one."""
    if text == _END:
        _patch_not_empty(state, text)
        state["mode"] = "ended"
        return True
    for op, marker in _OPS:
        if text.startswith(marker):
            _patch_not_empty(state, text)
            state["ops"].append({"op": op, "path": text[len(marker) :], "move": None, "body": []})
            state["mode"] = op
            return True
    return False


def _patch_not_empty(state, text):
    """Codex's ensure_update_hunk_is_not_empty: an update with no hunk, or an empty last hunk, refuses."""
    last = state["ops"][-1] if state["ops"] else None
    if last is None or last["op"] != "update":
        return
    if not last["body"] and state["mode"] == "update":
        _patch_refuse(state["number"], text, f"update of {last['path']!r} has no hunk")
    if last["body"] and not (last["body"][-1]["old"] or last["body"][-1]["new"]):
        _patch_refuse(state["number"], text, "a hunk has no lines")


def _patch_chunk(op, context=None):
    chunk = {"context": context, "old": [], "new": [], "pairs": [], "eof": False, "added": []}
    op["body"].append(chunk)
    return chunk


def _patch_hunk_marker(state, op, text):
    """An `@@` or `*** End of File` line in an update; False when `text` is neither."""
    chunks = op["body"]
    anchored = text == _HUNK or text.startswith(_HUNK_ANCHOR)
    if anchored and chunks and not (chunks[-1]["old"] or chunks[-1]["new"]):
        _patch_refuse(state["number"], text, "a hunk has no lines")
    if anchored:
        _patch_chunk(op, text[len(_HUNK_ANCHOR) :] if text != _HUNK else None)
        return True
    if text != _EOF:
        return False
    if chunks and not (chunks[-1]["old"] or chunks[-1]["new"]):
        _patch_refuse(state["number"], text, "a hunk has no lines")
    if chunks:
        chunks[-1]["eof"] = True
    return True


def _patch_change(op, line):
    """A context, added or removed line of an update; False when `line` is none of those."""
    kind = line[:1] if line else " "
    if kind not in (" ", "+", "-"):
        return False
    chunk = op["body"][-1] if op["body"] else _patch_chunk(op)
    text = line[1:]
    if kind == " ":
        chunk["pairs"].append((len(chunk["old"]), len(chunk["new"])))
    if kind != "+":
        chunk["old"].append(text)
    if kind != "-":
        chunk["new"].append(text)
    if kind == "+":
        chunk["added"].append(text)
    return True


def _patch_update_line(state, op, line):
    """One line of an update, read as Codex's UpdateFile mode reads it."""
    text = line.rstrip(_PATCH_SPACE)
    if _patch_header(state, text):
        return
    if op["body"] and op["body"][-1]["eof"]:
        if not text:
            return
        if text != _HUNK and not text.startswith(_HUNK_ANCHOR):
            _patch_refuse(state["number"], line, "expected an @@ hunk after End of File")
    if not op["body"] and op["move"] is None and text.startswith(_MOVE):
        op["move"] = text[len(_MOVE) :]
        return
    if not (_patch_hunk_marker(state, op, text) or _patch_change(op, line)):
        _patch_refuse(state["number"], line, "an update line must start with ' ', '+', '-' or @@")


def _patch_line(state, line):
    """Feed one patch line to the state machine."""
    mode = state["mode"]
    trimmed = line.strip(_PATCH_SPACE)
    if mode == "update":
        _patch_update_line(state, state["ops"][-1], line)
    elif mode == "begun" and trimmed.startswith(_ENVIRONMENT) and trimmed[len(_ENVIRONMENT) :].strip(_PATCH_SPACE):
        state["mode"] = "begun:env"
    elif _patch_header(state, trimmed):
        pass
    elif mode == "add" and line.startswith("+"):
        state["ops"][-1]["body"].append(line[1:])
    else:
        _patch_refuse(state["number"], line, "not a file header (Add File, Delete File, Update File)")


def _patch_lines(text):
    """`text` split on "\\n" as Codex splits it: str::lines, then its parser, each drop one trailing "\\r"."""
    lines = text.split("\n")
    if lines and not lines[-1]:
        lines.pop()
    return [line.removesuffix("\r").removesuffix("\r") for line in lines]


def _patch_one(lines, start, operations):
    """Read the patch whose Begin line is `lines[start]` into `operations`; the index after its End."""
    if lines[start].strip(_PATCH_SPACE) != _BEGIN:
        _patch_refuse(start + 1, lines[start], "the Begin marker must stand alone on its line")
    state = {"mode": "begun", "ops": operations, "number": start + 1}
    final = next((i for i in range(len(lines) - 1, start, -1) if lines[i].strip(_PATCH_SPACE)), None)
    for index in range(start + 1, len(lines)):
        state["number"] = index + 1
        line = lines[index]
        if index == final and line.strip(_PATCH_SPACE) == _END:
            _patch_not_empty(state, _END)
            return index + 1
        _patch_line(state, line)
        if state["mode"] == "ended":
            return index + 1
    return _patch_refuse(len(lines), lines[-1], "the patch has no End marker")


def parse_patch(patch):
    """[(op, path, moved_to, body)] for every patch in `patch`; ValueError when Codex would not parse one.

    op is add/delete/update; an add's body is its lines, an update's its hunks (dicts: context, old,
    new, pairs, eof, added).
    """
    lines = _patch_lines(patch)
    operations = []
    index = 0
    while index < len(lines):
        if _BEGIN in lines[index]:
            lines[index] = lines[index][lines[index].index(_BEGIN) :]
            index = _patch_one(lines, index, operations)
        else:
            index += 1
    return [(op["op"], op["path"], op["move"], op["body"]) for op in operations]


def _patch_match(lines, pattern, start, same):
    for index in range(start, len(lines) - len(pattern) + 1):
        if all(same(lines[index + i]) == same(want) for i, want in enumerate(pattern)):
            return index
    return None


def _seek(lines, pattern, start, *, eof):
    """Codex's seek_sequence: exact, then ignoring trailing space, then both ends, then ASCII punctuation."""
    if not pattern:
        return start
    if len(pattern) > len(lines):
        return None
    begin = max(len(lines) - len(pattern), start) if eof else start
    for same in (
        lambda s: s,
        lambda s: s.rstrip(_PATCH_SPACE),
        lambda s: s.strip(_PATCH_SPACE),
        lambda s: s.strip(_PATCH_SPACE).translate(_PATCH_ASCII),
    ):
        found = _patch_match(lines, pattern, begin, same)
        if found is not None:
            return found
    return None


def _patch_split(chunk, start, old, new):
    """Codex's replacements for one placed hunk: its context lines keep the file's own text."""
    out = []
    old_start = new_start = 0
    for old_at, new_at in chunk["pairs"]:
        if old_at >= len(old) or new_at >= len(new):
            break
        if (old_start, new_start) != (old_at, new_at):
            out.append((start + old_start, old_at - old_start, new[new_start:new_at]))
        old_start, new_start = old_at + 1, new_at + 1
    if old_start != len(old) or new_start != len(new):
        out.append((start + old_start, len(old) - old_start, new[new_start:]))
    return out


def _patch_place(chunk, lines, cursor):
    """(replacements, cursor) for one hunk, or None when it cannot be placed."""
    if chunk["context"] is not None:
        found = _seek(lines, [chunk["context"]], cursor, eof=False)
        if found is None:  # looser than Codex, which fails here: judging more never lets less through
            anchor = chunk["context"].strip(_PATCH_SPACE)
            found = next((i for i in range(cursor, len(lines)) if anchor in lines[i]), None)
        if found is None:
            return None
        cursor = found + 1
    old, new = chunk["old"], chunk["new"]
    if not old:
        return [(len(lines), 0, list(new))], cursor
    found = _seek(lines, old, cursor, eof=chunk["eof"])
    if found is None and old[-1] == "":
        old = old[:-1]
        new = new[:-1] if new and new[-1] == "" else new
        found = _seek(lines, old, cursor, eof=chunk["eof"])
    if found is None:
        return None
    return _patch_split(chunk, found, old, new), found + len(old)


def _patch_source(text):
    """[(line, ending)] as text_file.rs splits a file: on CRLF, CR or LF."""
    lines = []
    start = index = 0
    while index < len(text):
        ending = next((e for e in _PATCH_ENDINGS if text.startswith(e, index)), None)
        if ending is None:
            index += 1
            continue
        lines.append((text[start:index], ending))
        index += len(ending)
        start = index
    if start < len(text):
        lines.append((text[start:], None))
    return lines


def apply_hunks(text, hunks):
    """`text` with the hunks applied as Codex applies them, or None when one cannot be placed."""
    source = _patch_source(text)
    lines = [line for line, _ in source]
    preferred = next((ending for _, ending in source if ending), "\n")
    replacements = []
    cursor = 0
    for chunk in hunks:
        placed = _patch_place(chunk, lines, cursor)
        if placed is None:
            return None
        replacements.extend(placed[0])
        cursor = placed[1]
    out = []
    done = 0
    for start, length, new in sorted(replacements, key=lambda r: r[0]):
        out.extend(source[done:start])
        out.extend((line, preferred) for line in new)
        done = start + length
    out.extend(source[done:])
    return "".join(line + (ending or preferred) for line, ending in out)


def _patch_key(event, path):
    """`path` as the call names it: relative to the agent's working directory when the event has one."""
    cwd = getattr(event, "cwd", None)
    return os.path.normpath(os.path.join(cwd, path)) if cwd else path


def _read(root, path):
    target = Path(path)
    if not target.is_absolute():
        target = Path(root if root is not None else Path.cwd()) / target
    try:
        return target.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def patched_files(event, root=None):
    """{path: text} for every file an apply_patch call adds or updates and can be rebuilt."""
    patch = patch_text(event)
    if patch is None:
        return {}
    files = {}
    disk = {}
    for op, path, moved_to, body in parse_patch(patch):
        key = _patch_key(event, path)
        if op == "add":
            disk[key] = files[key] = "".join(line + "\n" for line in body)
        elif op == "delete":
            disk[key] = None
            files.pop(key, None)
        else:
            before = disk[key] if key in disk else _read(root, key)
            after = apply_hunks(before, body) if before is not None else None
            if after is not None:
                target = _patch_key(event, moved_to) if moved_to else key
                if target != key:
                    disk[key] = None
                    files.pop(key, None)
                disk[target] = files[target] = after
    return files


def patch_added(event):
    """{path: the lines the patch adds}, which is what `added_lines` means for it."""
    patch = patch_text(event)
    if patch is None:
        return {}
    added = {}
    for op, path, moved_to, body in parse_patch(patch):
        key = _patch_key(event, moved_to or path)
        if op == "add":
            added[key] = "\n".join(body)
        elif op == "update":
            lines = [line for chunk in body for line in chunk["added"]]
            added[key] = "\n".join(filter(None, (added.get(key, ""), *lines)))
    return added
