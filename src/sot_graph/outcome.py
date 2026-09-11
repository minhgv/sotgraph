"""sot_graph.outcome — commit outcome labeling for the 3-gate workflow (W0).

Post-hoc ground-truth layer: given a commit history window, label each
commit's *outcome* — did the change hold (``clean``), get reverted
(``reverted``), need a follow-up fix (``fixup``), or get re-touched as a
hotspot (``retouched``) — so per-commit risk classification can be
calibrated against what actually happened afterwards.

Design constraints (kept honest, matching CAPABILITY_MATRIX philosophy):

- **Code-file + hunk linkage.** Linking commit A to a later commit B
  uses shared *code files* (docs/meta/lockfile paths excluded — a
  release-notes edit cannot "fix" code), not symbols: a per-commit
  symbol index does not exist (the graph reflects current worktree
  state). A fixup candidate needs ≥2 shared code files, or ≥1 shared
  file with file-Jaccard ≥ 0.34 — and, when a ``verify_fixup`` callback
  is supplied, the later commit's diff hunks must overlap the original's
  hunks on ≥1 shared file (same file, different region = churn, not
  repair; measured limiter of file-only linkage).
- **Asymmetric windows.** Revert detection scans ALL later commits — a
  revert is evidence regardless of delay. Fixup/retouch linkage is
  bounded by ``window_days`` — a same-file fix three months later is not
  evidence the original change was faulty.
- **Observation honesty.** Commits newer than ``window_days`` before the
  newest observed commit carry ``window_complete=False``; aggregates
  report the complete-window subset separately so partial observation
  cannot masquerade as a clean outcome.
- **Fail-closed vocabulary.** Commits with no file linkage surface
  (merge commits, empty diffs) can only ever be ``clean``-by-absence;
  the evidence list always says which rule fired.

Pure layer (``label_outcomes``, ``classify_subject``) is git-free and
deterministic for unit tests; the IO layer (``collect_commit_records``)
wraps :class:`CommitHistoryEngine` and fetches revert bodies lazily —
``git show`` runs only for commits whose subject already looks like a
revert, which is rare in practice.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

__all__ = [
    "OUTCOMES",
    "ADVERSE_OUTCOMES",
    "CommitRecord",
    "CommitOutcome",
    "FIX_SUBJECT_RE",
    "REVERT_SUBJECT_RE",
    "classify_subject",
    "parse_git_timestamp",
    "collect_commit_records",
    "label_outcomes",
    "aggregate_outcomes",
    "label_commit_outcomes",
]

OUTCOMES: Tuple[str, ...] = ("clean", "fixup", "reverted", "retouched")
#: Outcomes that count AGAINST the originating commit ("the change did
#: not hold"). ``retouched`` is a neutral hotspot signal, not adverse.
ADVERSE_OUTCOMES: Tuple[str, ...] = ("reverted", "fixup")

# Conventional-commit fix families + git autosquash "fixup! <subject>".
# `perf:` is deliberately NOT here — an optimization pass is not evidence
# the earlier change was faulty (it still counts toward `retouched`).
FIX_SUBJECT_RE = re.compile(
    r"^(?:fix|fixup|hotfix|bugfix|patch)(?:\([^)]*\))?!?:|^fixup!",
    re.IGNORECASE,
)
# A commit that IS a revert: `revert: ...`, `revert(scope): ...`, or
# git's default `Revert "<original subject>"`.
REVERT_SUBJECT_RE = re.compile(
    r"^revert(?:\([^)]*\))?!?:|^revert\s+\"",
    re.IGNORECASE,
)
# Extracts the reverted original subject from git's default message.
REVERT_QUOTED_RE = re.compile(r'^Revert\s+"(?P<subject>.+)"\s*$', re.IGNORECASE)
# Present in the BODY of a `git revert` commit.
REVERTS_SHA_RE = re.compile(r"This reverts commit (?P<sha>[0-9a-fA-F]{7,40})\b")

_GIT_DATE_FMT = "%Y-%m-%d %H:%M:%S %z"

# Paths that cannot carry a code fault for linkage purposes: docs, repo
# meta, changelogs. Conservative — anything not listed still counts.
_META_PATH_RE = re.compile(
    r"(^|/)(docs?|\.github|\.devin|\.claude|\.agents|\.windsurf)/"
    r"|\.(?:md|rst|txt|adoc)$"
    r"|(^|/)(CHANGELOG|CHANGES|HISTORY|LICENSE|NOTICE|CODEOWNERS|"
    r"CONTRIBUTING|AUTHORS|RELEASE_NOTES)[^/]*$"
    # Lockfiles are dependency churn (every version bump links them);
    # manifests (pyproject.toml, package.json, go.mod) stay — a broken
    # manifest is a real fault source.
    r"|(^|/)(uv\.lock|package-lock\.json|poetry\.lock|Pipfile\.lock|"
    r"Cargo\.lock|go\.sum|yarn\.lock|pnpm-lock\.yaml|composer\.lock|"
    r"Gemfile\.lock)$",
    re.IGNORECASE,
)


def code_files(files: Sequence[str]) -> List[str]:
    """Changed files that can carry/link a code fault."""
    return [f for f in files if not _META_PATH_RE.search(f)]


def parse_git_timestamp(date_text: str) -> int:
    """Parse ``git log --date=iso`` output ("2026-09-10 21:47:39 +0700")
    into epoch seconds. Naive datetimes are assumed UTC; unparseable
    input returns 0 (sorts oldest — never silently "newest")."""
    text = (date_text or "").strip()
    if not text:
        return 0
    try:
        return int(datetime.strptime(text, _GIT_DATE_FMT).timestamp())
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return 0


def classify_subject(subject: str) -> Set[str]:
    """Message-level classification of ONE commit subject.

    Returns a subset of {"fix", "revert"}. A commit can be both only in
    the pathological case of `fix:` on a revert — callers should treat
    revert as dominant (see ``label_outcomes``).
    """
    tags: Set[str] = set()
    s = (subject or "").strip()
    if FIX_SUBJECT_RE.search(s):
        tags.add("fix")
    if REVERT_SUBJECT_RE.search(s) or REVERT_QUOTED_RE.match(s):
        tags.add("revert")
    return tags


@dataclass
class CommitRecord:
    """One commit as labeling input — fields mirror CommitSummary plus a
    parsed epoch timestamp and the (lazily fetched) body."""
    sha: str
    short_sha: str
    author: str
    date: str
    timestamp: int
    subject: str
    body: str = ""
    files: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    risk_level: str = "LOW"
    risk_reasons: List[str] = field(default_factory=list)
    touched_symbols: List[str] = field(default_factory=list)

    @property
    def tags(self) -> Set[str]:
        return classify_subject(self.subject)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tags"] = sorted(self.tags)
        return d


@dataclass
class CommitOutcome:
    """Labeled outcome for one commit."""
    sha: str
    short_sha: str
    subject: str
    date: str
    risk_level: str
    outcome: str  # clean | fixup | reverted | retouched
    follow_up_shas: List[str] = field(default_factory=list)
    reverted_by: List[str] = field(default_factory=list)
    retouch_count: int = 0
    window_days: int = 14
    window_complete: bool = True
    files: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# IO layer — git collection
# ---------------------------------------------------------------------------

def _git_show_body(repo_path: str, sha: str) -> str:
    """Fetch a commit body; only invoked for revert-looking subjects."""
    try:
        proc = subprocess.run(
            ["git", "show", "-s", "--format=%B", sha],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        return proc.stdout if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def collect_commit_records(
    repo_path: str = ".",
    limit: int = 400,
    since: Optional[str] = None,
    author: Optional[str] = None,
    db: Optional[Any] = None,
) -> List[CommitRecord]:
    """Collect commit history as labeler input.

    Reuses ``CommitHistoryEngine`` so risk_level/risk_reasons are byte-
    identical to ``sotgraph log`` output. ``db`` (optional) enables the
    same touched_symbols best-effort mapping; labeling itself only needs
    files. Revert bodies are fetched lazily per candidate commit.
    """
    from sot_graph.diff_impact import CommitHistoryEngine

    engine = CommitHistoryEngine(repo_path)
    result = engine.analyze_history(
        count=limit, author=author, since=since, db=db, with_impact=True
    )
    records: List[CommitRecord] = []
    for c in result.commits:
        tags = classify_subject(c.message)
        body = ""
        if "revert" in tags:
            body = _git_show_body(repo_path, c.commit_hash)
        records.append(
            CommitRecord(
                sha=c.commit_hash,
                short_sha=c.short_hash,
                author=c.author,
                date=c.date,
                timestamp=parse_git_timestamp(c.date),
                subject=c.message,
                body=body,
                files=list(c.files_changed),
                insertions=c.insertions,
                deletions=c.deletions,
                risk_level=c.risk_level,
                risk_reasons=list(c.risk_reasons),
                touched_symbols=list(c.touched_symbols),
            )
        )
    return records


# ---------------------------------------------------------------------------
# Pure layer — deterministic labeling
# ---------------------------------------------------------------------------

def _norm_subject(subject: str) -> str:
    return re.sub(r"\s+", " ", (subject or "").strip())


def _revert_targets(rec: CommitRecord) -> Tuple[Set[str], Set[str]]:
    """What a revert commit claims to undo: (sha-prefixes, subjects)."""
    shas: Set[str] = set()
    subjects: Set[str] = set()
    if "revert" not in rec.tags:
        return shas, subjects
    for m in REVERTS_SHA_RE.finditer(rec.body or ""):
        shas.add(m.group("sha").lower())
    m = REVERT_QUOTED_RE.match(_norm_subject(rec.subject))
    if m:
        subjects.add(_norm_subject(m.group("subject")))
    # `revert(scope): <subject>` style — best-effort subject capture.
    elif REVERT_SUBJECT_RE.match(rec.subject):
        tail = re.sub(r"^revert(?:\([^)]*\))?!?:\s*", "", rec.subject, flags=re.I)
        tail = tail.strip().strip('"')
        if tail:
            subjects.add(_norm_subject(tail))
    return shas, subjects


def _shared_files(a: CommitRecord, b: CommitRecord) -> List[str]:
    """Sorted CODE-file intersection — the deterministic linkage key."""
    return sorted(set(code_files(a.files)) & set(code_files(b.files)))


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    union = set(a) | set(b)
    return len(set(a) & set(b)) / len(union) if union else 0.0


def _is_fixup_link(cur: CommitRecord, later: CommitRecord,
                   shared: List[str]) -> bool:
    """A later fix-classed commit is evidence the original needed repair
    only when the file overlap is strong: ≥2 shared code files, or ≥1
    shared code file with Jaccard ≥ 0.34 (a lone shared god-file like
    cli.py in a 20-file commit is churn, not evidence)."""
    if len(shared) >= 2:
        return True
    return bool(shared) and _jaccard(code_files(cur.files),
                                    code_files(later.files)) >= 0.34


def make_hunk_verifier(
    repo_path: str,
    gap_lines: int = 10,
) -> Callable[[CommitRecord, CommitRecord, List[str]], bool]:
    """Build a ``verify_fixup`` callback that checks diff-hunk overlap.

    For each candidate (cur, later) pair sharing code files, the later
    commit's new-side hunk intervals must intersect cur's intervals
    (±``gap_lines``) on at least one shared file. Same file, different
    region => no link. Intervals are parsed per commit+file with the
    same ``GitDeltaExtractor.parse_unified_diff`` the impact engine uses;
    results are memoized per (sha, file). Git failures degrade to
    file-level evidence for that pair (fail-open on the *verifier* —
    absence of hunk data is not proof of unrelatedness).
    """
    from sot_graph.diff_impact import GitDeltaExtractor

    extractor = GitDeltaExtractor(repo_path)
    cache: Dict[Tuple[str, str], List[Tuple[int, int]]] = {}

    def intervals(sha: str, path: str) -> List[Tuple[int, int]]:
        key = (sha, path)
        if key in cache:
            return cache[key]
        code, out, _ = extractor.run_git(
            ["show", "-U0", "--format=", "--no-ext-diff", "--no-textconv",
             sha, "--", path]
        )
        ivs: List[Tuple[int, int]] = []
        if code == 0 and out.strip():
            _, hunks = extractor.parse_unified_diff(out)
            ivs = [
                (h.new_start, h.new_start + max(h.new_count, 1))
                for h in hunks if h.file_path == path
            ]
        cache[key] = ivs
        return ivs

    def verify(cur: CommitRecord, later: CommitRecord,
               shared: List[str]) -> bool:
        saw_hunks = False
        for f in shared:
            a_ivs = intervals(cur.sha, f)
            b_ivs = intervals(later.sha, f)
            if not a_ivs or not b_ivs:
                continue
            saw_hunks = True
            for s1, e1 in a_ivs:
                for s2, e2 in b_ivs:
                    if s2 <= e1 + gap_lines and s1 <= e2 + gap_lines:
                        return True
        # No comparable hunks anywhere (rename/delete/unparseable) — do
        # not let missing diff data veto file-level evidence.
        return not saw_hunks

    return verify


def _revert_hit(target: CommitRecord, shas: Set[str], subjects: Set[str]) -> bool:
    if not shas and not subjects:
        return False
    t_sha = target.sha.lower()
    if any(t_sha.startswith(p) or p.startswith(t_sha) for p in shas):
        return True
    t_subj = _norm_subject(target.subject)
    return any(t_subj == s or t_subj.startswith(s) for s in subjects)


def label_outcomes(
    records: Sequence[CommitRecord],
    window_days: int = 14,
    retouch_min: int = 2,
    verify_fixup: Optional[
        Callable[[CommitRecord, CommitRecord, List[str]], bool]
    ] = None,
) -> List[CommitOutcome]:
    """Label each commit's outcome. Deterministic; order-independent.

    Rules (priority order — first match wins):
      1. ``reverted`` — a later commit reverts it (sha or subject match),
         scanned over ALL later history (a revert is evidence at any delay).
      2. ``fixup`` — ≥1 later commit within ``window_days`` is fix-classed
         AND links strongly (≥2 shared code files, or 1 shared with
         file-Jaccard ≥ 0.34 — see ``_is_fixup_link``) AND, when
         ``verify_fixup`` is provided, survives the hunk-overlap check.
      3. ``retouched`` — ≥ ``retouch_min`` later non-fix/non-revert commits
         within the window share ≥1 code file (hotspot churn signal).
      4. ``clean`` — none of the above (absence claim is bounded by
         ``window_complete`` + file-linkage evidence).
    """
    recs = sorted(records, key=lambda r: (r.timestamp, r.sha))
    newest_ts = recs[-1].timestamp if recs else 0
    window_s = int(window_days) * 86400
    targets = {r.sha: _revert_targets(r) for r in recs}

    outcomes: List[CommitOutcome] = []
    for i, cur in enumerate(recs):
        later = recs[i + 1:]
        in_window = [d for d in later if 0 <= d.timestamp - cur.timestamp <= window_s]
        window_complete = (newest_ts - cur.timestamp) >= window_s
        evidence: List[str] = []

        reverted_by = [
            d.sha for d in later
            if _revert_hit(cur, *targets[d.sha])
        ]
        fixups: List[Tuple[CommitRecord, List[str]]] = []
        retouches: List[Tuple[CommitRecord, List[str]]] = []
        for d in in_window:
            shared = _shared_files(cur, d)
            if not shared:
                continue
            if "revert" in d.tags:
                continue  # already handled by the unbounded revert scan
            if ("fix" in d.tags and _is_fixup_link(cur, d, shared)
                    and (verify_fixup is None
                         or verify_fixup(cur, d, shared))):
                fixups.append((d, shared))
            elif "fix" not in d.tags:
                retouches.append((d, shared))

        if reverted_by:
            outcome = "reverted"
            evidence.append(
                f"reverted by {len(reverted_by)} later commit(s): "
                + ", ".join(s[:10] for s in reverted_by[:5])
            )
        elif fixups:
            outcome = "fixup"
            evidence.append(
                f"follow-up fix {fixups[0][0].short_sha} shares file(s): "
                + ", ".join(fixups[0][1][:3])
            )
        elif len(retouches) >= retouch_min:
            outcome = "retouched"
            evidence.append(
                f"{len(retouches)} later commit(s) re-touched shared file(s) "
                f"within {window_days}d"
            )
        else:
            outcome = "clean"
            if not cur.files:
                evidence.append("no changed files — linkage not observable")
            elif not window_complete:
                evidence.append(
                    f"observation window incomplete ({window_days}d not elapsed in range)"
                )
            else:
                evidence.append("no later overlapping commit within window")

        outcomes.append(
            CommitOutcome(
                sha=cur.sha,
                short_sha=cur.short_sha,
                subject=cur.subject,
                date=cur.date,
                risk_level=cur.risk_level,
                outcome=outcome,
                follow_up_shas=[d.sha for d, _ in fixups],
                reverted_by=reverted_by,
                retouch_count=len(retouches),
                window_days=window_days,
                window_complete=window_complete,
                files=list(cur.files),
                evidence=evidence,
            )
        )
    # Preserve caller-observable order: newest-first like `git log`.
    outcomes.reverse()
    return outcomes


def aggregate_outcomes(outcomes: Sequence[CommitOutcome]) -> Dict[str, Any]:
    """Cross-tab risk_level x outcome with adverse rates.

    Reports the complete-window subset separately — commits whose
    14d observation window has not fully elapsed cannot be declared
    clean by absence and are excluded from the primary rates.
    """
    levels = ("LOW", "MEDIUM", "HIGH")
    per_level: Dict[str, Dict[str, Any]] = {}
    for subset_name, subset in (
        ("all", list(outcomes)),
        ("window_complete", [o for o in outcomes if o.window_complete]),
    ):
        table: Dict[str, Dict[str, Any]] = {}
        for lvl in levels:
            rows = [o for o in subset if o.risk_level == lvl]
            counts = {k: 0 for k in OUTCOMES}
            for o in rows:
                counts[o.outcome] = counts.get(o.outcome, 0) + 1
            adverse = sum(counts[k] for k in ADVERSE_OUTCOMES)
            table[lvl] = {
                "n": len(rows),
                "outcomes": counts,
                "adverse": adverse,
                "adverse_rate": round(adverse / len(rows), 4) if rows else None,
                "retouch_rate": (
                    round(counts["retouched"] / len(rows), 4) if rows else None
                ),
            }
        per_level[subset_name] = table

    wc = per_level["window_complete"]
    rates = [wc[lvl]["adverse_rate"] for lvl in levels]
    observed = [r for r in rates if r is not None]
    monotonic = all(
        (rates[i] is None or rates[j] is None) or rates[i] <= rates[j]
        for i in range(len(levels))
        for j in range(i + 1, len(levels))
    )
    return {
        "total": len(outcomes),
        "window_complete_n": sum(1 for o in outcomes if o.window_complete),
        "outcome_breakdown": {
            k: sum(1 for o in outcomes if o.outcome == k) for k in OUTCOMES
        },
        "per_risk": per_level,
        "monotonic_adverse": monotonic if len(observed) >= 2 else None,
        "adverse_definition": list(ADVERSE_OUTCOMES),
    }


def label_commit_outcomes(
    repo_path: str = ".",
    limit: int = 400,
    since: Optional[str] = None,
    window_days: int = 14,
    retouch_min: int = 2,
    db: Optional[Any] = None,
    verify_hunks: bool = True,
) -> Dict[str, Any]:
    """End-to-end: collect → label → aggregate. Presentation-free.

    ``verify_hunks`` installs the diff-hunk overlap verifier (the
    precision-critical step — file-level linkage alone cannot tell
    same-file-different-region churn from an actual repair).
    """
    records = collect_commit_records(
        repo_path, limit=limit, since=since, db=db
    )
    verifier = make_hunk_verifier(repo_path) if verify_hunks else None
    outcomes = label_outcomes(
        records, window_days=window_days, retouch_min=retouch_min,
        verify_fixup=verifier,
    )
    return {
        "repo_path": repo_path,
        "params": {"window_days": window_days, "retouch_min": retouch_min,
                   "limit": limit, "since": since,
                   "linkage": "code-files-hunks-v4"},
        "records": [r.to_dict() for r in records],
        "outcomes": [o.to_dict() for o in outcomes],
        "aggregate": aggregate_outcomes(outcomes),
    }


def outcomes_from_hand_labels(
    outcomes: Sequence[CommitOutcome],
    hand_labels: Dict[str, str],
) -> Dict[str, Any]:
    """Agreement between labeler output and hand labels.

    ``hand_labels`` maps sha-prefix or full sha → expected outcome.
    Reports per-class precision/recall over the labeled sample.
    """
    by_sha = {o.sha: o for o in outcomes}
    by_short = {o.short_sha: o for o in outcomes}
    rows: List[Dict[str, Any]] = []
    for key, expected in hand_labels.items():
        o = by_sha.get(key) or by_short.get(key)
        if o is None:
            rows.append({"sha": key, "expected": expected, "actual": None,
                         "match": False, "error": "not_in_range"})
            continue
        rows.append({"sha": o.short_sha, "expected": expected,
                     "actual": o.outcome, "match": o.outcome == expected})

    classes = sorted(set(hand_labels.values()) | set(OUTCOMES))
    per_class: Dict[str, Dict[str, Any]] = {}
    for cls in classes:
        tp = sum(1 for r in rows if r["expected"] == cls and r["actual"] == cls)
        fn = sum(1 for r in rows if r["expected"] == cls and r["actual"] != cls)
        fp = sum(1 for r in rows if r["expected"] != cls and r["actual"] == cls)
        per_class[cls] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
        }
    matched = [r for r in rows if r.get("error") is None]
    return {
        "sample": len(rows),
        "matched": sum(1 for r in matched if r["match"]),
        "accuracy": (
            round(sum(1 for r in matched if r["match"]) / len(matched), 4)
            if matched else None
        ),
        "per_class": per_class,
        "confusions": [
            r for r in matched if not r["match"]
        ],
    }
