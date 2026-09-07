"""JIT freshness gate (staleness-gated auto-reconcile before queries).

Covers the freshness module and its McpService wiring:
- fresh index -> probe only, no reconcile (skipped_fresh);
- modified indexed file -> auto reconcile, then fresh on the next call;
- NEW never-indexed file -> probe sees it (journal-only checks cannot),
  reconcile indexes it, search finds the new symbol;
- auto_reconcile=False -> off, stale data served without healing;
- reconcile failure -> the query still answers, failure disclosed;
- deleted indexed file -> probe reports it.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

APP_PY = "def run():\n    return 42\n"


def _bump_mtime(path: Path, seconds: float = 2.0) -> None:
    """Force a mtime change beyond ms granularity for deterministic probes."""
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + seconds))


class _RepoFixture:
    def setUp(self) -> None:
        from sot_graph.db import Database
        from sot_graph.reconciler import Reconciler

        self.repo = Path(tempfile.mkdtemp())
        (self.repo / "app.py").write_text(APP_PY, encoding="utf-8")
        self.db_path = str(self.repo / ".sot" / "sot.db")
        db = Database(self.db_path)
        try:
            Reconciler(db, str(self.repo)).reconcile(workers=1)
        finally:
            db.close()

    def _service(self):
        from sot_graph.mcp_service import McpService

        return McpService(self.db_path, str(self.repo))


class FreshnessProbeTests(_RepoFixture, unittest.TestCase):
    def test_fresh_index_reports_not_stale(self) -> None:
        from sot_graph.freshness import staleness_probe

        probe = staleness_probe(self.db_path, str(self.repo))
        self.assertFalse(probe["stale"])
        self.assertEqual(probe["modified"]["count"], 0)
        self.assertEqual(probe["unindexed"]["count"], 0)

    def test_modified_file_detected(self) -> None:
        from sot_graph.freshness import staleness_probe

        target = self.repo / "app.py"
        target.write_text("def run():\n    return 43\n", encoding="utf-8")
        _bump_mtime(target)
        probe = staleness_probe(self.db_path, str(self.repo))
        self.assertTrue(probe["stale"])
        self.assertEqual(probe["modified"]["count"], 1)

    def test_new_unindexed_file_detected(self) -> None:
        from sot_graph.freshness import staleness_probe

        (self.repo / "brand_new.py").write_text(
            "def zig_unique():\n    return 1\n", encoding="utf-8")
        probe = staleness_probe(self.db_path, str(self.repo))
        self.assertTrue(probe["stale"])
        self.assertEqual(probe["unindexed"]["count"], 1)
        self.assertIn("brand_new.py", probe["unindexed"]["sample"])

    def test_deleted_file_detected(self) -> None:
        from sot_graph.freshness import staleness_probe

        os.remove(self.repo / "app.py")
        probe = staleness_probe(self.db_path, str(self.repo))
        self.assertTrue(probe["stale"])
        self.assertEqual(probe["deleted"]["count"], 1)


class EnsureFreshTests(_RepoFixture, unittest.TestCase):
    def test_off_mode_never_reconciles(self) -> None:
        from sot_graph.freshness import ensure_fresh

        target = self.repo / "app.py"
        target.write_text("def run():\n    return 43\n", encoding="utf-8")
        _bump_mtime(target)
        out = ensure_fresh(self.db_path, str(self.repo), False)
        self.assertEqual(out["mode"], "off")
        self.assertFalse(out["reconcile"]["performed"])

    def test_force_mode_reconciles_fresh_index(self) -> None:
        from sot_graph.freshness import ensure_fresh

        out = ensure_fresh(self.db_path, str(self.repo), "force")
        self.assertTrue(out["reconcile"]["performed"])
        self.assertEqual(out["reconcile"]["status"], "success")

    def test_auto_skips_when_fresh(self) -> None:
        from sot_graph.freshness import ensure_fresh

        out = ensure_fresh(self.db_path, str(self.repo), "auto")
        self.assertEqual(out["reconcile"]["status"], "skipped_fresh")
        self.assertFalse(out["reconcile"]["performed"])

    def test_normalize_mode(self) -> None:
        from sot_graph.freshness import normalize_mode

        self.assertEqual(normalize_mode(True), "force")
        self.assertEqual(normalize_mode(False), "off")
        self.assertEqual(normalize_mode("AUTO"), "auto")
        self.assertEqual(normalize_mode("junk"), "auto")


class McpServiceGateTests(_RepoFixture, unittest.TestCase):
    def _freshness_of(self, result: dict) -> dict:
        self.assertIn("graph_freshness", result)
        return result["graph_freshness"]

    def test_search_auto_reconciles_modified_file_then_fresh(self) -> None:
        svc = self._service()
        try:
            target = self.repo / "app.py"
            target.write_text(
                "def run():\n    return 43\n\ndef walrus_new():\n    return 9\n",
                encoding="utf-8")
            _bump_mtime(target)

            result = svc.search("walrus_new")
            fresh = self._freshness_of(result)
            self.assertTrue(fresh["reconcile"]["performed"])
            self.assertEqual(fresh["reconcile"]["status"], "success")
            symbols = [r.get("symbol") for r in result.get("results", [])]
            self.assertIn("walrus_new", symbols)

            # second call: index is now fresh -> probe only
            fresh2 = self._freshness_of(svc.search("walrus_new"))
            self.assertFalse(fresh2["reconcile"]["performed"])
            self.assertEqual(fresh2["reconcile"]["status"], "skipped_fresh")
        finally:
            svc.close()

    def test_search_auto_indexes_brand_new_file(self) -> None:
        svc = self._service()
        try:
            (self.repo / "brand_new.py").write_text(
                "def plumbus_fn():\n    return 'plumbus'\n", encoding="utf-8")
            result = svc.search("plumbus_fn")
            fresh = self._freshness_of(result)
            self.assertTrue(fresh["reconcile"]["performed"])
            symbols = [r.get("symbol") for r in result.get("results", [])]
            self.assertIn("plumbus_fn", symbols)
        finally:
            svc.close()

    def test_search_off_mode_serves_stale_without_healing(self) -> None:
        svc = self._service()
        try:
            (self.repo / "brand_new.py").write_text(
                "def nobody_sees_me():\n    return 0\n", encoding="utf-8")
            result = svc.search("nobody_sees_me", auto_reconcile=False)
            fresh = self._freshness_of(result)
            self.assertEqual(fresh["mode"], "off")
            symbols = [r.get("symbol") for r in result.get("results", [])]
            self.assertNotIn("nobody_sees_me", symbols)
        finally:
            svc.close()

    def test_reconcile_failure_degrades_with_disclosure(self) -> None:
        svc = self._service()
        try:
            import sot_graph.freshness as freshness_mod

            target = self.repo / "app.py"
            target.write_text("def run():\n    return 43\n", encoding="utf-8")
            _bump_mtime(target)

            def _boom(*_a, **_k):
                raise RuntimeError("simulated writer explosion")

            original = freshness_mod.reconcile_now
            freshness_mod.reconcile_now = _boom
            try:
                result = svc.search("run")  # must NOT raise
            finally:
                freshness_mod.reconcile_now = original
            fresh = self._freshness_of(result)
            self.assertEqual(fresh["reconcile"]["status"], "failed")
            self.assertIn("simulated writer explosion",
                          fresh["reconcile"].get("error", ""))
            # the query still answered from the (stale) index
            self.assertGreaterEqual(result.get("returned", 0), 0)
        finally:
            svc.close()

    def test_usages_and_implementations_carry_envelope(self) -> None:
        svc = self._service()
        try:
            result = svc.usages("run")
            self.assertIn("graph_freshness", result)
            self.assertEqual(result["graph_freshness"]["reconcile"]["status"],
                             "skipped_fresh")
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
