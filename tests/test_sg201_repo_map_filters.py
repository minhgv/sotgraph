"""SG-201: production-source repo-map filters.

The map must rank what matters (production source) by default, classify
paths deterministically, echo its filter scope back, never leak symbols
from another root, and never let callers infer absence-from-index from
absence-from-map.
"""
import argparse
import contextlib
import io
import os
import shutil
import tempfile
import unittest

from sot_graph.cli import cmd_map
from sot_graph.db import Database
from sot_graph.mcp_service import McpService, McpServiceError
from sot_graph.reconciler import Reconciler
from sot_graph.repo_map import (
    ALL_CATEGORIES,
    DEFAULT_CATEGORIES,
    build_repo_map,
    classify_path,
    parse_include_categories,
)
from sot_graph.tokenizer import estimate_tokens

FILTER_PROJECT = {
    "src/app/hub.py": "def hub():\n    return 1\n",
    "src/app/use.py": "from app.hub import hub\n\ndef use():\n    return hub()\n",
    "tests/test_hub.py": "def test_hub_runs():\n    assert True\n",
    "tests/fixtures/fake_site.py": "def fake_site():\n    return 2\n",
    "vendor/lib.py": "def vendored_helper():\n    return 3\n",
    "scripts/release_tool.py": "def release_main():\n    return 4\n",
}


def _insert_function(conn, node_id, path, symbol, updated_at=1700000000):
    conn.execute(
        "INSERT INTO graph_nodes (id, path, kind, symbol, label, body, keywords, "
        "line_start, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (node_id, path, "function", symbol, symbol, "", "", 1, updated_at),
    )


class ClassifyPathTests(unittest.TestCase):
    """Path shapes taken from this very repository (and its like)."""

    def test_repo_path_shapes(self):
        cases = {
            "src/sot_graph/repo_map.py": "production",
            "src/app/hub.py": "production",
            "pkg/deep/nested/mod.go": "production",
            "tests/test_repo_map.py": "test",
            "tests/fixtures/sg201/case.py": "fixture",  # fixture beats test
            "tests/testdata/inputs.json.py": "fixture",
            "evaluation/holdout/run.py": "fixture",
            "src/sot_graph/_vendor/d3/d3core.js": "vendor",
            "third_party/libleft/x.py": "vendor",
            "dist/sot/graph.js": "generated",
            "out/release/blob.py": "generated",
            "docs/architecture/overview.py": "docs",
            "scripts/bundle.py": "tooling",
            "benchmarks/bench_map.py": "tooling",
            ".github/workflows/helper.py": "tooling",
        }
        for path, expected in cases.items():
            self.assertEqual(classify_path(path), expected, path)

    def test_filename_rules_anywhere_in_tree(self):
        self.assertEqual(classify_path("src/app/conftest.py"), "test")
        self.assertEqual(classify_path("src/app/test_utils.py"), "test")
        self.assertEqual(classify_path("src/app/parser_test.py"), "test")
        self.assertEqual(classify_path("web/assets/app.min.js"), "vendor")
        self.assertEqual(classify_path("src/proto/user_pb2.py"), "generated")

    def test_canonicalizes_before_matching(self):
        # normalize_repo_path convention: backslashes are separators, "./"
        # prefixes are stripped — the category cannot be hidden by spelling.
        self.assertEqual(classify_path("src\\pkg\\_vendor\\x.py"), "vendor")
        self.assertEqual(classify_path("./tests/test_x.py"), "test")

    def test_matching_is_case_sensitive(self):
        # Segment names are case-sensitive: "Tests" and "Vendor" are not
        # category markers, and no basename rule rescues run_cases.py.
        self.assertEqual(classify_path("Tests/run_cases.py"), "production")
        self.assertEqual(classify_path("src/Vendor/lib.py"), "production")
        self.assertEqual(classify_path("src/App/Conftest.py"), "production")
        # ...but filename rules are directory-independent by design, so a
        # case-sensitive segment miss does not save a test-prefixed file.
        self.assertEqual(classify_path("Tests/test_x.py"), "test")


class ParseIncludeCategoriesTests(unittest.TestCase):
    def test_default_is_production_only(self):
        self.assertEqual(parse_include_categories(None), DEFAULT_CATEGORIES)
        self.assertEqual(parse_include_categories(), DEFAULT_CATEGORIES)
        self.assertEqual(parse_include_categories(""), DEFAULT_CATEGORIES)

    def test_all_expands_to_every_category(self):
        self.assertEqual(parse_include_categories("all"), ALL_CATEGORIES)
        self.assertEqual(parse_include_categories(["fixture", "all"]), ALL_CATEGORIES)

    def test_comma_string_and_sequence_are_canonicalized(self):
        self.assertEqual(
            parse_include_categories("vendor,test"),
            ("test", "vendor"))  # canonical ALL_CATEGORIES order, not input order
        self.assertEqual(
            parse_include_categories(["tooling", "test", "test"]),
            ("test", "tooling"))  # dedup

    def test_unknown_and_case_mismatch_rejected(self):
        for bad in ("bogus", "Production", "production,bogus"):
            with self.assertRaises(ValueError, msg=bad):
                parse_include_categories(bad)


class RepoMapFilterTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        for rel, content in FILTER_PROJECT.items():
            target = os.path.join(self.test_dir, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(content)
        self.db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(self.db, self.test_dir).reconcile(workers=1)
        # dist/ is default-ignored at index time; a build-artifact symbol is
        # simulated via a direct node row, exactly like real stale indexes.
        with self.db.conn:
            _insert_function(self.db.conn, "n:distgen000001",
                             "dist/gen_mod.py", "generated_stub")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _symbols(self, result):
        return {s["symbol"] for f in result["files"] for s in f["symbols"]}

    def test_default_map_is_production_only(self):
        result = build_repo_map(self.db.conn, max_tokens=2048, root=self.test_dir)
        included = self._symbols(result)
        self.assertEqual(included, {"hub", "use"})
        for banned in ("test_hub_runs", "fake_site", "vendored_helper",
                       "release_main", "generated_stub"):
            self.assertNotIn(banned, included)
            self.assertNotIn(banned, result["rendered"])

    def test_opt_in_all_includes_every_category(self):
        result = build_repo_map(self.db.conn, max_tokens=4096, root=self.test_dir,
                                include_categories="all")
        included = self._symbols(result)
        for expected in ("hub", "use", "test_hub_runs", "fake_site",
                         "vendored_helper", "release_main", "generated_stub"):
            self.assertIn(expected, included)

    def test_opt_in_single_category(self):
        result = build_repo_map(self.db.conn, max_tokens=2048, root=self.test_dir,
                                include_categories="test")
        self.assertEqual(self._symbols(result), {"test_hub_runs"})
        result = build_repo_map(self.db.conn, max_tokens=2048, root=self.test_dir,
                                include_categories=["production", "vendor"])
        self.assertEqual(self._symbols(result), {"hub", "use", "vendored_helper"})

    def test_filter_scope_echoed_in_dict_and_render(self):
        result = build_repo_map(self.db.conn, max_tokens=2048, root=self.test_dir)
        filters = result["filters"]
        self.assertEqual(filters["categories_included"], ["production"])
        self.assertEqual(filters["categories_excluded"],
                         ["test", "fixture", "vendor", "generated", "docs", "tooling"])
        self.assertEqual(filters["excluded_symbols"], 5)
        self.assertIn("map scope: production only", result["rendered"])
        self.assertIn("hid 5 of 7 indexed symbols", result["rendered"])
        self.assertEqual(result["tokens_estimate"], estimate_tokens(result["rendered"]))

    def test_all_categories_scope_reports_no_filter(self):
        result = build_repo_map(self.db.conn, max_tokens=4096, root=self.test_dir,
                                include_categories="all")
        filters = result["filters"]
        self.assertEqual(filters["categories_excluded"], [])
        self.assertEqual(filters["excluded_symbols"], 0)
        self.assertIn("map scope: all categories", result["rendered"])

    def test_absence_anti_inference_always_present(self):
        for categories in (None, "all", "test"):
            result = build_repo_map(self.db.conn, max_tokens=2048,
                                    root=self.test_dir,
                                    include_categories=categories)
            self.assertIn(
                "(absence from this map does not imply absence from the index)",
                result["rendered"], msg=str(categories))
            self.assertEqual(result["filters"]["absence_note"],
                             "absence from this map does not imply absence from the index")

    def test_cross_root_isolation_regardless_of_filters(self):
        other_root = tempfile.mkdtemp(prefix="sot-other-root-")
        try:
            with self.db.conn:
                _insert_function(self.db.conn, "n:crossroot00001",
                                 os.path.join(other_root, "elsewhere.py"),
                                 "foreign_symbol")
                _insert_function(self.db.conn, "n:crossroot00002",
                                 "../escaped.py", "escaped_symbol")
            for categories in (None, "all"):
                result = build_repo_map(self.db.conn, max_tokens=4096,
                                        root=self.test_dir,
                                        include_categories=categories)
                included = self._symbols(result)
                self.assertNotIn("foreign_symbol", included, msg=str(categories))
                self.assertNotIn("escaped_symbol", included, msg=str(categories))
                self.assertNotIn("foreign_symbol", result["rendered"])
        finally:
            shutil.rmtree(other_root, ignore_errors=True)

    def test_deterministic_output_for_same_db(self):
        first = build_repo_map(self.db.conn, max_tokens=2048, root=self.test_dir)
        second = build_repo_map(self.db.conn, max_tokens=2048, root=self.test_dir)
        self.assertEqual(first["rendered"], second["rendered"])
        self.assertEqual([f["path"] for f in first["files"]],
                         [f["path"] for f in second["files"]])

    def test_equal_rank_ties_break_by_path_then_symbol(self):
        # Three isolated, edge-less symbols share exactly the same rank; the
        # map order must come from the sort key, not from dict/row order.
        with self.db.conn:
            for node_id, symbol in (("n:tiezeta000001", "zeta_iso"),
                                    ("n:tiealpha00001", "alpha_iso"),
                                    ("n:tiemid0000001", "mid_iso")):
                _insert_function(self.db.conn, node_id, "iso.py", symbol)
        result = build_repo_map(self.db.conn, max_tokens=4096, root=self.test_dir)
        rendered = result["rendered"]
        self.assertLess(rendered.index("alpha_iso"), rendered.index("mid_iso"))
        self.assertLess(rendered.index("mid_iso"), rendered.index("zeta_iso"))

    def test_tiny_budget_keeps_footer_and_honest_accounting(self):
        result = build_repo_map(self.db.conn, max_tokens=32, root=self.test_dir)
        self.assertEqual(result["symbols"], 0)
        self.assertEqual(result["files"], [])
        self.assertIn("map scope:", result["rendered"])
        self.assertEqual(result["tokens_estimate"], estimate_tokens(result["rendered"]))

    def test_filter_hiding_everything_still_echoes_scope(self):
        result = build_repo_map(self.db.conn, max_tokens=2048, root=self.test_dir,
                                include_categories="docs")
        self.assertEqual(result["symbols"], 0)
        self.assertEqual(result["files"], [])
        self.assertEqual(result["filters"]["excluded_symbols"], 7)
        self.assertIn("map scope: docs only", result["rendered"])
        self.assertIn("(absence from this map does not imply absence from the index)",
                      result["rendered"])

    def test_empty_index_keeps_empty_render_with_filters(self):
        empty_dir = tempfile.mkdtemp(prefix="sot-empty-")
        try:
            db = Database(os.path.join(empty_dir, ".sot", "test.db"))
            try:
                result = build_repo_map(db.conn, root=empty_dir)
                self.assertEqual(result["rendered"], "")
                self.assertEqual(result["symbols"], 0)
                self.assertEqual(result["filters"]["categories_included"], ["production"])
            finally:
                db.close()
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)


