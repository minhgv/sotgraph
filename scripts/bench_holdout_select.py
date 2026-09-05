#!/usr/bin/env python3
"""bench_holdout_select.py — mechanical task selection for the UNSEEN
holdout split (SG-204 follow-up: untouched corpus, frozen provenance).

Builds ``benchmarks/holdout_unseen/manifest.json`` from a FIXED repo
roster using a deterministic, seeded-free rule that inspects ONLY git
history and the independent stdlib-ast oracle — never the production
SOT engine, its ranking, or its extractors:

For each repo (fixed order, fixed seed):
  1. clone once into the selection cache;
  2. ``commit`` = default-branch HEAD at selection time (pinned forever);
  3. walk non-merge commits backwards from HEAD (max ``--max-walk``);
     the FIRST commit whose diff
       a. touches 1-4 source .py files (non-test, non-docs),
       b. touches at least one test .py file,
       c. yields a non-empty ``top_level_delta`` over the changed
          source files, and
       d. has at least one ground-truth test (a changed test file, or
          a HEAD test file referencing a changed top-level name) —
     becomes ``diff_task.head`` (base = its first parent).

This mirrors the documented dev-corpus selection rule
(``benchmarks/holdout/manifest.json`` notes) so both splits are
comparable. The output manifest MUST then be frozen (FREEZE.json,
sha-256 of the manifest bytes) BEFORE any baseline evaluation — the
split is "untouched" because selection never conditions on production
scores and the frozen manifest is evaluated once, published as-is.

Honesty limits (printed and recorded in FREEZE.json by the caller):
selection-time HEAD moves as upstream repos advance; the frozen
manifest — not a re-run — is the single source of truth for the split.
Re-running this selector against a FROZEN output path refuses
(fail-closed); a new generation requires a new --output path and its
own FREEZE record.

Usage:
  python3 scripts/bench_holdout_select.py [--repos-dir .holdout-cache-unseen]
      [--max-walk 400] [--output benchmarks/holdout_unseen/manifest.json]
      [--check-only]   # verify an existing manifest without writing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from sot_graph.holdout import evaluator as oracle  # noqa: E402

OUTPUT_PATH = _REPO / "benchmarks" / "holdout_unseen" / "manifest.json"
DEFAULT_REPOS_DIR = _REPO / ".holdout-cache-unseen"

#: Fixed roster — order, seeds and licenses are part of the frozen
#: selection procedure. Seeds are disjoint from the dev corpus
#: (204001-204011). All repos are distinct from the 11 dev repos.
ROSTER: List[Dict[str, str]] = [
    {"name": "pyflakes", "url": "https://github.com/PyCQA/pyflakes",
     "license": "MIT", "seed": "205001"},
    {"name": "pluggy", "url": "https://github.com/pytest-dev/pluggy",
     "license": "MIT", "seed": "205002"},
    {"name": "soupsieve", "url": "https://github.com/facelessuser/soupsieve",
     "license": "MIT", "seed": "205003"},
    {"name": "more-itertools", "url": "https://github.com/more-itertools/more-itertools",
     "license": "MIT", "seed": "205004"},
    {"name": "sqlparse", "url": "https://github.com/andialbrecht/sqlparse",
     "license": "BSD-3-Clause", "seed": "205005"},
    {"name": "python-dateutil", "url": "https://github.com/dateutil/dateutil",
     "license": "Apache-2.0", "seed": "205006"},
    {"name": "attrs", "url": "https://github.com/python-attrs/attrs",
     "license": "MIT", "seed": "205007"},
    {"name": "filelock", "url": "https://github.com/tox-dev/py-filelock",
     "license": "Unlicense", "seed": "205008"},
    {"name": "iniconfig", "url": "https://github.com/pytest-dev/iniconfig",
     "license": "MIT", "seed": "205009"},
    {"name": "platformdirs", "url": "https://github.com/platformdirs/platformdirs",
     "license": "MIT", "seed": "205010"},
]

#: Source files excluded from the 1-4 source-file count (same rule the
#: test-selection suite uses for "source" .py paths).
_SOURCE_EXCLUDE_PREFIXES = ("docs/", ".github/", "examples/")


def git(repo_dir: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), *args], capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args[:3])} failed: {result.stderr.strip()[:200]}"
        )
    return result.stdout.strip()


def ensure_clone(repo_dir: Path, url: str) -> None:
    if repo_dir.exists():
        git(repo_dir, "fetch", "-q", "origin", "--prune", check=False)
        return
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", url, str(repo_dir)], check=True)


def _changed_pairs(repo_dir: Path, base: str, head: str) -> List[Tuple[str, str]]:
    """Rename-aware (old, new) pairs for a diff, mirroring the suite."""
    pairs: List[Tuple[str, str]] = []
    for line in git(repo_dir, "diff", "--name-status", "-M", base, head).splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            pairs.append((parts[1], parts[2]))
        elif len(parts) == 2:
            pairs.append((parts[1], parts[1]))
    return pairs


def _gt_tests(
    repo_dir: Path, head: str, changed_py: List[Tuple[str, str]], names: set
) -> bool:
    """Same ground-truth rule as ``suite_test_selection``: a changed test
    file, or a HEAD test module referencing a changed top-level name."""
    for _old, new in changed_py:
        if oracle.is_test_path(new):
            return True
    for rel in git(repo_dir, "ls-tree", "-r", "--name-only", head).splitlines():
        rel = rel.strip()
        if not rel or not oracle.is_test_path(rel):
            continue
        text = git(repo_dir, "show", f"{head}:{rel}", check=False)
        if text and (oracle.referenced_names(text) & names):
            return True
    return False


def select_diff_task(
    repo_dir: Path, head_commit: str, max_walk: int
) -> Optional[Dict[str, Any]]:
    candidates = git(
        repo_dir, "log", "--no-merges", f"--max-count={max_walk + 1}",
        "--format=%H", head_commit,
    ).splitlines()
    for head in candidates[1:]:  # skip HEAD itself; base must be older
        base = git(repo_dir, "rev-parse", f"{head}^")
        pairs = _changed_pairs(repo_dir, base, head)
        source_py = [
            (o, n) for o, n in pairs
            if n.endswith(".py")
            and not oracle.is_test_path(n)
            and not n.startswith(_SOURCE_EXCLUDE_PREFIXES)
        ]
        test_py = [(o, n) for o, n in pairs if oracle.is_test_path(n)]
        if not (1 <= len(source_py) <= 4) or not test_py:
            continue
        changed_names: set = set()
        for old, new in source_py:
            head_text = git(repo_dir, "show", f"{head}:{new}", check=False)
            base_text = git(repo_dir, "show", f"{base}:{old}", check=False)
            changed_names |= oracle.top_level_delta(head_text, base_text)
        if not changed_names:
            continue
        if not _gt_tests(repo_dir, head, source_py + test_py, changed_names):
            continue
        date = git(repo_dir, "show", "-s", "--format=%cI", head)[:10]
        subject = git(repo_dir, "show", "-s", "--format=%s", head)
        return {
            "base": base,
            "changed_files": [
                n for _o, n in sorted(pairs, key=lambda p: p[1])
            ],
            "date": date,
            "head": head,
            "subject": subject,
        }
    return None


def build_manifest(repos_dir: Path, max_walk: int) -> Dict[str, Any]:
    repos: List[Dict[str, Any]] = []
    for entry in ROSTER:
        repo_dir = repos_dir / entry["name"]
        ensure_clone(repo_dir, entry["url"])
        commit = git(repo_dir, "rev-parse", "origin/HEAD")
        task = select_diff_task(repo_dir, commit, max_walk)
        if task is None:
            raise SystemExit(
                f"no measurable diff task within {max_walk} commits "
                f"for {entry['name']} — refusing to invent one"
            )
        repos.append({
            "commit": commit,
            "diff_task": task,
            "language": "python",
            "license": entry["license"],
            "name": entry["name"],
            "seed": int(entry["seed"]),
            "tasks": ["presence", "retrieval", "impact", "test_selection"],
            "url": entry["url"],
        })
        print(
            f"selected {entry['name']:16s} head={commit[:10]} "
            f"diff={task['head'][:10]} {task['date']} {task['subject'][:48]}"
        )
    repos.sort(key=lambda r: r["name"])
    return {
        "benchmark": "real-repo-holdout-unseen",
        "description": (
            "SG-204 UNSEEN holdout split: 10 public repos disjoint from the "
            "development/regression corpus (benchmarks/holdout), pinned at "
            "full SHAs; diff tasks selected mechanically from git history + "
            "stdlib-ast oracle only (scripts/bench_holdout_select.py), then "
            "frozen in FREEZE.json BEFORE any evaluation. Never used for "
            "extractor, ranking, or gate tuning."
        ),
        "notes": [
            "split role: holdout — evaluated once after freeze; results are",
            "published as-is and must NOT feed any production tuning loop;",
            "the development/regression corpus lives in benchmarks/holdout",
            "and is the only split allowed to drive code changes;",
            "selection rule (identical to the dev corpus rule): most recent",
            "non-merge commit touching 1-4 source .py files plus tests, with",
            "non-empty top_level_delta and >=1 ground-truth test reference."
        ],
        "oracle": {
            "independence": (
                "evaluator uses stdlib ast only; it must not import sot_graph "
                "extraction internals (enforced by test)"
            ),
            "suites": ["presence", "retrieval", "impact", "test_selection", "abstention"],
        },
        "policy": {
            "evaluation": (
                "one frozen baseline per manifest generation; any re-run "
                "publishes deltas, never silently replaces the baseline"
            ),
            "tuning_exclusion": True,
        },
        "repos": repos,
        "role": "holdout-untouched",
        "schema_version": 1,
        "split": "holdout",
    }


def canonical_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def refuse_frozen_overwrite(out: Path) -> None:
    """Fail closed BEFORE any clone/selection work.

    ``<output dir>/FREEZE.json`` marks a FROZEN split generation — a
    generation that has been (or may have been) evaluated. Regenerating
    over it would silently replace an evaluated holdout, which is the
    tuning-loop hazard this split exists to prevent. There is NO bypass
    flag: a new generation must be written to a NEW ``--output`` path
    and frozen under its own FREEZE record. This applies whether or not
    the on-disk bytes still match the recorded hash (a mismatch means
    the manifest already diverged from its freeze — refusing is even
    more urgent).
    """
    freeze_path = out.parent / "FREEZE.json"
    if not out.exists():
        return
    if freeze_path.exists():
        raise SystemExit(
            f"REFUSING: {out} belongs to a FROZEN split generation "
            f"({freeze_path} exists). Regenerating would silently replace "
            "an evaluated holdout — forbidden (untouched-holdout "
            "tuning exclusion; workflow policy). "
            "Write a NEW generation to a new --output path and freeze it "
            "separately."
        )
    print(
        f"notice: {out} exists but is an UNFROZEN draft (no FREEZE.json); "
        "it will be regenerated",
        file=sys.stderr,
    )


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repos-dir", default=str(DEFAULT_REPOS_DIR))
    parser.add_argument("--max-walk", type=int, default=400)
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="print the freeze hash of an existing manifest, select nothing",
    )
    args = parser.parse_args(argv)

    out = Path(args.output)
    if args.check_only:
        if not out.exists():
            print(f"no manifest at {out}", file=sys.stderr)
            return 1
        print(f"manifest sha256: {canonical_sha256(out)}")
        return 0

    # Untouched-holdout governance: refuse BEFORE any cloning/selection
    # when the target is frozen.
    refuse_frozen_overwrite(out)

    manifest = build_manifest(Path(args.repos_dir), args.max_walk)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", "utf-8")
    frozen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    freeze = {
        "freeze_policy": (
            "manifest frozen BEFORE first evaluation; tuning_exclusion holds: "
            "no extractor, ranking, gate, or threshold change may be authored "
            "from this split's scores; the dev/regression split "
            "(benchmarks/holdout) is the only tuning-eligible corpus"
        ),
        "frozen_at": frozen_at,
        "manifest_path": str(out.relative_to(_REPO)),
        "manifest_sha256": canonical_sha256(out),
        "selection": {
            "procedure": "scripts/bench_holdout_select.py (deterministic, "
            "oracle-only; no production engine consulted)",
            "roster_seeds": "205001-205010 (disjoint from dev corpus seeds)",
            "rule": "most recent non-merge commit touching 1-4 source .py "
            "files plus tests, non-empty top_level_delta, >=1 GT test",
        },
    }
    out.parent.joinpath("FREEZE.json").write_text(
        json.dumps(freeze, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    print(f"frozen: {out} sha256={freeze['manifest_sha256'][:16]}... at {frozen_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
