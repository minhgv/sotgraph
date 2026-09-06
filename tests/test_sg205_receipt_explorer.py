"""SG-205: read-only human receipt explorer (render + diff + version gate).

The explorer's entry points take inert parsed receipt dicts — never DB
handles — and return strings. These tests pin that contract plus the
operator-question coverage (P1-6 Q1..Q7) and the fail-closed version
gating.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from sot_graph.assurance.impact_pipeline import ReceiptStore
from sot_graph.assurance.receipts import RECEIPT_SCHEMA_VERSION
from sot_graph.receipt_explorer import (
    NOT_RECORDED,
    UnsupportedReceiptVersion,
    diff_receipts,
    gate_receipt_version,
    render_receipt,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def scope_receipt() -> dict:
    """Realistic scope receipt built from the real schema-1.7 payload
    field names (assurance/receipts.py scope_receipt)."""
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "scope",
        "proof_scope": "pre_change_only",
        "digest": "a" * 64,
        "request": {
            "target": "Pipeline.process",
            "kind_of_change": "local-body",
            "depth": 2,
            "touches_auth": False,
            "dynamic_heavy": False,
        },
        "manifest": {"files": 3, "unsupported_constructs": []},
        "scope_universe": {
            "enumeration_complete": True,
            "parser_capability_complete": True,
            "partial_ast_present": False,
            "unsupported_constructs": [],
        },
        "identity": {
            "status": "UNIQUE",
            "candidates": [],
            "selected": {"path": "src/app.py", "symbol": "Pipeline.process"},
        },
        "assurance_facts": {
            "identity_status": "UNIQUE",
            "claim_profile": "scoped",
            "collection_error": False,
            "snapshot_bound": True,
            "stale_files": [],
            "truncated": False,
        },
        "snapshot": {
            "snapshot_id": None,
            "descriptor_digest": "b" * 64,
            "role": "query",
            "commit_sha": "c" * 40,
            "dirty": False,
            "generation": 7,
            "scope_digest": "d" * 64,
            "captured_at": 1730000000,
        },
        "stale_files": [],
        "source_anchors": [
            {"path": "src/app.py", "line_start": 10, "line_end": 40,
             "symbol": "Pipeline.process"},
        ],
        "direct_callers": [{"path": "src/main.py", "symbol": "main"}],
        "direct_callees": [{"path": "src/app.py", "symbol": "Pipeline.step"}],
        "relations": [],
        "transitive_impact": {
            "depth": 2, "nodes": ["x", "y", "z"], "truncated": False,
        },
        "collection_stats": {
            "direct_edges": {
                "enumerated_count": 12, "returned_count": 12, "cap": 200,
                "truncated": False, "cursor_exhausted": True,
            },
            "transitive": {
                "enumerated_count": 3, "returned_count": 3, "cap": 500,
                "truncated": False, "cursor_exhausted": True,
            },
        },
        "affected_files": ["src/app.py"],
        "candidate_tests": [{"path": "tests/test_app.py"}],
        "providers": {"provider_counts": {"builtin": 5}, "open_conflicts": 0},
        "warnings": [],
        "coverage": {"note": "coverage measured", "basis": "measured",
                     "gaps": []},
        "assurance": {
            "risk": {"rule": "local_body", "absence_assurance": False},
            "rename_gate": {"symbol": "Pipeline.process", "blocked": False,
                            "reason": "rename gate not applicable"},
            "omp_confirmations": [],
            "status": "ASSURED_WITHIN_SCOPE",
            "reason_codes": [],
            "decision": {"status": "ASSURED_WITHIN_SCOPE", "reason_codes": []},
        },
    }


@pytest.fixture
def downgrade_receipt(scope_receipt: dict) -> dict:
    """Same shape, downgraded to PARTIAL with cap + dynamic-dispatch facts."""
    receipt = copy.deepcopy(scope_receipt)
    receipt["digest"] = "e" * 64
    receipt["scope_universe"]["enumeration_complete"] = False
    receipt["collection_stats"]["transitive"] = {
        "enumerated_count": 900, "returned_count": 500, "cap": 500,
        "truncated": True, "cursor_exhausted": False,
    }
    receipt["transitive_impact"]["truncated"] = True
    receipt["assurance"]["status"] = "PARTIAL"
    receipt["assurance"]["reason_codes"] = [
        "dynamic_dispatch_unresolved", "collection_truncated:transitive",
    ]
    receipt["assurance"]["omp_confirmations"] = [
        "confirm no reflective dispatch on Pipeline.process",
    ]
    return receipt


# --------------------------------------------------------------------------
# Q1..Q6: one receipt, terminal view
# --------------------------------------------------------------------------
def test_render_answers_all_question_areas(scope_receipt: dict) -> None:
    out = render_receipt(scope_receipt)
    assert "Q1 CLAIM" in out and "ASSURED_WITHIN_SCOPE" in out
    assert "Q2 SCOPE" in out
    assert "Pipeline.process" in out          # approved request/binding
    assert ("generation=7" in out             # snapshot/generation binding
            and "scope_digest" in out)
    assert "Q3 OUTSIDE SCOPE" in out
    assert "collection 'direct_edges'" in out  # cap accounting
    assert "Q4 EVIDENCE" in out
    assert "direct callers: 1" in out          # evidence counts
    assert "provider evidence counts" in out
    assert "Q5 DOWNGRADE" in out
    assert "no downgrade recorded in this receipt" in out
    assert "Q6 REMEDIATION" in out
    assert "not recorded in this receipt" in out  # remediation is empty here
    assert "schema" in out and RECEIPT_SCHEMA_VERSION in out
    assert "read-only" in out


def test_render_downgrade_reasons_and_caps(downgrade_receipt: dict) -> None:
    out = render_receipt(downgrade_receipt)
    assert "PARTIAL" in out
    assert "dynamic_dispatch_unresolved —" in out
    assert "collection_truncated:transitive —" in out
    assert "TRUNCATED" in out                   # cap cut is visible
    assert "returned 500 of 900 (cap 500)" in out
    assert "[ ] confirm no reflective dispatch" in out  # remediation owed


def test_missing_question_data_is_explicit(scope_receipt: dict) -> None:
    receipt = copy.deepcopy(scope_receipt)
    del receipt["providers"]          # Q4 evidence area
    del receipt["coverage"]           # Q2 scope area
    del receipt["warnings"]           # Q5 errors area
    del receipt["collection_stats"]   # Q3 caps area
    out = render_receipt(receipt)
    assert out.count(NOT_RECORDED) >= 4
    # Never render absence-of-field as absence-of-error:
    assert "warnings: none" not in out
    assert "collection errors: none" not in out
    assert f"warnings: {NOT_RECORDED}" in out
    assert f"providers ledger: {NOT_RECORDED}" in out
    assert f"collection caps: {NOT_RECORDED}" in out


def test_missing_version_refused() -> None:
    with pytest.raises(UnsupportedReceiptVersion, match="schema_version"):
        render_receipt({"kind": "scope"})


# --------------------------------------------------------------------------
# Q7: diff of two receipts
# --------------------------------------------------------------------------
def test_diff_reports_status_scope_cap_generation(
    scope_receipt: dict, downgrade_receipt: dict,
) -> None:
    out = diff_receipts(scope_receipt, downgrade_receipt)
    assert "assurance.status: ASSURED_WITHIN_SCOPE → PARTIAL" in out
    assert "snapshot.generation" not in out  # unchanged binding: no noise
    assert "collection_stats.transitive.cap: 500 → 500" not in out
    assert "assurance.reason_codes" in out   # reason codes added
    assert "collection_stats.transitive.truncated: false → true" in out
    assert "digest" in out                    # header shows both digests
    assert "10 difference(s)" in out or "difference(s)" in out


def test_diff_identical_receipts_reports_no_differences(
    scope_receipt: dict,
) -> None:
    assert "no differences" in diff_receipts(scope_receipt, scope_receipt)


def test_diff_ignores_volatile_fields(scope_receipt: dict) -> None:
    changed_clock = copy.deepcopy(scope_receipt)
    changed_clock["snapshot"]["captured_at"] = 9999999999
    assert "no differences" in diff_receipts(scope_receipt, changed_clock)


# --------------------------------------------------------------------------
# Version gating
# --------------------------------------------------------------------------
def test_legacy_version_renders_with_banner(scope_receipt: dict) -> None:
    receipt = copy.deepcopy(scope_receipt)
    receipt["schema_version"] = "1.6"
    out = render_receipt(receipt)
    assert "[!]" in out
    assert "schema 1.6: rendered best-effort" in out
    assert "fields may be missing" in out


@pytest.mark.parametrize("bad_version", ["0.9", "2.0", "banana", None])
def test_unknown_version_refused(scope_receipt: dict,
                                 bad_version: str) -> None:
    receipt = copy.deepcopy(scope_receipt)
    if bad_version is None:
        del receipt["schema_version"]
    else:
        receipt["schema_version"] = bad_version
    with pytest.raises(UnsupportedReceiptVersion):
        render_receipt(receipt)
    with pytest.raises(UnsupportedReceiptVersion):
        diff_receipts(scope_receipt, receipt)


def test_gate_states(scope_receipt: dict) -> None:
    assert gate_receipt_version(scope_receipt).state == "current"
    legacy = dict(scope_receipt, schema_version="1.3")
    gate = gate_receipt_version(legacy)
    assert gate.state == "legacy" and gate.banner


# --------------------------------------------------------------------------
# Read-only design: inert parsed data in, strings out, inputs untouched
# --------------------------------------------------------------------------
def test_entry_points_take_plain_dicts_and_do_not_mutate(
    scope_receipt: dict, downgrade_receipt: dict,
) -> None:
    before = copy.deepcopy(scope_receipt)
    other = copy.deepcopy(downgrade_receipt)
    before_other = copy.deepcopy(other)
    out_a = render_receipt(scope_receipt)
    out_b = diff_receipts(scope_receipt, other)
    assert isinstance(out_a, str) and isinstance(out_b, str)
    assert scope_receipt == before and other == before_other


def test_module_surface_has_no_db_or_io_dependencies() -> None:
    import sot_graph.receipt_explorer as module
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "Database" not in source
    assert "reconcile(" not in source
    assert "open(" not in source and ".write" not in source


# --------------------------------------------------------------------------
# CLI: sotgraph receipt show / diff
# --------------------------------------------------------------------------
def _run_cli(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    # Global --root must precede the subcommand (argparse convention).
    return subprocess.run(
        [sys.executable, "-m", "sot_graph.cli", "--root", str(cwd), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, cwd=str(cwd),
    )


def test_cli_receipt_show_happy_path(tmp_path: Path,
                                     scope_receipt: dict) -> None:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(scope_receipt), encoding="utf-8")
    proc = _run_cli("receipt", "show", str(path), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "Q1 CLAIM" in proc.stdout
    assert "ASSURED_WITHIN_SCOPE" in proc.stdout


def test_cli_receipt_show_json(tmp_path: Path, scope_receipt: dict) -> None:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(scope_receipt), encoding="utf-8")
    proc = _run_cli("receipt", "show", str(path), "--json",
                    cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["kind"] == "scope"


def test_cli_receipt_show_by_digest(tmp_path: Path,
                                    scope_receipt: dict) -> None:
    store = ReceiptStore(tmp_path / ".sot" / "receipts")
    digest = store.put(scope_receipt)
    proc = _run_cli("receipt", "show", digest, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "Q1 CLAIM" in proc.stdout


def test_cli_receipt_show_unknown_version_exit_code(
    tmp_path: Path, scope_receipt: dict,
) -> None:
    receipt = copy.deepcopy(scope_receipt)
    receipt["schema_version"] = "9.9"
    path = tmp_path / "future.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    proc = _run_cli("receipt", "show", str(path), cwd=tmp_path)
    assert proc.returncode == 1
    assert "9.9" in proc.stderr and "refus" in proc.stderr


def test_cli_receipt_show_legacy_banner_but_zero_exit(
    tmp_path: Path, scope_receipt: dict,
) -> None:
    receipt = copy.deepcopy(scope_receipt)
    receipt["schema_version"] = "1.5"
    path = tmp_path / "old.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    proc = _run_cli("receipt", "show", str(path), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "best-effort" in proc.stderr


def test_cli_receipt_diff(tmp_path: Path, scope_receipt: dict,
                          downgrade_receipt: dict) -> None:
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(scope_receipt), encoding="utf-8")
    new_path.write_text(json.dumps(downgrade_receipt), encoding="utf-8")
    proc = _run_cli("receipt", "diff", str(old_path), str(new_path),
                    cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "assurance.status: ASSURED_WITHIN_SCOPE → PARTIAL" in proc.stdout
    # identical pair → explicit no-differences
    proc = _run_cli("receipt", "diff", str(old_path), str(old_path),
                    cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "no differences" in proc.stdout


def test_cli_receipt_missing_file_exit_code(tmp_path: Path) -> None:
    proc = _run_cli("receipt", "show", str(tmp_path / "nope.json"),
                    cwd=tmp_path)
    assert proc.returncode == 1
    assert "nope.json" in proc.stderr
