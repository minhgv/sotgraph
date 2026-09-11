"""W7 — risk calibration: learned weights from labeled commit outcomes.

The heuristic risk buckets in ``CommitHistoryEngine._calculate_commit_risk``
are hand-set. Once the W0 outcome labeler has seen enough history, the
weights should come from THIS repo's data instead — with an honest
fallback when there is not enough of it.

Model: pure-Python logistic regression (no new deps — Art 10), fixed
iteration count, deterministic. Labels: adverse = {fixup, reverted};
clean/retouched are non-adverse. Commits whose observation window has
not closed are EXCLUDED from training — the fail-closed rule applies to
learning the same way it applies to verdicts.

Honesty contract:
- ``model_source`` reports ``learned`` only when n >= MIN_SAMPLES AND the
  model beat the base-rate logloss on k-fold CV; otherwise
  ``heuristic_fallback`` — the heuristic stays in charge and the payload
  says why.
- Learned buckets are tertile cutoffs of the train-set probabilities, so
  LOW < MEDIUM < HIGH is monotone by construction; ``monotone_ok`` still
  verifies the empirical adverse rate is non-decreasing.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Fewer labeled commits than this → the model cannot honestly claim to
#: have learned this repo; heuristic stays with a disclosed reason.
MIN_SAMPLES = 30

MODEL_VERSION = "risk-model/1"
MODEL_FILENAME = "risk_model.json"

_FEATURE_NAMES = (
    "file_count", "log_churn", "critical_hits", "config_hits",
    "touched_symbols", "fix_subject",
)

_ADVERSE_OUTCOMES = frozenset({"fixup", "reverted"})


def commit_features(rec: Any) -> Dict[str, float]:
    """Shared feature vector for train and predict — ONE site so the two
    can never drift apart (CommitRecord duck-typed: files, insertions,
    deletions, touched_symbols, tags)."""
    from sot_graph.diff_impact import CommitHistoryEngine

    files = list(getattr(rec, "files", None) or [])
    churn = int(getattr(rec, "insertions", 0)) + int(
        getattr(rec, "deletions", 0))
    critical = sum(
        1 for f in files
        if any(p.search(f.lower()) for p in CommitHistoryEngine.CRITICAL_PATTERNS)
    )
    config = sum(
        1 for f in files
        if os.path.basename(f).lower() in CommitHistoryEngine.CONFIG_FILES
    )
    tags = getattr(rec, "tags", None) or set()
    return {
        "file_count": float(len(files)),
        "log_churn": math.log1p(float(churn)),
        "critical_hits": float(critical),
        "config_hits": float(config),
        "touched_symbols": float(
            len(getattr(rec, "touched_symbols", None) or [])),
        "fix_subject": 1.0 if "fix" in tags else 0.0,
    }


def _vector(feats: Dict[str, float]) -> List[float]:
    return [float(feats.get(k, 0.0)) for k in _FEATURE_NAMES]


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _fit_logistic(
    X: List[List[float]], y: List[int],
    *, epochs: int = 400, lr: float = 0.1, l2: float = 1e-3,
) -> Tuple[List[float], float, List[float], List[float]]:
    """Deterministic batch gradient descent. Returns (w, b, means, stds)
    — the caller MUST predict with the SAME normalization params."""
    n_feat = len(_FEATURE_NAMES)
    means = [sum(row[i] for row in X) / len(X) for i in range(n_feat)]
    stds = [
        max(1e-9, math.sqrt(
            sum((row[i] - means[i]) ** 2 for row in X) / len(X)))
        for i in range(n_feat)
    ]
    Xn = [[(row[i] - means[i]) / stds[i] for i in range(n_feat)]
          for row in X]
    w = [0.0] * n_feat
    b = 0.0
    n = len(Xn)
    for _ in range(epochs):
        gw = [0.0] * n_feat
        gb = 0.0
        for row, yi in zip(Xn, y):
            p = _sigmoid(sum(wi * xi for wi, xi in zip(w, row)) + b)
            err = p - yi
            for i in range(n_feat):
                gw[i] += err * row[i]
            gb += err
        for i in range(n_feat):
            w[i] -= lr * (gw[i] / n + l2 * w[i])
        b -= lr * gb / n
    return w, b, means, stds


def _logloss(probs: Sequence[float], y: Sequence[int]) -> float:
    eps = 1e-15
    return -sum(
        yi * math.log(max(eps, p)) + (1 - yi) * math.log(max(eps, 1 - p))
        for p, yi in zip(probs, y)
    ) / max(1, len(y))


@dataclass
class RiskModel:
    """Versioned learned risk model persisted at .sot/risk_model.json."""
    weights: List[float]
    intercept: float
    means: List[float]
    stds: List[float]
    cutoff_low_medium: float
    cutoff_medium_high: float
    n_samples: int
    adverse_rate: float
    cv_logloss: float
    baseline_logloss: float
    monotone_ok: bool
    version: str = MODEL_VERSION
    trained_at: str = ""
    feature_names: Tuple[str, ...] = _FEATURE_NAMES

    def p_adverse(self, feats: Dict[str, float]) -> float:
        row = _vector(feats)
        norm = [(row[i] - self.means[i]) / self.stds[i]
                for i in range(len(row))]
        return _sigmoid(
            sum(wi * xi for wi, xi in zip(self.weights, norm))
            + self.intercept)

    def level(self, feats: Dict[str, float]) -> str:
        p = self.p_adverse(feats)
        if p >= self.cutoff_medium_high:
            return "HIGH"
        if p >= self.cutoff_low_medium:
            return "MEDIUM"
        return "LOW"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "trained_at": self.trained_at,
            "n_samples": self.n_samples,
            "adverse_rate": round(self.adverse_rate, 4),
            "weights": [round(w, 6) for w in self.weights],
            "intercept": round(self.intercept, 6),
            "means": [round(m, 6) for m in self.means],
            "stds": [round(s, 6) for s in self.stds],
            "cutoff_low_medium": round(self.cutoff_low_medium, 6),
            "cutoff_medium_high": round(self.cutoff_medium_high, 6),
            "cv_logloss": round(self.cv_logloss, 6),
            "baseline_logloss": round(self.baseline_logloss, 6),
            "monotone_ok": self.monotone_ok,
            "feature_names": list(self.feature_names),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RiskModel":
        return cls(
            weights=[float(x) for x in d["weights"]],
            intercept=float(d["intercept"]),
            means=[float(x) for x in d["means"]],
            stds=[float(x) for x in d["stds"]],
            cutoff_low_medium=float(d["cutoff_low_medium"]),
            cutoff_medium_high=float(d["cutoff_medium_high"]),
            n_samples=int(d["n_samples"]),
            adverse_rate=float(d["adverse_rate"]),
            cv_logloss=float(d["cv_logloss"]),
            baseline_logloss=float(d["baseline_logloss"]),
            monotone_ok=bool(d["monotone_ok"]),
            version=str(d.get("version") or MODEL_VERSION),
            trained_at=str(d.get("trained_at") or ""),
        )


def model_path(repo_root: str) -> str:
    return os.path.join(repo_root, ".sot", MODEL_FILENAME)


def load_model(repo_root: str) -> Optional[RiskModel]:
    path = model_path(repo_root)
    try:
        with open(path, encoding="utf-8") as fh:
            return RiskModel.from_dict(json.load(fh))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_model(repo_root: str, model: RiskModel) -> str:
    path = model_path(repo_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(model.to_dict(), fh, indent=1, sort_keys=True)
    return path


def fit_model(
    records: Sequence[Any],
    outcomes: Sequence[Any],
    *,
    min_samples: int = MIN_SAMPLES,
    folds: int = 5,
) -> Tuple[Optional[RiskModel], Dict[str, Any]]:
    """Train on labeled outcomes joined to records by sha.

    Returns (model|None, report). ``model`` is None when the honesty
    gate fails — the report carries the reason so callers disclose
    ``heuristic_fallback`` rather than pretending to have learned.
    """
    import time

    by_sha = {o.sha: o for o in outcomes}
    X: List[List[float]] = []
    y: List[int] = []
    skipped_window = 0
    for rec in records:
        oc = by_sha.get(rec.sha)
        if oc is None:
            continue
        if not getattr(oc, "window_complete", True):
            skipped_window += 1
            continue  # incomplete window — fail closed, do not learn
        X.append(_vector(commit_features(rec)))
        y.append(1 if oc.outcome in _ADVERSE_OUTCOMES else 0)

    report: Dict[str, Any] = {
        "n_samples": len(y),
        "skipped_incomplete_window": skipped_window,
        "adverse": sum(y),
        "min_samples": min_samples,
        "model_source": "learned",
    }
    if len(y) < min_samples or len(set(y)) < 2:
        report["model_source"] = "heuristic_fallback"
        report["reason"] = (
            f"{len(y)} labeled commits (need ≥{min_samples} with both "
            "outcomes present); heuristic stays in charge")
        return None, report

    n_feat = len(_FEATURE_NAMES)
    w, b, means, stds = _fit_logistic(X, y)

    def _norm(row: List[float]) -> List[float]:
        return [(row[j] - means[j]) / stds[j] for j in range(n_feat)]

    def _p(row: List[float]) -> float:
        return _sigmoid(sum(w[j] * row[j] for j in range(n_feat)) + b)

    # k-fold CV logloss vs predicting the base rate — each fold uses its
    # OWN normalization params (leak-free).
    k = max(2, min(folds, len(y)))
    cv_err = 0.0
    for f in range(k):
        test_idx = [i for i in range(len(y)) if i % k == f]
        tr_idx = [i for i in range(len(y)) if i % k != f]
        if not test_idx or not tr_idx:
            continue
        wf, bf, mf, sf = _fit_logistic([X[i] for i in tr_idx],
                                       [y[i] for i in tr_idx])
        probs = [
            _sigmoid(sum(
                wf[j] * ((X[i][j] - mf[j]) / sf[j])
                for j in range(n_feat)) + bf)
            for i in test_idx
        ]
        cv_err += _logloss(probs, [y[i] for i in test_idx]) * len(test_idx)
    cv_logloss = cv_err / len(y)
    prior = sum(y) / len(y)
    baseline = _logloss([prior] * len(y), y)

    # Tertile cutoffs of train probabilities → monotone buckets by
    # construction; verify empirically anyway and disclose.
    train_probs = sorted(_p(_norm(r)) for r in X)
    c_lm = train_probs[len(y) // 3]
    c_mh = train_probs[(2 * len(y)) // 3]
    if c_lm >= c_mh:  # degenerate spread — collapse to binary split
        c_lm = c_mh = train_probs[len(y) // 2]

    def _level_of(p: float) -> int:
        return 2 if p >= c_mh else (1 if p >= c_lm else 0)

    bands = [[] for _ in range(3)]
    for r, yi in zip(X, y):
        bands[_level_of(_p(_norm(r)))].append(yi)
    rates = [sum(b) / len(b) if b else 0.0 for b in bands]
    monotone_ok = rates[0] <= rates[1] <= rates[2]

    if cv_logloss >= baseline:
        report["model_source"] = "heuristic_fallback"
        report["reason"] = (
            f"learned model did not beat base-rate logloss "
            f"(cv {cv_logloss:.4f} vs baseline {baseline:.4f}); "
            "heuristic stays in charge")
        report["cv_logloss"] = round(cv_logloss, 6)
        report["baseline_logloss"] = round(baseline, 6)
        return None, report

    model = RiskModel(
        weights=w, intercept=b, means=means, stds=stds,
        cutoff_low_medium=c_lm, cutoff_medium_high=c_mh,
        n_samples=len(y), adverse_rate=prior,
        cv_logloss=cv_logloss, baseline_logloss=baseline,
        monotone_ok=monotone_ok,
        trained_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    report.update({
        "cv_logloss": round(cv_logloss, 6),
        "baseline_logloss": round(baseline, 6),
        "monotone_ok": monotone_ok,
        "bucket_adverse_rates": {
            "LOW": round(rates[0], 4),
            "MEDIUM": round(rates[1], 4),
            "HIGH": round(rates[2], 4),
        },
    })
    return model, report
