"""
Honesty tests for the SG-201 independent NON-SELF corpus measurement
(``scripts/bench_sg201_external_corpus.py``).

These tests do NOT tune production and never touch the frozen
``holdout_unseen`` split. They build tiny real git checkouts + synthetic
mini-corpora and assert the runner fails closed: pinned-SHA verification,
errors published (never silently skipped), per-repo per-budget actual
rendered denominators published, partial corpus runs can never PASS, and
the evaluator scope text always reflects what was measured.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.exit_gates import sg201_contamination as sg201  # noqa: E402

ext_runner = importlib.import_module("scripts.bench_sg201_external_corpus")

CORE = (
    "def helper():\n"
    "    return 1\n"
    "\n"
    "def core_main():\n"
    "    return helper()\n"
)
VENDORED = "def vendored_util():\n    return 'v'\n"


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError(f"git {args} failed: {out.stderr}")
    return out.stdout.strip()


def _init_pinned_repo(path: Path) -> str:
    """Create a real git checkout with one commit; return the pinned SHA."""
    path.mkdir(parents=True)
    (path / "src/pkg").mkdir(parents=True)
    (path / "src/pkg/core.py").write_text(CORE)
    (path / "vendor_assets").mkdir()
    (path / "vendor_assets/util.py").write_text(VENDORED)
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "test", cwd=path)
    _git("config", "commit.gpgsign", "false", cwd=path)
    _git("add", "-A", cwd=path)
    _git("commit", "-qm", "pin", cwd=path)
    return _git("rev-parse", "HEAD", cwd=path)


def _gate_record(name: str, verdict: str, error: Optional[str] = None,
                 denominator: int = 100) -> dict:
    report = None if error else {"gate": {"verdict": verdict,
                                          "denominator": denominator}}
    return {"name": name, "error": error, "report": report,
            "rendered_texts": {}}


class ManifestGovernanceTests(unittest.TestCase):
    def test_refuses_holdout_unseen_path(self):
        with self.assertRaises(SystemExit):
            ext_runner.load_corpus_manifest(
                Path(REPO_ROOT / "benchmarks" / "holdout_unseen" / "manifest.json"))

    def test_refuses_holdout_role_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.json"
            p.write_text(json.dumps({"role": "holdout", "repos": [
                {"name": "x", "url": "u", "commit": "a" * 40}]}))
            with self.assertRaises(SystemExit):
                ext_runner.load_corpus_manifest(p)

    def test_refuses_short_sha(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.json"
            p.write_text(json.dumps({"role": "development-regression", "repos": [
                {"name": "x", "url": "u", "commit": "abc123"}]}))
            with self.assertRaises(SystemExit):
                ext_runner.load_corpus_manifest(p)

    def test_refuses_duplicate_names(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.json"
            p.write_text(json.dumps({"role": "development-regression", "repos": [
                {"name": "x", "url": "u1", "commit": "a" * 40},
                {"name": "x", "url": "u2", "commit": "b" * 40}]}))
            with self.assertRaises(SystemExit):
                ext_runner.load_corpus_manifest(p)

    def test_refuses_duplicate_urls(self):
        # Same repo under two names is one repo counted twice.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.json"
            p.write_text(json.dumps({"role": "development-regression", "repos": [
                {"name": "x", "url": "u", "commit": "a" * 40},
                {"name": "y", "url": "u", "commit": "b" * 40}]}))
            with self.assertRaises(SystemExit):
                ext_runner.load_corpus_manifest(p)

    def test_refuses_unsafe_path_names(self):
        bad_names = ["../evil", "a/b", ".hidden", "..", ""]
        for bad in bad_names:
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "m.json"
                p.write_text(json.dumps({
                    "role": "development-regression", "repos": [
                        {"name": bad, "url": "u", "commit": "a" * 40}]}))
                with self.assertRaises(SystemExit, msg=bad):
                    ext_runner.load_corpus_manifest(p)

    def test_refuses_tuning_exclusion_policy(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.json"
            p.write_text(json.dumps({
                "role": "development-regression",
                "policy": {"tuning_exclusion": "frozen by governance"},
                "repos": [{"name": "x", "url": "u", "commit": "a" * 40}]}))
            with self.assertRaises(SystemExit):
                ext_runner.load_corpus_manifest(p)

    def test_real_dev_manifest_accepted_and_fully_pinned(self):
        manifest = ext_runner.load_corpus_manifest(
            Path(REPO_ROOT / "benchmarks" / "holdout" / "manifest.json"))
        self.assertGreaterEqual(len(manifest["repos"]), 11)
        for repo in manifest["repos"]:
            self.assertEqual(len(repo["commit"]), 40)
            self.assertTrue(all(c in "0123456789abcdef" for c in repo["commit"]))


class PinVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sg201-ext-pin-")
        self.repo = Path(self.tmp) / "tiny"
        self.sha = _init_pinned_repo(self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_head_on_pinned_sha_verifies(self):
        v = ext_runner.verify_pinned_checkout(self.repo, self.sha)
        self.assertIsNone(v["error"])
        self.assertTrue(v["verified"])
        self.assertEqual(v["head_sha"], self.sha)
        self.assertEqual(v["violations"], [])

    def test_moved_head_is_an_error_not_a_measurement(self):
        (self.repo / "extra.py").write_text("def extra():\n    return 2\n")
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-qm", "drift", cwd=self.repo)
        v = ext_runner.verify_pinned_checkout(self.repo, self.sha)
        self.assertIsNotNone(v["error"])
        self.assertIn("HEAD", v["error"])
        self.assertFalse(v["verified"])

    def test_missing_checkout_is_an_error(self):
        v = ext_runner.verify_pinned_checkout(Path(self.tmp) / "nope", self.sha)
        self.assertIsNone(v["head_sha"])
        self.assertIsNotNone(v["error"])

    def test_tracked_edit_rejected_even_at_pinned_head(self):
        # The main review finding: HEAD==pinned alone is NOT enough.
        (self.repo / "src/pkg/core.py").write_text(CORE + "\n# tampered\n")
        v = ext_runner.verify_pinned_checkout(self.repo, self.sha)
        self.assertIsNone(v["error"])          # structural check passes
        self.assertFalse(v["verified"])
        self.assertTrue(any("tracked change" in x for x in v["violations"]))

    def test_staged_edit_rejected(self):
        (self.repo / "src/pkg/core.py").write_text(CORE + "\n# staged\n")
        _git("add", "-A", cwd=self.repo)
        v = ext_runner.verify_pinned_checkout(self.repo, self.sha)
        self.assertFalse(v["verified"])
        self.assertTrue(any("tracked change" in x for x in v["violations"]))

    def test_untracked_source_rejected(self):
        (self.repo / "stray.py").write_text("def stray():\n    return 1\n")
        v = ext_runner.verify_pinned_checkout(self.repo, self.sha)
        self.assertFalse(v["verified"])
        self.assertTrue(any("untracked source" in x and "stray.py" in x
                            for x in v["violations"]))

    def test_benign_sot_cache_allowed(self):
        sot = self.repo / ".sot"
        sot.mkdir()
        (sot / "sot.db").write_bytes(b"sqlite")
        v = ext_runner.verify_pinned_checkout(self.repo, self.sha)
        self.assertIsNone(v["error"])
        self.assertTrue(v["verified"])
        self.assertEqual(v["violations"], [])


class MeasureRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sg201-ext-meas-")
        self.repo = Path(self.tmp) / "tiny"
        self.sha = _init_pinned_repo(self.repo)
        self.entry = {"name": "tiny", "url": "https://example.com/tiny",
                      "commit": self.sha, "language": "python"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_measures_pinned_repo_with_external_scope(self):
        rec = ext_runner.measure_repo(
            self.entry, self.repo, budgets=(1024,), min_symbols=1,
            workers=1, keep_text=True)
        self.assertIsNone(rec["error"])
        rep = rec["report"]
        self.assertIn("independent non-self corpus", rep["scope"])
        self.assertNotIn("self-repo corpus (sot-graph)", rep["scope"])
        # The declared oracle MUST see the vendored content the production
        # filter hides; measurement is only meaningful if contam >= 0 and
        # denominators are real.
        self.assertGreaterEqual(rep["primary_run"]["rendered_symbols"], 1)
        self.assertIn("1024", rec["rendered_texts"])
        self.assertTrue(rec["rendered_texts"]["1024"].strip())

    def test_rendered_text_stripped_from_report_entries(self):
        rec = ext_runner.measure_repo(
            self.entry, self.repo, budgets=(1024,), min_symbols=1,
            workers=1, keep_text=True)
        for run in rec["report"]["runs"]:
            self.assertNotIn("rendered_text", run)

    def test_missing_checkout_published_as_error(self):
        rec = ext_runner.measure_repo(
            self.entry, Path(self.tmp) / "absent", budgets=(1024,),
            min_symbols=1, workers=1, keep_text=False)
        self.assertIsNotNone(rec["error"])
        self.assertIn("not cached", rec["error"])
        self.assertIsNone(rec["report"])

    def test_moved_head_refused(self):
        (self.repo / "extra.py").write_text("def extra():\n    return 2\n")
        _git("add", "-A", cwd=self.repo)
        _git("commit", "-qm", "drift", cwd=self.repo)
        rec = ext_runner.measure_repo(
            self.entry, self.repo, budgets=(1024,), min_symbols=1,
            workers=1, keep_text=False)
        self.assertIsNotNone(rec["error"])
        self.assertIn("HEAD", rec["error"])

    def test_dirty_checkout_rejected_before_measurement(self):
        # Tracked edit at the pinned HEAD: must NOT be measured.
        (self.repo / "src/pkg/core.py").write_text(CORE + "\n# tampered\n")
        rec = ext_runner.measure_repo(
            self.entry, self.repo, budgets=(1024,), min_symbols=1,
            workers=1, keep_text=False)
        self.assertIsNotNone(rec["error"])
        self.assertIn("BEFORE measurement", rec["error"])
        self.assertIsNone(rec["report"])
        self.assertIsNotNone(rec["pin_check_before"])

    def test_input_changed_during_measurement_is_rejected(self):
        from unittest import mock

        ok = {"head_sha": self.sha, "verified": True, "violations": [],
              "error": None}
        changed = {"head_sha": "b" * 40, "verified": False,
                   "violations": [], "error": "HEAD moved"}
        with mock.patch.object(
                ext_runner, "verify_pinned_checkout",
                side_effect=[ok, changed]):
            rec = ext_runner.measure_repo(
                self.entry, self.repo, budgets=(1024,), min_symbols=1,
                workers=1, keep_text=True)
        self.assertIsNotNone(rec["error"])
        self.assertIn("DURING measurement", rec["error"])
        # A rejected changing input never publishes measurement data.
        self.assertIsNone(rec["report"])
        self.assertEqual(rec["rendered_texts"], {})
        self.assertIsNotNone(rec["pin_check_after"])

    def test_verify_subprocess_timeout_never_raises(self):
        # Main review finding: the pin check ran OUTSIDE measure_repo's
        # try; a subprocess timeout leaked. Both layers must be safe.
        from unittest import mock

        with mock.patch.object(
                ext_runner, "_worktree_violations",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30)):
            v = ext_runner.verify_pinned_checkout(self.repo, self.sha)
        self.assertIsNotNone(v["error"])
        self.assertIn("timed out", v["error"])

        with mock.patch.object(
                ext_runner, "verify_pinned_checkout",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30)):
            rec = ext_runner.measure_repo(
                self.entry, self.repo, budgets=(1024,), min_symbols=1,
                workers=1, keep_text=False)
        self.assertIsNotNone(rec["error"])
        self.assertIn("TimeoutExpired", rec["error"])
        self.assertIsNone(rec["report"])


class AggregateGateTests(unittest.TestCase):
    def _run(self, records, expected):
        return ext_runner.aggregate_gate(
            records, expected_repos=expected, budgets=(1024, 2048),
            min_symbols=50)

    def test_all_pass_is_pass(self):
        recs = [_gate_record("a", "PASS"), _gate_record("b", "PASS")]
        self.assertEqual(self._run(recs, 2)["verdict"], "PASS")

    def test_measured_fail_beats_everything(self):
        recs = [_gate_record("a", "PASS"), _gate_record("b", "FAIL"),
                _gate_record("c", None, error="boom")]
        g = self._run(recs, 3)
        self.assertEqual(g["verdict"], "FAIL")
        self.assertEqual(g["repos_failed"], 1)
        self.assertEqual(g["repos_errored"], 1)

    def test_repo_error_is_not_evaluable_not_a_pass(self):
        recs = [_gate_record("a", "PASS"),
                _gate_record("b", None, error="not cached")]
        g = self._run(recs, 2)
        self.assertEqual(g["verdict"], "NOT_EVALUABLE")

    def test_partial_corpus_can_never_pass(self):
        # --limit smoke runs leave expected_repos > records: never PASS.
        recs = [_gate_record("a", "PASS")]
        self.assertEqual(self._run(recs, 11)["verdict"], "NOT_EVALUABLE")

    def test_insufficient_sampling_without_errors(self):
        recs = [_gate_record("a", "PASS"),
                _gate_record("b", "INSUFFICIENT_SAMPLING")]
        self.assertEqual(self._run(recs, 2)["verdict"],
                         "INSUFFICIENT_SAMPLING")

    def test_parse_mismatch_repo_is_not_evaluable(self):
        recs = [_gate_record("a", "PASS"),
                _gate_record("b", "RENDERED_OUTPUT_PARSE_MISMATCH")]
        self.assertEqual(self._run(recs, 2)["verdict"], "NOT_EVALUABLE")


class FlatRowsTests(unittest.TestCase):
    def test_rows_publish_per_budget_denominators_and_errors(self):
        rep = {"runs": [
            {"budget_tokens": 1024, "rendered_symbols": 44,
             "rendered_files": 14, "contaminated_symbols": 0,
             "symbol_contamination_pct": 0.0, "truncated": True,
             "rendered_sha256": "abc", "control_all_categories": False},
            {"budget_tokens": 1024, "rendered_symbols": 900,
             "rendered_files": 40, "contaminated_symbols": 12,
             "symbol_contamination_pct": 1.333, "truncated": False,
             "rendered_sha256": "def", "control_all_categories": True},
        ]}
        recs = [
            {"name": "ok", "error": None, "report": rep, "rendered_texts": {}},
            {"name": "bad", "error": "not cached", "report": None,
             "rendered_texts": {}},
        ]
        rows = ext_runner.flat_run_rows(recs)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["rendered_symbols"], 44)
        self.assertTrue(rows[1]["control_all_categories"])
        err = [r for r in rows if r["repo"] == "bad"][0]
        self.assertEqual(err["error"], "not cached")
        self.assertIsNone(err["rendered_symbols"])


class EvaluatorScopeTextTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sg201-ext-scope-")
        base = Path(self.root)
        (base / "src/pkg").mkdir(parents=True)
        (base / "src/pkg/core.py").write_text(CORE)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_explicit_external_scope_is_used_verbatim(self):
        rep = sg201.run_contamination(
            self.root, budgets=(1024,), min_symbols=1,
            include_all_control=False,
            scope="independent non-self corpus: tiny synthetic checkout")
        self.assertEqual(
            rep["scope"],
            "independent non-self corpus: tiny synthetic checkout")
        self.assertNotIn("PILOT", rep["scope"])

    def test_default_scope_still_self_repo_pilot(self):
        rep = sg201.run_contamination(self.root, budgets=(1024,),
                                      min_symbols=1, include_all_control=False)
        self.assertIn("PILOT", rep["scope"])
        self.assertIn("self-repo", rep["scope"])


class RenderedTextRoundtripTests(unittest.TestCase):
    """The captured rendered text must be exactly what the parser scored
    (sha256 agreement) — guards against post-hoc text substitution."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sg201-ext-rt-")
        self.repo = Path(self.tmp) / "tiny"
        self.sha = _init_pinned_repo(self.repo)
        self.entry = {"name": "tiny", "url": "u", "commit": self.sha,
                      "language": "python"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_captured_text_matches_reported_sha(self):
        import hashlib

        rec = ext_runner.measure_repo(
            self.entry, self.repo, budgets=(1024,), min_symbols=1,
            workers=1, keep_text=True)
        run = [r for r in rec["report"]["runs"]
               if not r.get("control_all_categories")][0]
        text = rec["rendered_texts"][str(run["budget_tokens"])]
        self.assertEqual(
            hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            run["rendered_sha256"])
        # And the text re-parses to the published denominators.
        rendered = __import__(
            "evaluation.exit_gates.common", fromlist=["parse_rendered_map"]
        ).parse_rendered_map(text)
        self.assertEqual(rendered.symbol_count, run["rendered_symbols"])


class DiskOracleUniverseTests(unittest.TestCase):
    """The report must publish what contamination COULD exist on disk, so
    a 0% control is auditable as a corpus property (nothing to detect)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sg201-ext-disk-")
        self.repo = Path(self.tmp) / "tiny"
        self.sha = _init_pinned_repo(self.repo)   # has vendor_assets/ on disk

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_disk_universe_sees_vendor_content(self):
        uni = ext_runner._disk_oracle_universe(self.repo)
        cats = uni["files_by_oracle_category"]
        self.assertGreaterEqual(cats.get("vendor", 0), 1)
        self.assertGreaterEqual(cats.get("production", 0), 1)
        self.assertEqual(uni["fixture_vendor_extensions"], {".py": 1})
        self.assertFalse(uni["walk_truncated"])

    def test_measure_repo_attaches_universe(self):
        entry = {"name": "tiny", "url": "u", "commit": self.sha,
                 "language": "python"}
        rec = ext_runner.measure_repo(entry, self.repo, budgets=(1024,),
                                      min_symbols=1, workers=1, keep_text=False)
        self.assertIn("disk_oracle_universe", rec)
        self.assertIn("production", rec["disk_oracle_universe"]["files_by_oracle_category"])


class MarkdownConsistencyTests(unittest.TestCase):
    """The markdown verdict cells must agree with the published JSON —
    regression: they read a stripped key and printed ERROR for PASS rows."""

    def test_markdown_verdicts_match_gate_verdicts(self):
        report = {
            "scope": "external", "manifest": "m", "manifest_role": "dev",
            "expected_repos": 1, "budgets": [1024, 2048], "min_symbols": 50,
            "repos": [{"name": "ok", "url": "u", "pinned_sha": "a" * 40,
                       "language": "python", "error": None,
                       "head_sha": "a" * 40, "head_matches_pinned": True,
                       "pin_verified": True,
                       "gate_verdict": "PASS", "primary_denominator": 94,
                       "metric_percent": 0.0,
                       "disk_oracle_universe": {
                           "files_by_oracle_category": {"production": 5},
                           "fixture_vendor_extensions": {},
                           "walk_truncated": False}}],
            "runs_flat": [
                {"repo": "ok", "budget_tokens": 1024,
                 "control_all_categories": False, "rendered_symbols": 44,
                 "rendered_files": 10, "contaminated_symbols": 0,
                 "symbol_contamination_pct": 0.0, "truncated": True,
                 "rendered_sha256": "x"},
                {"repo": "ok", "budget_tokens": 2048,
                 "control_all_categories": False, "rendered_symbols": 94,
                 "rendered_files": 14, "contaminated_symbols": 0,
                 "symbol_contamination_pct": 0.0, "truncated": True,
                 "rendered_sha256": "y"},
            ],
            "control_sensitivity": {"disk_fixture_files": 0,
                                    "disk_vendor_files": 0,
                                    "fixture_vendor_extensions": {}},
            "aggregate_gate": ext_runner.aggregate_gate(
                [_gate_record("ok", "PASS")], expected_repos=1,
                budgets=(1024, 2048), min_symbols=50),
            "tool_provenance": {"git_head": "h", "worktree_digest": "d",
                                "dirty_entries": 0, "digest_truncated": False},
        }
        md = ext_runner.render_markdown(report)
        self.assertIn("| ok | `aaaaaaaaaaaa…` | yes | PASS | 44@1024 94@2048 |",
                      md)
        self.assertNotIn("ERROR", md.split("## Per-repo verdicts")[1].split(
            "## Actual rendered")[0])


if __name__ == "__main__":
    unittest.main()
