#!/usr/bin/env python3
"""bench_three_gates.py — 3-gate workflow baseline harness (W0).

Measures what the ``sotgraph log`` risk classification is *worth* against
post-hoc outcomes: for each repo in the manifest, collect commit history
(same engine as ``sotgraph log``), label every commit's outcome with
``sot_graph.outcome`` (clean / fixup / reverted / retouched), and emit the
risk_level x outcome cross-tab with adverse rates — the baseline that
W3 (commit-verdict) and W4 (risk calibration) are measured against.

``--hand-labels labels.json`` (map of sha-prefix -> expected outcome)
adds a labeler-vs-human agreement section — the W0 pass bar is
precision/recall >= 0.9 on the ``reverted`` and ``fixup`` classes.

``--gate`` exits 1 when harness-health checks fail (sample size,
labeler coverage). The ``adverse_monotonic`` check is ADVISORY: it
records whether HIGH commits really did turn out worse — a *finding*
about the risk heuristic, not a harness failure.

Usage:
  python3 scripts/bench_three_gates.py \
      [--manifest benchmarks/three_gates/manifest.json] \
      [--report benchmarks/three_gates/report.json] \
      [--hand-labels benchmarks/three_gates/hand_labels.json] \
      [--only sotgraph] [--gate]
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from sot_graph.outcome import (  # noqa: E402
    ADVERSE_OUTCOMES,
    OUTCOMES,
    aggregate_outcomes,
    collect_commit_records,
    label_outcomes,
    make_hunk_verifier,
    outcomes_from_hand_labels,
)

MANIFEST_PATH = _REPO / "benchmarks" / "three_gates" / "manifest.json"
REPORT_PATH = _REPO / "benchmarks" / "three_gates" / "report.json"

_RISK_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
_OUTCOME_ICON = {"reverted": "⛔", "fixup": "🔧", "retouched": "🔁", "clean": "✅"}


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _open_db(repo_path: Path) -> Optional[Any]:
    """Best-effort: reuse the repo's own index for touched_symbols when
    present. Labeling itself only needs files — db is enrichment."""
    db_file = repo_path / ".sot" / "sot.db"
    if not db_file.is_file():
        return None
    try:
        from sot_graph.db import Database

        return Database(str(db_file), read_only=True)
    except Exception as exc:  # noqa: BLE001 - enrichment must never fail the run
        print(f"⚠️  db open skipped for {repo_path}: {exc}", file=sys.stderr)
        return None


def run_repo(repo_cfg: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Collect → label → aggregate for one manifest repo."""
    name = str(repo_cfg.get("name") or repo_cfg.get("path"))
    repo_path = (_REPO / str(repo_cfg.get("path", "."))).resolve()
    if not (repo_path / ".git").exists():
        return {"name": name, "error": f"not a git repo: {repo_path}"}

    window_days = int(repo_cfg.get("window_days", defaults.get("window_days", 14)))
    retouch_min = int(repo_cfg.get("retouch_min", defaults.get("retouch_min", 2)))
    limit = int(repo_cfg.get("limit", defaults.get("limit", 400)))
    since = repo_cfg.get("since", defaults.get("since"))

    db = _open_db(repo_path)
    try:
        records = collect_commit_records(
            str(repo_path), limit=limit, since=since, db=db
        )
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
    outcomes = label_outcomes(
        records, window_days=window_days, retouch_min=retouch_min,
        verify_fixup=make_hunk_verifier(str(repo_path)),
    )
    return {
        "name": name,
        "path": str(repo_path),
        "params": {"window_days": window_days, "retouch_min": retouch_min,
                   "limit": limit, "since": since},
        "n_commits": len(records),
        "outcomes": [o.to_dict() for o in outcomes],
        "aggregate": aggregate_outcomes(outcomes),
    }


