"""
Target-recovery tests for ``sotgraph pack``: agent-authored display strings
(``'func main — backend/cmd/server/main.go:28'``,
``'type struct Hub — hub.go:19'``, ``'pack.py:110'``) must resolve to the
indexed symbol instead of dead-ending on TARGET_NOT_FOUND.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest

from sot_graph.db import Database
from sot_graph.pack import (
    PackError,
    _find_target,
    _parse_target,
    build_bundle,
)


class ParseTargetTests(unittest.TestCase):
    """_parse_target must never rewrite an already-clean symbol/FQN."""

    def test_clean_symbol_untouched(self):
        for clean in ("main", "pkg.service.process", "Hub"):
            parsed = _parse_target(clean)
            self.assertEqual(parsed.symbol, clean)
            self.assertIsNone(parsed.path)
            self.assertIsNone(parsed.line)
            self.assertFalse(parsed.rewritten)

    def test_go_func_locator(self):
        parsed = _parse_target("func main — backend/cmd/server/main.go:28")
        self.assertEqual(parsed.symbol, "main")
        self.assertEqual(parsed.path, "backend/cmd/server/main.go")
        self.assertEqual(parsed.line, 28)
        self.assertTrue(parsed.rewritten)

    def test_go_struct_locator_with_misordered_keywords(self):
        # The field report's exact string: 'type struct Hub' (agent-mangled
        # word order) — both keywords must strip.
        parsed = _parse_target("type struct Hub — backend/internal/realtime/hub.go:19")
        self.assertEqual(parsed.symbol, "Hub")
        self.assertEqual(parsed.path, "backend/internal/realtime/hub.go")
        self.assertEqual(parsed.line, 19)

    def test_decl_prefix_without_path(self):
        parsed = _parse_target("func main")
        self.assertEqual(parsed.symbol, "main")
        self.assertIsNone(parsed.path)
        self.assertTrue(parsed.rewritten)

    def test_go_type_display_form(self):
        parsed = _parse_target("type Hub struct")
        self.assertEqual(parsed.symbol, "Hub")

    def test_parens_stripped(self):
        parsed = _parse_target("func main()")
        self.assertEqual(parsed.symbol, "main")

    def test_bare_path_line_locator(self):
        parsed = _parse_target("cli.py:1041")
        self.assertEqual(parsed.line, 1041)
        self.assertTrue(parsed.rewritten)

    def test_hash_line_anchor(self):
        parsed = _parse_target("src/sot_graph/pack.py#L110")
        self.assertEqual(parsed.path, "src/sot_graph/pack.py")
        self.assertEqual(parsed.line, 110)

    def test_absolute_path_locator(self):
        parsed = _parse_target("/abs/root/backend/main.go:28")
        self.assertEqual(parsed.path, "/abs/root/backend/main.go")
        self.assertEqual(parsed.line, 28)

    def test_dotted_fqn_without_line_is_not_a_locator(self):
        parsed = _parse_target("pkg.Foo")
        self.assertEqual(parsed.symbol, "pkg.Foo")
        self.assertIsNone(parsed.line)
        self.assertFalse(parsed.rewritten)

    def test_pipe_and_hyphen_separators(self):
        for text in ("func main | main.go:28", "func main - main.go:28"):
            parsed = _parse_target(text)
            self.assertEqual(parsed.symbol, "main")
            self.assertEqual(parsed.line, 28)

    def test_backticks_stripped(self):
        parsed = _parse_target("`func main` — `main.go:28`")
        self.assertEqual(parsed.symbol, "main")
        self.assertEqual(parsed.line, 28)


class FindTargetRecoveryTests(unittest.TestCase):
    """_find_target resolves display strings against a synthetic index.

    Paths are stored ABSOLUTE (mirroring the real index) while the agent
    locators are repo-relative, exercising the suffix-match path scoping.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="sot-pack-recovery-")
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.db = Database(os.path.join(self.test_dir, "test.db"))
        self.addCleanup(self.db.close)

    def _add_node(self, node_id, symbol, path, line_start, line_end,
                  kind="function", fqn=None):
        self.db.conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, "
            "signature, label, body, keywords, line_start, line_end, "
            "col_start, col_end, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '', ?, '', '', ?, ?, 0, 0, 0)",
            (node_id, os.path.join(self.test_dir, path), kind, symbol,
             fqn or symbol, symbol, line_start, line_end),
        )
        self.db.conn.commit()

    def test_go_func_locator_resolves(self):
        self._add_node("srv-main", "main", "backend/cmd/server/main.go", 28, 60)
        node, _ = _find_target(self.db, "func main — backend/cmd/server/main.go:28")
        self.assertEqual(node["symbol"], "main")
        self.assertEqual(node["_resolution_method"], "normalized_symbol")

    def test_go_struct_locator_resolves(self):
        self._add_node("hub", "Hub", "backend/internal/realtime/hub.go",
                       19, 120, kind="class")
        node, _ = _find_target(
            self.db, "type struct Hub — backend/internal/realtime/hub.go:19")
        self.assertEqual(node["symbol"], "Hub")
        self.assertEqual(node["_resolution_method"], "normalized_symbol")

    def test_path_scope_disambiguates_duplicate_symbols(self):
        # 'main' exists in two files: the locator's path must pick the
        # server one even though neither has inbound edges (bare 'main'
        # alone would be AMBIGUOUS_TARGET).
        self._add_node("srv-main", "main", "backend/cmd/server/main.go", 28, 60)
        self._add_node("tool-main", "main", "cmd/tool/main.go", 10, 30)
        node, _ = _find_target(self.db, "func main — backend/cmd/server/main.go:28")
        self.assertEqual(node["id"], "srv-main")

    def test_clean_ambiguous_symbol_still_raises(self):
        self._add_node("srv-main", "main", "backend/cmd/server/main.go", 28, 60)
        self._add_node("tool-main", "main", "cmd/tool/main.go", 10, 30)
        with self.assertRaises(PackError) as ctx:
            _find_target(self.db, "main")
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_TARGET")
        self.assertTrue(ctx.exception.candidates)

    def test_bare_path_line_resolves_innermost_node(self):
        self._add_node("handler", "Handler", "web/handler.go", 10, 100, kind="class")
        self._add_node("serve", "Handler.ServeHTTP", "web/handler.go", 40, 60,
                       fqn="Handler.ServeHTTP")
        node, _ = _find_target(self.db, "web/handler.go:50")
        self.assertEqual(node["symbol"], "Handler.ServeHTTP")
        self.assertEqual(node["_resolution_method"], "path_line_containment")

    def test_path_line_outside_inner_node_falls_back_to_enclosing(self):
        self._add_node("handler", "Handler", "web/handler.go", 10, 100, kind="class")
        self._add_node("serve", "Handler.ServeHTTP", "web/handler.go", 40, 60,
                       fqn="Handler.ServeHTTP")
        node, _ = _find_target(self.db, "web/handler.go:15")
        self.assertEqual(node["symbol"], "Handler")

    def test_absolute_path_locator_resolves(self):
        self._add_node("srv-main", "main", "backend/cmd/server/main.go", 28, 60)
        absolute = os.path.join(self.test_dir, "backend/cmd/server/main.go")
        node, _ = _find_target(self.db, f"{absolute}:28")
        self.assertEqual(node["symbol"], "main")

    def test_clean_target_has_no_resolution_method(self):
        self._add_node("hub", "Hub", "backend/internal/realtime/hub.go",
                       19, 120, kind="class")
        node, _ = _find_target(self.db, "Hub")
        self.assertNotIn("_resolution_method", node)
        self.assertFalse(node["_ambiguous_auto_resolved"])

    def test_typoed_name_with_exact_line_resolves_via_containment(self):
        # The agent mistyped the symbol but its line evidence is objective:
        # containment rescues the lookup.
        self._add_node("dispatch", "dispatchRequest", "api/routes.go", 5, 20)
        node, _ = _find_target(self.db, "func dispatchRequst — api/routes.go:5")
        self.assertEqual(node["symbol"], "dispatchRequest")
        self.assertEqual(node["_resolution_method"], "path_line_containment")

    def test_not_found_carries_fuzzy_candidates(self):
        # Typoed name AND a line outside every span: dead end, but the
        # error must still point at the closest indexed symbol.
        self._add_node("dispatch", "dispatchRequest", "api/routes.go", 5, 20)
        with self.assertRaises(PackError) as ctx:
            _find_target(self.db, "func dispatchRequst — api/routes.go:99")
        self.assertEqual(ctx.exception.code, "TARGET_NOT_FOUND")
        self.assertIn("dispatchRequest", ctx.exception.candidates)

    def test_not_found_clean_symbol_also_carries_candidates(self):
        self._add_node("dispatch", "dispatchRequest", "api/routes.go", 5, 20)
        with self.assertRaises(PackError) as ctx:
            _find_target(self.db, "dispatchRequst")
        self.assertEqual(ctx.exception.code, "TARGET_NOT_FOUND")
        self.assertIn("dispatchRequest", ctx.exception.candidates)

    def test_underscore_typo_matches_via_like_wildcard(self):
        # '_' is a LIKE single-char wildcard: 'cmd_pak' must find 'cmd_pack'.
        self._add_node("pack-cmd", "cmd_pack", "src/cli.py", 1041, 1120)
        with self.assertRaises(PackError) as ctx:
            _find_target(self.db, "cmd_pak")
        self.assertIn("cmd_pack", ctx.exception.candidates)


