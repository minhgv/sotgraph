"""Typing regression tests for ``_LimitVisitor`` sync/async dispatch.

Regression: ``visit_AsyncFunctionDef = visit_FunctionDef`` aliasing
violated Pyright override contravariance — ``ast.AsyncFunctionDef`` is
a *sibling* of ``ast.FunctionDef``, so the aliased signature
``(node: ast.FunctionDef)`` was not assignable to the
``NodeVisitor.visit_AsyncFunctionDef(node: ast.AsyncFunctionDef)``
slot (reportAssignmentType at accounting.py:320). The fix replaced the
alias with a type-correct shared ``_visit_function`` implementation and
two thin typed wrappers. These tests pin both the structural fix and
the unchanged traversal semantics (async collectors attributed exactly
like sync ones; prose docstrings still skipped).
"""

from __future__ import annotations

import ast
from pathlib import Path

from sot_graph.assurance.accounting import (
    _LimitVisitor,
    iter_sql_limit_sites,
)


class TestVisitorTypingRegression:
    def test_async_visitor_is_not_alias_of_sync_visitor(self) -> None:
        # The exact defect: assigning visit_FunctionDef into the
        # visit_AsyncFunctionDef slot types the parameter as
        # ast.FunctionDef, which Pyright rejects against the
        # NodeVisitor dispatch contract for ast.AsyncFunctionDef.
        # Both slots must hold their own (type-correct) definitions.
        assert (
            _LimitVisitor.visit_AsyncFunctionDef
            is not _LimitVisitor.visit_FunctionDef
        )
        assert callable(_LimitVisitor.visit_AsyncFunctionDef)
        assert callable(_LimitVisitor.visit_FunctionDef)

    def test_async_collector_attributed_like_sync_collector(
        self, tmp_path: Path
    ) -> None:
        # Traversal semantics preserved: an SQL LIMIT inside an async
        # def must be attributed to the async collector name, exactly
        # as the pre-fix alias did.
        (tmp_path / "mod.py").write_text(
            'def sync_collector():\n'
            '    return "SELECT 1 LIMIT 50"\n'
            "\n"
            "async def async_collector():\n"
            '    return "SELECT 2 LIMIT 25"\n',
            encoding="utf-8",
        )
        sites = iter_sql_limit_sites(tmp_path)
        keys = {(s.module, s.collector, s.sql) for s in sites}
        assert keys == {
            ("mod", "sync_collector", "SELECT 1 LIMIT 50"),
            ("mod", "async_collector", "SELECT 2 LIMIT 25"),
        }

    def test_async_docstring_prose_still_skipped(self, tmp_path: Path) -> None:
        # visit_Expr skips standalone string statements; the async
        # wrapper must not change that (prose LIMIT is not a cap site).
        (tmp_path / "prose.py").write_text(
            "async def documented():\n"
            '    """Mentions LIMIT in prose, not SQL."""\n'
            "    return None\n",
            encoding="utf-8",
        )
        assert iter_sql_limit_sites(tmp_path) == []

    def test_async_nested_stack_popped(self) -> None:
        # The shared implementation must restore the function stack
        # after each def (append/generic_visit/pop), so a module-level
        # LIMIT after an async def attributes to <module>, not the def.
        tree = ast.parse(
            "async def outer():\n"
            '    return "SELECT 1 LIMIT 1"\n'
            'X = "SELECT 2 LIMIT 2"\n'
        )
        visitor = _LimitVisitor("nested")
        visitor.visit(tree)
        collectors = {(s.collector, s.sql) for s in visitor.sites}
        assert collectors == {
            ("outer", "SELECT 1 LIMIT 1"),
            ("<module>", "SELECT 2 LIMIT 2"),
        }
        assert visitor._fn_stack == []
