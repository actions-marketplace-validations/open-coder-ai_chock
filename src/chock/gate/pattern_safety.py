"""A linear-time check for gate patterns that can take exponential time. Framework-side only.

A backtracking engine runs a repeat nested in a repeat in exponential time when the inner
repeat and what follows it inside the outer loop accept the same character: `(a+)+`,
`(\\w+\\s?)+`, `(?:\\.[\\w.-]+)+`. The parse tree is walked once; where that shape is found the
pattern is refused before it reaches a gate. Overlapping alternation (`(a|aa)+`) is not
detected here; the runtime deadline (`chock.gate.budget`) is the backstop for every shape.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from re import _constants as sre_constants
from re import _parser as sre_parser

#: The gate params that hold a regular expression.
REGEX_PARAM_SUFFIXES = ("_pattern", "_regex", "_pragma")
#: How much of a refused pattern a message shows.
_SHOWN = 120
#: One character of each class a gate pattern commonly names, to probe a class predicate with.
_SAMPLES = ("a", "Z", "5", "_", " ", "!", ".", "-", "/")
#: A repeat that can run twice is a loop.
_TWICE = 2
_REPEATS = (sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT, sre_constants.POSSESSIVE_REPEAT)
_ENDS = (sre_constants.AT_END, sre_constants.AT_END_STRING)
_SINGLE = (
    sre_constants.LITERAL,
    sre_constants.NOT_LITERAL,
    sre_constants.ANY,
    sre_constants.IN,
    sre_constants.CATEGORY,
)
_CATEGORY_TESTS: dict[object, Callable[[str], bool]] = {
    sre_constants.CATEGORY_DIGIT: str.isdecimal,
    sre_constants.CATEGORY_NOT_DIGIT: lambda ch: not ch.isdecimal(),
    sre_constants.CATEGORY_SPACE: str.isspace,
    sre_constants.CATEGORY_NOT_SPACE: lambda ch: not ch.isspace(),
    sre_constants.CATEGORY_WORD: lambda ch: ch.isalnum() or ch == "_",
    sre_constants.CATEGORY_NOT_WORD: lambda ch: not (ch.isalnum() or ch == "_"),
    sre_constants.CATEGORY_LINEBREAK: lambda ch: ch == "\n",
    sre_constants.CATEGORY_NOT_LINEBREAK: lambda ch: ch != "\n",
}


@dataclass(frozen=True)
class _Chars:
    """One single-character node: a membership test and some characters known to pass it."""

    contains: Callable[[str], bool]
    samples: frozenset[str]


_ANY = _Chars(lambda ch: ch != "\n", frozenset(_SAMPLES))


def _member(item: tuple) -> Callable[[str], bool]:
    """The membership test of one item of a character class."""
    op, av = item
    if op == sre_constants.LITERAL:
        return lambda ch: ord(ch) == av
    if op == sre_constants.RANGE:
        return lambda ch: av[0] <= ord(ch) <= av[1]
    if op == sre_constants.CATEGORY:
        return _CATEGORY_TESTS.get(av, _ANY.contains)
    return _ANY.contains


def _chars(op: object, av: object) -> _Chars:
    """The character set of a single-character node."""
    if op == sre_constants.LITERAL:
        return _Chars(lambda ch: ord(ch) == av, frozenset(chr(av)))
    if op == sre_constants.NOT_LITERAL:
        return _Chars(lambda ch: ord(ch) != av, frozenset(_SAMPLES) - {chr(av)})
    if op == sre_constants.CATEGORY:
        items: list[tuple] = [(op, av)]
    elif op == sre_constants.IN:
        items = list(av)
    else:
        return _ANY
    negate = bool(items) and items[0][0] == sre_constants.NEGATE
    tests = [_member(item) for item in items[1:] if negate] or [_member(item) for item in items]
    contains = (lambda ch: not any(t(ch) for t in tests)) if negate else (lambda ch: any(t(ch) for t in tests))
    named = {chr(av) for op, av in items if op == sre_constants.LITERAL}
    named |= {chr(av[0]) for op, av in items if op == sre_constants.RANGE}
    named |= {chr(av[1]) for op, av in items if op == sre_constants.RANGE}
    return _Chars(contains, frozenset(ch for ch in named | set(_SAMPLES) if contains(ch)))


def _overlap(left: Sequence[_Chars], right: Sequence[_Chars]) -> str | None:
    """A character both sets accept, or None."""
    for a in left:
        for b in right:
            hit = next((ch for ch in sorted(a.samples) if b.contains(ch)), None) or next(
                (ch for ch in sorted(b.samples) if a.contains(ch)), None
            )
            if hit is not None:
                return hit
    return None


def _first_node(op: object, av: object) -> tuple[list[_Chars], bool]:  # noqa: PLR0911 -- one return per node shape
    """(characters a node can start with, whether it can match nothing)."""
    if op in _SINGLE:
        return [_chars(op, av)], False
    if op in _REPEATS:
        chars, nullable = _first(av[2])
        return chars, nullable or av[0] == 0
    if op in (sre_constants.SUBPATTERN, sre_constants.ATOMIC_GROUP):
        return _first(av[-1] if op == sre_constants.SUBPATTERN else av)
    if op == sre_constants.BRANCH:
        parts = [_first(branch) for branch in av[1]]
        return [c for chars, _ in parts for c in chars], any(nullable for _, nullable in parts)
    if op == sre_constants.GROUPREF_EXISTS:
        parts = [_first(branch) for branch in av[1:] if branch is not None]
        return [c for chars, _ in parts for c in chars], any(nullable for _, nullable in parts)
    if op == sre_constants.AT:
        return [], av not in _ENDS  # nothing can follow the end of the text
    if op == sre_constants.ASSERT and av[0] > 0:
        return _first(av[1])[0], False  # a lookahead names what the next character must be
    if op in (sre_constants.ASSERT, sre_constants.ASSERT_NOT):
        return [], True
    return [_ANY], True


def _first(seq: Sequence[tuple]) -> tuple[list[_Chars], bool]:
    """(characters a sequence can start with, whether it can match nothing)."""
    chars: list[_Chars] = []
    for op, av in seq:
        found, nullable = _first_node(op, av)
        chars += found
        if not nullable:
            return chars, False
    return chars, True


def _children(op: object, av: object) -> list[Sequence[tuple]]:
    """The sequences a node holds, for the walk to descend into."""
    if op == sre_constants.SUBPATTERN:
        return [av[-1]]
    if op in (sre_constants.ATOMIC_GROUP, sre_constants.ASSERT, sre_constants.ASSERT_NOT):
        return [av if op == sre_constants.ATOMIC_GROUP else av[1]]
    if op == sre_constants.BRANCH:
        return list(av[1])
    if op == sre_constants.GROUPREF_EXISTS:
        return [branch for branch in av[1:] if branch is not None]
    return []


def _walk(seq: Sequence[tuple], after: list[_Chars], in_loop: bool) -> str | None:  # noqa: FBT001 -- internal recursion flag
    """The character that makes a nested repeat ambiguous, or None.

    `after` is what the enclosing loop's next iteration starts with, when nothing that must
    consume text stands between this sequence's end and it; `in_loop` says such a loop
    encloses this sequence. A repeat is ambiguous when it can run into that next iteration.
    """
    for index, (op, av) in enumerate(seq):
        follow = after if _first(seq[index + 1 :])[1] else []
        if op in _REPEATS:
            low, high, body = av
            loops = high >= _TWICE
            if in_loop and loops and high > low and (hit := _overlap(_first(body)[0], follow)) is not None:
                return hit
            found = _walk(body, _first(body)[0] if loops else follow, in_loop or loops)
        else:
            found = next((hit for child in _children(op, av) if (hit := _walk(child, follow, in_loop))), None)
        if found is not None:
            return found
    return None


def catastrophic(pattern: str) -> str | None:
    """Why `pattern` can take exponential time on a crafted line, or None; a pattern that does not compile is None too."""
    try:
        parsed = sre_parser.parse(pattern)
    except (re.error, ValueError, OverflowError, RecursionError):
        return None
    hit = _walk(list(parsed), [], in_loop=False)
    if hit is None:
        return None
    return f"a repeat nested in a repeat, where the inner repeat and what follows it both accept {hit!r}"


def catastrophic_message(name: str, pattern: str, why: str) -> str:
    """The refusal for param `name` holding `pattern`, naming both and the shape found."""
    shown = pattern if len(pattern) <= _SHOWN else pattern[:_SHOWN] + "..."
    return (
        f"{name} can take exponential time on a crafted line ({why}): {shown!r}. "
        "The gate would run out its deadline and refuse rather than judge; rewrite the pattern so the inner "
        "repeat cannot run into the next iteration (anchor it, or separate the repeats with a character neither accepts)"
    )