class BuildBundleRecoveryTests(unittest.TestCase):
    """End-to-end through build_bundle: resolution + honesty warnings."""

    GO_SOURCE = "\n".join([
        "package main",
        "",
        "func main() {",
        "\thub := NewHub()",
        "\thub.Run()",
        "}",
        "",
    ]) + "\n"

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="sot-pack-bundle-")
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.db = Database(os.path.join(self.test_dir, "test.db"))
        self.addCleanup(self.db.close)
        self.root = os.path.join(self.test_dir, "repo")
        os.makedirs(os.path.join(self.root, "backend/cmd/server"))
        self.src_path = os.path.join(self.root, "backend/cmd/server/main.go")
        with open(self.src_path, "w", encoding="utf-8") as handle:
            handle.write(self.GO_SOURCE)
        raw = self.GO_SOURCE.encode("utf-8")
        self.db.conn.execute(
            "INSERT INTO graph_nodes (id, path, kind, symbol, fqn, "
            "signature, label, body, keywords, line_start, line_end, "
            "col_start, col_end, updated_at) "
            "VALUES ('srv-main', ?, 'function', 'main', 'main', '', 'main', "
            "'', '', 3, 6, 0, 0, 0)",
            (self.src_path,),
        )
        self.db.conn.execute(
            "INSERT INTO file_journal (path, sha256, size, mtime_ms, reconciled_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.src_path, hashlib.sha256(raw).hexdigest(), len(raw),
             int(os.path.getmtime(self.src_path) * 1000), 0),
        )
        self.db.conn.commit()

    def test_display_string_target_builds_bundle(self):
        bundle = build_bundle(
            self.db, self.root,
            "func main — backend/cmd/server/main.go:28",
            max_hops=1, max_nodes=5,
        )
        self.assertEqual(bundle["resolution"]["status"], "NORMALIZED_TARGET")
        self.assertEqual(bundle["resolution"]["method"], "normalized_symbol")
        self.assertEqual(bundle["resolution"]["selected_fqn"], "main")
        self.assertTrue(
            any("target_normalized:" in w for w in bundle["limits"]["warnings"]),
            bundle["limits"]["warnings"],
        )

    def test_path_line_target_builds_bundle(self):
        bundle = build_bundle(
            self.db, self.root, "backend/cmd/server/main.go:4",
            max_hops=1, max_nodes=5,
        )
        self.assertEqual(bundle["resolution"]["status"], "PATH_LINE_RESOLVED")
        self.assertEqual(bundle["resolution"]["method"], "path_line_containment")

    def test_clean_target_stays_exact(self):
        bundle = build_bundle(
            self.db, self.root, "main", max_hops=1, max_nodes=5,
        )
        self.assertEqual(bundle["resolution"]["status"], "EXACT")
        self.assertNotIn("method", bundle["resolution"])


if __name__ == "__main__":
    unittest.main()
