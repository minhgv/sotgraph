"""Adversarial probes for bare-name retrieval ranking (advisor P1-6).

Covers the identifier-component ranking signal end to end:
  1. a bare-name query must strongly match a symbol stored as a qualified
     name (``Class.method`` / dotted FQN);
  2. an ambiguous bare name must NOT bury the exact qualified match behind
     an irrelevant popular symbol, and the boost must withdraw (dampen)
     when the bare name matches too many symbols;
  3. exact-bare-name matches must outrank prefix/coincidental matches;
  4. a bare-name query whose right answer is a bare function (not a method
     inside a same-named class) must still win;
  5. both retrieval surfaces (Database.search_fts and the MCP search
     ranker) must interpret the same query identically.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.db import (
    EXACT_BARE_NAME_CAP,
    Database,
    bare_name,
    exact_bare_name_flags,
    fts_query_terms,
    identifier_components,
)
from sot_graph.reconciler import Reconciler

VIEWER = (
    "class Viewer:\n"
    "    def render(self, scene):\n"
    "        'Render the scene to the screen.'\n"
    "        return scene\n"
)


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class BareNameRankingTestCase(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _db_with(self, files):
        for rel, content in files.items():
            _write(self.root, rel, content)
        self.db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        Reconciler(self.db, self.test_dir).reconcile(workers=1)
        return self.db

    def _mcp(self):
        from sot_graph.mcp_service import McpService

        return McpService(os.path.join(self.test_dir, ".sot", "test.db"),
                          self.test_dir)

    def tearDown(self):  # noqa: D102 - close db before rmtree
        db = getattr(self, "db", None)
        if db is not None:
            db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)


class IdentifierComponentAnalysis(BareNameRankingTestCase):
    def test_components_split_dotted_snake_camel(self):
        self.assertEqual(identifier_components("Class.method"),
                         ["class", "method"])
        self.assertEqual(identifier_components("render_trace_markdown"),
                         ["render", "trace", "markdown"])
        self.assertEqual(identifier_components("parseArgs"), ["parse", "args"])

    def test_bare_name_is_last_separator_segment_casefolded(self):
        self.assertEqual(bare_name("Viewer.render"), "render")
        self.assertEqual(bare_name("PaymentService.validateCard"),
                         "validatecard")
        self.assertEqual(bare_name("render"), "render")
        self.assertEqual(bare_name(None), "")

    def test_query_terms_carry_last_component_channel(self):
        tokens, parts = fts_query_terms("renderTrace")
        self.assertIn('"trace"*', tokens)
        self.assertIn("rendertrace", parts)

    def test_flags_dampen_when_bare_name_ambiguous(self):
        syms = [f"mod{i}.render" for i in range(EXACT_BARE_NAME_CAP + 4)]
        flags = exact_bare_name_flags(syms, {"render"})
        self.assertEqual(set(flags), {0}, "boost must withdraw when ambiguous")

    def test_flags_fire_below_ambiguity_cap(self):
        syms = ["Viewer.render", "Grid.render", "render_widget"]
        self.assertEqual(exact_bare_name_flags(syms, {"render"}), [1, 1, 0])

    def test_flags_grade_exact_short_name_above_qualified(self):
        # Mirrors the P4 identity semantics: exact short-name (2) >
        # qualified bare-name match (1) > no exact identity (0).
        syms = ["render", "Viewer.render", "render_widget"]
        self.assertEqual(exact_bare_name_flags(syms, {"render"}), [2, 1, 0])


class BareNameMatchesQualifiedSymbol(BareNameRankingTestCase):
    def test_bare_query_finds_class_method_rank1(self):
        self._db_with({
            "app/viewer.py": VIEWER,
            "app/misc.py": "def render_tree(node):\n"
                           "    'Render a tree structure.'\n"
                           "    return node\n",
        })
        hits = self.db.search_fts("render", limit=5)
        self.assertTrue(hits, "bare-name query must return hits")
        self.assertEqual(hits[0]["symbol"], "Viewer.render",
                         "Class.render must outrank prefix matches for 'render'")

    def test_bare_query_reaches_method_via_mcp_search(self):
        self._db_with({"app/viewer.py": VIEWER})
        svc = self._mcp()
        results = svc.search("render", limit=5, assurance=False)["results"]
        self.assertTrue(results)
        self.assertEqual(results[0]["symbol"], "Viewer.render")


class AmbiguousBareNameGuard(BareNameRankingTestCase):
    def _ambig_corpus(self):
        files = {}
        # A genuinely relevant qualified match with module context.
        files["app/template.py"] = (
            "class Template:\n"
            "    def render(self, ctx):\n"
            "        'Render the template with a context.'\n"
            "        return ctx\n"
        )
        # Many UNRELATED same-bare-name methods (above the ambiguity cap):
        # a blind boost would shove one of these to the top for 'render'.
        for i in range(EXACT_BARE_NAME_CAP + 4):
            files[f"app/gen{i}.py"] = (
                f"class Widget{i}:\n"
                f"    def render(self, obj):\n"
                f"        'Draw widget part {i}.'\n"
                f"        return obj\n"
            )
        # Neutral filler: keeps corpus idf non-degenerate so bm25 (and the
        # bounded candidate window) behave like a real repository instead
        # of a microscopic one where every doc matches every term.
        for i in range(20):
            files[f"app/filler{i}.py"] = (
                f"def filler_task{i}(payload):\n"
                f"    'Unrelated payload step {i}.'\n"
                f"    return payload\n"
            )
        return files

    def test_qualified_context_not_buried_by_popular_bare_name(self):
        self._db_with(self._ambig_corpus())
        hits = self.db.search_fts("template render", limit=5)
        self.assertTrue(hits)
        syms = [h["symbol"] for h in hits]
        self.assertIn("Template.render", syms[:2],
                      "intended qualified match must not be buried")
        widget_ranks = [i for i, s in enumerate(syms) if s.startswith("Widget")]
        template_rank = syms.index("Template.render")
        for r in widget_ranks:
            self.assertLess(template_rank, r,
                            "unrelated same-bare-name method outranks the intent")

    def test_mcp_path_same_guarantee(self):
        self._db_with(self._ambig_corpus())
        svc = self._mcp()
        results = svc.search("template render", limit=5,
                             assurance=False)["results"]
        self.assertTrue(results)
        syms = [h["symbol"] for h in results]
        self.assertIn("Template.render", syms[:2],
                      "mcp: intended qualified match must not be buried")
        widget_ranks = [i for i, s in enumerate(syms) if s.startswith("Widget")]
        template_rank = syms.index("Template.render")
        for r in widget_ranks:
            self.assertLess(template_rank, r)

    def test_bare_name_alone_stays_relevant_when_dampened(self):
        self._db_with(self._ambig_corpus())
        # Boost withdrawn (ambiguous): bm25 decides, but the top of the
        # list must still be exact-bare-name render methods — never an
        # unrelated node riding a generic body match. (search_fts returns
        # the whole candidate window; judge the top `limit` like callers do.)
        hits = self.db.search_fts("render", limit=10)[:10]
        self.assertTrue(hits)
        for h in hits:
            self.assertTrue(
                h["symbol"].endswith(".render") or h["symbol"] == "render",
                f"irrelevant node surfaced for bare 'render': {h['symbol']}")


class ExactVsPrefixDistinction(BareNameRankingTestCase):
    def test_exact_bare_outranks_prefix_matches(self):
        self._db_with({
            "app/draw.py": (
                "def render(scene):\n"
                "    'Draw the scene.'\n"
                "    return scene\n"
                "\n"
                "def render_widget(w):\n"
                "    'Draw one widget.'\n"
                "    return w\n"
                "\n"
                "def rendering_pipeline(frames):\n"
                "    'Run every drawing pass over frames.'\n"
                "    return frames\n"
            ),
        })
        hits = self.db.search_fts("render", limit=5)
        self.assertEqual(hits[0]["symbol"], "render",
                         "exact 'render' must outrank render_widget/rendering_pipeline")


class BareFunctionNotInSameNamedClass(BareNameRankingTestCase):
    def test_bare_function_wins_for_bare_query(self):
        self._db_with({
            "app/textops.py": (
                "def normalize(text):\n"
                "    'Normalize unicode text.'\n"
                "    return text\n"
            ),
            "app/color.py": (
                "class Color:\n"
                "    def normalize(self):\n"
                "        'Normalize this color in place.'\n"
                "        return self\n"
            ),
            "app/legacy.py": (
                "def normalize_content(blob):\n"
                "    'Normalize legacy content blobs.'\n"
                "    return blob\n"
            ),
        })
        for label, search in (("fts", self.db.search_fts("normalize", limit=5)),):
            self.assertEqual(
                search[0]["symbol"], "normalize",
                f"{label}: bare function must outrank method/prefix matches")
        svc = self._mcp()
        results = svc.search("normalize", limit=5, assurance=False)["results"]
        self.assertEqual(results[0]["symbol"], "normalize",
                         "mcp: bare function must win for bare query")


class TokenizerMigration(BareNameRankingTestCase):
    def test_legacy_tokenchars_index_is_rebuilt_on_writer_open(self):
        self._db_with({"app/viewer.py": VIEWER})
        self.db.close()
        # Simulate a legacy index created with the superseded tokenchars DDL.
        import sqlite3

        conn = sqlite3.connect(os.path.join(self.test_dir, ".sot", "test.db"))
        conn.executescript(
            "DROP TRIGGER IF EXISTS trg_nodes_ai;"
            "DROP TRIGGER IF EXISTS trg_nodes_ad;"
            "DROP TRIGGER IF EXISTS trg_nodes_au;"
            "DROP TABLE IF EXISTS graph_fts;"
            "CREATE VIRTUAL TABLE graph_fts USING fts5("
            "    label, fqn, body, keywords, content='graph_nodes',"
            "    content_rowid='rowid',"
            "    tokenize=\"unicode61 remove_diacritics 0 tokenchars '_-.:$@'\""
            ");"
        )
        conn.execute("INSERT INTO graph_fts(graph_fts) VALUES('rebuild')")
        conn.commit()
        conn.close()
        # Reopening (writer) must detect the stale tokenizer, rebuild, and
        # restore bare-name matches against qualified symbols.
        self.db = Database(os.path.join(self.test_dir, ".sot", "test.db"))
        sql = self.db.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='graph_fts'"
        ).fetchone()[0]
        self.assertNotIn("tokenchars", sql)
        hits = self.db.search_fts("render", limit=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["symbol"], "Viewer.render")


if __name__ == "__main__":
    unittest.main()
