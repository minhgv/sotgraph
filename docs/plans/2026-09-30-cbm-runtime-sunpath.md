# CBM runtime dir sun_path overflow — fix cbm_env

## Context
`sotgraph reconcile` on watcher worktrees (`~/.cache/watcher/worktrees/<r>`)
prints `(fallback: cbm_index_failed:error)`. Root cause: `cbm_env()` sets
`CBM_RUNTIME_DIR=<root>/.sot/cbm/runtime`; the engine binds
`$CBM_RUNTIME_DIR/cbm-daemon-<uid>/cbm-<16hex>.sock`, a Unix `sun_path`
bounded at 104 bytes. Worktree socket paths reach 104–116 bytes → engine
prints `secure daemon endpoint could not be created`, exits → warm daemon
call and cold CLI spawn both report status=error → honest fallback to
tree-sitter. Verified: all 3 daemon.logs identical; local repo (96 B socket
path) and a short-path git worktree index fine.

Managed spawns (`providers/bootstrap.py:engine_runtime_env`) already solve
this with `/private/tmp/sotgraph-engine-<uid>` + explicit budget math.
`cbm_env` has no equivalent.

## Approach
- `cbm_env`: `CBM_RUNTIME_DIR` → per-repo hashed dir
  `<tmp-parent>/sotgraph-engine-<uid>/sot-cbm-<sha256(realpath)[:24]>`
  (reuses `_engine_runtime_parent()`; ~60 B of headroom vs 103 limit).
- `CBM_CACHE_DIR` unchanged (repo-local, holds store DB).
- Preflight socket bytes like `ManagedRuntimeProfile`; if the hashed dir
  cannot be created (OSError), fall back to repo-local `.sot/cbm/runtime`
  (pre-change behavior — engine may still fail, honest fallback persists).
- Stale `<root>/.sot/cbm/runtime` dirs are inert; no migration.

## Critical files
- `src/sot_graph/cbm.py` — `cbm_env` only file changed.
- `src/sot_graph/providers/bootstrap.py` — import `_engine_runtime_parent`
  (leading underscore; same-package internal reuse, acceptable).
- `tests/test_cbm_store.py` — add regression test on runtime dir length.
## Execution checklist
- [x] T-01 implement cbm_env change (AC-01/02/03)
- [x] T-02 regression test (AC-01/03)
- [x] T-03 run focused tests + real reconcile (AC-04)

## Evidence and handoff
- `cbm_env` now emits `CBM_RUNTIME_DIR=/private/tmp/sotgraph-engine-501/
  sot-cbm-<sha256(realpath)[:16]>` (0700), socket path 98 B < 104.
  `CBM_CACHE_DIR` unchanged (`<root>/.sot/cbm/cache`).
- Computed for all 3 failing watcher worktrees: 98 bytes each.
- `uv run sotgraph reconcile` on this repo: `[codebase-memory:full]` —
  engine path exercised end-to-end.
- `pytest tests/test_cbm_store.py`: 25 passed incl. 2 new regression tests
  (bounded dir + OSError fallback).
- Exposed latent flake: suite relied on the engine FAILING under long
  pytest tmp roots (builtin then owned the graph). Fixed via session-level
  `SOT_EXTRACTOR=builtin` pin in `tests/conftest.py` (module-scoped
  fixtures run before monkeypatch; hard assignment, not setdefault).
- Full suite `uv run pytest tests/`: 2612 passed, 5 skipped (526s).
- Reviewer pass: no high-severity findings; hardened conftest pin per
  review; post-repair run of touched files: 126 passed.

## Assumptions and contingencies
- POSIX-only bounded path; non-getuid platforms keep repo-local runtime
  (same pre-fix behavior, builtin fallback still honest).
- Stale `<root>/.sot/cbm/runtime` dirs are inert leftovers.
- AC-04: `sotgraph reconcile` on this repo still uses codebase-memory.
