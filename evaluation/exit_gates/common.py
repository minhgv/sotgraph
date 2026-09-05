"""Shared machinery for the SG-201/SG-202 exit-gate evaluators.

Contains the DECLARED independent category oracle, a parser over the
ACTUAL rendered repo-map text (not internal ranks), and a temp-index
builder that never touches the shared ``.sot`` database.
"""

from __future__ import annotations

import fnmatch
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Declared category oracle (SG-201 contamination gate)
# ---------------------------------------------------------------------------
# This oracle is deliberately INDEPENDENT code from
# ``sot_graph.repo_map.classify_path``: it is a declared SUPERSET of the
# production rules (supersets can only over-flag fixture/vendor, never
# under-flag, so contamination can only be OVER-estimated, which is the
# conservative direction for a "<2%" gate). Every divergence between this
# oracle and the production classifier is published in the report.

ORACLE_SEGMENT_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    # fixture first (same precedence intent as production: a dir named
    # "fixtures" under tests/ is a fixture, not a test)
    ("fixture", ("fixtures", "fixture", "testdata", "test_data", "testdata_",
                 "evaluation", "evals", "__snapshots__", "__fixtures__",
                 "golden", "goldens", "samples")),
    ("test", ("tests", "test", "spec", "specs", "__tests__")),
    ("vendor", ("vendor", "_vendor", "vendored", "third_party", "thirdparty",
                "external", "node_modules", "bower_components")),
    ("generated", ("dist", "build", "out", "generated", "_generated",
                   "coverage", "__pycache__", ".tox", ".venv")),
    ("docs", ("docs", "doc", "documentation")),
    ("tooling", ("scripts", "tools", "tooling", "benchmark", "benchmarks",
                 "benches", "ci", ".github", ".circleci", ".gitlab")),
)
ORACLE_FILENAME_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("test", ("conftest.*", "test_*", "*_test.*", "*_test.py")),
    ("vendor", ("*.min.js", "*.min.css", "*.bundle.js", "*.bundle.min.js")),
    ("generated", ("*_pb2.py", "*_pb2_grpc.py", "*.pyc", "*.min.js.map")),
)

CONTAMINATION_CATEGORIES = ("fixture", "vendor")


def oracle_category(rel_path: str) -> str:
    """Classify a root-relative POSIX path with the DECLARED oracle rules.

    Superset of the production classifier: additionally treats any path
    segment that *starts or ends with* "vendor"/"fixture"/"test_" prefixes
    (e.g. ``vendor_assets/``, ``fixtures_dev/``) as vendor/fixture. Any
    such extra flagging can only OVER-count contamination — the
    conservative direction — and every such divergence from the
    production classifier is reported separately.
    """
    norm = (rel_path or "").replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    segments = re.split(r"/+", norm)
    for category, names in ORACLE_SEGMENT_RULES:
        if any(seg in names for seg in segments):
            return category
    # Declared superset heuristics (only ever ADD contamination flags).
    for seg in segments[:-1]:
        low = seg.lower()
        if low.startswith("vendor") or low.endswith("vendor") or \
                low.startswith("fixture") or low.endswith("fixture") or \
                low.startswith("testdata") or low.endswith("testdata"):
            return "vendor" if "vendor" in low else "fixture"
    base = segments[-1]
    for category, patterns in ORACLE_FILENAME_RULES:
        if any(fnmatch.fnmatchcase(base, pat) for pat in patterns):
            return category
    return "production"


def oracle_contaminated(rel_path: str) -> bool:
    return oracle_category(rel_path) in CONTAMINATION_CATEGORIES


# ---------------------------------------------------------------------------
# Parser over the ACTUAL rendered map text (SG-201)
# ---------------------------------------------------------------------------

@dataclass
class RenderedMap:
    """Entries parsed from the rendered text a consumer actually sees."""

    files: List[str] = field(default_factory=list)          # order of appearance
    file_symbols: Dict[str, List[str]] = field(default_factory=dict)
    raw: str = ""

    @property
    def symbol_count(self) -> int:
        return sum(len(v) for v in self.file_symbols.values())


