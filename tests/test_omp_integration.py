"""
test_omp_integration.py — End-to-End Test Scenarios for SOT-Graph and OMP Harness Integration.

Validates all 10 core operational scenarios:
1. Reconcile & full codebase synchronization
2. Verified Search with [STRONG] / [WEAK] trust verdicts
3. AST Cross-file Graph Exploration
4. Real-time disk verification & drift detection
5. Self-healing & auto-purging on file deletion
6. Knowledge note insertion and semantic retrieval
7. Community detection & Modularity Q calculation
8. Database diagnostics (doctor), clean plan, and vacuum
9. Interactive HTML viz and multi-format exporters (GraphRAG, Obsidian, GraphML)
10. (retired — the native OMP/OpenCode adapters were removed; capabilities are MCP-only)
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import require_shebang_exec

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_SOT = REPO_ROOT / "bin" / "sotgraph"


class TestOMPIntegrationScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = os.environ.copy()
        cls.env["PYTHONPATH"] = str(REPO_ROOT / "src")
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp_dir.name) / "sot.db"

    @classmethod
    def tearDownClass(cls):
        cls.tmp_dir.cleanup()

    def run_sot(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        require_shebang_exec()
        has_db = any(a == "--db" or a.startswith("--db=") for a in args)
        extra_args = [] if has_db else ["--db", str(self.db_path)]
        if sys.platform == "win32":
            # bin/sotgraph is a bash launcher; on Windows drive the CLI module
            # directly with the same PYTHONPATH the launcher exports.
            cmd = [sys.executable, "-m", "sot_graph.cli"] + extra_args + args
        else:
            cmd = [str(BIN_SOT)] + extra_args + args
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=self.env,
            capture_output=True,
            encoding="utf-8",  # the CLI reconfigures its streams to UTF-8
            errors="replace",  # on every platform; never locale-decode them
        )
        if check and proc.returncode != 0:
            self.fail(f"sotgraph command failed: {' '.join(cmd)}\nStdout: {proc.stdout}\nStderr: {proc.stderr}")
        return proc

    def test_scenario_01_reconcile_sync(self):
        """Scenario 1: Codebase Indexing & Synchronization."""
        res = self.run_sot(["reconcile", "--workers", "2"])
        self.assertIn("Reconcile complete", res.stdout)
        self.assertIn("failed", res.stdout)
        self.assertTrue(self.db_path.exists())

    def test_scenario_02_verified_search_trust_verdicts(self):
        """Scenario 2: Search with Trust Verdicts and Content Coverage."""
        res = self.run_sot(["search", "Database", "-n", "5"])
        self.assertIn("[STRONG", res.stdout)
        self.assertIn("Database", res.stdout)
        self.assertIn("cov:", res.stdout)

    def test_scenario_03_ast_explore(self):
        """Scenario 3: AST Cross-file Graph Exploration."""
        res = self.run_sot(["explore", "Database", "--depth", "2"])
        self.assertIn("Graph Walk:", res.stdout)
        self.assertTrue("Outward Calls" in res.stdout or "Incoming References" in res.stdout or "Defines" in res.stdout)

    def test_scenario_04_verify_drift(self):
        """Scenario 4: Drift Detection against Disk Reality.

        Runs against an isolated fixture repo. Asserting ZERO DRIFT on the
        live repository is inherently flaky: any repo file that changes
        between this class's reconcile (scenario 01) and this verify
        (another test's artifacts, a parallel process, an editor) is GENUINE
        drift and fails the assertion. Here drift is created deliberately
        (positive control), detected, then reconciled back to zero.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "app.py"
            app.write_text("def alpha():\n    return 1\n", encoding="utf-8")
            base = ["--db", str(root / "sot.db"), "--root", str(root)]

            res_add = self.run_sot(base + ["reconcile"])
            self.assertIn("Reconcile complete", res_add.stdout)

            # Positive control: journaled content changed on disk — deep
            # verify must report the file as drifted, never bless it with
            # a ZERO DRIFT verdict.
            app.write_text("def alpha():\n    return 2\n", encoding="utf-8")
            res_drift = self.run_sot(base + ["verify", "--deep"], check=False)
            self.assertEqual(res_drift.returncode, 1)
            self.assertIn("DRIFT DETECTED", res_drift.stdout)
            self.assertIn("hash_mismatch", res_drift.stdout)
            self.assertIn("app.py", res_drift.stdout)

            # Recovery: reconcile converges the graph; verify is zero again.
            res_fix = self.run_sot(base + ["reconcile"])
            self.assertIn("Reconcile complete", res_fix.stdout)
            res_ok = self.run_sot(base + ["verify", "--deep"])
            self.assertIn("ZERO DRIFT", res_ok.stdout)

    def test_scenario_05_self_healing_and_dead_path_autopurge(self):
        """Scenario 5: Self-Healing & Auto-Purging on File Deletion."""
        dummy_file = REPO_ROOT / "src" / "sot_graph" / "_dummy_omp_test.py"
        try:
            # Step A: Create temporary source file
            dummy_file.write_text("class DummyOMPTest:\n    def execute(self):\n        return True\n")
            
            # Step B: Reconcile -> file should be indexed
            res_add = self.run_sot(["reconcile"])
            self.assertIn("indexed/updated", res_add.stdout)

            # Step C: Search for temporary symbol
            res_search = self.run_sot(["search", "DummyOMPTest"])
            self.assertIn("[STRONG", res_search.stdout)
            self.assertIn("_dummy_omp_test.py", res_search.stdout)

            # Step D: Delete temporary file
            dummy_file.unlink()

            # Step E: Reconcile -> file should be automatically purged
            res_del = self.run_sot(["reconcile"])
            self.assertIn("purged", res_del.stdout)

            # Step F: Search again -> should not return active STRONG hit for deleted file
            res_search_after = self.run_sot(["search", "DummyOMPTest"])
            self.assertNotIn("_dummy_omp_test.py", res_search_after.stdout)
        finally:
            if dummy_file.exists():
                dummy_file.unlink()

    def test_scenario_06_knowledge_note_insertion_and_search(self):
        """Scenario 6: Knowledge Note Anchoring and Semantic Retrieval."""
        note_title = "OMP Native Tool Integration Guide"
        note_body = "Exposes sot_search and sot_explore as first-class native tools for Pi coding harness."
        note_keywords = "omp,pi,native,extension,tool"

        # Insert note
        res_insert = self.run_sot([
            "insert",
            "--title", note_title,
            "--body", note_body,
            "--keywords", note_keywords,
        ])
        self.assertIn("Stored knowledge node", res_insert.stdout)

        # Search note
        res_search = self.run_sot(["search", "OMP Native Tool Integration Guide"])
        self.assertIn("[STRONG", res_search.stdout)
        self.assertIn("OMP Native Tool Integration Guide", res_search.stdout)

    def test_scenario_07_community_detection_and_modularity(self):
        """Scenario 7: Graph Analytics & Louvain Clustering."""
        res_cluster = self.run_sot(["cluster"])
        self.assertIn("Detected", res_cluster.stdout)
        self.assertIn("Architectural Communities", res_cluster.stdout)

        res_report = self.run_sot(["report"])
        self.assertIn("Architectural report saved to", res_report.stdout)

    def test_scenario_08_doctor_and_database_maintenance(self):
        """Scenario 8: Database Diagnostics (Doctor) and Vacuum."""
        res_doc = self.run_sot(["doctor"])
        self.assertIn("SOT-Graph Doctor Report:", res_doc.stdout)
        self.assertIn("Graph Nodes", res_doc.stdout)
        self.assertIn("SQLite Database", res_doc.stdout)

        res_clean = self.run_sot(["clean", "--dry-run"])
        self.assertIn("Clean (stale):", res_clean.stdout)

        res_vac = self.run_sot(["vacuum", "--dry-run"])
        self.assertIn("Vacuum", res_vac.stdout)
    def test_scenario_09_viz_and_multi_format_exporters(self):
        """Scenario 9: Interactive HTML Visualizer & Multi-Format Exporters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # HTML Visualizer
            html_out = tmppath / "test_graph.html"
            self.run_sot(["viz", "-o", str(html_out)])
            self.assertTrue(html_out.exists())
            self.assertGreater(html_out.stat().st_size, 1000)
            self.assertIn("<!DOCTYPE html>", html_out.read_text())

            # GraphRAG JSON Export
            graphrag_out = tmppath / "graphrag.json"
            self.run_sot(["export", "--format", "graphrag", "-o", str(graphrag_out)])
            self.assertTrue(graphrag_out.exists())
            data = json.loads(graphrag_out.read_text())
            self.assertIn("entities", data)
            self.assertIn("relationships", data)
            self.assertIn("communities", data)

            # Obsidian Vault Export
            obsidian_out = tmppath / "obsidian_vault"
            self.run_sot(["export", "--format", "obsidian", "-o", str(obsidian_out)])
            self.assertTrue(obsidian_out.exists())
            md_files = list(obsidian_out.glob("*.md"))
            self.assertGreater(len(md_files), 0)

            # GraphML Export
            graphml_out = tmppath / "graph.graphml"
            self.run_sot(["export", "--format", "graphml", "-o", str(graphml_out)])
            self.assertTrue(graphml_out.exists())
            self.assertIn("<graphml", graphml_out.read_text())


if __name__ == "__main__":
    unittest.main()
