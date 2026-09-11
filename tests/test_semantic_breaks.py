"""W6 — semantic_breaks collector: signature/contract breaks with callers.

Pass bar: every planted breaking change WITH surviving callers → block;
compatible changes and counter-corpus (dynamic call sites) never block;
public removals without callers → warn; non-Python files disclosed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def _reconcile(repo: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
         "reconcile"], cwd=repo, check=True, capture_output=True)


def _diff_receipt(repo: Path):
    from sot_graph.assurance.impact_pipeline import (
        ImpactClaimRequest, run_impact_claim)
    from sot_graph.db import Database

    db = Database(str(repo / ".sot" / "sot.db"))
    try:
        return run_impact_claim(
            ImpactClaimRequest(working_tree=True), db, str(repo))
    finally:
        db.close()


@pytest.fixture()
def repo(tmp_path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    (r / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    (r / "util.py").write_text(
        "def help(a, b=1):\n    return a + b\n"
        "\ndef drop(x):\n    return x\n"
        "\ndef _priv(y):\n    return y\n",
        encoding="utf-8")
    (r / "app.py").write_text(
        "import util\n\ndef run():\n    return util.help(1) + util.drop(2)\n",
        encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "c1")
    _reconcile(r)
    return r


def _rewrite(repo: Path, name: str, body: str) -> None:
    (repo / name).write_text(body, encoding="utf-8")


class TestSemanticBreaks:
    def test_breaking_signature_with_caller_blocks(self, repo):
        _rewrite(repo, "util.py",
                 "def help(a, c=1):\n    return a + c\n"
                 "\ndef drop(x):\n    return x\n"
                 "\ndef _priv(y):\n    return y\n")
        r = _diff_receipt(repo)
        sb = r["resolution_ledger"]["semantic_breaks"]
        assert sb["counts"]["breaking"] == 1
        ch = sb["signature_changes"][0]
        assert ch["symbol"] == "help"
        assert "app.py" in ch["callers_at_risk"]
        assert any("breaking signature" in b
                   for b in r["safe_commit"]["block_reasons"])

    def test_added_optional_param_is_compatible(self, repo):
        _rewrite(repo, "util.py",
                 "def help(a, b=1, extra=0):\n    return a + b + extra\n"
                 "\ndef drop(x):\n    return x\n"
                 "\ndef _priv(y):\n    return y\n")
        r = _diff_receipt(repo)
        sb = r["resolution_ledger"]["semantic_breaks"]
        assert sb["counts"]["breaking"] == 0
        assert not any("breaking signature" in b
                       for b in r["safe_commit"]["block_reasons"])

    def test_removed_private_symbol_not_flagged(self, repo):
        _rewrite(repo, "util.py",
                 "def help(a, b=1):\n    return a + b\n"
                 "\ndef drop(x):\n    return x\n")
        r = _diff_receipt(repo)
        sb = r["resolution_ledger"]["semantic_breaks"]
        assert sb["counts"]["removed_public"] == 0

    def test_removed_public_without_caller_warns(self, repo):
        # remove `drop` AND its caller line in the same diff → no
        # surviving caller, but the public symbol is gone.
        _rewrite(repo, "util.py",
                 "def help(a, b=1):\n    return a + b\n"
                 "\ndef _priv(y):\n    return y\n")
        _rewrite(repo, "app.py",
                 "import util\n\ndef run():\n    return util.help(1)\n")
        r = _diff_receipt(repo)
        sb = r["resolution_ledger"]["semantic_breaks"]
        assert sb["counts"]["removed_public"] == 1
        assert any("public symbol(s) removed" in w
                   for w in r["safe_commit"]["warn_reasons"])

    def test_varargs_removed_is_breaking(self, repo):
        _rewrite(repo, "util.py",
                 "def help(a, *args):\n    return a + len(args)\n"
                 "\ndef drop(x):\n    return x\n"
                 "\ndef _priv(y):\n    return y\n")
        # first make *args exist in HEAD
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "add varargs")
        _reconcile(repo)
        _rewrite(repo, "util.py",
                 "def help(a):\n    return a\n"
                 "\ndef drop(x):\n    return x\n"
                 "\ndef _priv(y):\n    return y\n")
        r = _diff_receipt(repo)
        sb = r["resolution_ledger"]["semantic_breaks"]
        assert sb["counts"]["breaking"] == 1

    def test_dynamic_callsite_does_not_false_block(self, repo):
        # caller invokes via getattr — no `calls` edge → warn, not block.
        _rewrite(repo, "app.py",
                 "import util\n\ndef run():\n"
                 "    fn = getattr(util, 'help')\n"
                 "    return fn(1)\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "dynamic caller")
        _reconcile(repo)
        _rewrite(repo, "util.py",
                 "def help(a, b, c):\n    return a + b + c\n"
                 "\ndef drop(x):\n    return x\n"
                 "\ndef _priv(y):\n    return y\n")
        r = _diff_receipt(repo)
        sb = r["resolution_ledger"]["semantic_breaks"]
        assert sb["counts"]["breaking"] == 1
        # no indexed caller → warn, never block on this evidence
        assert not any("breaking signature" in b
                       for b in r["safe_commit"]["block_reasons"])
        assert any("breaking signature" in w
                   for w in r["safe_commit"]["warn_reasons"])

    def test_non_python_files_disclosed(self, repo):
        (repo / "data.cfg").write_text("[x]\nkey=1\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "cfg")
        _reconcile(repo)
        (repo / "data.cfg").write_text("[x]\nkey=2\n", encoding="utf-8")
        r = _diff_receipt(repo)
        sb = r["resolution_ledger"]["semantic_breaks"]
        assert sb["skipped_unsupported"] >= 1
        assert any("python-only" in b for b in sb["known_blind_spots"])

    def test_new_file_skipped_gracefully(self, repo):
        (repo / "new.py").write_text("def fresh():\n    return 1\n",
                                     encoding="utf-8")
        r = _diff_receipt(repo)
        sb = r["resolution_ledger"]["semantic_breaks"]
        assert sb["counts"]["breaking"] == 0
        assert sb["counts"]["removed_public"] == 0
