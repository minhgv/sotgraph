"""Explicit scoped-target identity precedence (T-01 / AC-01).

Regression for the confirmed SG-202 identity defect: the scope target
``src/sot_graph/pack.py::build_bundle`` selected a data variable in
``evaluation/exit_gates/fixtures/sg202_gt_subset.json`` whose stored
symbol literally equals the locator text, instead of the requested code
symbol. For ``path::name`` and ``path::Class.method`` targets the path
half must constrain selection BEFORE any literal graph-name matching;
scoped ambiguity must fail closed with candidates and a scoped dead end
must never fall back to a whole-string name match.
"""

import os
import shutil
import tempfile
import unittest

from sot_graph.assurance.engine import resolve_symbol_identity
from sot_graph.db import Database
from sot_graph.pack import PackError, _find_target, build_bundle
from sot_graph.reconciler import Reconciler


class _ScopedIndex(unittest.TestCase):
    """Synthetic index reproducing the literal-locator collision."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="sot-scoped-identity-")
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.db = Database(os.path.join(self.test_dir, "test.db"))
        self.addCleanup(self.db.close)
        # The real function under its file...
        self._add_node(
            "real-bb", "build_bundle", "src/sot_graph/pack.py",
            fqn="proj.src.sot_graph.pack.build_bundle")
        # ...and the historical collision shape: a stored symbol that
        # EQUALS the whole locator text (JSON fixture data key).
        self._add_node(
            "decoy-bb", "src/sot_graph/pack.py::build_bundle",
            "evaluation/exit_gates/fixtures/sg202_gt_subset.json",
            kind="variable")
        # A class-qualified method: stored symbol is unqualified, the
        # class lives in the dotted FQN tail.
        self._add_node(
            "mcp-pcb", "pack_context_bundle", "src/sot_graph/mcp_service.py",
            kind="method",
            fqn="proj.src.sot_graph.mcp_service.McpService.pack_context_bundle")
        self.db.conn.commit()

    def _add_node(self, node_id, symbol, path, line_start=10, line_end=40,
                  kind="function", fqn=None):
        self.db.conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, "
            "signature, label, body, keywords, line_start, line_end, "
            "col_start, col_end, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '', ?, '', '', ?, ?, 0, 0, 0)",
            (node_id, os.path.join(self.test_dir, path), kind, symbol,
             fqn or symbol, symbol, line_start, line_end),
        )


class EngineScopedDecisionTests(_ScopedIndex):
    """resolve_symbol_identity decides scoped targets by scope first."""

    def test_scoped_exact_beats_literal_collision(self):
        ident = resolve_symbol_identity(self.db, "src/sot_graph/pack.py::build_bundle")
        self.assertEqual(ident["status"], "UNIQUE")
        self.assertEqual(ident["selected"]["id"], "real-bb")
        self.assertEqual(ident["scoped_resolution"]["method"], "path_scoped_exact")

    def test_class_qualified_scoped_method_resolves(self):
        ident = resolve_symbol_identity(
            self.db, "src/sot_graph/mcp_service.py::McpService.pack_context_bundle")
        self.assertEqual(ident["status"], "UNIQUE")
        self.assertEqual(ident["selected"]["id"], "mcp-pcb")
        self.assertEqual(ident["scoped_resolution"]["method"], "path_scoped_suffix")

    def test_scoped_dead_end_never_falls_back_to_literal(self):
        # 'src/sot_graph/pack.py::nope' does not exist; a decoy whose
        # stored name equals a DIFFERENT locator text must stay invisible.
        ident = resolve_symbol_identity(self.db, "src/sot_graph/pack.py::nope")
        self.assertEqual(ident["status"], "NOT_FOUND")
        self.assertEqual(ident["candidates"], [])

    def test_failing_scoped_query_fails_closed_not_found(self):
        # First scoped query throws: the decision must fail closed to
        # NOT_FOUND with the scoped disclosure — never an UnboundLocalError
        # from the exception path (pre-fix 'method' was first bound inside
        # the very try whose handler returned it).
        class _BrokenConn:
            def execute(self, *_a, **_k):
                raise RuntimeError("graph read failed")

        class _BrokenDB:
            conn = _BrokenConn()

        ident = resolve_symbol_identity(
            _BrokenDB(), "src/sot_graph/pack.py::build_bundle")
        self.assertEqual(ident["status"], "NOT_FOUND")
        self.assertEqual(ident["candidates"], [])
        self.assertIsNone(ident["selected"])
        self.assertEqual(
            ident["scoped_resolution"]["method"], "path_scoped_exact")

    def test_scoped_underscore_path_exact_no_false_ambiguity(self):
        # 'http_utils.py' is a literal scope: an unescaped '_' would
        # wildcard-match the single-character-different sibling
        # 'httpXutils.py' and fail the scoped decision as ambiguous.
        self._add_node("us-real", "load_config", "pkg/http_utils.py",
                       fqn="proj.pkg.http_utils.load_config")
        self._add_node("us-sib", "load_config", "pkg/httpXutils.py",
                       fqn="proj.pkg.httpXutils.load_config")
        self.db.conn.commit()
        ident = resolve_symbol_identity(self.db, "pkg/http_utils.py::load_config")
        self.assertEqual(ident["status"], "UNIQUE")
        self.assertEqual(ident["selected"]["id"], "us-real")
        self.assertEqual(
            ident["scoped_resolution"]["method"], "path_scoped_exact")

    def test_scoped_suffix_underscore_name_is_literal_not_wildcard(self):
        # FQN suffix step: 'Cfg.load_config' must not wildcard-match the
        # single-character-different sibling tail 'Cfg.loadXconfig'.
        self._add_node("sx-real", "load_config", "pkg/a.py",
                       fqn="proj.pkg.a.Cfg.load_config")
        self._add_node("sx-sib", "load_config", "pkg/a.py",
                       fqn="proj.pkg.a.Cfg.loadXconfig")
        self.db.conn.commit()
        ident = resolve_symbol_identity(self.db, "pkg/a.py::Cfg.load_config")
        self.assertEqual(ident["status"], "UNIQUE")
        self.assertEqual(ident["selected"]["id"], "sx-real")
        self.assertEqual(
            ident["scoped_resolution"]["method"], "path_scoped_suffix")

    def test_scoped_suffix_wrong_case_sibling_not_selected(self):
        # Scoped FQN suffix matching is case-sensitive like the exact
        # steps: a sole 'Cls.run_Tests' must not be selected through
        # 'pkg/a.py::Cls.run_tests' — no LIKE casefold in the scoped path.
        self._add_node("wc-real", "run_tests", "pkg/a.py",
                       fqn="proj.pkg.a.Cls.run_Tests")
        self.db.conn.commit()
        ident = resolve_symbol_identity(self.db, "pkg/a.py::Cls.run_tests")
        self.assertEqual(ident["status"], "NOT_FOUND")
        self.assertEqual(ident["candidates"], [])

    def test_scoped_ambiguity_fails_closed_with_candidates(self):
        self._add_node("dup-fn", "helper", "pkg/a.py", fqn="proj.pkg.a.helper")
        self._add_node("dup-m", "helper", "pkg/a.py", kind="method",
                       fqn="proj.pkg.a.C.helper")
        self.db.conn.commit()
        ident = resolve_symbol_identity(self.db, "pkg/a.py::helper")
        self.assertEqual(ident["status"], "AMBIGUOUS")
        self.assertIsNone(ident["selected"])
        self.assertEqual(len(ident["candidates"]), 2)

    def test_bare_name_keeps_legacy_exact_shape(self):
        # Literal matching is unchanged for non-scoped queries: the
        # result shape carries no scoped disclosure and the exact-name
        # ladder still decides.
        ident = resolve_symbol_identity(self.db, "build_bundle")
        self.assertEqual(ident["status"], "UNIQUE")
        self.assertEqual(ident["selected"]["id"], "real-bb")
        self.assertNotIn("scoped_resolution", ident)

    def test_decoy_stays_unselected_but_in_graph(self):
        # Intended semantics change: a `path::name`-shaped string can no
        # longer reach the node whose literal symbol equals that text —
        # the scoped interpretation always decides. The fixture variable
        # itself remains in the graph as data; only its selection path
        # through the identity resolver is gone.
        ident = resolve_symbol_identity(
            self.db, "src/sot_graph/pack.py::build_bundle")
        self.assertEqual(ident["selected"]["id"], "real-bb")
        rows = self.db.conn.execute(
            "SELECT id FROM graph_nodes WHERE symbol = ?",
            ("src/sot_graph/pack.py::build_bundle",),
        ).fetchall()
        self.assertEqual([r[0] for r in rows], ["decoy-bb"])


class PackScopedPrecedenceTests(_ScopedIndex):
    """pack._find_target runs the scoped ladder before literal matching."""

    def test_pack_scoped_target_prefers_scoped_match(self):
        node, _ = _find_target(self.db, "src/sot_graph/pack.py::build_bundle")
        self.assertEqual(node["id"], "real-bb")
        self.assertEqual(node["_resolution_method"], "path_scoped")

    def test_pack_class_qualified_scoped_method(self):
        node, _ = _find_target(
            self.db, "src/sot_graph/mcp_service.py::McpService.pack_context_bundle")
        self.assertEqual(node["id"], "mcp-pcb")
        self.assertEqual(node["_resolution_method"], "path_scoped")

    def test_pack_scoped_ambiguity_raises_with_candidates(self):
        self._add_node("dup-fn", "helper", "pkg/a.py", fqn="proj.pkg.a.helper")
        self._add_node("dup-m", "helper", "pkg/a.py", kind="method",
                       fqn="proj.pkg.a.C.helper")
        self.db.conn.commit()
        with self.assertRaises(PackError) as ctx:
            _find_target(self.db, "pkg/a.py::helper")
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_TARGET")
        self.assertTrue(ctx.exception.candidates)

    def test_pack_scoped_missing_raises_not_found(self):
        # Locator-text decoy PRESENT — a stored symbol equal to the whole
        # queried locator, outside the scope — while the true scoped
        # target is ABSENT. The scoped miss must stay a miss: no
        # whole-string name fallback may resurrect the decoy (pre-fix the
        # unscoped literal ladder re-resolved it and packed the fixture
        # variable instead of failing closed).
        self._add_node(
            "decoy-nope", "src/sot_graph/pack.py::nope",
            "evaluation/exit_gates/fixtures/sg202_gt_subset.json",
            kind="variable")
        self.db.conn.commit()
        present = self.db.conn.execute(
            "SELECT id FROM graph_nodes WHERE symbol = ?",
            ("src/sot_graph/pack.py::nope",),
        ).fetchall()
        self.assertEqual([r[0] for r in present], ["decoy-nope"])
        with self.assertRaises(PackError) as ctx:
            build_bundle(self.db, self.test_dir, "src/sot_graph/pack.py::nope")
        self.assertEqual(ctx.exception.code, "TARGET_NOT_FOUND")

    def test_pack_scoped_underscore_path_is_literal_not_wildcard(self):
        # Scoped name ladder: 'http_utils.py' is a literal scope — an
        # unescaped '_' would wildcard-match the sibling path and raise a
        # false AMBIGUOUS_TARGET for a uniquely named symbol.
        self._add_node("us-real", "load_config", "pkg/http_utils.py",
                       fqn="proj.pkg.http_utils.load_config")
        self._add_node("us-sib", "load_config", "pkg/httpXutils.py",
                       fqn="proj.pkg.httpXutils.load_config")
        self.db.conn.commit()
        node, _ = _find_target(self.db, "pkg/http_utils.py::load_config")
        self.assertEqual(node["id"], "us-real")
        self.assertEqual(node["_resolution_method"], "path_scoped")

    def test_pack_path_line_underscore_path_is_literal_not_wildcard(self):
        # Containment fallback: stored paths are absolute while the
        # locator is repo-relative, so the suffix LIKE decides — an
        # unescaped '_' would match the sibling's SMALLER span and resolve
        # the wrong node (out-of-scope resolution).
        self._add_node("pl-real", "load_config", "pkg/http_utils.py",
                       fqn="proj.pkg.http_utils.load_config",
                       line_start=100, line_end=110)
        self._add_node("pl-sib", "load_config", "pkg/httpXutils.py",
                       fqn="proj.pkg.httpXutils.load_config",
                       line_start=102, line_end=108)
        self.db.conn.commit()
        node, _ = _find_target(self.db, "pkg/http_utils.py:105")
        self.assertEqual(node["id"], "pl-real")

    def test_pack_scoped_suffix_wrong_case_not_selected(self):
        # Scoped FQN matching keeps the exact steps' case convention:
        # 'pkg/a.py::Cls.run_tests' must not resolve the sole
        # 'Cls.run_Tests' node through a casefolding LIKE.
        self._add_node("wc-real", "run_tests", "pkg/a.py",
                       fqn="proj.pkg.a.Cls.run_Tests")
        self.db.conn.commit()
        with self.assertRaises(PackError) as ctx:
            _find_target(self.db, "pkg/a.py::Cls.run_tests")
        self.assertEqual(ctx.exception.code, "TARGET_NOT_FOUND")


class BuildBundleScopedTests(unittest.TestCase):
    """End-to-end: scoped class-qualified method packs with disclosure."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="sot-scoped-e2e-", dir=".sot/tmp")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        os.makedirs(os.path.join(self.repo, "src", "sot_graph"))
        with open(os.path.join(self.repo, "src", "sot_graph", "mcp_service.py"), "w") as fh:
            fh.write(
                "class McpService:\n"
                "    def pack_context_bundle(self, target):\n"
                "        return target\n"
            )
        self.db = Database(os.path.join(self.repo, "index.db"))
        self.addCleanup(self.db.close)
        Reconciler(self.db, self.repo).reconcile(workers=1)

    def test_bundle_resolves_scoped_method_with_disclosure(self):
        bundle = build_bundle(
            self.db, self.repo,
            "src/sot_graph/mcp_service.py::McpService.pack_context_bundle",
        )
        self.assertEqual(bundle["resolution"]["status"], "PATH_SCOPED_TARGET")
        self.assertEqual(bundle["resolution"]["method"], "path_scoped")
        # Vendored-extractor convention: method node symbols are
        # class-qualified ('Cls.method') — the resolver's class_methods
        # table depends on that shape — while the class lives in the FQN.
        self.assertEqual(bundle["target"]["symbol"], "McpService.pack_context_bundle")
        self.assertTrue(bundle["target"]["fqn"].endswith(
            ".McpService.pack_context_bundle"))
        self.assertEqual(bundle["target"]["kind"], "method")
        self.assertTrue(bundle["content_is_untrusted"])
        self.assertTrue(any(
            "target_resolved_by_path_scope" in w for w in bundle["limits"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
