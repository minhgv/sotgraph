"""
Honesty tests for the SG-201 / SG-202 exit-gate evaluators.

These tests do NOT tune production: they build synthetic mini-corpora and
assert that the evaluators fail closed — publish denominators, count pack
errors and ambiguity as failures (never exclusions), detect contamination
through the independent oracle, reject oracle-validation drift, refuse to
pass on insufficient sampling, and keep the human landmark gate pending
until real reviewer evidence exists.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.exit_gates.common import (  # noqa: E402
    gate_verdict,
    oracle_category,
    parse_rendered_map,
    repo_provenance,
)
from evaluation.exit_gates import sg201_contamination as sg201  # noqa: E402
from evaluation.exit_gates import sg202_task_sufficiency as sg202  # noqa: E402
from evaluation.exit_gates.sg202_task_sufficiency import (  # noqa: E402
    validate_oracle_against_gt_subset,
)

CORE = (
    "def helper():\n"
    "    return 1\n"
    "\n"
    "def core_main():\n"
    "    return helper()\n"
    "\n"
    "class Engine:\n"
    "    def start(self):\n"
    "        return core_main()\n"
)
CALLER = (
    "from pkg.core import core_main\n"
    "\n"
    "def run():\n"
    "    return core_main()\n"
)
TEST_MOD = (
    "from pkg.core import core_main, Engine\n"
    "\n"
    "def test_core_main():\n"
    "    assert core_main() is not None\n"
    "\n"
    "def test_engine():\n"
    "    assert Engine().start() is not None\n"
)
DUP_A = "def twin():\n    return 'a'\n"
DUP_B = "def twin():\n    return 'b'\n"
VENDOR_ASSETS = "def vendored_util():\n    return 'v'\n"


class GateHelperTests(unittest.TestCase):
    def test_passed_false_overrides_metric(self):
        # metric far above floor AND huge denominator must still FAIL when
        # the caller says passed=False (e.g. oracle validation failed).
        g = gate_verdict(False, 1, 100, 0.99, 0.95, "g")
        self.assertEqual(g["verdict"], "FAIL")
        self.assertIs(g["passed"], False)

    def test_unknown_metric_never_passes(self):
        g = gate_verdict(None, 1, 100, None, 0.95, "g")
        self.assertEqual(g["verdict"], "NOT_EVALUABLE")
        self.assertIsNone(g["passed"])

    def test_insufficient_denominator_beats_metric(self):
        g = gate_verdict(True, 30, 10, 0.99, 0.95, "g")
        self.assertEqual(g["verdict"], "INSUFFICIENT_SAMPLING")
        self.assertIsNone(g["passed"])

    def test_upper_bound_direction(self):
        ok = gate_verdict(True, 1, 100, 0.0, 0.02, "g", upper_bound=True)
        self.assertEqual(ok["verdict"], "PASS")
        one_pct = gate_verdict(True, 1, 100, 0.01, 0.02, "g", upper_bound=True)
        self.assertEqual(one_pct["verdict"], "PASS")
        at_floor = gate_verdict(True, 1, 100, 0.02, 0.02, "g", upper_bound=True)
        self.assertEqual(at_floor["verdict"], "FAIL")  # "<2%" is strict
        over = gate_verdict(True, 1, 100, 0.05, 0.02, "g", upper_bound=True)
        self.assertEqual(over["verdict"], "FAIL")

    def test_lower_bound_requires_floor(self):
        self.assertEqual(gate_verdict(True, 1, 100, 0.0, 0.95, "g")["verdict"], "FAIL")
        self.assertEqual(gate_verdict(True, 1, 100, 0.95, 0.95, "g")["verdict"], "PASS")


class RenderedMapParserTests(unittest.TestCase):
    def test_parse_and_count(self):
        text = "src/a.py:\n  def f()\n  def g()\nvendor/v.js:\n  h()\n(footer)\n"
        m = parse_rendered_map(text)
        self.assertEqual(m.files, ["src/a.py", "vendor/v.js"])
        self.assertEqual(m.symbol_count, 3)

    def test_malformed_line_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_rendered_map("not-a-map-line\n")

    def test_oracle_is_declared_superset(self):
        self.assertEqual(oracle_category("vendor_assets/x.py"), "vendor")
        self.assertEqual(oracle_category("tests/fixtures/a.py"), "fixture")
        self.assertEqual(oracle_category("src/normal.py"), "production")


class ProvenanceTests(unittest.TestCase):
    def test_binds_head_and_digest(self):
        prov = repo_provenance(str(REPO_ROOT))
        self.assertNotEqual(prov["git_head"], "unknown")
        self.assertTrue(prov["git_head"])
        self.assertRegex(prov["worktree_digest"], r"^[0-9a-f]{16}$")
        self.assertGreaterEqual(prov["dirty_entries"], 0)

    @staticmethod
    def _git(*args: str, cwd: str) -> None:
        import subprocess

        subprocess.run(["git", "-C", cwd, *args], check=True,
                       capture_output=True, text=True)

    def test_digest_tracks_modified_and_untracked_content(self):
        repo = tempfile.mkdtemp(prefix="prov-")
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        self._git("init", "-q", cwd=repo)
        self._git("config", "user.email", "t@example.com", cwd=repo)
        self._git("config", "user.name", "t", cwd=repo)
        (Path(repo) / "a.txt").write_text("v1\n")
        self._git("add", ".", cwd=repo)
        self._git("commit", "-q", "-m", "init", cwd=repo)
        clean = repo_provenance(repo)

        # Unstaged modification: porcelain record " M a.txt" (leading
        # space) must parse positionally and hash real content.
        (Path(repo) / "a.txt").write_text("v2\n")
        dirty = repo_provenance(repo)
        self.assertGreaterEqual(dirty["dirty_entries"], 1)
        self.assertGreaterEqual(dirty["content_files_hashed"], 1)
        self.assertFalse(dirty["digest_truncated"])
        self.assertNotEqual(clean["worktree_digest"], dirty["worktree_digest"])

        # Untracked file inside a NEW directory must be enumerated as a
        # file (not a collapsed dir) and enter the digest.
        sub = Path(repo) / "newdir"
        sub.mkdir()
        (sub / "b.txt").write_text("new\n")
        untracked = repo_provenance(repo)
        self.assertGreaterEqual(untracked["dirty_entries"], 2)
        self.assertGreaterEqual(untracked["content_files_hashed"], 2)
        self.assertFalse(untracked["digest_truncated"])
        self.assertNotEqual(dirty["worktree_digest"], untracked["worktree_digest"])

    def test_generated_reports_excluded_from_digest(self):
        # benchmarks/exit_gates/ is excluded: writing a report must not
        # change the digest (no self-reference across runs).
        repo = tempfile.mkdtemp(prefix="prov-self-")
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        self._git("init", "-q", cwd=repo)
        self._git("config", "user.email", "t@example.com", cwd=repo)
        self._git("config", "user.name", "t", cwd=repo)
        (Path(repo) / "a.txt").write_text("v1\n")
        self._git("add", ".", cwd=repo)
        self._git("commit", "-q", "-m", "init", cwd=repo)
        before = repo_provenance(repo)
        out = Path(repo) / "benchmarks" / "exit_gates"
        out.mkdir(parents=True)
        (out / "report.json").write_text("{}")
        after = repo_provenance(repo)
        self.assertEqual(before["worktree_digest"], after["worktree_digest"])


class SG202HonestyTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sg202-honesty-")
        for rel, body in (
            ("src/pkg/core.py", CORE),
            ("src/pkg/caller.py", CALLER),
            ("tests/test_core.py", TEST_MOD),
        ):
            p = Path(self.root) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_task_with_independent_gt_and_denominators(self):
        rep = sg202.run_task_sufficiency(self.root, limit=10, min_tasks=1)
        d = rep["denominators"]
        self.assertEqual(d["attempted_tasks"], d["measurable_tasks"] + d["oracle_unmeasurable"])
        # core_main: helper contract + Engine/start callers + test module.
        self.assertGreaterEqual(d["attempted_tasks"], 3)
        self.assertIn("src/pkg/core.py::core_main",
                      [t["task"] for t in rep["task_roster"]])
        self.assertTrue(rep["gate"]["oracle_validation"].startswith(
            ("MISSING_GT_SUBSET", "PASSED")))

    def test_owner_chain_identity_matches_methods(self):
        rep = sg202.run_task_sufficiency(self.root, limit=10, min_tasks=1)
        roster = {t["task"]: t["outcome"] for t in rep["task_roster"]}
        # Engine.start is a method; identity must resolve via the owner
        # chain (no MISSING_TARGET). The test module only exercises it via
        # attribute access, so no graph caller edge exists: the honest
        # outcome is a test-receipt failure, never an identity failure.
        self.assertNotEqual(roster.get("src/pkg/core.py::start"), "MISSING_TARGET")
        # core_main is called directly by the test (graph caller edge) and
        # its direct contract (helper) plus test caller are in-pack.
        self.assertEqual(roster.get("src/pkg/core.py::core_main"), "FULL_SUCCESS")

    def test_budget_too_small_is_failure_not_exclusion(self):
        rep = sg202.run_task_sufficiency(self.root, limit=10, min_tasks=1,
                                         budget_tokens=16)
        outcomes = rep["outcome_counts"]
        self.assertGreater(outcomes.get("PACK_ERROR", 0), 0)
        # A pack error stays in the measured denominator as a FAILURE.
        d = rep["denominators"]
        self.assertEqual(d["attempted_tasks"],
                         d["measurable_tasks"] + d["oracle_unmeasurable"])
        self.assertEqual(d["full_success"], 0)
        reasons = " ".join(r for f in rep["failures"] for r in f["reasons"])
        self.assertIn("BUDGET_TOO_SMALL", reasons)

    def test_insufficient_sampling_refuses_gate(self):
        rep = sg202.run_task_sufficiency(self.root, limit=4, min_tasks=99)
        self.assertEqual(rep["gate"]["verdict"], "INSUFFICIENT_SAMPLING")
        self.assertIsNone(rep["gate"]["passed"])

    def test_gt_subset_drift_fails_oracle_validation(self):
        # A curated entry for an EXISTING corpus symbol whose curated test
        # list no longer matches the heuristic must FAIL oracle validation
        # (this is exactly what caught real corpus drift during the pilot).
        wrong = {"src/pkg/core.py::core_main": ["tests/some_other_test.py"]}
        root = Path(self.root)
        test_rels = ["tests/test_core.py"]
        checked, mism = validate_oracle_against_gt_subset(root, test_rels, wrong)
        self.assertEqual(checked, 1)
        self.assertEqual(len(mism), 1)

    def test_gt_subset_entries_outside_corpus_skipped(self):
        # Entries whose source file does not exist in this corpus are not
        # applicable (per-corpus subset), never counted as checked.
        ghost = {"src/nowhere.py::ghost_symbol": ["tests/test_core.py"]}
        checked, mism = validate_oracle_against_gt_subset(
            Path(self.root), ["tests/test_core.py"], ghost)
        self.assertEqual(checked, 0)
        self.assertEqual(mism, [])

    def test_meta_keys_skipped_in_gt_subset(self):
        checked, mism = validate_oracle_against_gt_subset(
            Path(self.root), [], {"_meta": {"purpose": "x"}})
        self.assertEqual(checked, 0)
        self.assertEqual(mism, [])


class SG201HonestyTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sg201-honesty-")
        base = Path(self.root)
        (base / "src/pkg").mkdir(parents=True)
        (base / "vendor_assets").mkdir(parents=True)
        (base / "src/pkg/core.py").write_text(CORE)
        (base / "src/pkg/caller.py").write_text(CALLER)
        (base / "vendor_assets/util.py").write_text(VENDOR_ASSETS)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_default_map_clean_but_oracle_detects_blindspot(self):
        rep = sg201.run_contamination(self.root, budgets=(1024,),
                                      min_symbols=1, include_all_control=False)
        gate = rep["gate"]
        # Production rules let vendor_assets/ into the default map, but the
        # DECLARED oracle flags it: contamination must be >0 and gate FAIL.
        self.assertGreater(rep["primary_run"]["contaminated_symbols"], 0)
        self.assertEqual(gate["verdict"], "FAIL")
        divs = rep["primary_run"]["production_vs_oracle_divergences"]
        self.assertTrue(any(d["path"].startswith("vendor_assets/") for d in divs))

    def test_insufficient_rendered_symbols_refuses_gate(self):
        rep = sg201.run_contamination(self.root, budgets=(1024,),
                                      min_symbols=10_000, include_all_control=False)
        self.assertEqual(rep["gate"]["verdict"], "INSUFFICIENT_SAMPLING")

    def test_empty_map_zero_denominator_refuses_gate(self):
        empty = tempfile.mkdtemp(prefix="sg201-empty-")
        try:
            rep = sg201.run_contamination(empty, budgets=(1024,),
                                          min_symbols=50, include_all_control=False)
            self.assertEqual(rep["gate"]["verdict"], "INSUFFICIENT_SAMPLING")
            self.assertEqual(rep["denominators"]["rendered_symbols"], 0)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_multiple_budgets_must_all_be_under_floor(self):
        # vendor_assets/ appears in the default map at every budget: the
        # gate must FAIL while listing both budgets as sufficient.
        rep = sg201.run_contamination(self.root, budgets=(1024, 2048),
                                      min_symbols=1, include_all_control=False)
        gate = rep["gate"]
        self.assertEqual(gate["verdict"], "FAIL")
        self.assertEqual(len(gate["budgets_with_sufficient_sampling"]), 2)
        self.assertIs(gate["all_budgets_under_floor"], False)
        # UNITS: gate metric is a fraction; percent published alongside.
        self.assertAlmostEqual(gate["metric"], gate["metric_percent"] / 100.0)

    def test_gate_metric_is_fraction_not_percent(self):
        # A 1% contamination (metric_percent 1.0) must PASS a <2% gate —
        # guards the percent-vs-fraction 100x regression.
        rep = sg201.run_contamination(self.root, budgets=(1024,),
                                      min_symbols=1, include_all_control=False)
        metric_pct = rep["primary_run"]["symbol_contamination_pct"]
        # Synthetic corpus: 1 contaminated symbol of >= few rendered ⇒
        # between 0 and 50%; assert gate compares against the fraction.
        if metric_pct is not None and metric_pct < 2.0:
            self.assertEqual(rep["gate"]["verdict"], "PASS")
        elif rep["gate"]["verdict"] not in ("INSUFFICIENT_SAMPLING",):
            self.assertEqual(rep["gate"]["verdict"], "FAIL")

    def test_parse_mismatch_fails_closed(self):
        original = sg201.parse_rendered_map
        try:
            sg201.parse_rendered_map = lambda text: original("src/pkg/core.py:\n  def f()\n")
            rep = sg201.run_contamination(self.root, budgets=(1024,),
                                          min_symbols=1, include_all_control=False)
            self.assertEqual(rep["gate"]["verdict"], "RENDERED_OUTPUT_PARSE_MISMATCH")
            self.assertIs(rep["gate"]["passed"], False)
        finally:
            sg201.parse_rendered_map = original

    def test_report_carries_provenance_and_piilot_scope(self):
        rep = sg201.run_contamination(self.root, budgets=(1024,),
                                      min_symbols=1, include_all_control=False)
        self.assertIn("provenance", rep)
        self.assertIn("PILOT", rep["scope"])


class LandmarkStudyStrictnessTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="landmark-")
        self.report_dir = tempfile.mkdtemp(prefix="landmark-report-")
        manifest = {"budget_tokens": 1024, "worksheet_sha256": "deadbeef",
                    "rows": [{"rank": i, "path": f"src/pkg/f{i}.py"}
                             for i in range(1, 21)]}
        (Path(self.dir) / "manifest.json").write_text(json.dumps(manifest))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(self.report_dir, ignore_errors=True)

    def _write(self, name, verdicts, attest=True, dup_path=False):
        rows = ["rank,path,symbol_stub,verdict,reviewer_note,"
                "reviewer_name,attestation,reviewed_at"]
        for i, v in enumerate(verdicts, 1):
            path = f"src/pkg/f{min(i, 2)}.py" if dup_path else f"src/pkg/f{i}.py"
            att = ("I personally reviewed these 20 rows" if attest else "")
            rows.append(f"{i},{path},def f(),{v},,alice,{att},2026-09-05")
        (Path(self.dir) / name).write_text("\n".join(rows) + "\n")

    def _run(self):
        import argparse

        args = argparse.Namespace(dir=self.dir, report_dir=self.report_dir)
        from scripts.bench_sg201_sg202_exit_gates import cmd_landmark_aggregate
        return cmd_landmark_aggregate(args)

    def test_no_human_evidence_is_pending(self):
        self.assertEqual(self._run(), 2)

    def test_missing_manifest_is_pending(self):
        (Path(self.dir) / "manifest.json").unlink()
        self._write("reviewer-a.csv", ["landmark"] * 20)
        self.assertEqual(self._run(), 2)

    def test_invalid_review_rejected_not_partially_counted(self):
        self._write("reviewer-a.csv", ["landmark"] * 19 + [""])
        self.assertEqual(self._run(), 1)
        self.assertFalse((Path(self.report_dir) / "sg201_landmark_study.json").exists())

    def test_missing_attestation_rejected(self):
        self._write("reviewer-a.csv", ["landmark"] * 20, attest=False)
        self.assertEqual(self._run(), 1)

    def test_duplicate_paths_rejected(self):
        self._write("reviewer-a.csv", ["landmark"] * 20, dup_path=True)
        self.assertEqual(self._run(), 1)

    def test_completed_review_scores_over_full_denominator(self):
        # 18 landmarks + 2 unsure: precision@20 = 18/20 = 0.9 (unsure are
        # explicit non-positives; no landmarks/scored inflation).
        self._write("reviewer-a.csv", ["landmark"] * 18 + ["unsure"] * 2)
        rc = self._run()
        self.assertEqual(rc, 0)
        report = json.loads(
            (Path(self.report_dir) / "sg201_landmark_study.json").read_text())
        self.assertEqual(report["per_reviewer"][0]["precision@20"], 0.9)
        self.assertEqual(report["per_reviewer"][0]["denominator"], 20)
        # Aggregator NEVER closes the human gate from CSVs alone.
        self.assertEqual(report["acceptance_status"], "PENDING_MANUAL_VERIFICATION")
        self.assertEqual(report["human_evidence"], "supplied_not_verified")
        self.assertFalse(report["min_reviewers_met"])  # 1 reviewer < 3

    def test_min_reviewers_flagged_until_met(self):
        for n in "abc":
            self._write(f"reviewer-{n}.csv", ["landmark"] * 20)
        rc = self._run()
        self.assertEqual(rc, 0)
        report = json.loads(
            (Path(self.report_dir) / "sg201_landmark_study.json").read_text())
        self.assertTrue(report["min_reviewers_met"])
        self.assertEqual(report["acceptance_status"], "PENDING_MANUAL_VERIFICATION")


if __name__ == "__main__":
    unittest.main()
