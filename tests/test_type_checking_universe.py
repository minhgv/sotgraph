"""test_type_checking_universe.py — declaration-presence vs runtime-reachability.

Policy under test (advisor P1-2): symbols declared under ``if TYPE_CHECKING:``
are DECLARED — the engine must index them as findable nodes, honestly tagged
as type-only — while producing NO runtime edges (an import or call inside the
guard never executes, so fabricating ``imports``/``calls`` edges for it would
be false). The holdout oracle must mirror the split: type-only defs count in
the presence universe (symbol-lookup denominator) but stay out of the
runtime-impact universe.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from sot_graph._vendor.graphify.extract import extract_python  # noqa: E402
from sot_graph.db import Database  # noqa: E402
from sot_graph.extractor import parse_file_graph  # noqa: E402
from sot_graph.holdout import evaluator  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402

MODULE_SRC = '''\
import typing as t
from typing import TYPE_CHECKING

if t.TYPE_CHECKING:
    from decimal import Decimal

    class GhostModel:
        def ghost_method(self) -> "GhostModel":
            return helper()

    def ghost_func(x): ...
else:
    def runtime_fallback():
        return helper()

def helper():
    return 1

def user_fn():
    return helper()
'''


def _write(src: str, name: str = "m.py") -> Path:
    root = Path(tempfile.mkdtemp())
    path = root / name
    path.write_text(src, encoding="utf-8")
    return path


def _call_edges(result):
    return [(e["source"], e["target"]) for e in result["edges"] if e["relation"] == "calls"]


def _import_targets(result):
    return {e["target"] for e in result["edges"] if e["relation"] == "imports"}


class TestExtractorTypeCheckingPolicy(unittest.TestCase):
    def setUp(self):
        self.result = extract_python(_write(MODULE_SRC))

    def test_type_only_defs_indexed_and_tagged(self):
        """Declarations inside the guard become nodes, tagged type-only."""
        by_id = {n["id"]: n for n in self.result["nodes"]}
        for ghost in ("GhostModel", "GhostModel.ghost_method", "ghost_func"):
            self.assertIn(ghost, by_id, f"{ghost} must be indexed for lookup")
            self.assertEqual(
                by_id[ghost].get("keywords"), ["type_checking"],
                f"{ghost} must carry the type-only marker",
            )
        # The alias form `if t.TYPE_CHECKING:` is honored; runtime code is NOT tagged
        for runtime in ("helper", "user_fn", "runtime_fallback"):
            self.assertNotIn(
                "type_checking", by_id[runtime].get("keywords") or [],
                f"{runtime} is runtime code and must stay untagged",
            )

    def test_no_runtime_edges_from_inside_guard(self):
        """No imports/calls edges may originate inside the guard."""
        self.assertNotIn(
            "Decimal", _import_targets(self.result),
            "a TYPE_CHECKING-only import is not a runtime dependency",
        )
        calls = _call_edges(self.result)
        self.assertNotIn(
            ("GhostModel.ghost_method", "helper"), calls,
            "ghost_method never runs — its call must not become an edge",
        )
        # runtime code keeps its edges, including the else branch (runtime path)
        self.assertIn(("user_fn", "helper"), calls)
        self.assertIn(("runtime_fallback", "helper"), calls)

    def test_structural_defines_edges_survive(self):
        """Guard declarations still belong to the file's structure."""
        defines = {(e["source"], e["target"]) for e in self.result["edges"]
                   if e["relation"] == "defines"}
        self.assertIn(("m.py", "GhostModel"), defines)
        self.assertIn(("GhostModel", "GhostModel.ghost_method"), defines)


