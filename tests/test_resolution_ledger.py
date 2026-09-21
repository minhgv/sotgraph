"""P7.3 resolution ledger — collectors, payload wiring, CLI rendering.

The diff receipt must answer "what is left unresolved", not just "what
was affected": pre/post dispositions, dangling references (rename
leftovers), debt markers on added lines.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from sot_graph.assurance.receipts import (
    RECEIPT_SCHEMA_VERSION,
    diff_impact_receipt,
    receipt_digest,
    scope_receipt,
)
from sot_graph.assurance.resolution import (
    canonical_test_results,
    disposition_matrix,
    pre_receipt_binding,
    scan_added_lines_for_markers,
    validate_test_results,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True)


def _reconcile(repo: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
         "reconcile"],
        check=True, capture_output=True)


def _make_repo(base: Path) -> Path:
    repo = base / "rl_repo"
    repo.mkdir(parents=True)
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    (repo / "app.py").write_text(
        "import util\n\n"
        "def run():\n"
        "    return util.help() + 1\n",
        encoding="utf-8",
    )
    (repo / "util.py").write_text(
        "def help():\n    return 41\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text(
        "from app import run\n\n"
        "def test_run():\n    assert run()\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c1")
    _reconcile(repo)
    return repo


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


# ---------------------------------------------------------------------------
# 1. Pure diff-text scan
# ---------------------------------------------------------------------------


class TestScanAddedLines:
    DIFF = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,5 @@\n"
        " import util\n"
        "+# TODO(ship): wire the real calc\n"
        "+x = compute()  # type: ignore\n"
        "+try:\n"
        "+except:\n"
        "+    pass\n"
        "+clean = 1\n"
        "-# TODO(old): removed debt does not count\n"
    )

    def test_added_line_markers_with_new_line_numbers(self):
        hits = scan_added_lines_for_markers(self.DIFF)
        lines = {h["line"] for h in hits}
        # hunk starts at new line 1; markers land on 2,3,5
        assert lines == {2, 3, 5}
        by_line = {h["line"]: h for h in hits}
        assert by_line[2]["path"] == "app.py"
        assert "todo" in by_line[2]["kinds"]
        assert "type_ignore" in by_line[3]["kinds"]
        assert "bare_except" in by_line[5]["kinds"]

    def test_deleted_marker_lines_are_not_debt(self):
        hits = scan_added_lines_for_markers(self.DIFF)
        snippets = " ".join(h["snippet"] for h in hits)
        assert "TODO(old)" not in snippets

    def test_second_hunk_line_numbers(self):
        diff = (
            "--- a/util.py\n"
            "+++ b/util.py\n"
            "@@ -10,1 +10,2 @@\n"
            " keep\n"
            "+# FIXME: later\n"
        )
        hits = scan_added_lines_for_markers(diff)
        assert len(hits) == 1
        assert hits[0]["line"] == 11
        assert "fixme" in hits[0]["kinds"]

    def test_empty_diff(self):
        assert scan_added_lines_for_markers("") == []


# ---------------------------------------------------------------------------
# 2. Disposition matrix (pure)
# ---------------------------------------------------------------------------


class TestDispositionMatrix:
    def _pre(self) -> Dict[str, Any]:
        return {
            "identity": {"selected": {"symbol": "help"}},
            "direct_callers": [
                {"path": "/repo/src/app.py", "symbol": "run",
                 "relation": "calls"},
                {"path": "/repo/src/other.py", "symbol": "misc"},
            ],
            "candidate_tests": [
                "/repo/tests/test_app.py",
                "/repo/tests/test_other.py",
            ],
        }

    def test_addressed_vs_untouched(self):
        matrix = disposition_matrix(self._pre(), ["src/app.py"])
        callers = matrix["direct_callers"]
        assert callers["total"] == 2
        assert callers["addressed"] == 1
        assert [u["path"] for u in callers["untouched"]] == [
            "/repo/src/other.py"]
        tests = matrix["candidate_tests"]
        assert tests["addressed"] == 0
        assert len(tests["untouched"]) == 2

    def test_all_addressed(self):
        matrix = disposition_matrix(
            self._pre(), ["src/app.py", "src/other.py",
                          "tests/test_app.py", "tests/test_other.py"])
        assert matrix["direct_callers"]["untouched"] == []
        assert matrix["candidate_tests"]["untouched"] == []

    def test_no_pre_receipt_is_explicit(self):
        matrix = disposition_matrix(None, ["app.py"])
        assert matrix["pre_receipt_attached"] is False
        assert matrix["direct_callers"]["total"] == 0


# ---------------------------------------------------------------------------
# 3. End-to-end receipts
# ---------------------------------------------------------------------------


class TestDebtMarkersEndToEnd:
    def test_marker_in_committed_diff(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    return util.help() + 1  # TODO(p73): revisit\n",
            encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c2")
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        debt = payload["resolution_ledger"]["debt_markers"]
        assert debt["total"] == 1
        assert debt["introduced"][0]["path"] == "app.py"
        assert "todo" in debt["introduced"][0]["kinds"]
        stats = payload["collection_stats"]["debt_markers"]
        assert stats["returned_count"] == 1
        assert stats["truncated"] is False
        assert any("debt marker(s) introduced" in g
                   for g in payload["remaining_gaps"])

    def test_clean_diff_has_no_markers_and_no_gap(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    return util.help() + 2\n",
            encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c2")
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        assert payload["resolution_ledger"]["debt_markers"]["total"] == 0
        assert not any("debt marker" in g
                       for g in payload["remaining_gaps"])


class TestDanglingReferences:
    def test_rename_leftover_via_pre_receipt(self, tmp_path):
        repo = _make_repo(tmp_path)
        db = _db_of(repo)
        try:
            pre = scope_receipt(db, str(repo), "help")
        finally:
            db.close()
        assert pre["identity"]["status"] == "UNIQUE"
        # Rename help -> assist in util.py; app.py (the caller) untouched.
        (repo / "util.py").write_text(
            "def assist():\n    return 41\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "rename")
        _reconcile(repo)
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo), pre_receipt=pre)
            no_pre = diff_impact_receipt(db, str(repo))
        finally:
            db.close()

        dang = payload["resolution_ledger"]["dangling_references"]
        assert dang["count"] >= 1
        leftovers = [
            e for e in dang["removed_pre_change_symbols"]
            if e["dst_symbol"] == "help"
        ]
        assert leftovers, f"rename leftover not found: {dang}"
        assert any(e["path"].endswith("app.py") for e in leftovers)
        assert leftovers[0]["state"] == "PRE_CHANGE_CALLER_OF_REMOVED_SYMBOL"
        # Decision-grade: danglers block closure via unresolved_over_budget.
        assert "unresolved_over_budget" in (
            payload["assurance"]["reason_codes"])
        assert payload["closure_decision"] == "open"
        assert any("dangling reference(s)" in g
                   for g in payload["remaining_gaps"])
        # Scoped honesty: without the pre-receipt the same repo reports
        # no danglers — the receipt never claims repo-wide absence.
        assert no_pre["resolution_ledger"]["dangling_references"][
            "count"] == 0
        assert no_pre["resolution_ledger"]["dispositions"][
            "pre_receipt_attached"] is False

    def test_healthy_change_has_no_danglers(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "util.py").write_text(
            "def help():\n    return 42\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c2")
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        assert payload["resolution_ledger"][
            "dangling_references"]["count"] == 0

    def test_preexisting_pending_row_on_untouched_line_not_counted(
            self, tmp_path):
        """A pending row that predates the diff must not read as a dangler.

        Regression: the changed-file sweep used to count EVERY unresolved
        pending row in a touched file, so any edit to a file containing
        receiver-bearing calls the extractor cannot resolve (e.g. str
        methods) blocked safe_commit forever.
        """
        repo = _make_repo(tmp_path)
        (repo / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    label = 'x'.strip()\n"  # pre-existing unresolved call
            "    return util.help() + 1\n",
            encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c2")
        _reconcile(repo)
        db = _db_of(repo)
        try:
            parked = db.conn.execute(
                "SELECT COUNT(*) FROM pending_edges "
                "WHERE dst_symbol = 'strip'").fetchone()[0]
        finally:
            db.close()
        assert parked >= 1, "fixture must park a pre-existing unresolved row"
        # Edit an unrelated line; the strip line stays untouched context.
        (repo / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    label = 'x'.strip()\n"
            "    return util.help() + 2\n",
            encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c3")
        _reconcile(repo)
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        dang = payload["resolution_ledger"]["dangling_references"]
        assert dang["count"] == 0, dang
        assert dang["line_scoped"] is True
        assert dang["preexisting_unresolved"] >= 1

    def test_new_pending_row_on_added_line_counts(self, tmp_path):
        """A pending row introduced BY the diff still counts."""
        repo = _make_repo(tmp_path)
        (repo / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    label = 'x'.strip()\n"  # NEW unresolved call on added line
            "    return util.help() + 1\n",
            encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c2")
        _reconcile(repo)
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        dang = payload["resolution_ledger"]["dangling_references"]
        assert dang["count"] >= 1
        assert any(e["dst_symbol"] == "strip"
                   for e in dang["changed_or_caller_files"])


class TestDispositionWiring:
    def test_pre_receipt_join_untouched_caller(self, tmp_path):
        repo = _make_repo(tmp_path)
        db = _db_of(repo)
        try:
            pre = scope_receipt(db, str(repo), "help")
        finally:
            db.close()
        # Change touches ONLY an unrelated file: every predicted caller
        # and candidate test stays untouched.
        (repo / "README.md").write_text("docs only\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "docs")
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo), pre_receipt=pre)
        finally:
            db.close()
        disp = payload["resolution_ledger"]["dispositions"]
        assert disp["pre_receipt_attached"] is True
        assert disp["direct_callers"]["addressed"] == 0
        assert len(disp["direct_callers"]["untouched"]) == len(
            pre["direct_callers"])
        assert any("predicted direct caller(s) untouched" in g
                   for g in payload["remaining_gaps"])

    def test_pre_receipt_join_addressed_caller(self, tmp_path):
        repo = _make_repo(tmp_path)
        db = _db_of(repo)
        try:
            pre = scope_receipt(db, str(repo), "help")
        finally:
            db.close()
        assert pre["direct_callers"]
        (repo / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    return util.help() + 2\n",
            encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "caller")
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo), pre_receipt=pre)
        finally:
            db.close()
        disp = payload["resolution_ledger"]["dispositions"]
        # The app.py caller must now be addressed; whatever other
        # callers the pre-receipt found stay untouched.
        untouched_paths = [u["path"] for u in
                           disp["direct_callers"]["untouched"]]
        assert disp["direct_callers"]["addressed"] >= 1
        assert not any(p.endswith("app.py") for p in untouched_paths)
        assert disp["direct_callers"]["total"] == len(
            pre["direct_callers"])


class TestSchemaBlock:
    def test_schema_1_9_and_explorer_accepts(self, tmp_path):
        repo = _make_repo(tmp_path)
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        assert payload["schema_version"] == "1.12"
        assert RECEIPT_SCHEMA_VERSION == "1.12"
        from sot_graph.receipt_explorer import (
            KNOWN_RECEIPT_SCHEMA_VERSIONS,
            gate_receipt_version,
        )
        assert "1.11" in KNOWN_RECEIPT_SCHEMA_VERSIONS
        gate_receipt_version(payload)  # must not raise


# ---------------------------------------------------------------------------
# 4. CLI rendering
# ---------------------------------------------------------------------------


class TestCliRendering:
    def test_text_mode_renders_ledger_lines(self, tmp_path, capsys, monkeypatch):
        repo = _make_repo(tmp_path)
        (repo / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    return util.help() + 1  # TODO(p73): later\n",
            encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c2")
        import argparse

        from sot_graph.cli import cmd_diff_impact
        from sot_graph.db import Database

        args = argparse.Namespace(
            command="diff-impact", target="HEAD", depth=2, staged=False,
            working_tree=False, auto_reconcile=True, pre_receipt=None,
            json=False, format="text", output=None, gate=False,
            provider="builtin",
        )
        db = Database(str(repo / ".sot" / "sot.db"))
        try:
            rc = cmd_diff_impact(args, db, str(repo))
        finally:
            db.close()
        out = capsys.readouterr().out
        assert rc == 0
        assert "1 debt marker(s) introduced" in out

    def test_pre_receipt_flag_renders_disposition(self, tmp_path, capsys):
        repo = _make_repo(tmp_path)
        db = _db_of(repo)
        try:
            pre = scope_receipt(db, str(repo), "help")
        finally:
            db.close()
        (repo / "README.md").write_text("docs\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "docs")
        import argparse

        from sot_graph.assurance.impact_pipeline import ReceiptStore
        from sot_graph.cli import cmd_diff_impact
        from sot_graph.db import Database

        store = ReceiptStore(str(repo / ".sot" / "receipts"))
        digest = store.put(pre)
        args = argparse.Namespace(
            command="diff-impact", target="HEAD", depth=2, staged=False,
            working_tree=False, auto_reconcile=True,
            pre_receipt=digest, json=False, format="text", output=None,
            gate=False, provider="builtin",
        )
        db = Database(str(repo / ".sot" / "sot.db"))
        try:
            rc = cmd_diff_impact(args, db, str(repo))
        finally:
            db.close()
        out = capsys.readouterr().out
        assert rc == 0
        assert "predicted caller(s) addressed" in out


# ---------------------------------------------------------------------------
# 5. T-07/AC-05 — PRE-binding audit + test-result trust boundary
# ---------------------------------------------------------------------------


class TestValidateTestResults:
    def test_valid_counts_honored_exactly(self):
        ev = validate_test_results(
            {"ran": 3, "failed": 1, "failures": ["t"]})
        assert ev["provenance"] == "caller_reported"
        assert ev["validation"] == "valid"
        assert ev["ran"] == 3 and ev["failed"] == 1
        assert ev["effective_failed"] == 1
        assert ev["healed_failed"] is False

    def test_success_claim_with_failures_heals_up_only(self):
        ev = validate_test_results(
            {"ran": 5, "failed": 0, "failures": ["x"]})
        assert ev["validation"] == "valid"
        assert ev["effective_failed"] == 1
        assert ev["healed_failed"] is True

    def test_zero_counts_with_labels_stay_valid_and_blocking(self):
        """R-02: explicit zero counts beside a failure label are healed
        from the labels, not judged a contradictory claim — the report
        stays valid so the failure keeps blocking."""
        ev = validate_test_results(
            {"ran": 0, "failed": 0, "failures": ["x"]})
        assert ev["validation"] == "valid"
        assert ev["effective_failed"] == 1
        assert ev["healed_failed"] is True

    def test_label_explained_count_is_not_contradictory(self):
        """R-02: when the failed count equals the label list length it
        is label-explained healing — valid, still blocking."""
        ev = validate_test_results(
            {"ran": 1, "failed": 3, "failures": ["a", "b", "c"]})
        assert ev["validation"] == "valid"
        assert ev["effective_failed"] == 3

    def test_failures_only_echo_revalidates_as_blocking(self):
        """R-02: the canonical echo of a failures-only report must pass
        revalidation (as every strict CLI/MCP consumer performs it) with
        the same blocking count instead of degrading to invalid/warn."""
        raw = {"failures": ["a", "b"]}
        echo = canonical_test_results(raw, validate_test_results(raw))
        assert echo == {"ran": 0, "failed": 2, "failures": ["a", "b"]}
        ev2 = validate_test_results(echo)
        assert ev2["validation"] == "valid"
        assert ev2["effective_failed"] == 2
        assert ev2["healed_failed"] is False

    def test_idempotent_on_validated_blocks(self):
        once = validate_test_results({"ran": 2, "failed": 0})
        assert validate_test_results(once) == once
        bad = validate_test_results({"ran": "x"})
        assert validate_test_results(bad) == bad

    @pytest.mark.parametrize("raw", [
        True, "x", 42,
        {"ran": True},            # bool-as-int
        {"failed": 1.5},          # noninteger
        {"ran": -2},              # negative
        {"ran": "3"},             # string count
        {"ran": 1, "failed": 2},  # failed > ran
        {"ran": 3, "failed": 5, "failures": ["a"]},  # not label-explained
        {"ran": 0, "failures": "oops"},
        {"ran": 1, "command": "pytest -q", "snapshot_hash": "a" * 64},
    ])
    def test_invalid_shapes_trusted_in_neither_direction(self, raw):
        ev = validate_test_results(raw)
        assert ev["validation"] == "invalid"
        assert ev["effective_failed"] is None
        assert ev["errors"]
        assert ev["provenance"] == "caller_reported"

    def test_echo_stays_clean_json_without_nested_evidence(self):
        import json
        raw = {"ran": float("nan"), "failures": ["x"], "command": "pytest"}
        ev = validate_test_results(raw)
        echo = canonical_test_results(raw, ev)
        json.dumps(echo, allow_nan=False)  # must be standard JSON
        assert "provenance" not in echo  # no evidence nested in the echo

    def test_canonical_valid_shape_is_established_legacy(self):
        raw = {"ran": 5, "failed": 0, "failures": ["t_x"]}
        echo = canonical_test_results(raw, validate_test_results(raw))
        assert echo == {"ran": 5, "failed": 1, "failures": ["t_x"]}


class TestPreReceiptBindingAudit:
    def _pre(self, tmp_path):
        repo = _make_repo(tmp_path)
        db = _db_of(repo)
        try:
            return repo, scope_receipt(db, str(repo), "help")
        finally:
            db.close()

    def test_real_scope_receipt_binds(self, tmp_path):
        from sot_graph.assurance.receipts import _head_sha
        repo, pre = self._pre(tmp_path)
        # R-07 producer contract: real minted snapshots serialize the
        # canonical repository identity the binding guard checks.
        assert pre["snapshot"]["repo_root"] == os.path.realpath(str(repo))
        b = pre_receipt_binding(
            pre, repo_root=str(repo), head_sha=_head_sha(str(repo)))
        assert b["status"] == "bound"
        assert b["digest_verified"] is True
        assert b["head_moved"] is False

    def test_tampered_digest_incompatible(self, tmp_path):
        repo, pre = self._pre(tmp_path)
        pre["digest"] = "0" * 64
        b = pre_receipt_binding(pre, repo_root=str(repo))
        assert b["status"] == "incompatible"
        assert any("digest mismatch" in r for r in b["reasons"])

    def test_wrong_proof_scope_incompatible(self, tmp_path):
        repo, pre = self._pre(tmp_path)
        forged = dict(pre)
        forged["proof_scope"] = "post_change"
        b = pre_receipt_binding(forged, repo_root=str(repo))
        assert b["status"] == "incompatible"
        assert any("proof_scope" in r for r in b["reasons"])

    def test_foreign_repository_incompatible(self, tmp_path):
        repo, pre = self._pre(tmp_path)
        other = _make_repo(tmp_path / "elsewhere")
        b = pre_receipt_binding(pre, repo_root=str(other))
        assert b["status"] == "incompatible"
        assert any("different repository" in r for r in b["reasons"])

    def test_head_moved_flagged_but_still_bound(self, tmp_path):
        from sot_graph.assurance.receipts import _head_sha
        repo, pre = self._pre(tmp_path)
        (repo / "README.md").write_text("move on\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "docs")
        b = pre_receipt_binding(
            pre, repo_root=str(repo), head_sha=_head_sha(str(repo)))
        assert b["status"] == "bound"
        assert b["head_moved"] is True
        assert any("HEAD moved" in r for r in b["reasons"])

    def test_missing_and_unstructured(self):
        assert pre_receipt_binding(None)["status"] == "missing"
        b = pre_receipt_binding({"direct_callers": []})
        assert b["status"] == "unverified"
        assert b["digest_verified"] is None

    def test_unstructured_payload_with_valid_digest_stays_unverified(self):
        """R-06: a recomputable content digest proves internal
        consistency, not producer identity — a payload without
        kind/proof_scope markers must read unverified, never bound."""
        payload = {
            "snapshot": {"repo_root": "/somewhere",
                         "commit_sha": "c" * 40},
            "direct_callers": [],
        }
        payload["digest"] = receipt_digest(
            {k: v for k, v in payload.items() if k != "digest"})
        b = pre_receipt_binding(payload)
        assert b["status"] == "unverified"
        assert b["digest_verified"] is True
        assert any("kind/proof_scope" in r for r in b["reasons"])

    def test_snapshot_without_repo_identity_never_binds(self, tmp_path):
        """R-07: a receipt whose snapshot carries no repository identity
        (legacy pre-binding receipt, or a payload stripped of the field)
        stays advisory (unverified) even though its digest verifies —
        a missing field is not trust, and the foreign-repo guard cannot
        have run."""
        repo, pre = self._pre(tmp_path)
        legacy = dict(pre)
        legacy["snapshot"] = {
            k: v for k, v in pre["snapshot"].items()
            if k != "repo_root"}
        legacy["digest"] = receipt_digest(
            {k: v for k, v in legacy.items() if k != "digest"})
        b = pre_receipt_binding(legacy, repo_root=str(repo))
        assert b["status"] == "unverified"
        assert b["digest_verified"] is True
        assert any("repository identity" in r for r in b["reasons"])


class TestIncompatiblePreExcluded:
    def test_minted_foreign_pre_excluded_through_pipeline(self, tmp_path):
        """R-07 end to end: a PRE receipt MINTED by the real producer in
        repoA must read incompatible when attached to a repoB POST — the
        foreign-repo guard works on actual minted output, not only on
        synthetic payloads."""
        repo_a = _make_repo(tmp_path / "repo_a")
        repo_b = _make_repo(tmp_path / "repo_b")
        db_a = _db_of(repo_a)
        try:
            pre = scope_receipt(db_a, str(repo_a), "help")
        finally:
            db_a.close()
        assert pre["snapshot"]["repo_root"] == os.path.realpath(str(repo_a))
        (repo_b / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    return util.help() + 2\n",
            encoding="utf-8")
        _git(repo_b, "add", "-A")
        _git(repo_b, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "caller")
        db_b = _db_of(repo_b)
        try:
            payload = diff_impact_receipt(
                db_b, str(repo_b), pre_receipt=pre)
        finally:
            db_b.close()
        binding = payload["resolution_ledger"]["pre_receipt_binding"]
        assert binding["status"] == "incompatible"
        assert any("different repository" in r for r in binding["reasons"])
        disp = payload["resolution_ledger"]["dispositions"]
        assert disp["pre_receipt_attached"] is False
        assert disp["direct_callers"]["total"] == 0
        assert any("INCOMPATIBLE" in g for g in payload["remaining_gaps"])
        assert payload["safe_commit"]["verdict"] != "pass"
        assert (payload["safe_commit"]["inputs"]
                ["pre_receipt_binding"] == "incompatible")

    def test_tampered_pre_cannot_feed_dispositions_or_pass(self, tmp_path):
        repo = _make_repo(tmp_path)
        db = _db_of(repo)
        try:
            pre = scope_receipt(db, str(repo), "help")
        finally:
            db.close()
        assert pre["direct_callers"]  # the fixture has real predictions
        pre["digest"] = "0" * 64  # tampered / foreign bytes
        (repo / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    return util.help() + 2\n",
            encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "caller")
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo), pre_receipt=pre)
        finally:
            db.close()
        binding = payload["resolution_ledger"]["pre_receipt_binding"]
        assert binding["status"] == "incompatible"
        # Foreign predictions must not read as clean dispositions...
        disp = payload["resolution_ledger"]["dispositions"]
        assert disp["pre_receipt_attached"] is False
        assert disp["direct_callers"]["total"] == 0
        assert disp["candidate_tests"]["total"] == 0
        assert any("INCOMPATIBLE" in g for g in payload["remaining_gaps"])
        # ...and the gate must not pass on the strength of junk metadata.
        assert payload["safe_commit"]["verdict"] != "pass"
        assert (payload["safe_commit"]["inputs"]
                ["pre_receipt_binding"] == "incompatible")

    def test_ordinary_diff_contract_untouched(self, tmp_path):
        """T-08/AC-06: no PRE, no tests — engine surfaces unchanged and
        assurance metadata is honestly absent, not fabricated."""
        repo = _make_repo(tmp_path)
        (repo / "app.py").write_text(
            "import util\n\n"
            "def run():\n"
            "    return util.help() + 2\n",
            encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "caller")
        db = _db_of(repo)
        try:
            payload = diff_impact_receipt(db, str(repo))
        finally:
            db.close()
        assert payload["diff_identity"]["target"] == "HEAD"
        assert any("app.py" in str(f) for f in payload["changed_files"])
        for engine_key in ("direct_nodes", "caller_impacts", "api_impacts",
                           "test_impacts", "summary", "tests_to_run"):
            assert engine_key in payload
        assert payload["resolution_ledger"]["pre_receipt_binding"][
            "status"] == "missing"
        assert payload["safe_commit"]["tests"]["validation"] == "absent"
        assert (payload["safe_commit"]["inputs"]
                ["tests_verified_execution"] is False)
        assert payload["closure_decision"] in ("closed", "open")
