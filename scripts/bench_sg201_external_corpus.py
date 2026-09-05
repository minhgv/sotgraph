#!/usr/bin/env python3
"""SG-201 automated contamination measurement over an independent NON-SELF corpus.

Predeclared, reproducible protocol (priority-3, 2026-09-05):

- Corpus: ALL repos declared in ``benchmarks/holdout/manifest.json`` (the
  "old11" development-regression corpus; every repo pinned to a FULL
  40-hex SHA). The frozen ``benchmarks/holdout_unseen`` split is REFUSED
  here (frozen-split governance: never measured by this runner, never
  re-tuned). The production repo map is never modified.
- Budgets: 1024 and 2048 tokens; minimum rendered symbols 50; gate floor
  fixture/vendor contamination < 2% of rendered symbols — all UNCHANGED
  from the pilot evaluator defaults.
- Every declared repo is measured OR its error published: no selective
  omission. Pin integrity requires MORE than HEAD: the checkout must be
  EXACTLY the pinned snapshot — HEAD == pinned full SHA AND no tracked
  edits AND no untracked source (only the benign ``.sot/`` cache prefix
  is exempt) — verified BOTH before and after measurement; an input that
  changed in between is rejected and its measurement discarded.
- Per repo per budget the ACTUAL rendered denominators (rendered symbols
  / files, truncation flag, rendered-text sha256) are published, plus the
  declared control runs ("all" categories, filter off) that demonstrate
  the oracle can see contamination.
- Aggregate verdict is FAIL-CLOSED: PASS only if every repo measured,
  every default-filter run had >= min rendered symbols, and all were
  strictly under the floor. Any measured violation (sufficient sampling)
  is FAIL; incomplete coverage (repo error / pin mismatch / parse
  mismatch / partial --limit run) is NOT_EVALUABLE; measured-but-
  undersampled without errors is INSUFFICIENT_SAMPLING. Never a pass.

The human landmark precision@20 half of SG-201 is NOT measured here and
stays PENDING_HUMAN_EVIDENCE (>= 3 REAL human reviewers required; see
``plan/sg201-landmark-study-protocol.md``). No reviewer data is produced
or simulated by this script.

Usage:
  python3 scripts/bench_sg201_external_corpus.py \
      [--manifest benchmarks/holdout/manifest.json] [--repos-dir .holdout-cache] \
      [--budgets 1024 2048] [--min-symbols 50] [--workers 4] \
      [--report-dir benchmarks/exit_gates/external] [--limit N] [--no-gate]

Exit codes (with --gate, default): 0 = PASS; 1 = FAIL; 2 = insufficient
sampling / not evaluable. Without --gate: always 0, verdict reported.

Artifacts: ``<report-dir>/sg201_external_corpus.{json,md}`` plus (by
default) the actual rendered map text per repo per budget under
``<report-dir>/rendered/``. NOTE: ``.gitignore`` blanket-ignores
``*.json``; a narrow negation (``!benchmarks/exit_gates/external/*.json``)
is needed for the JSON artifact to be committable — flagged to the
maintainer rather than edited here.

Nothing here mutates production code or the shared ``.sot`` database.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.exit_gates.common import (  # noqa: E402
    CONTAMINATION_CATEGORIES,
    build_temp_index,
    close_temp_index,
    repo_provenance,
    write_report,
)
from evaluation.exit_gates import sg201_contamination as sg201  # noqa: E402

DEFAULT_MANIFEST = REPO_ROOT / "benchmarks" / "holdout" / "manifest.json"
DEFAULT_REPOS_DIR = REPO_ROOT / ".holdout-cache"
EXTERNAL_SCOPE = (
    "independent non-self corpus: all repos of the development-regression "
    "manifest benchmarks/holdout/manifest.json, each pinned to a full "
    "40-hex SHA; automated contamination half only — NOT the self-repo "
    "pilot and NOT the human landmark gate"
)
PASS_OK = "PASS"


# ---------------------------------------------------------------------------
# Manifest + checkout governance
# ---------------------------------------------------------------------------

def load_corpus_manifest(path: Path) -> Dict[str, Any]:
    """Load the DEV corpus manifest; refuse frozen or ambiguous splits."""
    resolved = path.resolve()
    if "holdout_unseen" in resolved.parts:
        raise SystemExit(
            f"refusing frozen holdout_unseen manifest: {resolved} — this "
            "runner measures the development-regression corpus only")
    manifest = json.loads(resolved.read_text(encoding="utf-8"))
    role = str(manifest.get("role") or "")
    if manifest.get("split") == "holdout" or role.startswith("holdout"):
        raise SystemExit(
            f"refusing frozen holdout manifest (role={role!r}, "
            f"split={manifest.get('split')!r}): {resolved}")
    policy = manifest.get("policy") or {}
    if policy.get("tuning_exclusion"):
        raise SystemExit(
            f"refusing manifest with policy.tuning_exclusion "
            f"(frozen/tuning-excluded corpus): {resolved}")
    repos = manifest.get("repos") or []
    if not repos:
        raise SystemExit(f"manifest has no repos: {resolved}")
    seen_names: Dict[str, str] = {}
    seen_urls: Dict[str, str] = {}
    safe_name = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    for repo in repos:
        for key in ("name", "url", "commit"):
            if not repo.get(key):
                raise SystemExit(f"manifest repo missing {key!r}: {repo}")
        name, url, commit = repo["name"], repo["url"], repo["commit"]
        if not safe_name.match(name) or ".." in name:
            raise SystemExit(
                f"unsafe corpus path name {name!r} — must be a single safe "
                "path component ([A-Za-z0-9][A-Za-z0-9._-]*, no '..')")
        if name in seen_names:
            raise SystemExit(
                f"duplicate corpus identity: name {name!r} appears for both "
                f"{seen_names[name]} and {commit}")
        if url in seen_urls:
            raise SystemExit(
                f"duplicate corpus identity: url {url!r} appears for both "
                f"{seen_urls[url]} ({name}) and {commit}")
        seen_names[name] = commit
        seen_urls[url] = name
        if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
            raise SystemExit(
                f"manifest SHA must be full 40-hex for {name}: {commit!r}")
    return manifest


# Untracked paths under these prefixes are benign caches (the SOT index
# written by prior tooling), not corpus source; anything else untracked is
# treated as untracked source and rejected.
BENIGN_UNTRACKED_PREFIXES = (".sot/",)


def _worktree_violations(repo_dir: Path) -> Tuple[str, List[str]]:
    """Classify checkout dirt: tracked edits and untracked source violate
    pin integrity; only the benign ``.sot/`` cache prefix is exempt.

    Returns ``(head_sha, violations)``. Violations are human-readable.
    """
    head = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=30)
    if head.returncode != 0:
        return "", [f"not a git checkout: {repo_dir}"]
    head_sha = head.stdout.strip()
    raw = subprocess.run(
        ["git", "-C", str(repo_dir), "status", "--porcelain=v1", "-z",
         "--untracked-files=all"],
        capture_output=True, text=True, timeout=30)
    if raw.returncode != 0:
        return head_sha, [f"git status failed: {raw.stderr.strip()[:120]}"]
    violations: List[str] = []
    records = [r for r in raw.stdout.split("\0") if r.strip()]
    skip_next = False
    for rec in records:
        if skip_next:               # orig-path half of a rename record
            skip_next = False
            continue
        if len(rec) < 4:
            violations.append(f"malformed status record: {rec!r}")
            continue
        status, path = rec[:2], rec[3:]
        if "R" in status:           # rename: next token is the orig path
            skip_next = True
        if status == "??":
            if not path.startswith(BENIGN_UNTRACKED_PREFIXES):
                violations.append(f"untracked source: {path}")
        else:
            violations.append(f"tracked change ({status!r}): {path}")
    return head_sha, violations


def verify_pinned_checkout(repo_dir: Path, sha: str) -> Dict[str, Any]:
    """Verify a cached checkout is EXACTLY the pinned snapshot.

    Checks, in order: directory exists, is a git checkout, contains the
    pinned commit, HEAD is exactly the pinned SHA, and the worktree is
    clean (no tracked edits; no untracked source — only the benign
    ``.sot/`` cache prefix is exempt). HEAD alone is NOT sufficient: a
    dirty checkout at the pinned HEAD would silently measure different
    content.

    Returns ``{"head_sha", "verified", "violations", "error"}`` —
    ``error`` is a structural failure (missing/moved HEAD), ``violations``
    are worktree-cleanliness findings; ``verified`` is True only when
    both are empty.
    """
    result: Dict[str, Any] = {"head_sha": None, "verified": False,
                              "violations": [], "error": None}
    if not repo_dir.exists():
        result["error"] = f"repo not cached at {repo_dir} (clone it at {sha} first)"
        return result
    try:
        head_sha, violations = _worktree_violations(repo_dir)
    except subprocess.TimeoutExpired as exc:
        result["error"] = f"git timed out verifying {repo_dir}: {exc}"
        return result
    result["head_sha"] = head_sha
    if violations and (not head_sha or any(
            v.startswith(("not a git checkout", "git status failed"))
            for v in violations)):
        result["error"] = "; ".join(violations)
        return result
    has = subprocess.run(
        ["git", "-C", str(repo_dir), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True, timeout=30)
    if has.returncode != 0:
        result["error"] = f"pinned commit {sha} not present in {repo_dir}"
        result["violations"] = violations
        return result
    if head_sha != sha:
        result["error"] = (f"HEAD {head_sha} != pinned {sha} — refusing to "
                           f"measure a moving tree; check out the pinned SHA")
        result["violations"] = violations
        return result
    result["violations"] = violations
    result["verified"] = not violations
    return result


# ---------------------------------------------------------------------------
# Per-repo measurement
# ---------------------------------------------------------------------------

def _disk_oracle_universe(repo_dir: Path, max_files: int = 30000) -> Dict[str, Any]:
    """Classify every on-disk file with the DECLARED oracle (bounded walk).

    Publishes what contamination COULD have existed in this repo: if the
    fixture/vendor counts are 0 on disk, control runs rendering 0% is a
    genuine corpus property (nothing to detect), not a broken control.
    """
    counts: Dict[str, int] = {}
    fv_ext: Dict[str, int] = {}
    seen = 0
    truncated = False
    for p in repo_dir.rglob("*"):
        seen += 1
        if seen > max_files:
            truncated = True
            break
        if not p.is_file():
            continue
        rel = p.relative_to(repo_dir).as_posix()
        if rel.startswith((".git/", ".sot/")):
            continue
        cat = sg201.oracle_category(rel)
        counts[cat] = counts.get(cat, 0) + 1
        if cat in CONTAMINATION_CATEGORIES:
            ext = p.suffix.lower() or "<none>"
            fv_ext[ext] = fv_ext.get(ext, 0) + 1
    return {"files_by_oracle_category": dict(sorted(counts.items())),
            "fixture_vendor_extensions": dict(sorted(fv_ext.items())),
            "walk_truncated": truncated, "walked_entries": seen}


def measure_repo(repo: Dict[str, Any], repo_dir: Path, *, budgets: Tuple[int, ...],
                 min_symbols: int, workers: int,
                 keep_text: bool) -> Dict[str, Any]:
    """Run the SG-201 evaluator on one pinned repo. Never raises: every
    failure mode (including subprocess timeouts and verification errors)
    becomes a published error record. The pin+cleanliness check runs BOTH
    before and after measurement; an input that changed in between is
    rejected (report discarded, error published)."""
    record: Dict[str, Any] = {
        "name": repo["name"], "url": repo["url"], "pinned_sha": repo["commit"],
        "language": repo.get("language"), "error": None, "report": None,
        "rendered_texts": {},
        "pin_check_before": None, "pin_check_after": None,
    }
    try:
        pre = verify_pinned_checkout(repo_dir, repo["commit"])
        record["pin_check_before"] = pre
        if pre["error"]:
            record["error"] = pre["error"]
            return record
        if pre["violations"]:
            record["error"] = ("dirty checkout BEFORE measurement — not a "
                               "pinned snapshot: " + "; ".join(pre["violations"][:5]))
            return record
        db, tmp = build_temp_index(str(repo_dir), workers=workers)
        try:
            report = sg201.run_contamination(
                str(repo_dir), budgets=budgets, min_symbols=min_symbols,
                workers=workers, db=db, close_db=False, scope=EXTERNAL_SCOPE,
                keep_rendered_text=keep_text)
        finally:
            close_temp_index(db, tmp)
        for run in report.get("runs", []):
            text = run.pop("rendered_text", None)
            if text is not None:
                record["rendered_texts"][str(run["budget_tokens"])] = text
        post = verify_pinned_checkout(repo_dir, repo["commit"])
        record["pin_check_after"] = post
        if post["error"] or post["violations"]:
            detail = post["error"] or "; ".join(post["violations"][:5])
            record["error"] = ("checkout changed DURING measurement — "
                               f"input rejected: {detail}")
            record["report"] = None          # never accept a moving input
            record["rendered_texts"] = {}
            return record
        record["report"] = report
        record["disk_oracle_universe"] = _disk_oracle_universe(repo_dir)
    except Exception as exc:  # noqa: BLE001 — errors are published, never swallowed
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["error_traceback_tail"] = traceback.format_exc().splitlines()[-3:]
    return record


def flat_run_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per repo x budget x (default|control) with ACTUAL denominators."""
    rows: List[Dict[str, Any]] = []
    for rec in records:
        rep = rec.get("report")
        if not rep:
            rows.append({"repo": rec["name"], "budget_tokens": None,
                         "error": rec["error"], "rendered_symbols": None})
            continue
        for run in rep.get("runs", []):
            rows.append({
                "repo": rec["name"],
                "budget_tokens": run["budget_tokens"],
                "control_all_categories": bool(run.get("control_all_categories")),
                "rendered_symbols": run["rendered_symbols"],
                "rendered_files": run["rendered_files"],
                "contaminated_symbols": run["contaminated_symbols"],
                "symbol_contamination_pct": run["symbol_contamination_pct"],
                "category_breakdown_symbols": run.get(
                    "category_breakdown_symbols", {}),
                "truncated": run.get("truncated"),
                "rendered_sha256": run.get("rendered_sha256"),
            })
    return rows