def _hand_label_section(
    repo_results: List[Dict[str, Any]], labels_path: Path
) -> Optional[Dict[str, Any]]:
    """Join hand labels onto labeled outcomes → per-class P/R."""
    hand = _load_json(labels_path)
    per_repo: Dict[str, Any] = {}
    for res in repo_results:
        if res.get("error"):
            continue
        from sot_graph.outcome import CommitOutcome

        outcomes = [
            CommitOutcome(
                sha=o["sha"], short_sha=o["short_sha"], subject=o["subject"],
                date=o["date"], risk_level=o["risk_level"], outcome=o["outcome"],
                follow_up_shas=o.get("follow_up_shas", []),
                reverted_by=o.get("reverted_by", []),
                retouch_count=o.get("retouch_count", 0),
                window_days=o.get("window_days", 14),
                window_complete=o.get("window_complete", True),
                files=o.get("files", []), evidence=o.get("evidence", []),
            )
            for o in res["outcomes"]
        ]
        scoped = {k: v for k, v in hand.get(res["name"], hand).items()
                  if not k.startswith("_")}
        if not scoped:
            continue
        per_repo[res["name"]] = outcomes_from_hand_labels(outcomes, scoped)
    if not per_repo:
        return None
    # Adverse-class pass bar (W0): P/R >= 0.9 where the class was sampled.
    bars: Dict[str, Any] = {}
    for cls in ADVERSE_OUTCOMES:
        tp = sum(r["per_class"][cls]["tp"] for r in per_repo.values())
        fp = sum(r["per_class"][cls]["fp"] for r in per_repo.values())
        fn = sum(r["per_class"][cls]["fn"] for r in per_repo.values())
        n = tp + fn
        bars[cls] = {
            "labeled": n,
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "recall": round(tp / n, 4) if n else None,
            "pass": (n == 0) or (
                (tp / (tp + fp) if (tp + fp) else 0) >= 0.9
                and (tp / n if n else 0) >= 0.9
            ),
        }
    return {"per_repo": per_repo, "adverse_class_bars": bars}


