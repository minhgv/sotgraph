"""W5 — lineage/dossier chain: scope receipt → diff receipt → commit → outcome.

The pass bar: every receipt minted through the plan→code→commit flow
resolves all three links (scope_to_diff, diff_to_commit, commit_to_outcome).
Missing links are named, never fabricated.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sot_graph.assurance.lineage import build_chain


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, check=True,
                         capture_output=True, text=True)
    return out.stdout.strip()


def _cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo), *args],
        cwd=repo, capture_output=True, text=True)


@pytest.fixture()
def chain_repo(tmp_path) -> Path:
    repo = tmp_path / "chain"
    repo.mkdir()
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    (repo / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8")
    (repo / "app.py").write_text(
        "import calc\n\ndef run():\n    return calc.add(1, 2)\n",
        encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c1")
    proc = _cli(repo, "reconcile")
    assert proc.returncode == 0, proc.stderr[-400:]
    return repo


def _mint_scope(repo: Path) -> str:
    proc = _cli(repo, "scope-receipt", "calc.add", "--json")
    assert proc.returncode == 0, proc.stderr[-400:]
    return json.loads(proc.stdout)["digest"]


def _edit_and_commit(repo: Path, body: str) -> str:
    (repo / "calc.py").write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change add")
    return _git(repo, "rev-parse", "HEAD")


def _mint_diff(repo: Path, scope: str) -> str:
    proc = _cli(repo, "diff-impact", "--working-tree",
                "--pre-receipt", scope, "--json")
    # diff-impact exits nonzero on advisory gates; the receipt JSON is on
    # stdout regardless.
    return json.loads(proc.stdout)["digest"]


class TestLineageChain:
    def test_full_chain_completes(self, chain_repo):
        scope = _mint_scope(chain_repo)
        # edit WITHOUT committing yet — receipt minted on working tree
        (chain_repo / "calc.py").write_text(
            "def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
        diff = _mint_diff(chain_repo, scope)
        sha = _edit_and_commit(
            chain_repo, "def add(a, b):\n    return a + b + 1\n")

        chain = build_chain(str(chain_repo), diff)
        assert chain["complete"] is True, chain["missing"]
        assert chain["links"] == {
            "scope_to_diff": True, "diff_to_commit": True,
            "commit_to_outcome": True}
        assert chain["commit"]["sha"] == sha
        assert chain["outcome"]["verdict"] in (
            "clear-fault", "still-hot", "unknown")

    def test_commit_anchor_finds_producing_receipts(self, chain_repo):
        scope = _mint_scope(chain_repo)
        (chain_repo / "calc.py").write_text(
            "def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
        _mint_diff(chain_repo, scope)
        sha = _edit_and_commit(
            chain_repo, "def add(a, b):\n    return a + b + 1\n")

        chain = build_chain(str(chain_repo), sha)
        assert chain["anchor"]["kind"] == "commit"
        assert chain["diff_receipts"], (
            "commit anchor must find the diff receipt minted before it")
        assert chain["links"]["diff_to_commit"] is True
        assert chain["links"]["commit_to_outcome"] is True

    def test_scope_anchor_walks_forward(self, chain_repo):
        scope = _mint_scope(chain_repo)
        (chain_repo / "calc.py").write_text(
            "def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
        _mint_diff(chain_repo, scope)
        _edit_and_commit(
            chain_repo, "def add(a, b):\n    return a + b + 1\n")

        chain = build_chain(str(chain_repo), scope)
        assert chain["anchor"]["kind"] == "scope"
        assert chain["diff_receipts"]
        assert chain["links"]["scope_to_diff"] is True
        assert chain["links"]["diff_to_commit"] is True

    def test_missing_scope_link_is_disclosed(self, chain_repo):
        (chain_repo / "calc.py").write_text(
            "def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
        proc = _cli(chain_repo, "diff-impact", "--working-tree", "--json")
        diff = json.loads(proc.stdout)["digest"]
        chain = build_chain(str(chain_repo), diff)
        assert chain["links"]["scope_to_diff"] is False
        assert any("pre_receipt" in m or "scope" in m
                   for m in chain["missing"])

    def test_unresolvable_ref_fails_closed(self, chain_repo):
        chain = build_chain(str(chain_repo), "nonexistent-ref-xyz")
        assert chain["error"]
        assert chain["complete"] is False

    def test_cli_chain_exit_codes(self, chain_repo):
        proc = _cli(chain_repo, "receipt", "chain", "deadbeef-not-a-thing")
        assert proc.returncode == 1
        proc = _cli(chain_repo, "receipt", "chain",
                    _git(chain_repo, "rev-parse", "HEAD"), "--json")
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["kind"] == "lineage_chain"
        assert payload["anchor"]["kind"] == "commit"
