"""Git hook provisioning: event-driven reconcile for the no-daemon model.

`sotgraph setup --hooks` appends a guarded reconcile invocation to post-merge
and post-checkout so the graph syncs exactly when branches change — no
polling, no resident process. Idempotent: a hook carrying our marker is
never duplicated.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

HOOK_MARKER = "# sotgraph: keep the knowledge graph in sync"
LEGACY_HOOK_MARKERS = ("# sot-graph: keep the knowledge graph in sync",)
HOOK_NAMES = ("post-merge", "post-checkout")


def _hooks_dir(root: Path) -> Path | None:
    git_path = root / ".git"
    if git_path.is_dir():
        return git_path / "hooks"
    if git_path.is_file():
        # Worktree: .git holds `gitdir: /path/to/main/.git/worktrees/name`.
        text = git_path.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir:"):
            return Path(text.split(":", 1)[1].strip()) / "hooks"
    return None


def install_git_hooks(root: Path) -> List[Path]:
    """Append the reconcile hook block; returns hook paths (idempotent)."""
    hooks_dir = _hooks_dir(root)
    if hooks_dir is None:
        return []

    src_dir = (root / "src").resolve()
    block = "\n".join([
        HOOK_MARKER,
        f'PYTHONPATH="{src_dir}" "{sys.executable}" -m sot_graph.cli reconcile >/dev/null 2>&1 || true',
        "",
    ])

    installed: List[Path] = []
    for name in HOOK_NAMES:
        hook = hooks_dir / name
        existing = ""
        if hook.exists():
            existing = hook.read_text(encoding="utf-8", errors="replace")
            if HOOK_MARKER in existing:
                installed.append(hook)
                continue
            # Migrate in place: a legacy-marked block is re-labelled, never
            # duplicated. Non-marker content (user lines, old command lines)
            # is preserved byte-for-byte.
            migrated = existing
            for legacy in LEGACY_HOOK_MARKERS:
                if legacy in migrated:
                    migrated = migrated.replace(legacy, HOOK_MARKER)
            if migrated != existing:
                hook.write_text(migrated, encoding="utf-8")
                hook.chmod(0o755)
                installed.append(hook)
                continue
        with open(hook, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(block)
        hook.chmod(0o755)
        installed.append(hook)
    return installed


GATE_HOOK_MARKER = "# sotgraph: pre-commit safe-commit gate"
GATE_HOOK_NAME = "pre-commit"


def install_precommit_gate(root: Path, *, timeout_s: int = 30) -> List[Path]:
    """Append a guarded pre-commit gate block; returns hook path (idempotent).

    The hook runs the staged-diff receipt gate:

      sotgraph diff-impact --staged --gate-strict --format json

    Exit semantics:
      * gate verdict ``block`` → exit 2 → commit refused;
      * ``--gate-strict`` assurance/timeout: by default a TIMEOUT is
        advisory (prints a warning, commit proceeds — a slow gate must
        never wedge the commit loop); setting env
        ``SOTGRAPH_GATE_STRICT_TIMEOUT=1`` fails closed instead.
    """
    hooks_dir = _hooks_dir(root)
    if hooks_dir is None:
        return []

    src_dir = (root / "src").resolve()
    # No external `timeout` binary (absent on macOS) — the gate carries
    # its own SIGALRM timeout; on timeout the CLI itself decides
    # advisory-vs-strict via SOTGRAPH_GATE_STRICT_TIMEOUT.
    block = "\n".join([
        GATE_HOOK_MARKER,
        f'PYTHONPATH="{src_dir}" "{sys.executable}" -m sot_graph.cli '
        'diff-impact --staged --gate-strict --format json '
        f'--gate-timeout "${{SOTGRAPH_GATE_TIMEOUT:-{int(timeout_s)}}}" '
        '>/dev/null 2>&1',
        '_sot_rc=$?',
        'if [ "$_sot_rc" -ne 0 ]; then',
        '  echo "sotgraph gate: unsafe to commit — rerun '
        '`sotgraph diff-impact --staged` for details" >&2; '
        'exit "$_sot_rc";',
        'fi',
        "",
    ])

    hook = hooks_dir / GATE_HOOK_NAME
    installed: List[Path] = []
    existing = hook.read_text(encoding="utf-8", errors="replace") if hook.exists() else ""
    if GATE_HOOK_MARKER not in existing:
        with open(hook, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(block)
        hook.chmod(0o755)
        installed.append(hook)
    return installed


__all__ = [
    "install_git_hooks", "install_precommit_gate",
    "HOOK_MARKER", "LEGACY_HOOK_MARKERS", "HOOK_NAMES",
    "GATE_HOOK_MARKER", "GATE_HOOK_NAME",
]
