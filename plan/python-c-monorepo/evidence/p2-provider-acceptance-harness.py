#!/usr/bin/env python3
"""P2 OUTER provider binding acceptance — managed-only dispatch, narrow.

Complements p2-managed-acceptance-harness.py (executor-only; it does NOT
instantiate the outer provider). THIS harness instantiates, over a real
scratch git repo + real SOT Database inside one fresh /private/tmp root:
    ManagedRuntimeProfile(root, repo, artifact_digest=PINNED)
    ManagedNativeRuntime(profile, repo, (binary,), exact_context)
    CodebaseMemoryProvider(command=(binary,), db=..., exact_context=...,
                           managed_runtime=runtime)
then runs explicit provider.index() -> provider.search_symbols() and checks
(EXPLICIT fatal checks, never bare asserts, so `python -O` cannot skip them):
UI-off preseed + 7-key env BEFORE any native; auto_watch=false proven by
managed.prepare(); sha256(binary) == 996bad5fe6fb89c0c50363d87f03dc78f6e536a
eea746c06679a294d14eca435. Baseline expectation (pinned 0.10.8 artifact
reports no native head through the managed flow): index receipt status ok
while NO ledger binding row is published (require_native_head refuses), and
the post-index search carries freshness UNBOUND / snapshot_bound False —
a missing native head stays UNBOUND, never FRESH. The query-window
no-mutation check hashes ALL files including SQLite -wal/-shm sidecar bytes
(conservative: a write landing only in WAL is detected, a read-induced shm
touch honestly flags CHANGED). Registry records are REUSED measured evidence
from tracked p2-managed-registry-records.json, validated via from_dict()
against THIS artifact/protocol/commit — never fabricated here.
Budget: 120 s ACTUAL monotonic elapsed over the native span
(prepare->index->search). Admission requires the REMAINING budget to cover
the stage's max expected duration (prepare 62 s = 2x executor query cap,
index 60 s, search 32 s = query cap + overhead); the post-run verdict also
FAILS on any overrun (the harness never signals a running stage).
No signals, no global daemon/config access, no negative noUI control, no
cleanup pass: the root is ALWAYS a fresh mkdtemp (no --root option; nothing
pre-existing can be overwritten) and is left frozen; the ONLY file written
is the sanitized receipt INSIDE that new root.
Compile/lint only at authoring time — NO native run yet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVIDENCE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))  # pinned source tree, not site-packages

from sot_graph.db import Database  # noqa: E402
from sot_graph.provider_contract import (  # noqa: E402
    Capability, IntegrationMode, ProviderIdentity)
from sot_graph.providers.base import IndexRequest, SymbolRequest  # noqa: E402
from sot_graph.providers.codebase_memory import (  # noqa: E402
    CodebaseMemoryProvider, ExactCompatibilityContext)
from sot_graph.providers.compatibility import (  # noqa: E402
    CompatibilityRegistry, CompatibilityVerdict, TestedCompatibilityRecord)
from sot_graph.providers.managed import ManagedNativeRuntime  # noqa: E402
from sot_graph.providers.runtime import ManagedRuntimeProfile  # noqa: E402

PINNED_SHA = "996bad5fe6fb89c0c50363d87f03dc78f6e536aeea746c06679a294d14eca435"
RELEASE_COMMIT = "46ae198fc11cda80e817acbc5f5908d7c2de7032"
PROTO = "p2-managed-measured-acceptance-v1"
REQUIRED_OPS = ("config_set_auto_watch", "config_get_auto_watch", "index_repository",
                "list_projects", "search_graph", "index_status")
BUDGET_S = 120.0
RESERVES = {"p_prepare": 62.0, "i_index": 60.0, "q_search": 32.0}
WALLS: dict[str, float] = {}
SCRATCH = ""


class Budget(Exception):
    pass


def admit(tag: str) -> None:
    left = BUDGET_S - sum(WALLS.values())
    if left < RESERVES[tag]:
        raise Budget(f"{tag} needs {RESERVES[tag]}s reserve, {left:.1f}s left")


def charge(tag: str, t0: float) -> None:
    WALLS[tag] = round(time.monotonic() - t0, 3)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_json(obj):
    if isinstance(obj, str):
        return obj.replace(SCRATCH, "<SCRATCH>").replace(str(Path.home()), "<HOME>")
    if isinstance(obj, list):
        return [sanitize_json(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    return obj


def fatal(msg: str) -> int:
    print(f"FATAL: {msg}", file=sys.stderr)
    return 2


def check(cond: bool, msg: str) -> None:
    """Explicit safety gate: survives `python -O` (never a bare assert)."""
    if not cond:
        raise RuntimeError(msg)


def make_repo(root: Path) -> tuple[str, str]:
    """Real scratch git repo; global git config is never read (=/dev/null)."""
    repo = root / "repo"
    repo.mkdir()
    (repo / "alpha.py").write_text(
        'def greet(name: str) -> str:\n    """Return a greeting."""\n'
        '    return f"hello {name}"\n')
    (repo / "beta.py").write_text(
        'class Greeter:\n    """Fixture class for the acceptance query."""\n'
        '    def shout(self, word: str) -> str:\n        return word.upper() + "-"\n')
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    base = ["git", "-C", str(repo)]

    def git(*argv: str, allow_fail: bool = False) -> subprocess.CompletedProcess:
        r = subprocess.run(base + list(argv), env=env, capture_output=True, text=True)
        if r.returncode != 0 and not allow_fail:
            raise RuntimeError(f"git {argv[0]} failed: {r.stderr.strip()[:200]}")
        return r

    if git("init", "-q", "-b", "main", allow_fail=True).returncode != 0:
        git("init", "-q")  # git < 2.28 has no -b
    git("add", "-A")
    git("-c", "user.email=harness@invalid", "-c", "user.name=harness",
        "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    return str(repo), git("rev-parse", "HEAD").stdout.strip()


def load_measured_registry(path: Path, bin_sha: str):
    """Validate + load tracked MEASURED records; context must match this run."""
    payload = json.loads(path.read_text())
    records = [TestedCompatibilityRecord.from_dict(r)  # rejects field drift
               for r in payload["records"]]
    version = payload["version"]
    if sorted(r.operation for r in records) != sorted(REQUIRED_OPS):
        raise ValueError("record ops do not cover exactly the six required ops")
    digests: dict[str, str] = {}
    for rec in records:
        if (rec.provider_name != "codebase-memory" or rec.artifact_sha256 != bin_sha
                or rec.protocol_compatibility_id != PROTO
                or rec.engine_commit != RELEASE_COMMIT or rec.version != version
                or len(rec.fixture_digest) != 64):
            raise ValueError(f"record context mismatch for op {rec.operation}")
        digests[rec.operation] = rec.fixture_digest
    bad = {op: v for op, v in payload["per_op_verdict"].items()
           if v != CompatibilityVerdict.COMPATIBLE.value}
    if bad:
        raise ValueError(f"tracked verdicts not all compatible: {bad}")
    registry = CompatibilityRegistry()
    for rec in records:
        registry.register(rec)
    return registry, digests, version


def fs_snapshot(repo: str, namespace: Path) -> dict[str, str]:
    """Hash ALL files incl. -wal/-shm sidecar bytes (conservative, WAL-safe)."""
    out: dict[str, str] = {}
    for base in (Path(repo), namespace):
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in ("tmp", "runtime", "logs"))
            for name in sorted(files):
                if name.endswith((".log", ".lock", ".pid")):
                    continue  # unbounded/appended or advisory-lock artifacts
                p = Path(root) / name
                try:
                    out[str(p)] = sha_bytes(p.read_bytes())
                except OSError as exc:
                    out[str(p)] = f"UNREADABLE:{type(exc).__name__}"
    return out


DAEMON_TOKEN = "--cbm-daemon-internal"  # passive match token only; never signalled


def ps_inventory(bin_path: str, basename: str) -> dict[str, dict[str, str]]:
    """Passive `ps` snapshot; RAISES if ps fails (a silent {} would fake a
    pass). Local filtering — ps argv is not reliably shlex-able, so match the
    exact trusted executable path as prefix with a word boundary (spaces
    preserved), fallback exact basename token, else the daemon token.
    Persists pid+lstart+role ONLY (never argv/env tails)."""
    try:
        r = subprocess.run(["ps", "-axo", "pid=,lstart=,command="],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"ps inventory unavailable: {type(exc).__name__}") from exc
    if r.returncode != 0:
        raise RuntimeError(f"ps inventory failed rc={r.returncode}")
    found: dict[str, dict[str, str]] = {}
    for line in r.stdout.splitlines():
        fields = line.split(None, 6)
        if len(fields) < 7:
            continue
        pid, lstart, cmd = fields[0], " ".join(fields[1:6]), fields[6]
        if cmd == bin_path or cmd.startswith(bin_path + " "):
            role = "binary"
        elif Path(cmd.split()[0]).name == basename:
            role = "binary"
        elif DAEMON_TOKEN in cmd.split():
            role = "daemon"
        else:
            continue
        found[f"{pid} {lstart}"] = {"pid": pid, "start": lstart, "role": role}
    return found


def process_verdict(bin_path: str, basename: str,
                    baseline: dict[str, dict]) -> dict:
    """Bounded 10s poll for NEW matching processes (baseline pid+start keyed).
    Preexisting same pid+start preserved and gate-checked; new ones classed
    `unknown` (NOT proven orphan/terminated). No signals, no adoption."""
    t0 = time.monotonic()
    snap: dict = {}
    while True:
        snap = ps_inventory(bin_path, basename)
        new = {k: v for k, v in snap.items() if k not in baseline}
        if not new or time.monotonic() - t0 >= 10.0:
            break
        time.sleep(1.0)
    new = {k: v for k, v in snap.items() if k not in baseline}
    return {
        "method": "passive ps; pid+start+role only; no signals, no adoption",
        "poll_elapsed_s": round(time.monotonic() - t0, 3),
        "baseline_count": len(baseline),
        "preexisting_preserved": sorted(snap[k]["pid"] for k in snap if k in baseline),
        "preexisting_preserved_ok": set(baseline) <= set(snap),
        "new_remaining_unknown": {k: dict(v, classification="unknown_not_"
                                                 "proven_orphan_or_terminated")
                                  for k, v in new.items()},
        "no_new_remaining": not new,
        "causal_note": "empty post-poll snapshot: no new matching process "
                       "remains; full causal linkage NOT claimed"}


def ledger_digest(db_path: str) -> str:
    import sqlite3
    from urllib.parse import quote
    conn = sqlite3.connect("file:" + quote(os.path.abspath(db_path), safe="/")
                           + "?mode=ro", uri=True)
    try:
        parts = []
        for table in ("provider_runs", "provider_project_bindings", "provider_evidence"):
            try:
                rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            except sqlite3.OperationalError:
                rows = ["<absent>"]
            parts.append(f"{table}={rows!r}")
        return sha_bytes("\n".join(parts).encode("utf-8"))
    finally:
        conn.close()


def main() -> int:
    global SCRATCH
    ap = argparse.ArgumentParser(description="P2 outer provider acceptance")
    ap.add_argument("--binary", default=str(Path.home() / ".local/bin/codebase-memory-mcp"))
    ap.add_argument("--registry", default=str(EVIDENCE_DIR / "p2-managed-registry-records.json"))
    args = ap.parse_args()

    bin_path = Path(os.path.realpath(args.binary))
    if not bin_path.is_file():
        return fatal(f"binary not found: {bin_path}")
    bin_sha = sha_bytes(bin_path.read_bytes())
    if bin_sha != PINNED_SHA:
        return fatal(f"binary sha256 {bin_sha} != pinned {PINNED_SHA}")
    root = os.path.realpath(tempfile.mkdtemp(prefix="s-", dir="/private/tmp"))
    if len(root.encode()) > 27:
        return fatal(f"fresh root {len(root.encode())} bytes exceeds sun_path budget")
    SCRATCH = root
    root_path = Path(root)
    try:
        repo, sot_head = make_repo(root_path)
        db = Database(str(root_path / "sot" / "sot.db"))
        registry, digests, version = load_measured_registry(Path(args.registry), bin_sha)
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
        return fatal(f"setup failed: {exc}")
    ctx = ExactCompatibilityContext(
        registry=registry,
        runtime_identity=ProviderIdentity(
            name="codebase-memory", version=version, mode=IntegrationMode.FEDERATED_CLI,
            capability=Capability.SYMBOLS, engine_commit=RELEASE_COMMIT,
            artifact_sha256=bin_sha, protocol_compatibility_id=PROTO),
        operation_fixture_digests=digests, protocol_compatibility_id=PROTO)
    stages: dict = {"binary_sha256": bin_sha, "registry_ops": sorted(digests),
                    "sot_head": sot_head, "no_native_run_at_authoring": True}

    # UI-off preseed + 7-key env BEFORE any native start (explicit checks).
    prof = ManagedRuntimeProfile(root, repo, artifact_digest=bin_sha, generation="provider")
    prof.initialize()
    env = prof.environment()
    try:
        check(set(env) == {"HOME", "CBM_CACHE_DIR", "CBM_RUNTIME_DIR", "XDG_CONFIG_HOME",
                           "TMPDIR", "PATH", "TERM"}, f"env keys: {sorted(env)}")
        check(env["PATH"] == "/usr/bin:/bin", f"PATH: {env['PATH']}")
        check(env["TERM"] == "dumb", f"TERM: {env['TERM']}")
        check(json.loads((prof.paths["cache"] / "config.json").read_bytes())
              == {"ui_enabled": False}, "ui_enabled=false preseed missing pre-native")
        check(isinstance(prof.namespace, Path) and prof.namespace.is_dir(),
              "profile namespace is not an existing Path")
    except RuntimeError as exc:
        return fatal(f"preflight: {exc}")
    stages["env_preflight"] = "7-key env + ui_enabled=false preseed, pre-native"

    # Real outer provider binding over the executor (existing ctor seams only).
    runtime = ManagedNativeRuntime(prof, repo, (str(bin_path),), ctx)
    provider = CodebaseMemoryProvider(command=(str(bin_path),), db=db,
                                      exact_context=ctx, managed_runtime=runtime)
    binding = {"managed_is_runtime": provider._managed is runtime,
               "repo_binding": provider._managed_repo == os.path.realpath(repo),
               "exe_binding": provider._managed_command == (str(bin_path),),
               "exact_context_is_ctx": provider._exact is ctx}
    stages["provider_binding"] = binding

    # Passive process inventory: baseline BEFORE any native start (read-only).
    # ps failure raises here => FATAL exit before any stage or receipt write.
    bin_name = bin_path.name
    base_procs = ps_inventory(str(bin_path), bin_name)
    stages["process_baseline"] = {"matched_preexisting": len(base_procs)}

    # auto_watch=false proven by managed.prepare() (set+get+_config.db readback).
    t_start = time.monotonic()
    admit("p_prepare")
    t0 = time.monotonic()
    p = runtime.prepare()
    charge("p_prepare", t0)
    stages["prepare"] = {"status": p.status, "state": p.runtime_state, "err": p.error}
    ok_p = p.status == "ok"

    # Explicit provider.index -> managed prepare+sync. Baseline: receipt ok but
    # NO ledger binding row (require_native_head refuses without a native head).
    admit("i_index")
    t0 = time.monotonic()
    idx = provider.index(IndexRequest(repo_root=repo))
    charge("i_index", t0)
    row = db.get_provider_binding(os.path.realpath(repo), "codebase-memory")
    stages["index"] = {"status": idx.status, "ledger_binding_row": row is not None}
    ok_i = idx.status == "ok" and row is None

    # Query window: search must stay UNBOUND (no native head) — never FRESH —
    # and must not mutate repo/index bytes (WAL/SHM included) nor ledger rows.
    snap0, led0 = fs_snapshot(repo, prof.namespace), ledger_digest(str(db.db_path))
    admit("q_search")
    t0 = time.monotonic()
    res = provider.search_symbols(SymbolRequest(repo_root=repo, query="greet"))
    charge("q_search", t0)
    ok_q = (res.metadata.get("freshness") == "UNBOUND"
            and res.metadata.get("snapshot_bound") is False)
    stages["search"] = {"ok": res.ok, "status": res.run.status,
                        "freshness": res.metadata.get("freshness"),
                        "snapshot_bound": res.metadata.get("snapshot_bound")}
    stages["query_no_mutation"] = {
        "bytes_incl_wal_shm": fs_snapshot(repo, prof.namespace) == snap0,
        "ledger_rows": ledger_digest(str(db.db_path)) == led0}

    elapsed = round(time.monotonic() - t_start, 3)
    stages["budget"] = {"per_stage": dict(WALLS), "elapsed_native_span_s": elapsed,
                        "budget_s": BUDGET_S, "reserves": RESERVES}
    # Final passive inventory AFTER all stages: bounded 10s poll for new procs.
    stages["process_final"] = process_verdict(str(bin_path), bin_name, base_procs)
    ok = (ok_p and ok_i and ok_q and all(binding.values())
          and all(stages["query_no_mutation"].values())
          and stages["process_final"]["no_new_remaining"]
          and stages["process_final"]["preexisting_preserved_ok"]
          and elapsed <= BUDGET_S)
    (root_path / "provider-acceptance-receipt.json").write_text(
        json.dumps(sanitize_json(stages), indent=1))
    print(json.dumps(sanitize_json(stages), indent=1, default=str)[:4000])
    print(f"scratch root (left frozen; receipt inside): {root}")
    print("PROVIDER_ACCEPTANCE_RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Budget as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