_PATH_LINE = re.compile(r"^(\S.*?):$")
_STUB_LINE = re.compile(r"^  (\S.*)$")


def parse_rendered_map(text: str) -> RenderedMap:
    """Parse the rendered repo-map text (``path:`` groups + stub lines).

    This parses the ACTUAL budgeted output — truncation and formatting
    semantics included by construction. Raises ``ValueError`` on any
    line that fits neither grammar (fail-closed, never silently skip).
    """
    rendered = RenderedMap(raw=text)
    current: Optional[str] = None
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith("  "):
            m = _STUB_LINE.match(line)
            if m is None or current is None:
                raise ValueError(f"rendered-map parse error at line {lineno}: {line!r}")
            rendered.file_symbols[current].append(m.group(1).strip())
            continue
        if line.startswith("("):
            continue  # scope/absence footer lines are not map entries
        m = _PATH_LINE.match(line)
        if m is None:
            raise ValueError(f"rendered-map parse error at line {lineno}: {line!r}")
        matched: str = m.group(1)      # group(1) of a matched str pattern is str
        current = matched
        if current not in rendered.file_symbols:
            rendered.files.append(current)
            rendered.file_symbols[current] = []
    return rendered


# ---------------------------------------------------------------------------
# Temp index builder (never touches the shared .sot DB)
# ---------------------------------------------------------------------------

def build_temp_index(repo_root: str, workers: int = 4) -> Tuple[Any, str]:
    """Index ``repo_root`` into a throwaway DB.

    Returns ``(Database, tmp_dir)`` — callers MUST finish with
    :func:`close_temp_index(db, tmp_dir)` so the temp directory does not
    leak (db.close() alone is not enough).
    """
    from sot_graph.db import Database
    from sot_graph.reconciler import Reconciler

    tmp = tempfile.mkdtemp(prefix="sot-exit-gates-")
    db = Database(os.path.join(tmp, ".sot", "exit-gates.db"))
    try:
        Reconciler(db, repo_root).reconcile(workers=workers)
    except Exception:
        close_temp_index(db, tmp)
        raise
    return db, tmp


def normalize_rel(path: str, root: str) -> str:
    """Best-effort root-relative POSIX form of an engine-reported path."""
    p = (path or "").replace("\\", "/")
    root_posix = root.replace("\\", "/").rstrip("/")
    if p.startswith(root_posix + "/"):
        p = p[len(root_posix) + 1:]
    while p.startswith("./"):
        p = p[2:]
    return p


def gate_verdict(passed: Optional[bool], min_denominator: int,
                 denominator: int, metric: Optional[float], floor: float,
                 gate_id: str, upper_bound: bool = False) -> Dict[str, Any]:
    """Fail-closed gate verdict.

    The caller's ``passed`` flag is authoritative and never overridden:
    - ``passed=False``  → verdict FAIL (e.g. oracle validation failed),
      regardless of metric/denominator;
    - ``passed=None``   → NOT_EVALUABLE (caller cannot decide);
    - denominator < min → INSUFFICIENT_SAMPLING (never a pass);
    - only ``passed=True`` AND denominator >= min AND the metric clears
      the threshold yields PASS (``metric >= floor`` for lower-bound
      gates, ``metric < floor`` for ``upper_bound=True`` gates such as
      contamination "<2%").
    """
    base = {"gate": gate_id, "denominator": denominator,
            "min_denominator": min_denominator,
            "metric": metric, "floor": floor,
            "direction": "metric<floor" if upper_bound else "metric>=floor"}
    if passed is False:
        return {**base, "verdict": "FAIL", "passed": False}
    if denominator < min_denominator:
        return {**base, "verdict": "INSUFFICIENT_SAMPLING", "passed": None}
    if passed is None:
        return {**base, "verdict": "NOT_EVALUABLE", "passed": None}
    ok = (metric is not None
          and (metric < floor if upper_bound else metric >= floor))
    return {**base, "verdict": "PASS" if ok else "FAIL", "passed": ok}