def aggregate_report(repo_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Overall metrics + harness-health checks."""
    ok = [r for r in repo_results if not r.get("error")]
    all_outcomes = [o for r in ok for o in r["outcomes"]]
    checks: Dict[str, Dict[str, Any]] = {}

    checks["sample_size"] = {
        "passed": all(
            r["n_commits"] >= int(r.get("min_commits", 0) or 0)
            for r in repo_results
        ),
        "detail": {r["name"]: r.get("n_commits", 0) for r in repo_results},
    }
    checks["outcome_coverage"] = {
        "passed": all(
            o.get("outcome") in OUTCOMES for o in all_outcomes
        ),
        "detail": f"{len(all_outcomes)} outcomes labeled",
    }
    mono = [r["aggregate"].get("monotonic_adverse") for r in ok]
    mono = [m for m in mono if m is not None]
    checks["adverse_monotonic"] = {
        "passed": all(mono) if mono else None,
        "advisory": True,
        "detail": "P(adverse) rises with risk level — finding about the "
                  "heuristic, not a harness failure",
        "values": {r["name"]: r["aggregate"].get("monotonic_adverse")
                   for r in ok},
    }
    return {
        "repos_ok": len(ok),
        "repos_total": len(repo_results),
        "commits_labeled": len(all_outcomes),
        "outcome_breakdown": {
            k: sum(1 for o in all_outcomes if o["outcome"] == k)
            for k in OUTCOMES
        },
        "checks": checks,
    }


def markdown_summary(report: Dict[str, Any]) -> str:
    lines = [
        "# Three-Gate Baseline — risk classification vs real outcomes",
        "",
        f"Repos: {report['aggregate']['repos_ok']}/{report['aggregate']['repos_total']} | "
        f"Commits labeled: {report['aggregate']['commits_labeled']} | "
        f"Adverse = {', '.join(ADVERSE_OUTCOMES)}",
        "",
    ]
    for res in report["repos"]:
        if res.get("error"):
            lines.append(f"## {res['name']}\n\n❌ {res['error']}\n")
            continue
        agg = res["aggregate"]
        lines.append(f"## {res['name']} — {res['n_commits']} commits "
                     f"({agg['window_complete_n']} fully observed, "
                     f"window {res['params']['window_days']}d)")
        lines.append("")
        lines.append("| Risk | n | ✅ clean | 🔧 fixup | ⛔ reverted | 🔁 retouched | P(adverse) |")
        lines.append("|---|---|---|---|---|---|---|")
        wc = agg["per_risk"]["window_complete"]
        for lvl in ("HIGH", "MEDIUM", "LOW"):
            row = wc[lvl]
            oc = row["outcomes"]
            rate = f"{row['adverse_rate']:.0%}" if row["adverse_rate"] is not None else "n/a"
            lines.append(
                f"| {_RISK_ICON[lvl]} {lvl} | {row['n']} | {oc['clean']} | "
                f"{oc['fixup']} | {oc['reverted']} | {oc['retouched']} | {rate} |"
            )
        lines.append("")
        mono = agg.get("monotonic_adverse")
        mono_s = "yes" if mono else ("no" if mono is False else "n/a")
        lines.append(f"Monotonic adverse (LOW ≤ MED ≤ HIGH): **{mono_s}**")
        lines.append("")
        flagged = [o for o in res["outcomes"] if o["outcome"] in ADVERSE_OUTCOMES]
        if flagged:
            lines.append("<details><summary>Adverse-outcome commits</summary>")
            lines.append("")
            for o in flagged[:25]:
                icon = _OUTCOME_ICON.get(o["outcome"], "?")
                lines.append(
                    f"- {icon} `{o['short_sha']}` [{o['risk_level']}] "
                    f"{o['subject']} — {'; '.join(o['evidence'][:1])}"
                )
            lines.append("")
            lines.append("</details>")
            lines.append("")
    hl = report.get("hand_label_agreement")
    if hl:
        lines.append("## Labeler vs hand labels")
        lines.append("")
        lines.append("| Class | labeled | precision | recall | pass≥0.9 |")
        lines.append("|---|---|---|---|---|")
        for cls, bar in hl["adverse_class_bars"].items():
            p = f"{bar['precision']:.0%}" if bar["precision"] is not None else "n/a"
            r = f"{bar['recall']:.0%}" if bar["recall"] is not None else "n/a"
            lines.append(
                f"| {cls} | {bar['labeled']} | {p} | {r} | "
                f"{'✅' if bar['pass'] else '❌'} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="3-gate baseline: risk levels vs commit outcomes")
    ap.add_argument("--manifest", default=str(MANIFEST_PATH))
    ap.add_argument("--report", default=str(REPORT_PATH))
    ap.add_argument("--hand-labels", default=None,
                    help="JSON map sha-prefix -> expected outcome "
                         "(optionally nested under repo name)")
    ap.add_argument("--only", default=None, help="run a single repo by name")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 on harness-health check failure")
    args = ap.parse_args(argv)

    manifest = _load_json(Path(args.manifest))
    defaults = manifest.get("params", {})
    repo_results: List[Dict[str, Any]] = []
    for cfg in manifest.get("repos", []):
        if args.only and cfg.get("name") != args.only:
            continue
        cfg = dict(cfg)
        cfg.setdefault("min_commits", manifest.get("min_commits", 0))
        repo_results.append(run_repo(cfg, defaults))
        last = repo_results[-1]
        if last.get("error"):
            print(f"❌ {last['name']}: {last['error']}", file=sys.stderr)
        else:
            agg = last["aggregate"]
            print(f"📦 {last['name']}: {last['n_commits']} commits, "
                  f"outcomes={agg['outcome_breakdown']}")

    report: Dict[str, Any] = {
        "benchmark": manifest.get("benchmark", "three-gates"),
        "schema_version": manifest.get("schema_version", 1),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "manifest": str(Path(args.manifest)),
        "repos": repo_results,
        "aggregate": aggregate_report(repo_results),
    }
    if args.hand_labels:
        section = _hand_label_section(repo_results, Path(args.hand_labels))
        if section:
            report["hand_label_agreement"] = section

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n",
                   encoding="utf-8")
    (out.parent / "report.md").write_text(
        markdown_summary(report), encoding="utf-8")

    checks = report["aggregate"]["checks"]
    print(f"\n3-gate baseline: {report['aggregate']['commits_labeled']} commits, "
          f"outcomes={report['aggregate']['outcome_breakdown']}")
    for name, chk in checks.items():
        tag = "advisory" if chk.get("advisory") else "gate"
        print(f"  [{tag}] {name}: {chk.get('passed')}")
    print(f"  report: {out}")
    if args.gate:
        failed = [k for k, c in checks.items()
                  if c.get("passed") is False and not c.get("advisory")]
        if failed:
            print(f"GATE FAIL: {failed}", file=sys.stderr)
            return 1
        print("  gates: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
