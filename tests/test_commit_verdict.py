"""W3 commit-verdict — the G3 monitoring verdict: did a commit leave
residual defects? Maps labeled outcomes to clear-fault | still-hot |
unknown with fail-closed semantics (absence-based verdicts need a
complete observation window; positive evidence does not).

Integration fixture builds a tiny history with controlled dates via
GIT_AUTHOR_DATE/GIT_COMMITTER_DATE so the 14-day observation window is
complete for old commits and incomplete for the newest one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sot_graph.outcome import (
    CommitOutcome,
    COMMIT_VERDICTS,
    collect_commit_records,
    commit_verdict,
    label_outcomes,
)


def _git(repo: Path, *args: str, days_ago: float = 0) -> None:
    env = dict(os.environ)
    if days_ago:
        ts = int(time.time() - days_ago * 86400)
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = str(ts)
    subprocess.run(["git", *args], cwd=repo, check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _mk_outcome(**kw) -> CommitOutcome:
    base = dict(
        sha="a" * 40, short_sha="aaaaaaa", subject="c", date="2026-01-01",
        risk_level="LOW", outcome="clean", window_complete=True)
    base.update(kw)
    return CommitOutcome(**base)


class TestCommitVerdictPure:
    def test_reverted_is_still_hot(self):
        v = commit_verdict(_mk_outcome(
            outcome="reverted", reverted_by=["b" * 40]))
        assert v["verdict"] == "still-hot"
        assert any("reverted_by" in r for r in v["reason_codes"])

    def test_fixup_is_still_hot(self):
        v = commit_verdict(_mk_outcome(
            outcome="fixup", follow_up_shas=["b" * 40]))
        assert v["verdict"] == "still-hot"
        assert any("follow_up_repairs" in r for r in v["reason_codes"])

    def test_positive_evidence_beats_incomplete_window(self):
        """A KNOWN revert/fixup stays still-hot even when the
        observation window is incomplete — positive evidence does not
        need the window."""
        v = commit_verdict(_mk_outcome(
            outcome="fixup", follow_up_shas=["b" * 40],
            window_complete=False))
        assert v["verdict"] == "still-hot"

    def test_clean_complete_window_clears(self):
        v = commit_verdict(_mk_outcome(outcome="clean"))
        assert v["verdict"] == "clear-fault"

    def test_clean_incomplete_window_is_unknown(self):
        v = commit_verdict(_mk_outcome(
            outcome="clean", window_complete=False))
        assert v["verdict"] == "unknown"
        assert any("insufficient_window" in r for r in v["reason_codes"])

    def test_retouched_is_unknown_not_still_hot(self):
        """Churn is a hotspot signal, not defect evidence — honest
        'unknown' keeps still-hot precision meaningful."""
        v = commit_verdict(_mk_outcome(
            outcome="retouched", retouch_count=3))
        assert v["verdict"] == "unknown"
        assert any("hotspot_churn" in r for r in v["reason_codes"])

    def test_every_verdict_has_reason_codes(self):
        for oc in ("clean", "fixup", "reverted", "retouched"):
            for wc in (True, False):
                v = commit_verdict(_mk_outcome(
                    outcome=oc, window_complete=wc,
                    follow_up_shas=["b" * 40] if oc == "fixup" else [],
                    reverted_by=["c" * 40] if oc == "reverted" else []))
                assert v["verdict"] in COMMIT_VERDICTS
                assert v["reason_codes"], f"{oc}/{wc} has no reason"


@pytest.fixture()
def verdict_repo(tmp_path) -> Path:
    """History with a planted break+repair pair and controlled dates:
      c0 (35d): initial README          → clean, complete window
      c1 (30d): util.helper + app.run   → clean, complete window
      c2 (20d): helper returns 99
                (planted regression)    → fixup (c3 repairs it)
      c3 (19d): restore return value    → clean, complete window
      c4 (0d):  docs touch              → window incomplete → unknown
    """
    repo = tmp_path / "vrepo"
    repo.mkdir()
    (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("# x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c0 init", days_ago=35)

    (repo / "util.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8")
    (repo / "app.py").write_text(
        "import util\n\ndef run():\n    return util.helper() + 1\n",
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c1 add helper", days_ago=30)

    (repo / "util.py").write_text(
        "def helper():\n    return 99  # planted regression\n",
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "c2 change helper", days_ago=20)

    (repo / "util.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "fix: restore helper return", days_ago=19)

    (repo / "README.md").write_text("# x\n\ndocs\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "docs update", days_ago=0)
    return repo


def _verdicts(repo: Path):
    records = collect_commit_records(str(repo), limit=50)
    return {o.sha: commit_verdict(o) for o in label_outcomes(records)}, \
        label_outcomes(records)


class TestCommitVerdictIntegration:
    def test_verdicts_match_history(self, verdict_repo):
        verdicts, outcomes = _verdicts(verdict_repo)
        by_subj = {o.subject: o for o in outcomes}
        c2 = verdicts[by_subj["c2 change helper"].sha]
        assert c2["verdict"] == "still-hot", c2
        assert c2["outcome"] == "fixup"
        c3 = verdicts[by_subj["fix: restore helper return"].sha]
        assert c3["verdict"] == "clear-fault", c3
        c4 = verdicts[by_subj["docs update"].sha]
        assert c4["verdict"] == "unknown"  # window incomplete

    def test_cli_commit_verdict(self, verdict_repo):
        sha = subprocess.run(
            ["git", "log", "--format=%H", "-1"], cwd=verdict_repo,
            capture_output=True, text=True).stdout.strip()
        proc = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root",
             str(verdict_repo), "commit-verdict", sha, "--json"],
            cwd=verdict_repo, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr[-400:]
        payload = json.loads(proc.stdout)
        assert payload["kind"] == "commit_verdict"
        assert payload["verdict"] in COMMIT_VERDICTS
        assert payload["reason_codes"]
        # Newest commit has an incomplete window → unknown.
        assert payload["verdict"] == "unknown"

    def test_cli_commit_verdict_unknown_sha(self, verdict_repo):
        proc = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root",
             str(verdict_repo), "commit-verdict", "deadbeef", "--json"],
            cwd=verdict_repo, capture_output=True, text=True)
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["verdict"] == "unknown"
        assert any("not_in_collected_window" in r
                   for r in payload["reason_codes"])

    def test_log_outcomes_column(self, verdict_repo):
        proc = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root",
             str(verdict_repo), "log", "-n", "5", "--outcomes",
             "--no-impact"],
            cwd=verdict_repo, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr[-400:]
        assert "Outcome" in proc.stdout
        assert "still-hot" in proc.stdout or "unknown" in proc.stdout
