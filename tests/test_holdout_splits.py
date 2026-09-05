"""Split-governance tests for the untouched-holdout honesty gates
(SG-204 follow-up).

Enforces, in code:

1. ROLES — ``benchmarks/holdout`` is the development/regression split
   (tuning-eligible, never reportable as holdout);
   ``benchmarks/holdout_unseen`` is the untouched holdout split with
   ``tuning_exclusion`` set.
2. SPLIT DISJOINTNESS — the holdout split shares NO repo name, URL,
   pinned commit, or seed with the dev split (a holdout that reuses a
   dev repo is not untouched).
3. PROVENANCE — every pin is complete and verifiable: full 40-hex
   commit SHAs, https GitHub URLs, license/language metadata, int seeds,
   non-vacuous diff tasks (source .py + test contact + dates/subjects).
4. FREEZE — FREEZE.json binds the sha-256 of the exact manifest bytes
   recorded BEFORE first evaluation; any post-freeze manifest edit is a
   hard failure, and the freeze policy/selection procedure must be
   documented.
"""

from __future__ import annotations

import ast
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "scripts"))

from sot_graph.holdout import evaluator as oracle  # noqa: E402
from sot_graph.holdout import splits  # noqa: E402

import bench_holdout  # noqa: E402  (the ACTUAL runner under governance test)
import bench_holdout_select as selector  # noqa: E402  (the ACTUAL generator)

DEV = splits.load_json(splits.DEV_MANIFEST)
HOLDOUT = splits.load_json(splits.HOLDOUT_MANIFEST)
FREEZE = splits.load_json(splits.HOLDOUT_FREEZE)


# ---------------------------------------------------------------------------
# 1. Roles: dev tunes, holdout is excluded from tuning
# ---------------------------------------------------------------------------


def test_roles_declared_on_both_splits():
    errors = splits.validate_roles(DEV, HOLDOUT)
    assert not errors, errors
    assert DEV["role"] == "development-regression"
    assert DEV["policy"]["tuning_eligible"] is True
    assert HOLDOUT["role"] == "holdout-untouched"
    assert HOLDOUT["split"] == "holdout"
    assert HOLDOUT["policy"]["tuning_exclusion"] is True
    dev_notes = "\n".join(DEV.get("notes", []))
    assert "MUST NOT be reported as untouched-holdout" in dev_notes, (
        "dev manifest must carry the anti-relabeling warning in prose too"
    )


def test_holdout_manifest_documents_tuning_exclusion():
    text = (splits.HOLDOUT_MANIFEST).read_text(encoding="utf-8")
    assert '"tuning_exclusion": true' in text
    assert '"role": "holdout-untouched"' in text
    # the holdout manifest must point at the dev/regression split so the
    # two roles can never be silently swapped or relabeled
    assert "benchmarks/holdout" in text
    assert "development/regression corpus lives in benchmarks/holdout" in text
    # selection must document that it never conditioned on production scores
    sel = FREEZE["selection"]["procedure"]
    assert "oracle-only" in sel and "no production engine" in sel


# ---------------------------------------------------------------------------
# 2. Split disjointness
# ---------------------------------------------------------------------------


def test_holdout_repos_disjoint_from_dev_split():
    overlaps = splits.split_overlap(DEV, HOLDOUT)
    assert not overlaps, f"holdout shares identifiers with dev split: {overlaps}"


def test_holdout_repos_are_distinct_projects():
    dev_names = {r["name"] for r in DEV["repos"]}
    holdout_names = {r["name"] for r in HOLDOUT["repos"]}
    assert len(holdout_names) == len(HOLDOUT["repos"])
    assert not (dev_names & holdout_names), "same project in both splits"


# ---------------------------------------------------------------------------
# 3. Provenance
# ---------------------------------------------------------------------------


def test_both_manifests_have_complete_provenance():
    for label, manifest in (("dev", DEV), ("holdout", HOLDOUT)):
        errors = splits.validate_provenance(manifest)
        assert not errors, [f"{label}/{e}" for e in errors]


def test_holdout_diff_tasks_are_measurable_not_vacuous():
    for repo in HOLDOUT["repos"]:
        task = repo["diff_task"]
        src = [
            f for f in task["changed_files"]
            if f.endswith(".py")
            and not oracle.is_test_path(f)
            and not f.startswith(("docs/", ".github/", "examples/"))
        ]
        assert 1 <= len(src) <= 4, f"{repo['name']}: {len(src)} source files (rule: 1-4)"
        assert any(oracle.is_test_path(f) for f in task["changed_files"]), repo["name"]
        for sha in (repo["commit"], task["base"], task["head"]):
            assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)


