"""Where Codex places an apply_patch hunk, and the file it leaves: a port of codex-rs apply-patch.

seek_sequence.rs (exact, trailing space, both ends, ASCII punctuation), file_update.rs's
compute_replacements and text_file.rs's line endings. Extracted into the vendored runtime, so
stdlib-only; patch_image reads the patch.
"""

from __future__ import annotations

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
