"""W8.2 — pre-commit gate hook: install idempotent, gates staged diffs.

The hook runs `diff-impact --staged --gate-strict` with the in-process
SIGALRM timeout (--gate-timeout) — no external `timeout` binary, which
does not exist on stock macOS.
"""
from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import pytest

from sot_graph.adapters.hooks import (
    GATE_HOOK_MARKER, GATE_HOOK_NAME, install_precommit_gate,
)


def _git(repo: Path, *args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, **kw)


@pytest.fixture()
def repo(tmp_path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    (r / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    (r / "util.py").write_text("def help(a, b):\n    return a + b\n",
                               encoding="utf-8")
    (r / "app.py").write_text(
        "import util\n\ndef run():\n    return util.help(1, 2)\n",
        encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c1")
    subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(r),
         "reconcile"], cwd=r, check=True, capture_output=True)
    return r


class TestHookInstall:
    def test_install_is_idempotent(self, repo):
        first = install_precommit_gate(repo)
        second = install_precommit_gate(repo)
        assert len(first) == 1
        assert second == []  # marker already present → no duplicate
        hook = repo / ".git" / "hooks" / GATE_HOOK_NAME
        text = hook.read_text()
        assert text.count(GATE_HOOK_MARKER) == 1
        assert "diff-impact --staged" in text
        assert "--gate-timeout" in text
        assert "timeout " not in text.split("--gate-timeout")[0].replace(
            GATE_HOOK_MARKER, "")  # no external timeout binary
        assert hook.stat().st_mode & stat.S_IXUSR

    def test_no_git_dir_returns_empty(self, tmp_path):
        assert install_precommit_gate(tmp_path / "nogit") == []


class TestHookBehavior:
    def _hook_ready(self, repo: Path) -> Path:
        """Install the hook, then repoint PYTHONPATH at the real src —
        the generated block assumes the dogfooded repo layout."""
        install_precommit_gate(repo)
        hook = repo / ".git" / "hooks" / GATE_HOOK_NAME
        real_src = Path(__file__).resolve().parents[1] / "src"
        text = hook.read_text()
        hook.write_text(text.replace(str(repo / "src"), str(real_src)))
        return hook

    def test_clean_staged_commit_passes(self, repo):
        self._hook_ready(repo)
        (repo / "notes.txt").write_text("hello\n", encoding="utf-8")
        _git(repo, "add", "notes.txt")
        proc = _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "add notes")
        assert proc.returncode == 0, proc.stderr[-400:]

    def test_breaking_staged_change_blocks(self, repo):
        self._hook_ready(repo)
        # breaking: drop required param b while app.py still calls
        # util.help(1, 2) — the W6 semantic-break collector must block.
        (repo / "util.py").write_text(
            "def help(a):\n    return a\n", encoding="utf-8")
        _git(repo, "add", "-A")
        proc = _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "break help")
        assert proc.returncode != 0
        assert "sotgraph gate" in proc.stderr
