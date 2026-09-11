"""W7 — risk calibration: learned weights from labeled outcomes.

Pass bar: learned model only surfaces when it beats base-rate CV;
below MIN_SAMPLES or a non-beating fit → heuristic_fallback with a
disclosed reason; predictions deterministic; window-incomplete commits
never enter the training set.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List


from sot_graph.calibration import (
    MIN_SAMPLES, commit_features, fit_model, load_model,
    save_model,
)


@dataclass
class _Rec:
    sha: str
    files: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    touched_symbols: List[str] = field(default_factory=list)
    subject: str = ""
    tags: set = field(default_factory=set)


@dataclass
class _Oc:
    sha: str
    outcome: str = "clean"
    window_complete: bool = True


def _synthetic(n: int = 90):
    """Adverse correlates with churn+critical paths — learnable signal."""
    recs, outs = [], []
    for i in range(n):
        heavy = i % 3 == 0
        recs.append(_Rec(
            sha=f"{i:040x}",
            files=(["auth/login.py", "schema/mig.sql", "app.py"]
                   if heavy else ["readme.md"]),
            insertions=400 if heavy else 5,
            deletions=100 if heavy else 0,
            touched_symbols=["a", "b"] if heavy else [],
            subject="fix stuff" if heavy else "docs",
            tags={"fix"} if heavy else set(),
        ))
        outs.append(_Oc(
            sha=f"{i:040x}",
            outcome="fixup" if heavy and i % 9 else "clean"))
    return recs, outs


class TestFitModel:
    def test_learns_when_signal_present(self):
        recs, outs = _synthetic()
        model, report = fit_model(recs, outs)
        assert model is not None, report
        assert report["model_source"] == "learned"
        assert report["cv_logloss"] < report["baseline_logloss"]
        rates = report["bucket_adverse_rates"]
        assert rates["LOW"] <= rates["MEDIUM"] <= rates["HIGH"]

    def test_few_samples_falls_back_honestly(self):
        recs, outs = _synthetic(10)
        model, report = fit_model(recs, outs)
        assert model is None
        assert report["model_source"] == "heuristic_fallback"
        assert str(MIN_SAMPLES) in report["reason"]

    def test_single_class_falls_back(self):
        recs, outs = _synthetic()
        for o in outs:
            o.outcome = "clean"
        model, report = fit_model(recs, outs)
        assert model is None
        assert report["model_source"] == "heuristic_fallback"

    def test_incomplete_windows_excluded(self):
        recs, outs = _synthetic()
        for o in outs[:60]:
            o.window_complete = False
        _, report = fit_model(recs, outs)
        assert report["skipped_incomplete_window"] == 60
        assert report["n_samples"] == len(recs) - 60

    def test_deterministic_fit(self):
        recs, outs = _synthetic()
        m1, _ = fit_model(recs, outs)
        m2, _ = fit_model(recs, outs)
        assert m1 is not None and m2 is not None
        assert m1.weights == m2.weights and m1.intercept == m2.intercept

    def test_save_load_roundtrip(self, tmp_path):
        recs, outs = _synthetic()
        model, _ = fit_model(recs, outs)
        assert model is not None
        path = save_model(str(tmp_path), model)
        loaded = load_model(str(tmp_path))
        assert loaded is not None
        # to_dict rounds to 6dp — compare the serialized form
        assert loaded.weights == [round(w, 6) for w in model.weights]
        assert loaded.cutoff_low_medium == round(
            model.cutoff_low_medium, 6)
        assert os.path.basename(path) == "risk_model.json"

    def test_heavy_commit_scores_higher(self):
        recs, outs = _synthetic()
        model, _ = fit_model(recs, outs)
        heavy = commit_features(recs[0])
        light = commit_features(recs[1])
        assert model.p_adverse(heavy) > model.p_adverse(light)


class TestCalibrateCli:
    def test_calibrate_then_log_carries_learned_fields(self, tmp_path):
        repo = tmp_path / "r"
        repo.mkdir()
        (repo / ".gitignore").write_text(".sot/\n", encoding="utf-8")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        for c in (["git", "init", "-q"], ["git", "add", "-A"],
                  ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                   "commit", "-qm", "c1"]):
            subprocess.run(c, cwd=repo, check=True)
        proc = subprocess.run(
            [sys.executable, "-m", "sot_graph.cli", "--root", str(repo),
             "calibrate", "--json"],
            cwd=repo, capture_output=True, text=True)
        assert proc.returncode == 0
        report = json.loads(proc.stdout)
        # one clean commit — far below MIN_SAMPLES → honest fallback
        assert report["model_source"] == "heuristic_fallback"
        assert not (repo / ".sot" / "risk_model.json").exists()
