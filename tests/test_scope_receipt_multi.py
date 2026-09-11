"""W1 multi-target scope receipts — task-level union of blast radius.

Layout of the fixture repo:
    util.py: help() (callee), helper2() calls help()
    app.py:  run() calls util.help(), main() calls run() and helper2()
    tests/test_app.py: tests run()
So targets {run, help} share callers (test_app, main…) — dedup matters.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sot_graph.assurance.receipts import (
    RECEIPT_SCHEMA_VERSION,
    _strip_volatile,
    receipt_digest,
    scope_receipt,
    scope_receipt_multi,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture(scope="module")
def multi_repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("mrepo")
    (repo / "util.py").write_text(
        "def help():\n    return 41\n\n"
        "def helper2():\n    return help() + 1\n",
        encoding="utf-8",
    )
    (repo / "app.py").write_text(
        "import util\n\n"
        "def run():\n    return util.help() + 1\n\n"
        "def main():\n    return run() + util.helper2()\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text(
        "from app import run\n\n"
        "def test_run():\n    assert run()\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c1")
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
         "reconcile"],
        check=True, cwd=repo, capture_output=True,
    )
    return repo


def _db_of(repo: Path):
    from sot_graph.db import Database

    return Database(str(repo / ".sot" / "sot.db"))


class TestMultiScopeReceipt:
    def test_single_target_parity(self, multi_repo):
        """One target through the multi API is identical modulo the
        wall-clock capture fields (captured_at is digest-excluded but
        part of the raw payload — compare the volatile-stripped view)."""
        db = _db_of(multi_repo)
        try:
            a = scope_receipt(db, str(multi_repo), "run")
            b = scope_receipt_multi(db, str(multi_repo), ["run"])
        finally:
            db.close()
        assert _strip_volatile(a) == _strip_volatile(b)
        assert a["digest"] == b["digest"]

    def test_union_superset_and_dedup(self, multi_repo):
        db = _db_of(multi_repo)
        try:
            s_run = scope_receipt(db, str(multi_repo), "run")
            s_help = scope_receipt(db, str(multi_repo), "help")
            m = scope_receipt_multi(db, str(multi_repo), ["run", "help"])
        finally:
            db.close()
        # Union covers both singles.
        af = set(m["affected_files"])
        assert set(s_run["affected_files"]) <= af
        assert set(s_help["affected_files"]) <= af
        # Shared caller (main calls run AND helper2->help) deduplicated.
        ids = [c.get("id") or c.get("node_id") for c in m["direct_callers"]]
        assert len(ids) == len(set(ids))
        # Candidate tests discovered via either target appear once.
        assert any("test_app" in t for t in m["candidate_tests"])
        # Merged request block + per-target breakdown exist.
        assert m["request"]["targets"] == ["help", "run"]  # sorted
        assert set(m["per_target"]) == {"run", "help"}
        assert m["schema_version"] == RECEIPT_SCHEMA_VERSION == "1.10"
        assert len(m["digest"]) == 64

    def test_multi_digest_differs_and_deterministic(self, multi_repo):
        db = _db_of(multi_repo)
        try:
            m1 = scope_receipt_multi(db, str(multi_repo), ["run", "help"])
            m2 = scope_receipt_multi(db, str(multi_repo), ["help", "run"])
            s = scope_receipt(db, str(multi_repo), "run")
        finally:
            db.close()
        # Target order must not change the merged receipt.
        assert m1["digest"] == m2["digest"]
        assert m1["digest"] != s["digest"]
        # Digest recomputes over content.
        recomputed = receipt_digest(
            {k: v for k, v in m1.items() if k != "digest"})
        assert m1["digest"] == recomputed

    def test_partial_isolation_not_found(self, multi_repo):
        """One dead target degrades to PARTIAL, keeps the good evidence."""
        db = _db_of(multi_repo)
        try:
            m = scope_receipt_multi(
                db, str(multi_repo), ["run", "ghost_fn_xyz"])
        finally:
            db.close()
        pt = m["per_target"]
        assert pt["run"]["identity_status"] == "UNIQUE"
        assert pt["ghost_fn_xyz"]["identity_status"] == "NOT_FOUND"
        # run()'s evidence is still present in the union.
        assert m["affected_files"]
        assert m["direct_callers"] or m["candidate_tests"]
        # Fail-closed: mixed resolution caps at PARTIAL via canonical
        # decide() — not silently ASSURED, not fully ABSTAINED.
        assert m["assurance"]["status"] == "PARTIAL"
        assert "targets_partially_resolved" in m["assurance"]["reason_codes"]
        assert m["assurance_facts"]["partial_targets"] == 1

    def test_all_unresolved_abstains(self, multi_repo):
        db = _db_of(multi_repo)
        try:
            m = scope_receipt_multi(
                db, str(multi_repo), ["ghost_a", "ghost_b"])
        finally:
            db.close()
        assert m["assurance"]["status"] == "ABSTAINED"
        assert m["identity"]["status"] in ("NOT_FOUND", "AMBIGUOUS")
        assert "target_not_found" in m["assurance"]["reason_codes"]

    def test_multi_ambiguous_not_quietly_unique(self, multi_repo):
        # "helper2" and "help" are unique; a bare common name that maps
        # to several nodes would surface AMBIGUOUS — covered indirectly
        # via the recovery path in single-target tests.
        db = _db_of(multi_repo)
        try:
            m = scope_receipt_multi(
                db, str(multi_repo), ["help", "helper2"])
        finally:
            db.close()
        # Both resolve: no partial cap.
        assert m["assurance_facts"]["partial_targets"] == 0
        assert m["assurance"]["status"] in (
            "ASSURED_WITHIN_SCOPE", "PARTIAL")  # PARTIAL ok (coverage etc.)

    def test_rename_gate_aggregates(self, multi_repo):
        db = _db_of(multi_repo)
        try:
            m = scope_receipt_multi(
                db, str(multi_repo), ["run", "help"],
                kind_of_change="rename")
        finally:
            db.close()
        gate = m["assurance"]["rename_gate"]
        assert "per_target" in gate and set(gate["per_target"]) == {
            "run", "help"}
        # Any blocked target blocks the merged gate.
        assert gate["blocked"] == any(
            g.get("blocked") for g in gate["per_target"].values())

    def test_empty_targets_raise(self, multi_repo):
        db = _db_of(multi_repo)
        try:
            with pytest.raises(ValueError):
                scope_receipt_multi(db, str(multi_repo), [])
            with pytest.raises(ValueError):
                scope_receipt_multi(db, str(multi_repo), ["  ", ""])
        finally:
            db.close()

    def test_cli_multi_acceptance(self, multi_repo):
        """End-to-end: two positional targets through the CLI."""
        proc = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root",
             str(multi_repo), "scope-receipt", "run", "help", "--json"],
            capture_output=True, text=True, cwd=multi_repo,
        )
        assert proc.returncode in (0, 2), proc.stderr[:500]
        import json

        payload = json.loads(proc.stdout)
        assert payload["request"]["targets"] == ["help", "run"]
        assert "per_target" in payload