# ---------------------------------------------------------------------------
# 4. Freeze integrity
# ---------------------------------------------------------------------------


def test_freeze_binds_exact_manifest_bytes():
    errors = splits.validate_freeze(splits.HOLDOUT_MANIFEST, splits.HOLDOUT_FREEZE)
    assert not errors, errors
    assert FREEZE["manifest_sha256"] == splits.manifest_sha256(splits.HOLDOUT_MANIFEST)


def test_freeze_detects_post_freeze_manifest_edit(tmp_path):
    tampered = copy.deepcopy(HOLDOUT)
    tampered["repos"][0]["seed"] = 999999999
    tampered_path = tmp_path / "manifest.json"
    tampered_path.write_text(
        json.dumps(tampered, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    freeze_path = tmp_path / "FREEZE.json"
    freeze_path.write_text(
        json.dumps({**FREEZE, "manifest_path": "benchmarks/holdout_unseen/manifest.json"}),
        "utf-8",
    )
    errors = splits.validate_freeze(tampered_path, freeze_path)
    assert any("FREEZE MISMATCH" in e for e in errors), errors


def test_freeze_requires_selection_procedure_and_policy(tmp_path):
    freeze_path = tmp_path / "FREEZE.json"
    freeze_path.write_text(json.dumps({"frozen_at": "2026-09-05T00:00:00Z"}), "utf-8")
    errors = splits.validate_freeze(splits.HOLDOUT_MANIFEST, freeze_path)
    assert any("manifest_sha256" in e for e in errors)
    assert any("selection" in e for e in errors)
    assert any("freeze_policy" in e for e in errors)


# ---------------------------------------------------------------------------
# 5. Full governance gate
# ---------------------------------------------------------------------------


def test_enforce_holdout_integrity_passes():
    report = splits.enforce_holdout_integrity()
    assert report["ok"], report["errors"]
    assert report["dev_repos"] >= 10
    assert report["holdout_repos"] >= 10


def test_selection_script_consults_only_git_and_the_oracle():
    """The unseen-split selector must consult only git and the stdlib-ast
    oracle — the ONLY sot_graph import it may have is
    ``sot_graph.holdout.evaluator`` (the independent oracle). Extraction,
    ranking, diff and db engines are forbidden."""
    source = (_REPO / "scripts" / "bench_holdout_select.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    stdlib = set(sys.stdlib_module_names)
    allowed_sot = {"sot_graph.holdout", "sot_graph.holdout.evaluator"}
    forbidden_roots = (
        "reconciler", "diff_impact", "db", "providers", "extractor",
        "mcp_service", "search", "verifier",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root in stdlib, f"non-stdlib import in selector: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root == "sot_graph":
                assert module in allowed_sot, (
                    f"selector imports production internals: {module}"
                )
            else:
                assert root in stdlib, f"non-stdlib import-from in selector: {module}"
    for name in forbidden_roots:
        assert f"from sot_graph.{name}" not in source and (
            f"import sot_graph.{name}" not in source
        ), f"selector references engine module: {name}"


# ---------------------------------------------------------------------------
# 6. The ACTUAL runner refuses to evaluate a tampered holdout (fail closed)
# ---------------------------------------------------------------------------


def _tampered_frozen_manifest_dir(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A holdout manifest whose bytes differ from its freeze binding —
    i.e. exactly what a post-freeze edit looks like."""
    tampered = copy.deepcopy(HOLDOUT)
    tampered["repos"][0]["seed"] = 999999999
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(tampered, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    freeze = tmp_path / "FREEZE.json"
    freeze.write_text(
        json.dumps(
            {
                **FREEZE,
                "manifest_path": "benchmarks/holdout_unseen/manifest.json",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "utf-8",
    )
    return manifest, freeze, tmp_path / "repos"


def test_runner_selfcheck_refuses_tampered_frozen_manifest(tmp_path, capsys):
    manifest, _freeze, repos_dir = _tampered_frozen_manifest_dir(tmp_path)
    report = tmp_path / "report.json"
    with pytest.raises(SystemExit) as ei:
        bench_holdout.main(
            [
                "--manifest", str(manifest),
                "--repos-dir", str(repos_dir),
                "--report", str(report),
                "--selfcheck",
            ]
        )
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "SPLIT GOVERNANCE FAIL" in err
    assert "FREEZE MISMATCH" in err
    # refused BEFORE any artifact: no report written, no repos touched
    assert not report.exists()
    assert not repos_dir.exists()


def test_runner_evaluation_refuses_before_any_clone(tmp_path, capsys):
    """Even with --ensure-clone the runner must refuse BEFORE cloning or
    evaluating anything — governance precedes the repo loop."""
    manifest, _freeze, repos_dir = _tampered_frozen_manifest_dir(tmp_path)
    report = tmp_path / "report.json"
    with pytest.raises(SystemExit) as ei:
        bench_holdout.main(
            [
                "--manifest", str(manifest),
                "--repos-dir", str(repos_dir),
                "--report", str(report),
                "--ensure-clone",
                "--only", "pluggy",
            ]
        )
    assert ei.value.code == 1
    assert "SPLIT GOVERNANCE FAIL" in capsys.readouterr().err
    assert not repos_dir.exists(), "gate must fire before any clone attempt"
    assert not report.exists()


def test_runner_selfcheck_passes_on_untampered_frozen_copy(tmp_path):
    """Positive control: an exact byte-copy of the frozen manifest with
    its matching FREEZE record passes the same gate."""
    manifest = tmp_path / "manifest.json"
    shutil.copyfile(splits.HOLDOUT_MANIFEST, manifest)
    shutil.copyfile(splits.HOLDOUT_FREEZE, tmp_path / "FREEZE.json")
    rc = bench_holdout.main(
        ["--manifest", str(manifest), "--repos-dir", str(tmp_path / "repos"), "--selfcheck"]
    )
    assert rc == 0


def test_runner_selfcheck_allows_dev_manifest_without_freeze():
    """The dev/regression corpus is not a declared holdout: it needs no
    FREEZE record, but its provenance is still validated by the gate."""
    rc = bench_holdout.main(
        ["--manifest", str(splits.DEV_MANIFEST), "--selfcheck"]
    )
    assert rc == 0


def test_runner_gate_rejects_holdout_declaration_without_freeze_file(tmp_path, capsys):
    """A holdout-declaring manifest with NO freeze record at all must
    also fail closed (freeze cannot be optional for declared holdouts)."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(HOLDOUT, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    with pytest.raises(SystemExit) as ei:
        bench_holdout.main(
            ["--manifest", str(manifest), "--repos-dir", str(tmp_path / "r"), "--selfcheck"]
        )
    assert ei.value.code == 1
    assert "freeze record missing" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 7. The ACTUAL generator refuses to overwrite a frozen generation
# ---------------------------------------------------------------------------


def test_selector_refuses_overwriting_frozen_generation(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", "utf-8")
    freeze = tmp_path / "FREEZE.json"
    freeze.write_text(
        json.dumps({**FREEZE, "manifest_path": "x/manifest.json"}), "utf-8"
    )
    before = manifest.read_bytes()
    with pytest.raises(SystemExit) as ei:
        selector.main(["--output", str(manifest), "--repos-dir", str(tmp_path / "repos")])
    assert "REFUSING" in str(ei.value)
    assert manifest.read_bytes() == before, "frozen generation must be untouched"
    assert not (tmp_path / "repos").exists(), "refusal must precede any clone"


def test_selector_refuses_real_frozen_corpus(tmp_path):
    before = splits.manifest_sha256(splits.HOLDOUT_MANIFEST)
    with pytest.raises(SystemExit) as ei:
        selector.main(
            [
                "--output", str(splits.HOLDOUT_MANIFEST),
                "--repos-dir", str(tmp_path / "repos"),
            ]
        )
    assert "REFUSING" in str(ei.value)
    assert splits.manifest_sha256(splits.HOLDOUT_MANIFEST) == before


def test_selector_overwrite_gate_allows_new_and_unfrozen_paths(tmp_path):
    # fresh path: no refusal
    selector.refuse_frozen_overwrite(tmp_path / "fresh" / "manifest.json")
    # existing but unfrozen draft: allowed with a notice, not silent
    draft = tmp_path / "draft" / "manifest.json"
    draft.parent.mkdir(parents=True)
    draft.write_text("{}\n", "utf-8")
    selector.refuse_frozen_overwrite(draft)  # must not raise
    # frozen: raises
    (draft.parent / "FREEZE.json").write_text("{}", "utf-8")
    with pytest.raises(SystemExit):
        selector.refuse_frozen_overwrite(draft)
