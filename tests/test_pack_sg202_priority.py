"""SG-202 dedicated pack regression tests: priority-aware budget delivery.

Pins the budget-starvation fix and the honest edge behaviors of
``sot_graph.pack.build_bundle``:

- at an unchanged 1500-token budget the serialized bundle keeps the target
  identity, the direct outbound contracts, and a test-module usage caller,
  with optional content (trusted instructions, transitive stubs) shed first;
- tiny budgets degrade honestly (never silent: accounting + truncated flag)
  and fail closed only when the metadata floor alone exceeds the budget;
- an oversize source span is delivered truncated with explicit warnings
  instead of failing the whole bundle (no TARGET_TOO_LARGE raise);
- ambiguous bare-name targets still fail closed with candidates;
- the reported tokens_estimate equals the actual serialized render size.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.db import Database
from sot_graph.pack import PackError, build_bundle, render_yaml
from sot_graph.reconciler import Reconciler
from sot_graph.tokenizer import estimate_tokens

BUDGET = 1500
TRUNCATED = "PARTIAL"

SERVICE_BODY = "".join(
    f"    # padding comment line {i} to give the span real size\n"
    for i in range(120)
)

# several same-line-range production callers so the OLD raw-line-order
# node-cap selection would have dropped the test-module caller
PROD_CALLERS = {
    f"pkg/prod_{i}.py": (
        f"from pkg.service import service_main\n\n"
        f"def run_{i}():\n    return service_main()\n"
    )
    for i in range(4)
}

PROJECT_FILES = {
    "pkg/__init__.py": "# pkg root\n",
    "pkg/leaf.py": "def leaf_helper():\n    return 42\n",
    # service_main has a same-FILE callee (_local_helper) and a same-DIR
    # callee (leaf_helper) to pin the exact-file -> same-dir -> other order
    "pkg/service.py": (
        "from pkg.leaf import leaf_helper\n\n"
        "def _local_helper(x):\n    return x\n\n"
        "def service_main():\n"
        f"{SERVICE_BODY}"
        "    return _local_helper(leaf_helper())\n"
    ),
    # production callers with EARLIER call-site lines than the test caller
    **PROD_CALLERS,
    # 2-hop stub chain: top -> run_0 -> service_main
    "pkg/top.py": (
        "from pkg.prod_0 import run_0\n\n"
        "def top():\n    return run_0()\n"
    ),
    "tests/__init__.py": "# tests root\n",
    "tests/test_service.py": (
        "from pkg.service import service_main\n\n"
        "class TestService:\n"
        "    def test_calls_main(self):\n"
        "        return service_main()\n"
    ),
    "AGENTS.md": (
        "# Agent Instructions\nSG202_PRIORITY_MARKER_TRUSTED\n"
        "Always verify budgets.\n"
    ),
}

BIG_AGENTS_MD = "# Agent Instructions\n" + ("Operator guidance line.\n" * 500)

OVERSIZE_FUNCTION = (
    "def big_span():\n"
    + "".join(f"    x{i} = {i}  # padding to push the span past 64KiB\n"
              for i in range(3000))
    + "    return x0\n"
)


class SG202PackPriorityTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self._write_files(PROJECT_FILES)
        self.db_path = os.path.join(self.test_dir, ".sot", "test.db")
        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, self.test_dir)
        self.reconciler.reconcile(workers=1)
        self.addCleanup(self.db.close)

    def _write_files(self, files):
        for rel, content in files.items():
            path = Path(self.test_dir) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def _reconcile(self):
        self.reconciler.reconcile(workers=1)

    def _build(self, **kwargs):
        return build_bundle(self.db, self.test_dir, "service_main",
                            max_hops=2, max_nodes=50, max_bytes=65_536,
                            **kwargs)

    # --- 1. The 1500-token contract: identity + contracts + test caller ---

    def test_budget_keeps_contracts_and_test_caller(self):
        bundle = self._build(max_tokens=BUDGET)
        rendered = render_yaml(bundle)
        self.assertLessEqual(estimate_tokens(rendered), BUDGET)
        # direct outbound contract delivered with identity fields
        callees = bundle["outbound_callees"]
        self.assertTrue(callees, "direct contract dropped under budget")
        self.assertTrue(
            any(c["fqn"].endswith("leaf_helper") and
                c["relative_path"] == "pkg/leaf.py" for c in callees))
        # a usage caller is retained and the TEST module outranks the
        # production caller despite its later call-site line
        callers = bundle["inbound_callers"]
        self.assertTrue(callers, "usage caller dropped under budget")
        self.assertTrue(callers[0]["relative_path"].startswith("test"),
                        callers[0]["relative_path"])
        self.assertIn("tests", Path(callers[0]["relative_path"]).parts)

    def test_reported_tokens_equal_serialized_render(self):
        bundle = self._build(max_tokens=BUDGET)
        self.assertEqual(bundle["limits"]["tokens_estimate"],
                         estimate_tokens(render_yaml(bundle)))

    # --- 2. Budget starvation: optional content yields before code context

    def test_trusted_instructions_yield_before_code_context(self):
        self._write_files({"AGENTS.md": BIG_AGENTS_MD})
        self._reconcile()
        bundle = self._build(max_tokens=BUDGET)
        rendered = render_yaml(bundle)
        # the ~13KB trusted block must NOT crowd the code context out
        self.assertNotIn("trusted_instructions", bundle)
        self.assertGreater(len(bundle["outbound_callees"]), 0,
                           "instructions starved the direct contracts")
        self.assertGreater(len(bundle["inbound_callers"]), 0,
                           "instructions starved the usage caller")
        # honesty: the omission is explicit, never silent
        entry = bundle["accounting"]["instructions"]
        self.assertEqual(entry["discovered"], 1)
        self.assertEqual(entry["returned"], 0)
        self.assertEqual(entry["omit_reason"], "token_budget_exhausted")
        self.assertTrue(
            any("trusted instructions omitted" in w
                for w in bundle["limits"]["warnings"]))
        self.assertLessEqual(estimate_tokens(rendered), BUDGET)

    def test_transitive_stubs_omit_reason_attributed(self):
        bundle = self._build(max_tokens=BUDGET)
        acct = bundle["accounting"]
        self.assertGreater(acct["transitive_stubs"]["omitted"], 0)
        self.assertEqual(acct["transitive_stubs"]["omit_reason"],
                         "token_budget_exhausted")
        self.assertTrue(bundle["limits"]["truncated"])
        self.assertEqual(bundle["completeness"], TRUNCATED)

    def test_omitted_refs_sample_thin_under_budget(self):
        bundle = self._build(max_tokens=BUDGET)
        for category, entry in bundle["accounting"].items():
            refs = entry.get("omitted_refs") or []
            self.assertLessEqual(len(refs), 1, category)
            if entry.get("omitted"):
                self.assertTrue(entry.get("omit_reason"), category)

    # --- 3. Accounting invariants hold under pruning ----------------------

    def test_accounting_invariants_under_budget(self):
        bundle = self._build(max_tokens=BUDGET)
        target_id = bundle["target"]["node_id"]
        for category in ("inbound_callers", "outbound_callees",
                         "transitive_stubs"):
            entry = bundle["accounting"][category]
            self.assertEqual(entry["discovered"],
                             entry["returned"] + entry["omitted"], category)
        # discovered counts agree with the indexed graph, not with success
        db_in = self.db.conn.execute(
            "SELECT COUNT(DISTINCT src) FROM graph_edges "
            "WHERE dst = ? AND relation IN ('calls','extends')",
            (target_id,)).fetchone()[0]
        self.assertEqual(
            bundle["accounting"]["inbound_callers"]["discovered"], db_in)

    def test_absence_note_present_on_truncated_bundle(self):
        bundle = self._build(max_tokens=BUDGET)
        text = render_yaml(bundle)
        self.assertIn("absence_interpretation:", text)
        self.assertLess(text.index("absence_interpretation:"),
                        text.index("inbound_callers:"))

    # --- 4. Tiny budgets: honest degradation, fail-closed only at floor ---

    def test_tiny_budget_returns_target_identity_within_limit(self):
        # Slightly above the pure-metadata floor: the bundle degrades to
        # identity + truncated source and says so, within the hard limit.
        bundle = self._build(max_tokens=620)
        rendered = render_yaml(bundle)
        self.assertLessEqual(estimate_tokens(rendered), 620)
        self.assertEqual(bundle["target"]["symbol"], "service_main")
        self.assertEqual(bundle["target"]["fqn"], "pkg.service.service_main")
        self.assertEqual(bundle["limits"]["truncated"], True)
        self.assertEqual(bundle["completeness"], TRUNCATED)
        # nothing vanished silently
        acct = bundle["accounting"]
        for category in ("inbound_callers", "outbound_callees",
                         "transitive_stubs"):
            entry = acct[category]
            self.assertEqual(entry["discovered"],
                             entry["returned"] + entry["omitted"], category)
            if entry["omitted"]:
                self.assertTrue(entry["omit_reason"], category)

    def test_budget_below_metadata_floor_fails_closed(self):
        # Below the pure-metadata floor no honest bundle exists: fail closed
        # with BUDGET_TOO_SMALL rather than return a bundle that lies about
        # its own size.
        for tiny in (32, 40):
            with self.subTest(budget=tiny):
                with self.assertRaises(PackError) as ctx:
                    self._build(max_tokens=tiny)
                self.assertEqual(ctx.exception.code, "BUDGET_TOO_SMALL")

    # --- 5. Oversize source span: truncated delivery, not a pack error ----

    def test_oversize_source_delivered_truncated_without_error(self):
        self._write_files({"pkg/big.py": OVERSIZE_FUNCTION})
        self._reconcile()
        bundle = build_bundle(self.db, self.test_dir, "big_span")
        source = bundle["target"]["full_source"]
        self.assertTrue(source)
        self.assertLessEqual(len(source.encode("utf-8")), 65_536)
        self.assertTrue(bundle["limits"]["truncated"])
        self.assertEqual(bundle["completeness"], TRUNCATED)
        self.assertTrue(
            any("target_source_oversize" in w for w in bundle["limits"]["warnings"]))
        self.assertEqual(
            bundle["accounting"]["target_source"]["truncated"], True)

    def test_oversize_source_within_token_budget(self):
        self._write_files({"pkg/big.py": OVERSIZE_FUNCTION})
        self._reconcile()
        bundle = build_bundle(self.db, self.test_dir, "big_span",
                              max_tokens=BUDGET)
        self.assertLessEqual(estimate_tokens(render_yaml(bundle)), BUDGET)
        self.assertEqual(bundle["target"]["symbol"], "big_span")

    def test_read_cap_bounds_memory_on_giant_file(self):
        # A file larger than _MAX_SOURCE_READ_BYTES is never materialized in
        # full: the freshness hash streams (so the snapshot stays FRESH) and
        # a span reaching past the materialized prefix is flagged explicitly.
        giant = (
            "def giant_span():\n"
            + "".join(f"    x{i} = {i}  # padding beyond the 1MiB read cap\n"
                      for i in range(40000))
            + "    return x0\n"
        )
        self.assertGreater(len(giant.encode("utf-8")), 1_048_576)
        self._write_files({"pkg/giant.py": giant})
        self._reconcile()
        bundle = build_bundle(self.db, self.test_dir, "giant_span")
        self.assertEqual(bundle["target"]["symbol"], "giant_span")
        source = bundle["target"]["full_source"]
        self.assertTrue(source)
        self.assertLessEqual(len(source.encode("utf-8")), 1_048_576)
        self.assertTrue(
            any("source_read_bounded" in w for w in bundle["limits"]["warnings"]))
        # streaming hash kept the freshness binding exact: no STALE_SNAPSHOT

    def test_outbound_order_exact_file_then_dir_then_other(self):
        bundle = build_bundle(self.db, self.test_dir, "service_main")
        fqns = [c["fqn"] for c in bundle["outbound_callees"]]
        paths = [c["relative_path"] for c in bundle["outbound_callees"]]
        self.assertEqual(paths, sorted(paths, key=lambda p: p != "pkg/service.py"))
        self.assertTrue(fqns[0].endswith("_local_helper"), fqns)
        self.assertTrue(fqns[1].endswith("leaf_helper"), fqns)

    # --- 7. Node-cap and byte-cap scarcity keep the valuable neighbors ----

    def test_node_cap_keeps_test_caller_despite_earlier_prod_lines(self):
        # Several production callers have earlier call-site lines than the
        # test caller; raw discovery order would spend the node cap on them
        # and irrecoverably lose the test usage example.
        bundle = build_bundle(self.db, self.test_dir, "service_main",
                              max_hops=2, max_nodes=3, max_bytes=65_536)
        callers = bundle["inbound_callers"]
        self.assertTrue(callers)
        self.assertTrue(
            all(c["relative_path"].startswith("test") for c in callers[:1]),
            f"test caller lost under node cap: {callers}")
        acct = bundle["accounting"]
        self.assertGreater(acct["inbound_callers"]["omitted"], 0)
        self.assertEqual(acct["inbound_callers"]["omit_reason"], "node_cap")

    def test_node_cap_reserved_test_then_contract_then_surplus(self):
        # Priority classes under the cap: reserved test caller, then direct
        # contracts, then surplus callers — max_nodes=2 must retain exactly
        # the reserved test caller and the same-file contract.
        bundle = build_bundle(self.db, self.test_dir, "service_main",
                              max_hops=2, max_nodes=2, max_bytes=65_536)
        self.assertEqual(len(bundle["inbound_callers"]), 1)
        self.assertTrue(bundle["inbound_callers"][0]["relative_path"]
                        .startswith("test"))
        self.assertEqual(len(bundle["outbound_callees"]), 1)
        self.assertTrue(bundle["outbound_callees"][0]["fqn"]
                        .endswith("_local_helper"))
        acct = bundle["accounting"]
        self.assertEqual(acct["inbound_callers"]["omit_reason"], "node_cap")
        self.assertEqual(acct["outbound_callees"]["omit_reason"], "node_cap")

    def test_byte_cap_shrinks_source_before_contracts(self):
        natural = build_bundle(self.db, self.test_dir, "service_main")
        natural_source = natural["target"]["full_source"]
        tight = build_bundle(self.db, self.test_dir, "service_main",
                             max_bytes=4096)
        # direct contract NOT sacrificed for the source span
        self.assertTrue(tight["outbound_callees"],
                        "byte cap dropped direct contracts before source")
        self.assertTrue(
            any(c["fqn"].endswith("leaf_helper")
                for c in tight["outbound_callees"]))
        # source shrank instead, and the shrink is explicit with counts
        self.assertLess(len(tight["target"]["full_source"].encode("utf-8")),
                        len(natural_source.encode("utf-8")))
        src_entry = tight["accounting"]["target_source"]
        self.assertTrue(src_entry["truncated"])
        self.assertEqual(src_entry["partial"], True)
        self.assertGreater(src_entry["returned_lines"], 0)
        self.assertLess(src_entry["returned_lines"],
                        src_entry["recorded_lines"])
        self.assertEqual(src_entry["omit_reason"], "byte_budget_exhausted")
        self.assertIn("partial: true", render_yaml(tight))

    def test_byte_cap_below_metadata_floor_stays_honest(self):
        # A 256-byte cap cannot hold even the metadata floor: no empty
        # shell, no crash — the identity and source floor survive and the
        # unreachable cap is declared.
        bundle = build_bundle(self.db, self.test_dir, "service_main",
                              max_bytes=256)
        self.assertTrue(bundle["target"]["full_source"])
        self.assertEqual(bundle["target"]["symbol"], "service_main")
        self.assertTrue(
            any("byte_cap_unreachable" in w for w in bundle["limits"]["warnings"]))

    # --- 8. Dense hubs: the frozen-replay reconcile regression -------------

    def test_dense_hub_budget_keeps_reserved_test_and_contracts(self):
        # reconcile-shaped dense hub (>50 neighbors): at the unchanged
        # 1500-token budget the reserved tests/-rooted usage caller and the
        # direct contracts must survive together with a useful source share
        # (allocation + metadata compaction absorb the pressure) — the
        # frozen replay showed success flipping to MISSING_TEST when the
        # token pass popped the reserved caller after squeezing the source.
        files = {
            "pkg/hub.py": (
                "from pkg.h_a import h_a\n"
                "from pkg.h_b import h_b\n"
                "from pkg.h_c import h_c\n\n"
                "def _hub_helper(x):\n    return x\n\n"
                "def hub_fn():\n"
                + "".join(
                    f"    # hub padding line {i} to give the span real size\n"
                    for i in range(120))
                + "    return _hub_helper(h_a(h_b(h_c())))\n"
            ),
            "pkg/h_a.py": "def h_a(x=1):\n    return x\n",
            "pkg/h_b.py": "def h_b(x=2):\n    return x\n",
            "pkg/h_c.py": "def h_c(x=3):\n    return x\n",
        }
        for i in range(56):
            files[f"pkg/hub_user_{i}.py"] = (
                f"from pkg.hub import hub_fn\n\n"
                f"def use_{i}():\n    return hub_fn()\n")
        files["tests/test_hub.py"] = (
            "from pkg.hub import hub_fn\n\n"
            "def test_hub_basic():\n    return hub_fn()\n")
        self._write_files(files)
        self._reconcile()
        bundle = build_bundle(self.db, self.test_dir, "hub_fn",
                              max_hops=2, max_nodes=50, max_bytes=65_536,
                              max_tokens=BUDGET)
        rendered = render_yaml(bundle)
        self.assertLessEqual(estimate_tokens(rendered), BUDGET)
        callers = bundle["inbound_callers"]
        self.assertTrue(
            any(c["relative_path"].startswith("tests/") for c in callers),
            f"reserved tests/ caller lost on dense hub: "
            f"{[c['relative_path'] for c in callers]}")
        callee_names = {c["fqn"].rsplit(".", 1)[-1]
                        for c in bundle["outbound_callees"]}
        self.assertTrue({"h_a", "h_b", "h_c", "_hub_helper"} <= callee_names,
                        f"direct contracts dropped on dense hub: {callee_names}")
        self.assertTrue(bundle["limits"]["truncated"])
        # reported == actual serialized size, even after compaction
        self.assertEqual(bundle["limits"]["tokens_estimate"],
                         estimate_tokens(rendered))

    def test_metadata_compact_rendering_omits_derivable_fields(self):
        # Compaction is a rendering mode: derivable metadata (neighbor
        # node_id, FRESH trust_verdict) leaves the serialized form while the
        # dict keeps the data, and non-derivable contract lines survive.
        bundle = self._build(max_tokens=BUDGET)
        natural = render_yaml(bundle)
        self.assertIn("  - node_id:", natural)
        bundle["metadata_compact"] = True
        compact = render_yaml(bundle)
        self.assertNotIn("  - node_id:", compact)
        self.assertIn("  - fqn:", compact)
        self.assertNotIn("    trust_verdict:", compact)
        self.assertIn("relative_path:", compact)
        self.assertIn("callsite_line:", compact)
        self.assertIn("contract:", compact)
        self.assertTrue(bundle["inbound_callers"][0]["node_id"])

    def test_fixture_corpus_caller_is_not_reserved_as_test(self):
        # evaluation/tests/ is oracle-classified fixture corpus, NOT the
        # test universe: despite its earlier call-site line it must not win
        # the reserved test-caller slot over the tests/-rooted module.
        self._write_files({
            "evaluation/tests/test_shadow.py": (
                "from pkg.service import service_main\n\n"
                "def shadow_case():\n    return service_main()\n"),
        })
        self._reconcile()
        bundle = build_bundle(self.db, self.test_dir, "service_main",
                              max_hops=2, max_nodes=1, max_bytes=65_536)
        callers = bundle["inbound_callers"]
        self.assertEqual(len(callers), 1)
        self.assertEqual(callers[0]["relative_path"], "tests/test_service.py")

    # --- 9. Ambiguity stays fail-closed ------------------------------------

    def test_ambiguous_bare_name_fails_closed_with_candidates(self):
        self._write_files({
            "pkg/orphan_a.py": "def tie_name():\n    return 1\n",
            "pkg/orphan_b.py": "def tie_name():\n    return 2\n",
        })
        self._reconcile()
        with self.assertRaises(PackError) as ctx:
            build_bundle(self.db, self.test_dir, "tie_name",
                         max_hops=2, max_nodes=50, max_bytes=65_536,
                         max_tokens=BUDGET)
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_TARGET")
        self.assertEqual(len(ctx.exception.candidates), 2)


if __name__ == "__main__":
    unittest.main()