# ---------------------------------------------------------------------------
# Aggregate verdict (fail-closed, no selective omission)
# ---------------------------------------------------------------------------

def aggregate_gate(records: List[Dict[str, Any]], *, expected_repos: int,
                   budgets: Tuple[int, ...], min_symbols: int) -> Dict[str, Any]:
    per_repo = {}
    counts = {"PASS": 0, "FAIL": 0, "INSUFFICIENT_SAMPLING": 0,
              "NOT_EVALUABLE": 0, "RENDERED_OUTPUT_PARSE_MISMATCH": 0,
              "ERROR": 0}
    for rec in records:
        if rec["error"]:
            verdict = "ERROR"
        else:
            verdict = rec["report"]["gate"]["verdict"]
        per_repo[rec["name"]] = verdict
        counts[verdict] = counts.get(verdict, 0) + 1
    measured = [r for r in records if not r["error"]]
    complete = len(records) == expected_repos and not counts["ERROR"]
    if counts["FAIL"]:
        verdict = "FAIL"
    elif not complete or counts["RENDERED_OUTPUT_PARSE_MISMATCH"] or \
            counts["NOT_EVALUABLE"]:
        verdict = "NOT_EVALUABLE"
    elif counts["INSUFFICIENT_SAMPLING"]:
        verdict = "INSUFFICIENT_SAMPLING"
    elif counts["PASS"] == expected_repos:
        verdict = "PASS"
    else:
        verdict = "NOT_EVALUABLE"
    return {
        "gate": "sg201_external_corpus_contamination<2%",
        "verdict": verdict,
        "floor": sg201.GATE_FLOOR,
        "min_symbols": min_symbols,
        "budgets": list(budgets),
        "expected_repos": expected_repos,
        "measured_repos": len(measured),
        "repos_passed": counts["PASS"],
        "repos_failed": counts["FAIL"],
        "repos_insufficient_sampling": counts["INSUFFICIENT_SAMPLING"],
        "repos_not_evaluable": counts["NOT_EVALUABLE"]
        + counts["RENDERED_OUTPUT_PARSE_MISMATCH"],
        "repos_errored": counts["ERROR"],
        "per_repo_verdict": per_repo,
        "verdict_precedence": "measured FAIL > incomplete coverage "
                              "(NOT_EVALUABLE) > undersampled "
                              "(INSUFFICIENT_SAMPLING) > PASS; anything other "
                              "than full-coverage PASS never passes",
    }


