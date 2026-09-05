"""Split governance for the untouched-holdout benchmark split (SG-204
follow-up; splits.py).

Two corpora, two roles. Code enforces the STRUCTURAL part of the
split contract — declared roles, repo disjointness (name/url/commit/
seed), and freeze binding (sha-256 of the exact manifest bytes).
The BEHAVIORAL part is workflow policy, recorded but not machine-
enforceable by these checks: ``tuning_exclusion`` (no extractor,
ranking, gate, or threshold change authored from holdout scores) and
the freeze-before-evaluation chronology rely on the recorded process;
the hash binding only makes post-freeze byte tampering detectable.

- ``benchmarks/holdout``            → role ``development-regression``:
  tuning-eligible; drives day-to-day development and regression gates.
  Its scores MUST NOT be reported as untouched-holdout results.
- ``benchmarks/holdout_unseen``     → role ``holdout-untouched``:
  repos disjoint from the dev split, tasks selected mechanically from
  git history + stdlib-ast oracle only (``scripts/bench_holdout_select.py``),
  then FROZEN (``FREEZE.json`` binds the sha-256 of the manifest bytes)
  BEFORE the first evaluation. ``tuning_exclusion`` holds: no extractor,
  ranking, gate, or threshold change may be authored from this split's
  scores.

Every validator here is stdlib-only and read-only; failures are returned
as explicit error strings so tests and CI can report them without this
module ever mutating state.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
DEV_MANIFEST = REPO_ROOT / "benchmarks" / "holdout" / "manifest.json"
HOLDOUT_MANIFEST = REPO_ROOT / "benchmarks" / "holdout_unseen" / "manifest.json"
HOLDOUT_FREEZE = REPO_ROOT / "benchmarks" / "holdout_unseen" / "FREEZE.json"

ROLE_DEVELOPMENT = "development-regression"
ROLE_HOLDOUT = "holdout-untouched"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REQUIRED_REPO_KEYS = ("name", "url", "commit", "language", "license", "seed", "tasks")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_sha256(path: Path) -> str:
    """Freeze hash: sha-256 over the exact manifest bytes on disk."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Provenance — every repo pin must be complete and verifiable
# ---------------------------------------------------------------------------