class TestStandardizerAndGraph(unittest.TestCase):
    def test_marker_survives_standardization(self):
        root = _write(MODULE_SRC).parent
        record = parse_file_graph(str(root / "m.py"), str(root))
        by_symbol = {n["symbol"]: n for n in record["nodes"]}
        self.assertIn("type_checking", by_symbol["GhostModel"]["keywords"])
        self.assertNotIn("type_checking", by_symbol["helper"]["keywords"])

    def test_ghost_symbols_searchable_after_reconcile(self):
        root = _write(MODULE_SRC).parent
        db = Database(str(root / ".sot" / "sot.db"))
        try:
            Reconciler(db, str(root)).reconcile(workers=1)
            rows = db.conn.execute(
                "SELECT symbol, keywords FROM graph_nodes WHERE symbol IN "
                "('GhostModel', 'ghost_func', 'helper')"
            ).fetchall()
            kw = {sym: kws or "" for sym, kws in rows}
            self.assertIn("type_checking", kw["GhostModel"])
            self.assertIn("type_checking", kw["ghost_func"])
            self.assertNotIn("type_checking", kw["helper"])
            hits = {h["symbol"] for h in db.search_fts("GhostModel")}
            self.assertIn("GhostModel", hits, "type-only symbol must be findable")
        finally:
            db.close()


class TestEvaluatorUniverseSplit(unittest.TestCase):
    def setUp(self):
        self.root = _write(MODULE_SRC).parent
        self.defs, _ = evaluator.extract_definitions(self.root, evaluator.OracleConfig())

    def test_type_checking_defs_in_presence_universe(self):
        """The evaluator no longer blanket-excludes TYPE_CHECKING bodies."""
        by_name = {(d.name, d.type_only) for d in self.defs}
        self.assertIn(("GhostModel", True), by_name)
        self.assertIn(("ghost_method", True), by_name)
        self.assertIn(("ghost_func", True), by_name)
        # else branch is the runtime path — declared and NOT type-only
        self.assertIn(("runtime_fallback", False), by_name)
        self.assertIn(("helper", False), by_name)

    def test_type_only_defs_out_of_runtime_impact_universe(self):
        edges, _ = evaluator.resolve_direct_calls(
            self.root, self.defs, evaluator.OracleConfig()
        )
        edge_pairs = {(e.caller_name, e.callee_name) for e in edges}
        self.assertNotIn(("ghost_method", "helper"), edge_pairs)
        self.assertNotIn(("GhostModel", "helper"), edge_pairs)
        self.assertNotIn(("ghost_func", "helper"), edge_pairs)
        self.assertIn(("user_fn", "helper"), edge_pairs)
        self.assertIn(("runtime_fallback", "helper"), edge_pairs)

    def test_type_only_import_does_not_resolve_calls(self):
        """A from-import bound only under TYPE_CHECKING is no runtime binding."""
        src = (
            "if TYPE_CHECKING:\n"
            "    from ghosts import Phantom\n"
            "\n"
            "def user():\n"
            "    return Phantom()\n"
        )
        root = _write(src).parent
        defs, _ = evaluator.extract_definitions(root, evaluator.OracleConfig())
        edges, unresolved = evaluator.resolve_direct_calls(
            root, defs, evaluator.OracleConfig()
        )
        self.assertEqual(
            [e for e in edges if e.callee_name == "Phantom"], [],
            "type-only from-imports must not mint runtime call edges",
        )
        self.assertEqual(
            [e for e in edges if e.callee_name == "ghosts"], [],
            "the guard import itself must not appear as a call target",
        )

    def test_calls_inside_guard_body_are_skipped(self):
        src = (
            "def helper():\n"
            "    return 1\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    helper()\n"
            "\n"
            "def caller():\n"
            "    return helper()\n"
        )
        root = _write(src).parent
        defs, _ = evaluator.extract_definitions(root, evaluator.OracleConfig())
        edges, _ = evaluator.resolve_direct_calls(root, defs, evaluator.OracleConfig())
        edge_pairs = {(e.caller_name, e.callee_name) for e in edges}
        self.assertEqual(edge_pairs, {("caller", "helper")})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
