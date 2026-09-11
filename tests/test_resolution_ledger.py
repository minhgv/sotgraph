"""P7.3 resolution ledger — collectors, payload wiring, CLI rendering.

The diff receipt must answer "what is left unresolved", not just "what
was affected": pre/post dispositions, dangling references (rename
leftovers), debt markers on added lines.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from sot_graph.assurance.receipts import (
    RECEIPT_SCHEMA_VERSION,
    diff_impact_receipt,
    scope_receipt,
)
from sot_graph.assurance.resolution import (
    debt_markers,
    disposition_matrix,
    scan_added_lines_for_markers,
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
        import json as _json

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