class RepoMapFilterSurfaceTests(unittest.TestCase):
    """CLI and MCP must share the one interpretation built into build_repo_map."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        for rel, content in FILTER_PROJECT.items():
            target = os.path.join(self.test_dir, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(content)
        self.db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(self.db, self.test_dir).reconcile(workers=1)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cmd_map_prints_scope_and_default_filtering(self):
        args = argparse.Namespace(tokens=2048, focus=None, include=None)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cmd_map(args, self.db, self.test_dir), 0)
        out = buf.getvalue()
        self.assertIn("scope: production", out)
        self.assertIn("def hub", out)
        self.assertNotIn("vendored_helper", out)
        self.assertIn("absence from this map does not imply absence from the index", out)

    def test_cmd_map_include_flag_and_invalid_value(self):
        args = argparse.Namespace(tokens=4096, focus=None, include="all")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cmd_map(args, self.db, self.test_dir), 0)
        self.assertIn("vendored_helper", buf.getvalue())
        self.assertIn("scope: all categories", buf.getvalue())

        err = io.StringIO()
        bad = argparse.Namespace(tokens=1024, focus=None, include="bogus")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(cmd_map(bad, self.db, self.test_dir), 2)
        self.assertIn("unknown category", err.getvalue())

    def test_mcp_repo_map_returns_filters_and_opt_in(self):
        service = McpService(os.path.join(self.test_dir, ".sot", "test.db"),
                             self.test_dir)
        res = service.repo_map()
        self.assertTrue(res["ok"])
        self.assertEqual(res["filters"]["categories_included"], ["production"])
        self.assertNotIn("vendored_helper", res["map"])
        all_res = service.repo_map(include_categories="all")
        self.assertIn("vendored_helper", all_res["map"])
        self.assertEqual(all_res["filters"]["categories_excluded"], [])

    def test_mcp_repo_map_rejects_unknown_category(self):
        service = McpService(os.path.join(self.test_dir, ".sot", "test.db"),
                             self.test_dir)
        with self.assertRaises(McpServiceError) as ctx:
            service.repo_map(include_categories="bogus")
        self.assertEqual(ctx.exception.code, "invalid_argument")


if __name__ == "__main__":
    unittest.main()
