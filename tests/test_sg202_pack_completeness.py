"""
SG-202: Honest pack completeness tests.

Covers: completeness flips at the truncation boundary, never-silent ambiguous
targets, per-category discovered/returned/omitted accounting with reasons and
refs, seeds never silently dropped, the anti-inference signal on truncated
bundles, and the snapshot-generation binding (CLI + MCP included).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.cli import cmd_pack
from sot_graph.db import Database
from sot_graph.envelope import compute_snapshot_generation
from sot_graph.mcp_service import McpService
from sot_graph.pack import PackError, build_bundle, render_yaml
from sot_graph.reconciler import Reconciler

COMPLETE = "COMPLETE_WITHIN_INDEX_CAPABILITY"
TRUNCATED = "PARTIAL"


class SG202PackCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        # service_main: sizeable body (so token budgets can truncate it),
        # three inbound callers, one outbound callee, one 2-hop stub (top).
        service_body = "".join(
            f"    # padding comment line {i} to give the span real size\n"
            for i in range(40)
        )
        self.project_files = {
            "pkg/__init__.py": "# pkg root\n",
            "pkg/leaf.py": "def leaf_func():\n    return 42\n",
            "pkg/service.py": (
                "from pkg.leaf import leaf_func\n\n"
                "def service_main():\n"
                f"{service_body}"
                "    return leaf_func()\n"
            ),
            "pkg/app1.py": "from pkg.service import service_main\n\ndef run_one():\n    return service_main()\n",
            "pkg/app2.py": "from pkg.service import service_main\n\ndef run_two():\n    return service_main()\n",
            "pkg/app3.py": "from pkg.service import service_main\n\ndef run_three():\n    return service_main()\n",
            "pkg/top.py": "from pkg.app1 import run_one\n\ndef top():\n    return run_one()\n",
            "AGENTS.md": "# Agent Instructions\nSG202_MARKER_TRUSTED\nAlways verify budgets.\n",
        }
        self._write_files(self.project_files)
        self.db_path = os.path.join(self.test_dir, ".sot", "test.db")
        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, self.test_dir)
        self.reconciler.reconcile(workers=1)
        self.addCleanup(self.db.close)
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)

    def _write_files(self, files):
        for rel, content in files.items():
            path = Path(self.test_dir) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def _reconcile(self):
        self.reconciler.reconcile(workers=1)

    # --- 1. Honest completeness -------------------------------------------

    def test_complete_bundle_reports_within_index_capability(self):
        bundle = build_bundle(self.db, self.test_dir, "service_main")
        self.assertFalse(bundle["limits"]["truncated"])
        self.assertEqual(bundle["completeness"], COMPLETE)
        self.assertNotIn("absence_interpretation", bundle)
        text = render_yaml(bundle)
        self.assertIn(f'completeness: "{COMPLETE}"', text)
        self.assertNotIn("absence_interpretation", text)

    def test_completeness_flips_exactly_at_truncation_boundary(self):
        full = build_bundle(self.db, self.test_dir, "service_main")
        self.assertEqual(full["completeness"], COMPLETE)
        est = full["limits"]["tokens_estimate"]
        # Headroom covers the rendering delta of `max_tokens: <int>` vs null.
        headroom = 50

        # Above the natural size nothing is cut.
        above = build_bundle(self.db, self.test_dir, "service_main", max_tokens=est + headroom)
        self.assertFalse(above["limits"]["truncated"])
        self.assertEqual(above["completeness"], COMPLETE)

        # One token below the natural size: the projection must be cut and
        # say so — never a complete status on a truncated bundle.
        below = build_bundle(self.db, self.test_dir, "service_main", max_tokens=est - 1)
        self.assertTrue(below["limits"]["truncated"])
        self.assertEqual(below["completeness"], TRUNCATED)
        self.assertLessEqual(below["limits"]["tokens_estimate"], est - 1)
        self.assertNotIn(below["completeness"], ("COMPLETE", "GLOBAL_COMPLETE", COMPLETE))

        # And across the whole window the two fields can never disagree.
        for delta in range(0, headroom + 1):
            bundle = build_bundle(
                self.db, self.test_dir, "service_main", max_tokens=est - 1 + delta
            )
            with self.subTest(delta=delta):
                self.assertEqual(
                    bundle["limits"]["truncated"],
                    bundle["completeness"] == TRUNCATED,
                )

    # --- 2. Ambiguous targets are never silently picked -------------------

    def test_ambiguous_target_tie_fails_closed_with_candidates(self):
        self._write_files({
            "pkg/orphan_a.py": "def orphan_z():\n    return 1\n",
            "pkg/orphan_b.py": "def orphan_z():\n    return 2\n",
        })
        self._reconcile()
        with self.assertRaises(PackError) as ctx:
            build_bundle(self.db, self.test_dir, "orphan_z")
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_TARGET")
        self.assertEqual(len(ctx.exception.candidates), 2)

    def test_ambiguous_target_dominant_pick_is_explicit(self):
        self._write_files({"pkg/dup.py": "def service_main():\n    return -1\n"})
        self._reconcile()
        bundle = build_bundle(self.db, self.test_dir, "service_main")
        resolution = bundle["resolution"]
        # A bundle was returned, so the pick must be marked, never silent.
        self.assertEqual(resolution["status"], "AMBIGUOUS_AUTO_RESOLVED")
        self.assertEqual(resolution["selected_fqn"], "pkg.service.service_main")
        self.assertIn("pkg.dup.service_main", resolution["candidates"])
        self.assertTrue(
            any("ambiguous_target_auto_resolved" in w for w in bundle["limits"]["warnings"])
        )
        text = render_yaml(bundle)
        self.assertIn('status: "AMBIGUOUS_AUTO_RESOLVED"', text)
        self.assertIn('"pkg.dup.service_main"', text)

    def test_unambiguous_target_resolution_is_exact(self):
        bundle = build_bundle(self.db, self.test_dir, "service_main")
        self.assertEqual(bundle["resolution"]["status"], "EXACT")
        self.assertNotIn("candidates", bundle["resolution"])

    # --- 3. Per-category accounting ----------------------------------------

    def test_accounting_node_cap_discovered_returned_omitted(self):
        bundle = build_bundle(self.db, self.test_dir, "service_main", max_nodes=2)
        acct = bundle["accounting"]
        target_id = bundle["target"]["node_id"]
        db_inbound = self.db.conn.execute(
            "SELECT COUNT(DISTINCT src) FROM graph_edges "
            "WHERE dst = ? AND relation IN ('calls','extends')", (target_id,)
        ).fetchone()[0]
        self.assertGreaterEqual(db_inbound, 3)

        entry = acct["inbound_callers"]
        self.assertEqual(entry["discovered"], db_inbound)
        self.assertEqual(entry["returned"], len(bundle["inbound_callers"]))
        self.assertEqual(entry["discovered"], entry["returned"] + entry["omitted"])
        self.assertGreater(entry["omitted"], 0)
        self.assertEqual(entry["omit_reason"], "node_cap")
        self.assertEqual(len(entry["omitted_refs"]), entry["omitted"])

        out_entry = acct["outbound_callees"]
        self.assertEqual(out_entry["discovered"], out_entry["returned"] + out_entry["omitted"])
        # SG-202 priority selection: the direct contract outranks surplus
        # callers, so the node cap retains the callee (no omission, no
        # omit_reason) and spends the cap budget on callers instead.
        self.assertEqual(out_entry["omitted"], 0)
        self.assertNotIn("omit_reason", out_entry)

    def test_accounting_token_budget_reason_with_refs(self):
        full = build_bundle(self.db, self.test_dir, "service_main")
        self.assertGreater(full["accounting"]["transitive_stubs"]["discovered"], 0)
        est = full["limits"]["tokens_estimate"]
        tight = build_bundle(self.db, self.test_dir, "service_main", max_tokens=est - 1)
        acct = tight["accounting"]
        self.assertTrue(tight["limits"]["truncated"])
        # Stubs are dropped first, so their omission must be budget-attributed.
        self.assertGreater(acct["transitive_stubs"]["omitted"], 0)
        self.assertEqual(acct["transitive_stubs"]["omit_reason"], "token_budget_exhausted")
        self.assertTrue(acct["transitive_stubs"]["omitted_refs"])
        self.assertEqual(
            acct["transitive_stubs"]["discovered"],
            acct["transitive_stubs"]["returned"] + acct["transitive_stubs"]["omitted"],
        )
        self.assertIn("omitted_refs: [", render_yaml(tight))

    # --- 4. Seeds are never silently dropped -------------------------------

    def test_seed_target_and_instructions_accounted_when_complete(self):
        bundle = build_bundle(self.db, self.test_dir, "service_main")
        acct = bundle["accounting"]
        self.assertEqual(acct["target_source"], {"discovered": 1, "returned": 1, "omitted": 0})
        self.assertEqual(acct["instructions"]["returned"], 1)
        self.assertEqual(acct["instructions"]["omitted"], 0)
        self.assertIn("trusted_instructions", bundle)

    def test_dropped_seed_instructions_get_explicit_omission(self):
        big_agents = "# Agent Instructions\n" + ("Operator guidance line.\n" * 500)
        (Path(self.test_dir) / "AGENTS.md").write_text(big_agents, encoding="utf-8")
        # Budget above the metadata floor (~600 here) but far below the big
        # trusted block: the instructions seed must be dropped explicitly.
        bundle = build_bundle(self.db, self.test_dir, "service_main", max_tokens=700)
        # Seed dropped by budget -> explicit accounting, never silent.
        self.assertNotIn("trusted_instructions", bundle)
        entry = bundle["accounting"]["instructions"]
        self.assertEqual(entry["discovered"], 1)
        self.assertEqual(entry["returned"], 0)
        self.assertEqual(entry["omitted"], 1)
        self.assertEqual(entry["omit_reason"], "token_budget_exhausted")
        # The target seed block itself is never dropped as a block.
        self.assertEqual(bundle["accounting"]["target_source"]["returned"], 1)
        self.assertTrue(
            any("trusted instructions omitted" in w for w in bundle["limits"]["warnings"])
        )

    # --- 5. Anti-inference signal -------------------------------------------

    def test_truncated_bundle_carries_anti_inference_note(self):
        full = build_bundle(self.db, self.test_dir, "service_main")
        tight = build_bundle(
            self.db, self.test_dir, "service_main",
            max_tokens=full["limits"]["tokens_estimate"] - 1,
        )
        self.assertTrue(tight["limits"]["truncated"])
        note = tight["absence_interpretation"]
        self.assertIn("zero callers", note)
        text = render_yaml(tight)
        self.assertIn("absence_interpretation:", text)
        # The note sits directly above the neighbor sections.
        self.assertLess(text.index("absence_interpretation:"), text.index("inbound_callers:"))
        # And the complete bundle makes no such claim.
        self.assertNotIn("absence_interpretation", render_yaml(full))

    # --- 6. Snapshot binding -------------------------------------------------

    def test_snapshot_generation_binding_detects_reconcile(self):
        bundle = build_bundle(self.db, self.test_dir, "service_main")
        self.assertEqual(bundle["snapshot_generation"], compute_snapshot_generation(self.db))
        self.assertIn(
            f"snapshot_generation: {bundle['snapshot_generation']}", render_yaml(bundle)
        )
        # A change + reconcile bumps the global generation: stale bundles
        # become detectable by comparing snapshot_generation.
        app1 = Path(self.test_dir) / "pkg/app1.py"
        app1.write_text(app1.read_text() + "\ndef run_one_late():\n    return service_main()\n")
        self._reconcile()
        refreshed = build_bundle(self.db, self.test_dir, "service_main")
        self.assertGreater(refreshed["snapshot_generation"], bundle["snapshot_generation"])

    # --- 7. Surfaces share one interpretation --------------------------------

    def test_mcp_surface_reports_honesty_fields(self):
        svc = McpService(self.db_path, project_root=self.test_dir)
        res = svc.pack_context_bundle("service_main")
        self.assertTrue(res["ok"])
        direct = build_bundle(self.db, self.test_dir, "service_main")
        self.assertEqual(res["completeness"], direct["completeness"])

        tight = svc.pack_context_bundle("service_main", max_tokens=700)
        self.assertTrue(tight["ok"])
        self.assertTrue(tight["limits"]["truncated"])
        self.assertEqual(tight["completeness"], TRUNCATED)

        self._write_files({
            "pkg/orphan_a.py": "def orphan_z():\n    return 1\n",
            "pkg/orphan_b.py": "def orphan_z():\n    return 2\n",
        })
        self._reconcile()
        err = svc.pack_context_bundle("orphan_z")
        self.assertFalse(err["ok"])
        self.assertEqual(err["code"], "AMBIGUOUS_TARGET")
        self.assertTrue(err["candidates"])

    def test_cli_json_envelope_reports_honesty_fields(self):
        args = argparse.Namespace(
            target="service_main", max_hops=2, max_nodes=50, max_bytes=65536,
            max_tokens=None, json=True, output=None,
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ret = cmd_pack(args, self.db, self.test_dir)
        self.assertEqual(ret, 0)
        envelope = json.loads(buf.getvalue())
        self.assertEqual(envelope["completeness"], COMPLETE)
        self.assertEqual(envelope["snapshot_generation"], compute_snapshot_generation(self.db))
        self.assertNotIn("truncated", envelope)

        tight_args = argparse.Namespace(
            target="service_main", max_hops=2, max_nodes=50, max_bytes=65536,
            max_tokens=700, json=True, output=None,
        )
        buf_tight = io.StringIO()
        with contextlib.redirect_stdout(buf_tight):
            ret_tight = cmd_pack(tight_args, self.db, self.test_dir)
        self.assertEqual(ret_tight, 0)
        tight_envelope = json.loads(buf_tight.getvalue())
        self.assertTrue(tight_envelope["truncated"])
        self.assertEqual(tight_envelope["completeness"], TRUNCATED)

    def test_cli_yaml_output_contains_honesty_fields(self):
        args = argparse.Namespace(
            target="service_main", max_hops=2, max_nodes=50, max_bytes=65536,
            max_tokens=700, json=False, output=None,
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ret = cmd_pack(args, self.db, self.test_dir)
        self.assertEqual(ret, 0)
        output = buf.getvalue()
        self.assertIn('completeness: "PARTIAL"', output)
        self.assertIn("absence_interpretation:", output)
        self.assertIn("accounting:", output)


if __name__ == "__main__":
    unittest.main()