def close_temp_index(db: Any, tmp_dir: Optional[str]) -> None:
    """Close the temp index DB and remove its whole temp directory.

    ``tmp_dir`` is accepted as Optional because callers track it as
    ``Optional[str]`` (None only before build_temp_index succeeds); a
    None means there is nothing to clean up.
    """
    import shutil

    try:
        db.close()
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def repo_provenance(root: str, max_content_files: int = 200,
                    exclude_prefixes: Tuple[str, ...] = ("benchmarks/exit_gates/",),
                    ) -> Dict[str, Any]:
    """Bind a report to the exact repo snapshot it measured.

    - ``git_head``: HEAD commit at run time.
    - ``worktree_digest``: sha256 over HEAD + every dirty/untracked file's
      repo-relative path + content hash. Porcelain v1 ``-z`` records are
      parsed positionally (``status = rec[:2]``, ``path = rec[3:]``) so
      unstaged entries like ``" M foo"`` resolve to the real path.
      ``--untracked-files=all`` enumerates files inside new directories.
      Bounded at ``max_content_files``; beyond that ``digest_truncated``
      is True and the digest MUST NOT be treated as content-exact.
      ``exclude_prefixes`` keeps generated report artifacts out of the
      digest (no self-reference).
    """
    import hashlib
    import subprocess

    def git(*args: str) -> str:
        try:
            out = subprocess.run(["git", "-C", root, *args],
                                 capture_output=True, text=True, timeout=15)
            return out.stdout if out.returncode == 0 else ""
        except Exception:
            return ""

    head = git("rev-parse", "HEAD").strip() or "unknown"
    raw = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    records = [r for r in raw.split("\0") if r.strip()]
    hasher = hashlib.sha256()
    hasher.update(f"HEAD={head}\n".encode())
    content_files = 0
    truncated = False
    skip_next = False
    hashed_paths = []
    for rec in records:
        if skip_next:              # orig-path half of a rename record
            skip_next = False
            continue
        if len(rec) < 4:
            truncated = True
            continue
        status, path = rec[:2], rec[3:]
        if "R" in status:          # rename: next token is the orig path
            skip_next = True
        if any(path.startswith(p) for p in exclude_prefixes):
            continue
        abs_path = Path(root) / path
        try:
            blob = abs_path.read_bytes()
        except OSError:
            truncated = True
            hasher.update(f"unreadable {status} {path}\n".encode())
            continue
        if content_files >= max_content_files:
            truncated = True
            hasher.update(f"overflow {path}\n".encode())
            continue
        content_files += 1
        hashed_paths.append(path)
        hasher.update(f"{status} {path} "
                      f"{hashlib.sha256(blob).hexdigest()}\n".encode())
    return {
        "git_head": head,
        "worktree_digest": hasher.hexdigest()[:16],
        "dirty_entries": len(records),
        "content_files_hashed": content_files,
        "digest_truncated": truncated,
        "digest_basis": "HEAD + porcelain-v1 -z status + per-file content "
                        "sha256 (untracked-files=all; generated reports "
                        "under benchmarks/exit_gates/ excluded)",
    }


def write_report(report_dir: str, name: str, report: Dict[str, Any],
                 markdown: str) -> Dict[str, str]:
    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)
    import json

    json_path = out / f"{name}.json"
    md_path = out / f"{name}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    md_path.write_text(markdown)
    return {"json": str(json_path), "markdown": str(md_path)}


def format_pct(part: int, whole: int) -> str:
    return "n/a" if whole == 0 else f"{(part / whole) * 100.0:.2f}%"


def seq_summary(items: Sequence[str], limit: int = 10) -> List[str]:
    listed = sorted(items)[:limit]
    if len(items) > limit:
        listed.append(f"... (+{len(items) - limit} more)")
    return listed