def validate_provenance(manifest: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    repos = manifest.get("repos") or []
    if not (10 <= len(repos) <= 20):
        errors.append(f"manifest must hold 10-20 repos, has {len(repos)}")
    seen_names: Dict[str, str] = {}
    seen_seeds: Dict[int, str] = {}
    seen_commits: Dict[str, str] = {}
    for repo in repos:
        name = str(repo.get("name") or "<missing>")
        for key in _REQUIRED_REPO_KEYS:
            if not repo.get(key):
                errors.append(f"{name}: missing required key {key!r}")
        url = str(repo.get("url") or "")
        if not url.startswith("https://github.com/"):
            errors.append(f"{name}: url must be an https GitHub URL, got {url!r}")
        commit = str(repo.get("commit") or "")
        if not _HEX40.match(commit):
            errors.append(f"{name}: commit must be a full 40-hex SHA, got {commit!r}")
        if repo.get("language") not in ("python",):
            errors.append(f"{name}: unsupported language {repo.get('language')!r}")
        seed = repo.get("seed")
        if not isinstance(seed, int):
            errors.append(f"{name}: seed must be an int, got {seed!r}")
        task = repo.get("diff_task") or {}
        base, head = str(task.get("base") or ""), str(task.get("head") or "")
        if not _HEX40.match(base):
            errors.append(f"{name}: diff_task.base must be 40-hex, got {base!r}")
        if not _HEX40.match(head):
            errors.append(f"{name}: diff_task.head must be 40-hex, got {head!r}")
        if base and base == head:
            errors.append(f"{name}: diff_task.base == head (empty diff)")
        if not task.get("subject"):
            errors.append(f"{name}: diff_task.subject missing")
        if not _ISO_DATE.match(str(task.get("date") or "")):
            errors.append(f"{name}: diff_task.date must be YYYY-MM-DD")
        files = task.get("changed_files") or []
        if not files:
            errors.append(f"{name}: diff_task.changed_files is empty")
        else:
            if not any(f.endswith(".py") for f in files):
                errors.append(f"{name}: diff touches no .py file (vacuous task)")
            if not any(
                f.endswith(".py") and not f.startswith(("docs/", ".github/", "examples/"))
                for f in files
            ):
                errors.append(f"{name}: diff touches no source .py file")
        # global disjointness inside this manifest
        if name in seen_names:
            errors.append(f"{name}: duplicate repo name (also {seen_names[name]})")
        seen_names[name] = name
        if isinstance(seed, int) and seed in seen_seeds:
            errors.append(f"{name}: seed {seed} reused by {seen_seeds[seed]}")
        seen_seeds[seed] = name
        if commit in seen_commits:
            errors.append(f"{name}: commit {commit[:10]} reused by {seen_commits[commit]}")
        seen_commits[commit] = name
    return errors


# ---------------------------------------------------------------------------
# Freeze — the holdout manifest is immutable after the freeze record
# ---------------------------------------------------------------------------


def validate_freeze(
    manifest_path: Path = HOLDOUT_MANIFEST, freeze_path: Path = HOLDOUT_FREEZE
) -> List[str]:
    errors: List[str] = []
    if not manifest_path.exists():
        return [f"holdout manifest missing: {manifest_path}"]
    if not freeze_path.exists():
        return [f"freeze record missing: {freeze_path}"]
    freeze = load_json(freeze_path)
    for key in ("frozen_at", "manifest_sha256", "manifest_path", "selection", "freeze_policy"):
        if not freeze.get(key):
            errors.append(f"freeze record missing {key!r}")
    digest = manifest_sha256(manifest_path)
    if freeze.get("manifest_sha256") != digest:
        errors.append(
            "FREEZE MISMATCH: manifest bytes changed after freeze "
            f"(freeze={str(freeze.get('manifest_sha256'))[:16]}... "
            f"disk={digest[:16]}...)"
        )
    recorded = str(freeze.get("manifest_path") or "")
    if recorded and Path(recorded).name != manifest_path.name:
        errors.append(
            f"freeze record pins {recorded!r}, validated against {manifest_path.name!r}"
        )
    if not _ISO_DATE.match(str(freeze.get("frozen_at") or "")[:10]):
        errors.append(f"freeze frozen_at not parseable: {freeze.get('frozen_at')!r}")
    sel = freeze.get("selection")
    if not isinstance(sel, dict) or not sel.get("procedure"):
        errors.append("freeze selection procedure not documented")
    return errors


# ---------------------------------------------------------------------------
# Roles & split semantics
# ---------------------------------------------------------------------------


def validate_roles(dev: Dict[str, Any], holdout: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if dev.get("role") != ROLE_DEVELOPMENT:
        errors.append(f"dev corpus role must be {ROLE_DEVELOPMENT!r}, got {dev.get('role')!r}")
    if dev.get("policy", {}).get("tuning_eligible") is not True:
        errors.append("dev corpus policy.tuning_eligible must be true")
    if holdout.get("split") != "holdout":
        errors.append(f"holdout corpus split must be 'holdout', got {holdout.get('split')!r}")
    if holdout.get("role") != ROLE_HOLDOUT:
        errors.append(f"holdout corpus role must be {ROLE_HOLDOUT!r}, got {holdout.get('role')!r}")
    if holdout.get("policy", {}).get("tuning_exclusion") is not True:
        errors.append("holdout corpus policy.tuning_exclusion must be true")
    return errors


def split_overlap(dev: Dict[str, Any], holdout: Dict[str, Any]) -> Dict[str, List[str]]:
    """Every shared identifier between the two splits — name, URL,
    pinned commit, or seed. The holdout split is only "untouched" if
    ALL of these are empty."""
    overlaps: Dict[str, List[str]] = {"name": [], "url": [], "commit": [], "seed": []}
    dev_names = {r.get("name") for r in dev.get("repos", [])}
    dev_urls = {r.get("url") for r in dev.get("repos", [])}
    dev_commits = {r.get("commit") for r in dev.get("repos", [])}
    dev_seeds = {r.get("seed") for r in dev.get("repos", [])}
    for r in holdout.get("repos", []):
        if r.get("name") in dev_names:
            overlaps["name"].append(r["name"])
        if r.get("url") in dev_urls:
            overlaps["url"].append(r["url"])
        if r.get("commit") in dev_commits:
            overlaps["commit"].append(r["commit"])
        if r.get("seed") in dev_seeds:
            overlaps["seed"].append(str(r["seed"]))
    return {k: v for k, v in overlaps.items() if v}


def enforce_holdout_integrity(
    dev_path: Path = DEV_MANIFEST,
    holdout_path: Path = HOLDOUT_MANIFEST,
    freeze_path: Path = HOLDOUT_FREEZE,
) -> Dict[str, Any]:
    """Full governance gate: roles, provenance, disjointness, freeze.

    Returns ``{"ok": bool, "errors": [...]}`` — safe to call from tests
    and CI; never mutates anything.
    """
    errors: List[str] = []
    dev = load_json(dev_path)
    holdout = load_json(holdout_path)
    errors.extend(validate_roles(dev, holdout))
    errors.extend(f"dev/{e}" for e in validate_provenance(dev))
    errors.extend(f"holdout/{e}" for e in validate_provenance(holdout))
    for kind, shared in split_overlap(dev, holdout).items():
        errors.append(f"split overlap on {kind}: {sorted(shared)}")
    errors.extend(validate_freeze(holdout_path, freeze_path))
    return {
        "ok": not errors,
        "errors": errors,
        "dev_repos": len(dev.get("repos", [])),
        "holdout_repos": len(holdout.get("repos", [])),
    }


__all__ = [
    "DEV_MANIFEST",
    "HOLDOUT_FREEZE",
    "HOLDOUT_MANIFEST",
    "ROLE_DEVELOPMENT",
    "ROLE_HOLDOUT",
    "enforce_holdout_integrity",
    "load_json",
    "manifest_sha256",
    "split_overlap",
    "validate_freeze",
    "validate_provenance",
    "validate_roles",
]
