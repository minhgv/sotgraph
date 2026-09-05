"""SG-201 exit-gate evaluator: repo-map fixture/vendor contamination.

Exit gate (issue #8): "Fixture/vendor contamination in the top map < 2%
(and landmark precision@20 >= 90% via a human reviewer — see
``landmark_study``; NOT measurable by this script)."

Measurement contract:
- Scores the ACTUAL rendered map text within the declared token budget
  (formatting + truncation semantics included), parsed independently;
  the parser cross-checks its counts against the API result
  (``symbols`` / ``files``) and fails closed on any mismatch.
- Categories come from the DECLARED independent oracle in
  ``common.oracle_category`` (a conservative superset of the production
  classifier); every production-vs-oracle divergence on rendered files
  is published.
- Landmark precision@20 requires a human reviewer: this script emits the
  worksheet and, at most, an automated PROXY (clearly labelled, never a
  gate).
- Self-repo results are PILOT scope (the default ``scope`` text); they do
  not close the global gate. Non-self corpus runs MUST pass an explicit
  ``scope`` describing the external corpus so the report always reflects
  what was actually measured.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sot_graph.repo_map import build_repo_map, classify_path

from .common import (
    RenderedMap,
    build_temp_index,
    close_temp_index,
    format_pct,
    gate_verdict,
    oracle_category,
    oracle_contaminated,
    parse_rendered_map,
    repo_provenance,
)

GATE_FLOOR = 0.02          # contamination must be strictly below 2%
DEFAULT_MIN_SYMBOLS = 50
DEFAULT_BUDGETS = (1024, 2048)
LANDMARK_SLICE_FILES = 20
# Default scope text: accurate ONLY for the self-repo (sot-graph) runs.
# External corpus runners override it via ``run_contamination(scope=...)``.
DEFAULT_SCOPE = ("PILOT — self-repo corpus (sot-graph); does NOT close the "
                 "global exit gate")


def _score_rendered(rendered: RenderedMap, root: str) -> Dict[str, Any]:
    file_cats = {f: oracle_category(f) for f in rendered.files}
    sym_total = rendered.symbol_count
    sym_contam = sum(
        len(syms) for f, syms in rendered.file_symbols.items()
        if oracle_contaminated(f))
    file_contam = sum(1 for c in file_cats.values() if c in ("fixture", "vendor"))

    # Prefix slice: first N file groups in rendered (appearance) order.
    head = rendered.files[:LANDMARK_SLICE_FILES]
    head_syms = sum(len(rendered.file_symbols[f]) for f in head)
    head_contam = sum(
        len(rendered.file_symbols[f]) for f in head if oracle_contaminated(f))

    divergences = [
        {"path": f, "oracle": cat, "production": classify_path(f)}
        for f, cat in sorted(file_cats.items())
        if classify_path(f) != cat
    ]
    src_syms = sum(
        len(syms) for f, syms in rendered.file_symbols.items()
        if oracle_category(f) == "production" and f.startswith("src/"))

    return {
        "rendered_files": len(rendered.files),
        "rendered_symbols": sym_total,
        "contaminated_files": file_contam,
        "contaminated_symbols": sym_contam,
        "symbol_contamination_pct": round(sym_contam / sym_total * 100, 3) if sym_total else None,
        "file_contamination_pct": round(file_contam / len(rendered.files) * 100, 3)
        if rendered.files else None,
        f"head{LANDMARK_SLICE_FILES}_symbols": head_syms,
        f"head{LANDMARK_SLICE_FILES}_contaminated": head_contam,
        "src_production_symbols": src_syms,
        "src_production_share_pct": round(src_syms / sym_total * 100, 2) if sym_total else None,
        "category_breakdown_symbols": _breakdown(rendered),
        "production_vs_oracle_divergences": divergences,
    }


def _breakdown(rendered: RenderedMap) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for f, syms in rendered.file_symbols.items():
        cat = oracle_category(f)
        out[cat] = out.get(cat, 0) + len(syms)
    return dict(sorted(out.items()))


def run_contamination(
    repo_root: str,
    *,
    budgets: Tuple[int, ...] = DEFAULT_BUDGETS,
    min_symbols: int = DEFAULT_MIN_SYMBOLS,
    workers: int = 4,
    include_all_control: bool = True,
    db: Any = None,
    close_db: bool = True,
    scope: Optional[str] = None,
    keep_rendered_text: bool = False,
) -> Dict[str, Any]:
    root = str(Path(repo_root).resolve())
    owned_db = db is None
    tmp_dir: Optional[str] = None
    if db is None:
        db, tmp_dir = build_temp_index(root, workers=workers)

    runs: List[Dict[str, Any]] = []
    parse_mismatches: List[str] = []
    try:
        for budget in budgets:
            result = build_repo_map(db.conn, root=root, max_tokens=budget)
            text = result["rendered"]
            rendered = parse_rendered_map(text)
            # Fail-closed cross-check: the independent parser must agree
            # with the API's own counts about what was actually rendered.
            api_files = {f["path"] for f in result.get("files", [])}
            parsed_files = set(rendered.files)
            if rendered.symbol_count != int(result.get("symbols") or 0):
                parse_mismatches.append(
                    f"budget={budget}: parsed {rendered.symbol_count} symbols "
                    f"vs API {result.get('symbols')}")
            if parsed_files != api_files:
                parse_mismatches.append(
                    f"budget={budget}: parsed file set differs from API "
                    f"({sorted(parsed_files ^ api_files)[:5]})")
            entry = {
                "budget_tokens": budget,
                "filters_echo": result.get("filters"),
                "truncated": result.get("truncated"),
                "rendered_sha256": hashlib.sha256(
                    text.encode("utf-8")).hexdigest()[:16],
                **_score_rendered(rendered, root),
            }
            if keep_rendered_text:
                entry["rendered_text"] = text
            runs.append(entry)

            if include_all_control:
                # Control run: opt-in "all" categories — demonstrates the
                # measurement CAN see contamination when the filter is off
                # (declared control, not the gate configuration).
                ctrl = build_repo_map(db.conn, root=root, max_tokens=budget,
                                      include_categories="all")
                ctrl_rendered = parse_rendered_map(ctrl["rendered"])
                runs.append({
                    "budget_tokens": budget,
                    "control_all_categories": True,
                    "filters_echo": ctrl.get("filters"),
                    "truncated": ctrl.get("truncated"),
                    **_score_rendered(ctrl_rendered, root),
                })
    finally:
        if owned_db and close_db:
            close_temp_index(db, tmp_dir)

    default_runs = [r for r in runs if not r.get("control_all_categories")]
    # Gate: EVERY declared-budget default run with sufficient sampling must
    # be under the floor; primary numbers reported from the largest budget.
    primary = max(default_runs, key=lambda r: r["budget_tokens"])
    sufficient = [r for r in default_runs if r["rendered_symbols"] >= min_symbols]
    # UNITS: the gate compares a FRACTION against GATE_FLOOR (0.02 = 2%);
    # the percent value is kept separate for publication only.
    metric_pct = primary["symbol_contamination_pct"]
    metric_frac = None if metric_pct is None else metric_pct / 100.0
    all_under = all(
        r["symbol_contamination_pct"] is not None
        and (r["symbol_contamination_pct"] / 100.0) < GATE_FLOOR
        for r in sufficient)
    if parse_mismatches or not sufficient:
        passed_flag = None      # cannot evaluate: parse broken or undersampled
    else:
        passed_flag = all_under
    gate = gate_verdict(
        passed=passed_flag,
        min_denominator=min_symbols,
        denominator=primary["rendered_symbols"],
        metric=metric_frac, floor=GATE_FLOOR, gate_id="sg201_top_map_contamination<2%",
        upper_bound=True)
    gate["metric_percent"] = metric_pct
    gate["metric_unit"] = "fraction of rendered symbols (metric_percent = 100x metric)"
    gate["all_budgets_under_floor"] = all_under if sufficient else None
    gate["budgets_with_sufficient_sampling"] = [r["budget_tokens"] for r in sufficient]
    if parse_mismatches:
        gate["verdict"] = "RENDERED_OUTPUT_PARSE_MISMATCH"
        gate["passed"] = False
        gate["mismatches"] = parse_mismatches

    # Provenance note must be CONDITIONAL on digest exactness.
    prov = repo_provenance(root)
    prov["note"] = (
        "snapshot binding: scores apply to exactly this HEAD+worktree "
        "(content-exact digest)" if not prov["digest_truncated"]
        else "snapshot binding PARTIAL: digest truncated (cap/unreadable) — "
             "treat as HEAD + declared dirty set, NOT content-exact")

    return {
        "benchmark": "sg201-map-contamination",
        "scope": scope or DEFAULT_SCOPE,
        "provenance": prov,
        "policy": {
            "selection": "ACTUAL rendered map text within declared token budget "
                         "(default budgets " + ",".join(map(str, budgets)) + ")",
            "default_categories": "production only (the shipped default)",
            "category_oracle": "declared superset oracle (common.ORACLE_*_RULES); "
                               "over-flagging only, divergences published",
            "gate": f"symbol-level fixture+vendor contamination < {GATE_FLOOR:.0%} "
                    f"of rendered symbols, min rendered symbols {min_symbols}",
            "landmark_precision@20": "NOT measured here — requires human reviewer "
                                     "(plan/sg201-landmark-study-protocol.md)",
        },
        "runs": runs,
        "primary_run": primary,
        "denominators": {
            "rendered_symbols": primary["rendered_symbols"],
            "rendered_files": primary["rendered_files"],
        },
        "parse_mismatches": parse_mismatches,
        "gate": gate,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    g = report["gate"]
    p = report["primary_run"]
    lines = [
        "# SG-201 exit-gate measurement — top-map contamination",
        "",
        f"Scope: {report['scope']}",
        "",
        "## Provenance",
        f"- git HEAD: `{report['provenance']['git_head']}` "
        f"worktree digest: `{report['provenance']['worktree_digest']}` "
        f"(dirty entries: {report['provenance']['dirty_entries']}, "
        f"digest truncated: {report['provenance']['digest_truncated']})",
        f"- {report['provenance']['note']}",
        "",
        "## Policy (declared)",
    ]
    for k, v in report["policy"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Primary run (default filter, largest declared budget)"]
    lines += [
        f"- rendered symbols / files: {p['rendered_symbols']} / {p['rendered_files']}",
        f"- fixture+vendor symbols: {p['contaminated_symbols']} "
        f"({format_pct(p['contaminated_symbols'], p['rendered_symbols'])})",
        f"- fixture+vendor files: {p['contaminated_files']} "
        f"({format_pct(p['contaminated_files'], p['rendered_files'])})",
        f"- head-{LANDMARK_SLICE_FILES}-files slice contaminated symbols: "
        f"{p[f'head{LANDMARK_SLICE_FILES}_contaminated']} / {p[f'head{LANDMARK_SLICE_FILES}_symbols']}",
        f"- src/ production share: {p['src_production_share_pct']}%",
        f"- category breakdown (symbols): {p['category_breakdown_symbols']}",
        "",
        "## Runs",
        "",
        "| budget | control(all) | rendered syms | contam syms | contam % |",
        "|---|---|---|---|---|",
    ]
    for r in report["runs"]:
        lines.append(
            f"| {r['budget_tokens']} | {'yes' if r.get('control_all_categories') else 'no'} "
            f"| {r['rendered_symbols']} | {r['contaminated_symbols']} "
            f"| {r['symbol_contamination_pct']}% |")
    lines += ["", "## Production-vs-oracle divergences (rendered files)"]
    divs = p.get("production_vs_oracle_divergences") or []
    if divs:
        for d in divs:
            lines.append(f"- `{d['path']}`: oracle={d['oracle']} production={d['production']}")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Gate",
        f"- verdict: **{g['verdict']}** (metric {g['metric_percent']}% = "
        f"fraction {g['metric']} vs floor <{GATE_FLOOR:.0%}, "
        f"denominator {g['denominator']} / min {g['min_denominator']}; "
        f"budgets with sufficient sampling: "
        f"{g.get('budgets_with_sufficient_sampling')})",
        "",
        "> Landmark precision@20 >= 90% requires HUMAN reviewers — status "
        "PENDING_HUMAN_EVIDENCE. Any automated proxy is reported separately and "
        "never substitutes the gate.",
    ]
    return "\n".join(lines) + "\n"
