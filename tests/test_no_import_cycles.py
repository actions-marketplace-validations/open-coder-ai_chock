"""No module-level import cycle in chock. CodeQL found one; this keeps it found.

A cycle is not a style complaint here. It makes import order load-bearing, so a module that
imported cleanly for years starts failing because something unrelated imported it first, and
the usual repair -- deferring the import into a function -- hides the cycle from the reader
while leaving it in the graph. This asserts over the graph instead.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE = "chock"


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts).removesuffix(".__init__")


def _imports(path: Path) -> set[str]:
    """Only imports at column zero: a deferred one is not what makes import order matter."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        # ast.walk yields the Module node too, which carries no position at all.
        if not isinstance(node, (ast.Import, ast.ImportFrom)) or node.col_offset != 0:
            continue
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(PACKAGE):
                found.add(node.module)
        else:
            found.update(alias.name for alias in node.names if alias.name.startswith(PACKAGE))
    return found


def import_graph(extra: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for path in SRC.rglob("*.py"):
        graph[_module_name(path)] |= _imports(path)
    for module, targets in (extra or {}).items():
        graph[module] |= targets
    return graph


def cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    found: list[list[str]] = []
    seen: set[str] = set()
    stack: list[str] = []

    def walk(module: str) -> None:
        if module in stack:
            found.append([*stack[stack.index(module) :], module])
            return
        if module in seen:
            return
        seen.add(module)
        stack.append(module)
        for target in sorted(graph.get(module, ())):
            walk(target)
        stack.pop()

    for module in sorted(graph):
        walk(module)
    return found


def test_no_module_level_import_cycle() -> None:
    found = cycles(import_graph())
    assert not found, "import cycle(s): " + "; ".join(" -> ".join(c) for c in found)


def test_the_check_would_notice_the_cycle_it_was_written_for() -> None:
    """A checker that only ever reports zero is not a checker. This is the edge that was cut.

    chock.config used to import chock.compile.surfaces for the Surface enum and the agent
    names; surfaces reaches the installer, the installer the in-agent emitter, and from there
    the gate builder reaches config again. The enum now lives in a leaf and config takes its
    agent names from the vendor table.
    """
    graph = import_graph({"chock.config": {"chock.compile.surfaces"}})
    found = cycles(graph)
    assert found, "restoring the removed edge must reproduce a cycle"
    assert any("chock.config" in c and "chock.compile.surfaces" in c for c in found)
