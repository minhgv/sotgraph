"""
Scope-receipt target recovery + CLI gate rendering (P7.1 parity with pack):

- identity resolution must recover agent display-string targets
  ('func run — app.py:3') and bare path:line locators ('app.py:4') while
  keeping exact-match decision semantics (no dominant auto-pick);
- the CLI text output must surface the rename-gate verdict when the gate
  is applicable — BLOCKED *and* passed — plus the recovery disclosure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from sot_graph.assurance.receipts import scope_receipt
from sot_graph.cli import cmd_scope_receipt
from sot_graph.db import Database


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _reconcile(repo: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), "reconcile"],
        check=True, cwd=repo, capture_output=True,
    )


def _make_repo(repo: Path) -> Path:
    """Same shape as the test_impact_pipeline._make_repo fixture."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    # app.py: line 1 import, 3-4 def run, 6-7 def orphan (never called).
    (repo / "app.py").write_text(
        "import util\n"
        "\n"
        "def run():\n"
        "    return util.help() + 1\n"
        "\n"
        "def orphan():\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (repo / "util.py").write_text(
        "def help():\n    return 41\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_app.py").write_text(
        "from app import run\n\n"
        "def test_run():\n    assert run()\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c1")
    _reconcile(repo)
    return repo


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    return _make_repo(tmp_path_factory.mktemp("srrecover"))


def _receipt(repo: Path, target: str, **kwargs):
    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        return scope_receipt(db, str(repo), target, **kwargs)
    finally:
        db.close()


class TestIdentityRecovery:
    def test_display_string_target_recovers_uniquely(self, repo):
        payload = _receipt(repo, "func run — app.py:3")
        assert payload["identity"]["status"] == "UNIQUE"
        rec = payload["identity"]["recovery"]
        assert rec["method"] == "normalized_symbol"
        assert rec["symbol"] == "run"
        assert payload["identity"]["selected"]["symbol"] == "run"
        # The receipt must still carry the ORIGINAL query, not the rewrite.
        assert payload["request"]["target"] == "func run — app.py:3"

    def test_path_line_locator_recovers_via_containment(self, repo):
        payload = _receipt(repo, "app.py:4")
        assert payload["identity"]["status"] == "UNIQUE"
        rec = payload["identity"]["recovery"]
        assert rec["method"] == "path_line_containment"
        assert payload["identity"]["selected"]["symbol"] == "run"

    def test_clean_target_has_no_recovery_block(self, repo):
        payload = _receipt(repo, "run")
        assert payload["identity"]["status"] == "UNIQUE"
        assert "recovery" not in payload["identity"]

    def test_unrecoverable_target_stays_not_found(self, repo):
        payload = _receipt(repo, "func Nope — app.py:99")
        assert payload["identity"]["status"] == "NOT_FOUND"
        assert "recovery" not in payload["identity"]
        assert payload["assurance"]["status"] == "ABSTAINED"
        assert "target_not_found" in payload["assurance"]["reason_codes"]

    def test_schema_version_bumped(self, repo):
        payload = _receipt(repo, "run")
        assert payload["schema_version"] == "1.8"


class TestCliRendering:
    @staticmethod
    def _run_cli(repo: Path, capsys, target: str, kind: str = "local-body"):
        db = Database(str(repo / ".sot" / "sot.db"))
        args = argparse.Namespace(
            target=target, depth=2, change_kind=kind,
            auth=False, dynamic=False, json=False,
        )
        try:
            code = cmd_scope_receipt(args, db, str(repo))
        finally:
            db.close()
        return code, capsys.readouterr().out

    def test_recovery_line_rendered(self, repo, capsys):
        code, out = self._run_cli(repo, capsys, "func run — app.py:3")
        assert code == 0
        assert "target recovered: 'func run — app.py:3' → 'app.run'" in out
        assert "(via normalized_symbol)" in out

    def test_rename_gate_passed_line_rendered(self, repo, capsys):
        # run() has one caller (tests/test_app.py) — the gate must PASS
        # and the text output must now say so, not stay silent.
        code, out = self._run_cli(repo, capsys, "run", kind="rename")
        assert code == 0
        assert "✅ rename gate passed:" in out
        assert "1 caller(s) resolved" in out

    def test_rename_gate_blocked_line_rendered(self, repo, capsys):
        # Unresolvable target: the gate cannot bound the rename scope.
        code, out = self._run_cli(repo, capsys, "NoSuchSymbol", kind="rename")
        assert code == 2
        assert "🚫 rename gate BLOCKED:" in out

    def test_local_body_does_not_render_gate(self, repo, capsys):
        _, out = self._run_cli(repo, capsys, "run", kind="local-body")
        assert "rename gate" not in out
