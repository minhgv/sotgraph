"""W2 safe-commit gate — the composite pass|warn|block verdict on the
diff receipt plus --gate-strict exit semantics.

Planted-fault integration: a tiny repo where a change deletes a still-
called symbol — the rename/delete leftover the gate exists to catch.
Two detection nets are exercised separately:
  * caller file also touched → pending_edges row lands in the
    changed/caller-file sweep;
  * caller file left untouched + a PRE-change scope receipt attached →
    the pre-receipt symbol net catches what the graph edge can no
    longer see.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sot_graph.assurance.impact_pipeline import (
    ImpactClaimRequest,
    run_impact_claim,
)
from sot_graph.assurance.receipts import scope_receipt
from sot_graph.assurance.resolution import (
    SAFE_COMMIT_VERDICTS,
    safe_commit_verdict,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _reconcile(repo: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
         "reconcile"],
        cwd=repo, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-400:]


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


@pytest.fixture()
def gate_repo(tmp_path) -> Path:
    """util.helper() is called by app.run() — the planted break target."""
    repo = tmp_path / "gate_repo"
    repo.mkdir()
    # Mirror real usage: .sot/ internals are gitignored so the graph's
    # own state files never land in the diff's changed_files set.
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    (repo / "util.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8")
    (repo / "app.py").write_text(
        "import util\n\ndef run():\n    return util.helper() + 1\n",
        encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c1")
    _reconcile(repo)
    return repo


def _claim(repo: Path, **kwargs) -> dict:
    db = _db_of(repo)
    try:
        return run_impact_claim(
            ImpactClaimRequest(working_tree=True, **kwargs),
            db, str(repo))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Pure verdict unit tests
# ---------------------------------------------------------------------------

class TestSafeCommitVerdictPure:
    def _disp(self, untouched_callers=0, untouched_tests=0, attached=True):
        return {
            "pre_receipt_attached": attached,
            "direct_callers": {"untouched": ["f%d" % i
                                           for i in range(untouched_callers)]},
            "candidate_tests": {"untouched": ["t%d" % i
                                              for i in range(untouched_tests)]},
        }

    def test_clean_passes(self):
        v = safe_commit_verdict(
            assurance_status="ASSURED_WITHIN_SCOPE", dangling_count=0,
            debt_introduced=0, dispositions=self._disp(0, 0))
        assert v["verdict"] == "pass"
        assert not v["block_reasons"] and not v["warn_reasons"]

    def test_dangling_blocks(self):
        v = safe_commit_verdict(
            assurance_status="ASSURED_WITHIN_SCOPE", dangling_count=2,
            debt_introduced=0, dispositions=self._disp())
        assert v["verdict"] == "block"
        assert any("dangling" in r for r in v["block_reasons"])

    @pytest.mark.parametrize(
        "status", ["ABSTAINED", "UNVERIFIABLE", "CONFLICTED", "STALE"])
    def test_unverifiable_statuses_block(self, status):
        v = safe_commit_verdict(
            assurance_status=status, dangling_count=0,
            debt_introduced=0, dispositions=self._disp())
        assert v["verdict"] == "block", status

    def test_partial_only_warns(self):
        v = safe_commit_verdict(
            assurance_status="PARTIAL", dangling_count=0,
            debt_introduced=0, dispositions=self._disp())
        assert v["verdict"] == "warn"

    def test_failed_tests_block(self):
        v = safe_commit_verdict(
            assurance_status="ASSURED_WITHIN_SCOPE", dangling_count=0,
            debt_introduced=0, dispositions=self._disp(),
            test_results={"ran": 5, "failed": 1, "failures": ["t_x"]})
        assert v["verdict"] == "block"
        assert v["inputs"]["tests_failed"] == 1

    def test_passing_tests_do_not_block(self):
        v = safe_commit_verdict(
            assurance_status="ASSURED_WITHIN_SCOPE", dangling_count=0,
            debt_introduced=0, dispositions=self._disp(),
            test_results={"ran": 5, "failed": 0, "failures": []})
        assert v["verdict"] == "pass"
        assert v["inputs"]["test_results_attached"] is True

    def test_untouched_dispositions_warn(self):
        v = safe_commit_verdict(
            assurance_status="ASSURED_WITHIN_SCOPE", dangling_count=0,
            debt_introduced=0, dispositions=self._disp(2, 1))
        assert v["verdict"] == "warn"
        assert v["inputs"]["untouched_callers"] == 2
        assert v["inputs"]["untouched_tests"] == 1

    def test_debt_markers_warn(self):
        v = safe_commit_verdict(
            assurance_status="ASSURED_WITHIN_SCOPE", dangling_count=0,
            debt_introduced=3, dispositions=self._disp())
        assert v["verdict"] == "warn"

    def test_escalation_is_one_directional(self):
        v = safe_commit_verdict(
            assurance_status="PARTIAL", dangling_count=1,
            debt_introduced=1, dispositions=self._disp(1, 0),
            test_results={"ran": 1, "failed": 1})
        assert v["verdict"] == "block"
        assert v["block_reasons"] and v["warn_reasons"]
        assert v["verdict"] in SAFE_COMMIT_VERDICTS


# ---------------------------------------------------------------------------
# Planted-fault integration
# ---------------------------------------------------------------------------

class TestSafeCommitGateIntegration:
    def test_clean_change_passes(self, gate_repo):
        (gate_repo / "util.py").write_text(
            "def helper():\n    return 2\n", encoding="utf-8")
        _reconcile(gate_repo)
        r = _claim(gate_repo)
        sc = r["safe_commit"]
        assert sc["verdict"] == "pass", (
            f"clean body edit blocked: {sc}")
        assert r["closure_decision"] == "closed"

    def test_fault_caller_also_touched_blocks(self, gate_repo):
        """Delete helper AND touch the caller file — the pending_edges
        row lands inside the changed-file sweep without any receipt."""
        (gate_repo / "util.py").write_text("", encoding="utf-8")
        (gate_repo / "app.py").write_text(
            "import util\n\ndef run():\n    # still calls a deleted symbol\n"
            "    return util.helper() + 1\n",
            encoding="utf-8")
        _reconcile(gate_repo)
        r = _claim(gate_repo)
        sc = r["safe_commit"]
        assert r["resolution_ledger"]["dangling_references"]["count"] >= 1
        assert sc["verdict"] == "block"
        assert any("dangling" in b for b in sc["block_reasons"])

    def test_fault_untouched_caller_needs_pre_receipt(self, gate_repo):
        """The strong net: scope-receipt BEFORE the break, then delete
        helper leaving app.py untouched — the pre-change symbol net
        catches what the post-change graph can no longer see."""
        db = _db_of(gate_repo)
        try:
            pre = scope_receipt(db, str(gate_repo), "helper")
        finally:
            db.close()
        (gate_repo / "util.py").write_text("", encoding="utf-8")
        _reconcile(gate_repo)
        r = _claim(gate_repo, pre_receipt=pre)
        sc = r["safe_commit"]
        assert sc["inputs"]["pre_receipt_attached"] is True
        assert sc["verdict"] == "block", (
            "deleted still-called symbol must block even with an "
            f"untouched caller: {sc}")
        # The disposition matrix also reports the untouched caller.
        assert sc["inputs"]["untouched_callers"] >= 1 or \
            r["resolution_ledger"]["dangling_references"]["count"] >= 1

    def test_debt_marker_change_only_warns(self, gate_repo):
        (gate_repo / "app.py").write_text(
            "import util\n\ndef run():\n    # TODO tighten this later\n"
            "    return util.helper() + 1\n",
            encoding="utf-8")
        _reconcile(gate_repo)
        r = _claim(gate_repo)
        sc = r["safe_commit"]
        assert r["resolution_ledger"]["debt_markers"]["total"] >= 1
        assert sc["verdict"] == "warn"

    def test_provided_test_failure_blocks_clean_change(self, gate_repo):
        (gate_repo / "util.py").write_text(
            "def helper():\n    return 2\n", encoding="utf-8")
        _reconcile(gate_repo)
        r = _claim(gate_repo, test_results={
            "ran": 3, "failed": 1, "failures": ["test_run"]})
        sc = r["safe_commit"]
        assert sc["verdict"] == "block"
        assert r["request"]["test_results"]["failed"] == 1

    def test_request_normalizes_failures_count(self):
        req = ImpactClaimRequest(
            working_tree=True,
            test_results={"failures": ["a", "b"]}).normalize()
        # Established echo shape: failures-only claims heal UP into the
        # blocking count, and the count stays caller-reported.
        assert req.test_results["ran"] == 0
        assert req.test_results["failed"] == 2
        assert req.test_results["failures"] == ["a", "b"]
        # Trust-boundary evidence lives in the separate field.
        assert req.test_results_validation["provenance"] == "caller_reported"
        assert req.test_results_validation["validation"] == "valid"
        assert req.test_results_validation["healed_failed"] is True
        # Non-object input is a type error; structurally malformed dicts
        # are RECORDED invalid (trusted in neither direction), not raised.
        with pytest.raises(ValueError):
            ImpactClaimRequest(test_results="x").normalize()
        bad = ImpactClaimRequest(
            working_tree=True, test_results={"ran": "x"}).normalize()
        assert bad.test_results == {"ran": "x"}
        assert bad.test_results_validation["validation"] == "invalid"
        assert bad.test_results_validation["errors"]
        assert bad.test_results_validation["effective_failed"] is None


class TestGateStrictCli:
    def _cli(self, repo: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
             "diff-impact", "--working-tree", "--gate-strict",
             "--format", "json", *extra],
            cwd=repo, capture_output=True, text=True)

    def test_strict_exit_2_on_planted_fault(self, gate_repo):
        (gate_repo / "util.py").write_text("", encoding="utf-8")
        (gate_repo / "app.py").write_text(
            "import util\n\ndef run():\n    return util.helper() + 1  # broken\n",
            encoding="utf-8")
        proc = self._cli(gate_repo)  # auto-reconcile runs by default
        assert proc.returncode == 2, proc.stderr[-400:]
        payload = json.loads(proc.stdout)
        receipt = payload.get("receipt", payload)
        assert receipt["safe_commit"]["verdict"] == "block"
        assert "safe_commit verdict: block" in proc.stderr

    def test_strict_exit_0_on_clean(self, gate_repo):
        (gate_repo / "util.py").write_text(
            "def helper():\n    return 2\n", encoding="utf-8")
        proc = self._cli(gate_repo)
        assert proc.returncode == 0, proc.stderr[-400:]
        payload = json.loads(proc.stdout)
        receipt = payload.get("receipt", payload)
        assert receipt["safe_commit"]["verdict"] == "pass"

    def test_test_report_flag(self, gate_repo):
        (gate_repo / "util.py").write_text(
            "def helper():\n    return 2\n", encoding="utf-8")
        report = gate_repo / "tests.json"
        report.write_text(json.dumps(
            {"ran": 4, "failed": 1, "failures": ["test_run"]}))
        proc = self._cli(gate_repo, "--test-report", str(report))
        assert proc.returncode == 2, proc.stderr[-400:]
        assert "1 provided test(s) failed" in proc.stderr


# ---------------------------------------------------------------------------
# T-07/AC-05 trust boundary — caller test claims are never proof
# ---------------------------------------------------------------------------


class TestTestResultsTrustBoundary:
    """Caller-supplied counts are CLAIMS, never verified execution.

    bool-as-int, negative/noninteger counts, ``failed > ran``, and
    success counts with nonempty failures must not reassure; ``ran=0``
    is not a verified pass; caller command/hash metadata cannot upgrade
    provenance; the graph verdict stays independent of caller claims.
    """

    def _v(self, test_results, status="ASSURED_WITHIN_SCOPE"):
        return safe_commit_verdict(
            assurance_status=status, dangling_count=0,
            debt_introduced=0, dispositions={"pre_receipt_attached": False},
            test_results=test_results)

    @pytest.mark.parametrize("report", [
        {"ran": True, "failed": 0},            # bool-as-int ran
        {"ran": 5, "failed": True},            # bool-as-int failed
        {"ran": 5, "failed": -1},              # negative failed
        {"ran": -5, "failed": 0},              # negative ran
        {"ran": 2.0, "failed": 0},             # float count
        {"ran": "5", "failed": 0},             # string count
        {"ran": 1, "failed": 3},               # failed > ran
        {"ran": 5, "failed": 0, "failures": [],
         "command": "pytest -q"},              # command metadata
        {"ran": 5, "failed": 0, "failures": [],
         "snapshot_hash": "a" * 64},           # hash metadata
        {"ran": float("nan"), "failed": 0},    # NaN is not a count
    ])
    def test_invalid_reports_cannot_reassure(self, report):
        v = self._v(report)
        assert v["verdict"] == "warn", report
        assert v["inputs"]["tests_validation"] == "invalid"
        # Nothing from an invalid report is honored in either direction.
        assert v["inputs"]["tests_failed"] == 0
        assert v["inputs"]["tests_verified_execution"] is False
        assert v["tests"]["provenance"] == "caller_reported"
        assert v["tests"]["errors"]

    def test_success_count_with_failures_blocks(self):
        v = self._v({"ran": 5, "failed": 0, "failures": ["t_x"]})
        assert v["verdict"] == "block"
        assert v["inputs"]["tests_failed"] == 1
        assert v["tests"]["healed_failed"] is True

    def test_failures_only_blocks(self):
        v = self._v({"failures": ["a", "b"]})
        assert v["verdict"] == "block"
        assert v["inputs"]["tests_failed"] == 2

    def test_claimed_failures_block_with_message(self):
        v = self._v({"ran": 3, "failed": 1, "failures": ["test_run"]})
        assert v["verdict"] == "block"
        assert any("1 provided test(s) failed" in r
                   for r in v["block_reasons"])

    def test_ran_zero_is_not_a_verified_pass(self):
        v = self._v({"ran": 0, "failed": 0, "failures": []})
        # Legacy graph-only closure stays reachable (no runner exists in
        # this product), but a vacuous report must never read as a run.
        assert v["inputs"]["tests_ran"] == 0
        assert v["inputs"]["tests_provenance"] == "caller_reported"
        assert v["inputs"]["tests_verified_execution"] is False

    def test_absent_tests_disclosed_honestly(self):
        v = self._v(None)
        assert v["tests"]["validation"] == "absent"
        assert "never implies tests were executed" in v["tests"]["note"]
        assert v["inputs"]["tests_provenance"] == "absent"
        assert v["inputs"]["tests_verified_execution"] is False

    def test_caller_success_cannot_lift_graph_status(self):
        v = self._v({"ran": 10, "failed": 0}, status="PARTIAL")
        assert v["verdict"] == "warn"
        assert v["inputs"]["assurance_status"] == "PARTIAL"

    def test_incompatible_pre_receipt_never_reads_clean(self):
        v = safe_commit_verdict(
            assurance_status="ASSURED_WITHIN_SCOPE", dangling_count=0,
            debt_introduced=0, dispositions={"pre_receipt_attached": False},
            pre_receipt_binding={"status": "incompatible",
                                 "reasons": ["digest mismatch"]})
        assert v["verdict"] == "warn"
        assert v["inputs"]["pre_receipt_binding"] == "incompatible"
        assert any("incompatible" in r for r in v["warn_reasons"])

    def test_canonical_echo_keeps_established_shape(self):
        from sot_graph.assurance.resolution import (
            canonical_test_results, validate_test_results)
        raw = {"ran": 5, "failed": 0, "failures": ["t_x"]}
        ev = validate_test_results(raw)
        assert canonical_test_results(raw, ev) == {
            "ran": 5, "failed": 1, "failures": ["t_x"]}
        bad = validate_test_results(
            {"ran": float("nan"), "failed": 0, "command": "pytest"})
        echo = canonical_test_results(
            {"ran": float("nan"), "failed": 0, "command": "pytest"}, bad)
        # JSON-clean echo, no evidence block nested inside.
        import json as _json
        _json.dumps(echo, allow_nan=False)
        assert "provenance" not in echo