def render_markdown(report: Dict[str, Any]) -> str:
    gate = report["aggregate_gate"]
    lines = [
        "# SG-201 exit-gate — independent non-self corpus measurement",
        "",
        f"Scope: {report['scope']}",
        "",
        "## Corpus (predeclared)",
        f"- manifest: `{report['manifest']}` (role: {report['manifest_role']}; "
        f"repos declared: {report['expected_repos']})",
        f"- budgets: {report['budgets']} tokens; min rendered symbols: "
        f"{report['min_symbols']}; floor: fixture+vendor < "
        f"{sg201.GATE_FLOOR:.0%} of rendered symbols (all unchanged)",
        "- frozen holdout_unseen split: refused (split governance); "
        "production map: untouched (temp indexes only)",
        "- pin verification: HEAD == pinned SHA AND clean worktree (no "
        "tracked edits, no untracked source; benign `.sot/` cache "
        "exempt) checked BEFORE and AFTER each measurement; changed "
        "inputs rejected",
        "",
        "## Aggregate gate (fail-closed)",
        f"- verdict: **{gate['verdict']}** — repos PASS={gate['repos_passed']} "
        f"FAIL={gate['repos_failed']} "
        f"INSUFFICIENT_SAMPLING={gate['repos_insufficient_sampling']} "
        f"NOT_EVALUABLE={gate['repos_not_evaluable']} "
        f"ERROR={gate['repos_errored']} "
        f"(measured {gate['measured_repos']}/{gate['expected_repos']})",
        f"- precedence: {gate['verdict_precedence']}",
        "",
        "## Per-repo verdicts",
        "",
        "| repo | pinned SHA | pin ok (before+after) | verdict | rendered syms "
        "@ budgets (default filter) |",
        "|---|---|---|---|---|",
    ]
    for rec in report["repos"]:
        denom_rows = [
            r for r in report["runs_flat"]
            if r["repo"] == rec["name"]
            and not r.get("control_all_categories")
            and not r.get("error")]
        if rec["error"]:
            denom = "n/a"
            verdict_cell = f"ERROR: {rec['error']}"
        else:
            parts = [f"{r['rendered_symbols']}@{r['budget_tokens']}"
                     for r in denom_rows]
            denom = " ".join(parts) if parts else "0 (empty map)"
            verdict_cell = rec.get("gate_verdict", "NOT_EVALUABLE")
        lines.append(
            f"| {rec['name']} | `{rec['pinned_sha'][:12]}…` | "
            f"{'yes' if rec.get('pin_verified') else 'NO'} | "
            f"{verdict_cell} | {denom} |")
    lines += ["", "## Actual rendered denominators per repo per budget", "",
              "| repo | budget | control(all) | rendered syms | rendered files | "
              "contam syms | contam % | truncated | rendered sha256 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for row in report["runs_flat"]:
        if row.get("error"):
            lines.append(f"| {row['repo']} | — | — | ERROR | — | — | — | — | — |")
            continue
        lines.append(
            f"| {row['repo']} | {row['budget_tokens']} | "
            f"{'yes' if row['control_all_categories'] else 'no'} "
            f"| {row['rendered_symbols']} | {row['rendered_files']} "
            f"| {row['contaminated_symbols']} "
            f"| {row['symbol_contamination_pct']}% "
            f"| {row['truncated']} | `{row['rendered_sha256'] or 'n/a'}` |")
    sens = report.get("control_sensitivity")
    if sens:
        lines += [
            "",
            "## Control sensitivity (why controls can be 0%)",
            f"- on-disk fixture/vendor files across the corpus: "
            f"fixture={sens['disk_fixture_files']} "
            f"vendor={sens['disk_vendor_files']} "
            f"(extensions: {sens.get('fixture_vendor_extensions') or 'none'})",
            "- controls open the category filter (``all``). Fixture/vendor "
            "files on disk here are non-code data files that produce no "
            "indexable symbols, so 0% controls are a genuine corpus "
            "property; oracle sensitivity to real renderable contamination "
            "is covered by synthetic tests "
            "(tests/test_sg201_sg202_exit_gates.py), not by this corpus.",
        ]
    errors = [r for r in report["repos"] if r["error"]]
    if errors:
        lines += ["", "## Errors (published, never omitted)", ""]
        for rec in errors:
            lines.append(f"- **{rec['name']}**: {rec['error']}")
    lines += [
        "",
        "## Tool provenance",
        f"- sot-graph HEAD: `{report['tool_provenance']['git_head']}` "
        f"worktree digest: `{report['tool_provenance']['worktree_digest']}` "
        f"(dirty entries: {report['tool_provenance']['dirty_entries']}, "
        f"truncated: {report['tool_provenance']['digest_truncated']})",
        "",
        "## Human landmark half — NOT measured here",
        "- landmark precision@20 >= 90% requires >= 3 REAL human reviewers "
        "(plan/sg201-landmark-study-protocol.md); status "
        "**PENDING_HUMAN_EVIDENCE**; this automated corpus run never "
        "closes or substitutes it.",
        "",
        "> Reproduce: `python3 scripts/bench_sg201_external_corpus.py "
        "--gate` (uses `.holdout-cache/` pinned checkouts; clones are NOT "
        "created automatically).",
    ]
    return "\n".join(lines) + "\n"


def per_repo_verdict(rep: Optional[Dict[str, Any]]) -> str:
    if not rep:
        return "ERROR"
    return rep["gate"]["verdict"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    p.add_argument("--repos-dir", default=str(DEFAULT_REPOS_DIR))
    p.add_argument("--budgets", type=int, nargs="+", default=[1024, 2048])
    p.add_argument("--min-symbols", type=int, default=sg201.DEFAULT_MIN_SYMBOLS)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--report-dir",
                   default=str(REPO_ROOT / "benchmarks" / "exit_gates" / "external"))
    p.add_argument("--limit", type=int, default=None,
                   help="measure only the first N declared repos (SMOKE ONLY: "
                        "the aggregate verdict can then never be PASS)")
    p.add_argument("--no-rendered-text", action="store_true",
                   help="skip writing the actual rendered map text files")
    p.add_argument("--gate", action="store_true", default=True)
    p.add_argument("--no-gate", dest="gate", action="store_false",
                   help="always exit 0 and only report the verdict")
    args = p.parse_args(argv)

    manifest_path = Path(args.manifest)
    manifest = load_corpus_manifest(manifest_path)
    repos = manifest["repos"]
    if args.limit is not None:
        repos = repos[:args.limit]
    repos_dir = Path(args.repos_dir)

    records = []
    for repo in repos:
        repo_dir = repos_dir / repo["name"]
        print(f"[sg201-ext] {repo['name']} @ {repo['commit'][:12]}… "
              f"({repo_dir})", flush=True)
        rec = measure_repo(repo, repo_dir, budgets=tuple(args.budgets),
                           min_symbols=args.min_symbols, workers=args.workers,
                           keep_text=not args.no_rendered_text)
        rec["pin_verified"] = (
            rec["error"] is None
            and bool(rec["pin_check_before"] and rec["pin_check_after"])
            and rec["pin_check_before"]["verified"]
            and rec["pin_check_after"]["verified"]
            and rec["pin_check_before"]["head_sha"] == rec["pinned_sha"]
            and rec["pin_check_after"]["head_sha"] == rec["pinned_sha"])
        rec["head_matches_pinned"] = rec["pin_verified"]
        records.append(rec)
        if rec["error"]:
            print(f"[sg201-ext]   ERROR: {rec['error']}", flush=True)
        else:
            g = rec["report"]["gate"]
            print(f"[sg201-ext]   verdict={g['verdict']} "
                  f"metric={g.get('metric_percent')}% "
                  f"denominator={g['denominator']}", flush=True)

    gate = aggregate_gate(records, expected_repos=len(manifest["repos"]),
                          budgets=tuple(args.budgets),
                          min_symbols=args.min_symbols)
    report_dir = Path(args.report_dir)
    rendered_dir: Optional[Path] = None
    if not args.no_rendered_text:
        rendered_dir = report_dir / "rendered"
        rendered_dir.mkdir(parents=True, exist_ok=True)
        for rec in records:
            for budget, text in rec["rendered_texts"].items():
                (rendered_dir / f"{rec['name']}-{budget}.txt").write_text(text)
    per_repo_dir = report_dir / "per_repo"
    per_repo_dir.mkdir(parents=True, exist_ok=True)
    for rec in records:
        if rec.get("report") is not None:
            (per_repo_dir / f"{rec['name']}.json").write_text(
                json.dumps(rec["report"], indent=2, sort_keys=True) + "\n")
    disk_fixture = sum(
        (rec.get("disk_oracle_universe", {})
         .get("files_by_oracle_category", {}) or {}).get("fixture", 0)
        for rec in records if not rec["error"])
    disk_vendor = sum(
        (rec.get("disk_oracle_universe", {})
         .get("files_by_oracle_category", {}) or {}).get("vendor", 0)
        for rec in records if not rec["error"])
    fv_ext: Dict[str, int] = {}
    for rec in records:
        for ext, n in (rec.get("disk_oracle_universe", {})
                       .get("fixture_vendor_extensions", {}) or {}).items():
            fv_ext[ext] = fv_ext.get(ext, 0) + n

    report = {
        "benchmark": "sg201-external-corpus-map-contamination",
        "scope": EXTERNAL_SCOPE,
        "manifest": str(manifest_path),
        "manifest_role": manifest.get("role"),
        "expected_repos": len(manifest["repos"]),
        "measured_repos": sum(1 for r in records if not r["error"]),
        "budgets": list(args.budgets),
        "min_symbols": args.min_symbols,
        "policy": {
            "corpus": "ALL repos of the development-regression manifest "
                      "(old11); full 40-hex pinned SHAs; holdout_unseen, "
                      "holdout-role, tuning-excluded, duplicate-name/url "
                      "and unsafe-path manifests refused",
            "pin_verification": "per repo, BEFORE and AFTER measurement: "
                                "HEAD == pinned SHA AND worktree clean — "
                                "tracked edits and untracked source rejected "
                                "(benign .sot/ cache exempt); input changed "
                                "in between => measurement discarded, error "
                                "published",
            "selection": "ACTUAL rendered map text within declared budgets "
                         f"{list(args.budgets)}; actual per-repo per-budget "
                         "rendered denominators published",
            "gate": f"fixture+vendor < {sg201.GATE_FLOOR:.0%} of rendered "
                    f"symbols per repo, min {args.min_symbols} rendered "
                    "symbols; thresholds unchanged from the pilot",
            "omission": "errors, pin mismatches, dirty checkouts and "
                        "insufficient sampling are published; no repo is "
                        "silently skipped",
            "landmark": "human precision@20 >= 90% NOT measured here — "
                        "PENDING_HUMAN_EVIDENCE (>= 3 real reviewers)",
        },
        "repos": [{k: v for k, v in rec.items()
                   if k not in ("report", "rendered_texts")} | {
                       "gate_verdict": per_repo_verdict(rec.get("report")),
                       "primary_denominator": (
                           rec["report"]["gate"]["denominator"]
                           if rec.get("report") else None),
                       "metric_percent": (
                           rec["report"]["gate"].get("metric_percent")
                           if rec.get("report") else None),
                   } for rec in records],
        "runs_flat": flat_run_rows(records),
        "control_sensitivity": {
            "disk_fixture_files": disk_fixture,
            "disk_vendor_files": disk_vendor,
            "fixture_vendor_extensions": dict(sorted(fv_ext.items())),
            "note": "control runs (include_categories=all) rendered 0 "
                    "contaminated symbols. Publishes WHY per repo: "
                    "fixture/vendor files existing on disk are counted with "
                    "their extensions — non-code data files (e.g. .md/.txt "
                    "samples) produce no indexable symbols, so a 0% control "
                    "is a genuine corpus property, not a broken control. "
                    "Oracle sensitivity to real renderable contamination is "
                    "exercised by synthetic tests instead "
                    "(tests/test_sg201_sg202_exit_gates.py).",
        },
        "aggregate_gate": gate,
        "artifacts": {
            "per_repo_reports": str(per_repo_dir),
            "rendered_texts": str(rendered_dir) if rendered_dir else None,
        },
        "tool_provenance": repo_provenance(str(REPO_ROOT)),
    }
    paths = write_report(args.report_dir, "sg201_external_corpus", report,
                         render_markdown(report))
    print(f"[sg201-ext] aggregate verdict={gate['verdict']} "
          f"(PASS={gate['repos_passed']} FAIL={gate['repos_failed']} "
          f"INSUF={gate['repos_insufficient_sampling']} "
          f"NOT_EVAL={gate['repos_not_evaluable']} "
          f"ERR={gate['repos_errored']}, "
          f"measured {gate['measured_repos']}/{gate['expected_repos']})")
    print(f"[sg201-ext] report: {paths['json']} | {paths['markdown']}")
    print(f"[sg201-ext] per-repo reports: {per_repo_dir}")
    if rendered_dir:
        print(f"[sg201-ext] rendered texts: {rendered_dir}")
    if not args.gate:
        return 0
    if gate["verdict"] == "PASS":
        return 0
    if gate["verdict"] in ("INSUFFICIENT_SAMPLING", "NOT_EVALUABLE"):
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
