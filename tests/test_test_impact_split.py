"""W4(c) — import-driven vs call-driven test impact.

Before the split, any edge into a changed node — including a plain
``imports`` edge — was labeled ``calls_modified_node``, so a test file
that merely imported the changed module was indistinguishable from one
that actually calls the changed symbol (the B7 miss shape from the
requests-repo evaluation).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sot_graph.db import Database
from sot_graph.diff_impact import DiffImpactEngine


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture()
def impact_repo(tmp_path) -> Path:
    repo = tmp_path / "irepo"
    repo.mkdir()
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    (repo / "lib.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_calls.py").write_text(
        "import lib\n\ndef test_helper():\n    assert lib.helper() == 1\n",
        encoding="utf-8")
    (tests / "test_imports_only.py").write_text(
        "import lib\n\ndef test_smoke():\n    assert True\n",
        encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c1")
    proc = subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
         "reconcile"], cwd=repo, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-400:]
    return repo


def _impact(repo: Path):
    (repo / "lib.py").write_text(
        "def helper():\n    return 2\n", encoding="utf-8")
    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        return DiffImpactEngine(db, str(repo)).analyze_diff_impact(
            working_tree=True)
    finally:
        db.close()


def test_import_only_test_gets_import_reason(impact_repo):
    res = _impact(impact_repo)
    by_path = {}
    for t in res.test_impacts:
        by_path.setdefault(Path(t.path).name, set()).add(t.impact_reason)
    assert "imports_modified_module" in by_path.get(
        "test_imports_only.py", set()), (
        "import-only test must surface as imports_modified_module")


def test_call_test_keeps_call_reason(impact_repo):
    res = _impact(impact_repo)
    call_hits = [
        t for t in res.test_impacts
        if t.impact_reason == "calls_modified_node"
        and "test_calls" in t.path
    ]
    assert call_hits, "test calling the changed symbol must keep calls_modified_node"


def test_import_only_test_not_mislabeled_as_call(impact_repo):
    res = _impact(impact_repo)
    bad = [
        t for t in res.test_impacts
        if "test_imports_only" in t.path
        and t.impact_reason == "calls_modified_node"
    ]
    assert not bad, (
        "import-only test must not claim call-driven evidence")
