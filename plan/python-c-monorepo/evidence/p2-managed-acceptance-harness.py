#!/usr/bin/env python3
"""P2 managed native acceptance runner — measured-fixture, reproducible, safe.

CLI (trusted admin inputs, no negative controls):
    .venv/bin/python p2-managed-acceptance-harness.py [--binary PATH] [--root DIR]

Provenance model (explicit):
- Phase CAPTURE is the ONE explicit lab capture step: the executor withholds
  raw native stdout by design, so the six required operations are dispatched
  once via sot_graph.proc.run_command through the PROFILE-SERVED 7-key
  replacement env (verbatim; root is short enough post-fix) against a fresh
  namespace. The sha256 fixture digests are computed over the EXACT raw
  stdout text as delivered by run_command (UTF-8 encoded, nothing stripped)
  BEFORE any sanitization. Stored fixture copies are SANITIZED
  (scratch/home -> <SCRATCH>/<HOME>); the digest always binds the raw bytes
  and the redaction map is documented next to each fixture — raw and
  sanitized bytes are NOT the same and are never claimed to be.
- Raw stdout bytes live only in the run scratch (temp, discarded); this
  script writes ONLY digest/sanitized/status artifacts. No raw lab files.
- Registry records are ACTUAL MEASURED records (real artifact sha256, real
  measured --version, real protocol id, measured per-op fixture digest) —
  not placeholders. Honesty note: the "fixture suite" a record binds is, for
  now, the op's own captured raw output of the same artifact (self-binding);
  upstream fixture-suite provenance remains future work and is stated as such
  in every record's tested_by.
- Phase ACCEPT reruns the executor (prepare x2, sync, queries) using ONLY
  those measured records via the exact-compatibility gate.
- Phase TIMEBOUND exercises cancellation_unknown through the executor with a
  tiny dispatch deadline on a FRESH generation. Inspection note: the
  constructor exposes NO timeout attribute; the deadline source is the module
  constant managed._QUERY_TIMEOUT, patched in-process only (no production
  edit), restored in finally. The owned process-group kill is performed
  solely by run_command's deadline; any owned daemon is only OBSERVED to
  terminal (bounded 15 s) — this script never signals any process.
- Quarantined namespaces are left frozen forever (never cleared).
- Overall native budget: 150 s. FIX (evidence-only, post-run): the budget guard now
  covers ALL phases (executor prepare/sync/queries + timebound), not only raw_op
  capture dispatches; this guard fix has NOT been re-validated by a full rerun
  (markfix notvalidatedfull). Wall sums include Python/spawn overhead — they are
  NOT a pure native-time breakdown.

Artifacts written (all sanitized, no raw):
    p2-managed-fixture-digests.json   raw-digest <-> sanitized fixture binding
    p2-managed-registry-records.json  the six actual measured records
    p2-managed-acceptance-receipt.json stage receipts (statuses, timings, digests)
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
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVIDENCE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))  # pinned source tree, not site-packages

from sot_graph.proc import run_command  # noqa: E402
from sot_graph.provider_contract import ProviderIdentity, Capability, IntegrationMode  # noqa: E402
from sot_graph.providers import managed as managed_mod  # noqa: E402
from sot_graph.providers.codebase_memory import ExactCompatibilityContext  # noqa: E402
from sot_graph.providers.compatibility import (  # noqa: E402
    CompatibilityRegistry,
    CompatibilityVerdict,
    TestedCompatibilityRecord,
)
from sot_graph.providers.managed import ManagedNativeRuntime  # noqa: E402
from sot_graph.providers.runtime import ManagedRuntimeProfile  # noqa: E402

PINNED_SHA = "996bad5fe6fb89c0c50363d87f03dc78f6e536aeea746c06679a294d14eca435"
RELEASE_COMMIT = "46ae198fc11cda80e817acbc5f5908d7c2de7032"
OPS = ("config_set_auto_watch", "config_get_auto_watch", "index_repository",
       "list_projects", "search_graph", "index_status")
PROTO = "p2-managed-measured-acceptance-v1"
NATIVE_BUDGET_S = 150.0
OPS_TIMINGS: dict[str, dict] = {}
SCRATCH = ""


def sha(text: str) -> str:
    """sha256 over the EXACT captured stdout text (UTF-8), pre-sanitization."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Budget(Exception):
    pass


def budget_left() -> float:
    return NATIVE_BUDGET_S - sum(t["wall"] for t in OPS_TIMINGS.values())


def charge(tag: str, wall: float) -> None:
    """Charge an executor-phase wall to the same ledger the budget guard reads."""
    OPS_TIMINGS[tag] = {"wall": wall, "rc": "managed", "timed_out": None}


def ensure_budget(tag: str, need: float) -> None:
    if budget_left() < need:
        raise Budget(f"native budget exhausted before {tag}")


def sanitize(text: str) -> str:
    return (text.replace(SCRATCH, "<SCRATCH>")
                .replace(str(Path.home()), "<HOME>"))


def profile_env(prof: ManagedRuntimeProfile) -> dict:
    env = prof.environment()
    assert set(env) == {"HOME", "CBM_CACHE_DIR", "CBM_RUNTIME_DIR",
                        "XDG_CONFIG_HOME", "TMPDIR", "PATH", "TERM"}
    assert env["PATH"] == "/usr/bin:/bin" and env["TERM"] == "dumb"
    assert json.loads((prof.paths["cache"] / "config.json").read_bytes()) == {
        "ui_enabled": False}, "UI-off pre-seed must exist before any native start"
    return env


def raw_op(tag: str, argv: list[str], repo: str, env: dict, timeout: float):
    if budget_left() < timeout + 2:
        raise Budget(f"native budget exhausted before {tag}")
    t0 = time.monotonic()
    r = run_command(argv, cwd=repo, env=env, timeout_seconds=timeout,
                    max_output_bytes=8 << 20)
    wall = round(time.monotonic() - t0, 2)
    OPS_TIMINGS[tag] = {"wall": wall, "rc": r.returncode, "timed_out": r.timed_out}
    return r


def fs_snapshot(repo: str, cache: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for base in (Path(repo), cache):
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in ("tmp", "runtime", "logs"))
            for name in sorted(files):
                if ".log" in name or name.endswith(".lock") or name.endswith(".pid"):
                    continue
                p = Path(root) / name
                try:
                    h = hashlib.sha256()
                    with open(p, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1 << 20), b""):
                            h.update(chunk)
                    out[str(p)] = h.hexdigest()
                except OSError as exc:
                    out[str(p)] = f"UNREADABLE:{type(exc).__name__}"
    return out


def write_json(name: str, payload) -> None:
    (EVIDENCE_DIR / name).write_text(json.dumps(sanitize_json(payload), indent=1))


def sanitize_json(obj):
    if isinstance(obj, str):
        return sanitize(obj)
    if isinstance(obj, list):
        return [sanitize_json(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    return obj


def main() -> int:
    global SCRATCH
    ap = argparse.ArgumentParser(description="P2 managed acceptance (measured fixtures)")
    ap.add_argument("--binary", default=str(Path.home() / ".local/bin/codebase-memory-mcp"))
    ap.add_argument("--root", default=None,
                    help="trusted admin profile root; default fresh mkdtemp under /private/tmp")
    args = ap.parse_args()

    stages: dict[str, dict] = {"artifacts": "sanitized-only; raw bytes stay in scratch"}

    bin_path = Path(os.path.realpath(args.binary))
    if not bin_path.is_file():
        print(f"FATAL: binary not found: {bin_path}", file=sys.stderr)
        return 2
    bin_sha = hashlib.sha256(bin_path.read_bytes()).hexdigest()
    if bin_sha != PINNED_SHA:
        print(f"FATAL: binary sha256 {bin_sha} != pinned release artifact {PINNED_SHA}; "
              "this acceptance is bound to the pinned artifact", file=sys.stderr)
        return 2

    root = args.root or tempfile.mkdtemp(prefix="s-", dir="/private/tmp")
    root = os.path.realpath(root)
    if len(root.encode()) > 27:
        print(f"FATAL: root {len(root.encode())} UTF-8 bytes exceeds the 27-byte "
              "budget for uid 501 (sun_path preflight will reject)", file=sys.stderr)
        return 2
    SCRATCH = root
    repo = os.path.join(root, "repo")
    os.makedirs(repo, exist_ok=True)
    (Path(repo) / "alpha.py").write_text(
        'def greet(name: str) -> str:\n    """Return a greeting."""\n'
        '    return f"hello {name}"\n')
    (Path(repo) / "beta.py").write_text(
        'class Greeter:\n    """Fixture class for the acceptance queries."""\n'
        '    def shout(self, word: str) -> str:\n        return word.upper() + "-"\n')
    pgrep_pre = sorted(subprocess.run(["pgrep", "-f", "codebase-memory-mcp"],
                                      capture_output=True, text=True).stdout.split())
    stages["env"] = {"root_bytes": len(root.encode()), "binary": str(bin_path),
                     "binary_sha256": bin_sha, "pgrep_pre": pgrep_pre}

    prof_cap = ManagedRuntimeProfile(root, repo, artifact_digest=bin_sha,
                                     generation="capture")
    prof_cap.initialize()
    env = profile_env(prof_cap)

    # ---------------- phase CAPTURE (one explicit lab capture; raw kept in scratch) ----------
    raw_dir = prof_cap.paths["tmp"]  # raw stdout files stay in scratch only
    captured: dict[str, dict] = {}

    def capture(op_key: str, argv: list[str], timeout: float) -> None:
        r = raw_op(f"capture:{op_key}", argv, repo, env, timeout)
        raw = r.stdout  # EXACT text as delivered; nothing stripped
        raw_file = raw_dir / f"raw-{op_key}.txt"  # scratch-only, never published
        raw_file.write_text(raw)
        payload = None
        if r.returncode == 0 and raw.strip():
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = None
        captured[op_key] = {
            "argv": [argv[0]] + argv[1:],
            "rc": r.returncode, "timed_out": r.timed_out,
            "raw_sha256": sha(raw), "raw_bytes": len(raw.encode("utf-8")),
            "raw_scratch_copy": str(raw_file),
            "payload": payload,
        }

    r_ver = raw_op("capture:version", [str(bin_path), "--version"], repo, env, 30.0)
    version_text = r_ver.stdout.strip().splitlines()[0] if r_ver.stdout.strip() else None

    capture("config_set_auto_watch", [str(bin_path), "config", "set", "auto_watch", "false"], 60.0)
    capture("config_get_auto_watch", [str(bin_path), "config", "get", "auto_watch"], 60.0)
    capture("index_repository", [str(bin_path), "cli", "index_repository",
                                 "--repo-path", repo], 120.0)
    af = prof_cap.paths["tmp"] / "args-list.json"
    af.write_text(json.dumps({"limit": 50, "offset": 0}))
    capture("list_projects", [str(bin_path), "cli", "list_projects",
                              "--args-file", str(af)], 60.0)
    proj = None
    lp_payload = captured["list_projects"]["payload"]
    if isinstance(lp_payload, dict) and isinstance(lp_payload.get("projects"), list):
        matches = sorted({p["name"] for p in lp_payload["projects"]
                          if isinstance(p, dict) and isinstance(p.get("name"), str)
                          and isinstance(p.get("root_path"), str)
                          and os.path.realpath(p["root_path"]) == os.path.realpath(repo)})
        proj = matches[0] if len(matches) == 1 else None
    if proj is None:
        print("FATAL: could not bind unique project from list_projects", file=sys.stderr)
        return 1
    af = prof_cap.paths["tmp"] / "args-search.json"
    af.write_text(json.dumps({"query": "greet", "project": proj, "format": "json", "limit": 20}))
    capture("search_graph", [str(bin_path), "cli", "search_graph",
                             "--args-file", str(af)], 60.0)
    af = prof_cap.paths["tmp"] / "args-status.json"
    af.write_text(json.dumps({"project": proj}))
    capture("index_status", [str(bin_path), "cli", "index_status",
                             "--args-file", str(af)], 60.0)

    for op, want in (("config_set_auto_watch", "rc0_nonempty"),
                     ("config_get_auto_watch", "false"),
                     ("index_repository", "indexed"),
                     ("list_projects", "bound"),
                     ("search_graph", "json"),
                     ("index_status", "json")):
        rec = captured[op]
        ok = {"rc0_nonempty": lambda: rec["rc"] == 0 and rec["raw_bytes"] > 0,
              "false": lambda: rec["payload"] is False,
              "indexed": lambda: isinstance(rec["payload"], dict)
                                 and rec["payload"].get("status") == "indexed",
              "bound": lambda: proj is not None,
              "json": lambda: isinstance(rec["payload"], dict)}[want]()
        rec["capture_assert"] = f"{want}:{'ok' if ok else 'FAIL'}"
        if not ok:
            print(f"FATAL: capture assert failed for {op}", file=sys.stderr)
            return 1

    # sanitized fixtures + documented raw<->sanitized binding
    fixtures = {op: {
        "raw_sha256": captured[op]["raw_sha256"],
        "binding": ("digest is sha256 over the EXACT raw stdout text as delivered by "
                    "proc.run_command (UTF-8), computed BEFORE sanitization; the stored "
                    "fixture below is the SANITIZED copy (scratch/home redacted) and does "
                    "NOT hash to raw_sha256 — raw and sanitized bytes are intentionally "
                    "different, and raw bytes live only in the run scratch"),
        "redaction_map": {SCRATCH: "<SCRATCH>", str(Path.home()): "<HOME>"},
        "raw_capture_source": ("direct run_command dispatch through the profile-served 7-key "
                               "replacement env on fresh namespace 'capture' — the one "
                               "explicit lab capture step (executor withholds raw stdout)"),
        "sanitized_fixture": sanitize(captured[op]["payload"] is not None
                                      and isinstance(captured[op]["payload"], dict)
                                      and json.dumps(captured[op]["payload"], sort_keys=True)
                                      or captured[op]["raw_sha256"]),
        "capture_assert": captured[op]["capture_assert"],
    } for op in OPS}
    write_json("p2-managed-fixture-digests.json",
               {"version_native": sanitize(version_text or ""), "fixtures": fixtures})

    # ---------------- registry: ACTUAL measured records (not placeholders) ----------
    tested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = []
    registry = CompatibilityRegistry()
    for op in OPS:
        rec = TestedCompatibilityRecord(
            provider_name="codebase-memory", operation=op, artifact_sha256=bin_sha,
            fixture_digest=captured[op]["raw_sha256"], protocol_compatibility_id=PROTO,
            version=version_text, engine_commit=RELEASE_COMMIT,
            tested_by=("measured managed-acceptance capture: fixture digest = sha256 of THIS "
                       "artifact's raw stdout for this op, measured this run; self-binding "
                       "(upstream fixture-suite provenance is future work)"),
            tested_at=tested_at)
        registry.register(rec)
        records.append(rec.to_dict())
    identity = ProviderIdentity(name="codebase-memory", version=version_text,
                                mode=IntegrationMode.FEDERATED_CLI,
                                capability=Capability.SYMBOLS,
                                engine_commit=RELEASE_COMMIT, artifact_sha256=bin_sha,
                                protocol_compatibility_id=PROTO)
    ctx = ExactCompatibilityContext(registry=registry, runtime_identity=identity,
                                    operation_fixture_digests={o: captured[o]["raw_sha256"]
                                                               for o in OPS},
                                    protocol_compatibility_id=PROTO)
    per_op_gate = {}
    for op in OPS:
        a = registry.assess(identity, op, fixture_digest=captured[op]["raw_sha256"],
                            protocol_compatibility_id=PROTO)
        per_op_gate[op] = a.verdict.value
    stages["registry"] = {"per_op_verdict": per_op_gate, "version": version_text,
                          "records": records}
    write_json("p2-managed-registry-records.json", stages["registry"])
    if any(v != CompatibilityVerdict.COMPATIBLE.value for v in per_op_gate.values()):
        print(f"FATAL: registry gate not compatible for all ops: {per_op_gate}", file=sys.stderr)
        return 1

    # ---------------- phase ACCEPT: executor rerun on measured records ----------
    prof_acc = ManagedRuntimeProfile(root, repo, artifact_digest=bin_sha,
                                     generation="accept")
    runtime = ManagedNativeRuntime(prof_acc, repo, (str(bin_path),), ctx)
    ensure_budget("accept:prepare1", 60.0)
    t0 = time.monotonic(); p1 = runtime.prepare()
    charge("accept:prepare1", round(time.monotonic() - t0, 2))
    stages["accept_prepare1"] = {"status": p1.status, "state": p1.runtime_state,
                                 "err": p1.error, "wall": round(time.monotonic() - t0, 2)}
    ensure_budget("accept:prepare2", 10.0)
    t0 = time.monotonic(); p2 = runtime.prepare()
    charge("accept:prepare2", round(time.monotonic() - t0, 3))
    stages["accept_prepare2"] = {"status": p2.status, "err": p2.error,
                                 "wall": round(time.monotonic() - t0, 3)}
    marker = prof_acc.namespace / "managed-ready.json"
    stages["accept_prepare1"]["marker_mode"] = (oct(os.lstat(marker).st_mode & 0o777)
                                                if marker.exists() else "absent")
    ensure_budget("accept:sync", 60.0)
    t0 = time.monotonic(); sy = runtime.sync(repo)
    charge("accept:sync", round(time.monotonic() - t0, 2))
    stages["accept_sync"] = {"status": sy.status,
                             "payload_status": sy.payload.get("status")
                                               if isinstance(sy.payload, dict) else None,
                             "err": sy.error, "wall": round(time.monotonic() - t0, 2)}
    snap1 = fs_snapshot(repo, prof_acc.paths["cache"])
    queries = {}
    for op, qargs in (("search_graph", {"query": "greet"}), ("index_status", {}),
                      ("list_projects", {})):
        ensure_budget(f"accept:query:{op}", 30.0)
        t0 = time.monotonic(); q = runtime.query(op, qargs)
        wall_q = round(time.monotonic() - t0, 2)
        charge(f"accept:query:{op}", wall_q)
        queries[op] = {"status": q.status, "err": q.error,
                       "payload_sha256_16": (hashlib.sha256(json.dumps(
                           q.payload, sort_keys=True).encode()).hexdigest()[:16]
                           if q.payload is not None else None),
                       "payload_keys": sorted(q.payload)[:8] if isinstance(q.payload, dict) else None,
                       "wall": wall_q}
    stages["accept_queries"] = queries
    stages["accept_fs_invariant"] = ("identical" if fs_snapshot(repo, prof_acc.paths["cache"]) == snap1
                                     else "CHANGED")
    d = runtime.query("trace_path", {"query": "x"})
    stages["accept_denied_nospawn"] = {"trace_path": d.status}

    # ---------------- phase TIMEBOUND: cancellation_unknown, fresh generation ----------
    prof_tb = ManagedRuntimeProfile(root, repo, artifact_digest=bin_sha,
                                    generation="timebound")
    rt_tb = ManagedNativeRuntime(prof_tb, repo, (str(bin_path),), ctx)
    orig = managed_mod._QUERY_TIMEOUT
    try:
        managed_mod._QUERY_TIMEOUT = 1.5  # harness-only tiny deadline; no ctor attr exists
        ensure_budget("timebound:prepare", 20.0)
        t0 = time.monotonic(); c = rt_tb.prepare(); wall_c = round(time.monotonic() - t0, 2)
        charge("timebound_native:prepare", wall_c)
    finally:
        managed_mod._QUERY_TIMEOUT = orig
    stages["timebound"] = {"status": c.status, "cancel": c.cancellation_state,
                           "profile_state": prof_tb.status()["state"],
                           "marker_absent": not (prof_tb.namespace / "managed-ready.json").exists(),
                           "wall": wall_c}
    t0 = time.monotonic(); nr = rt_tb.prepare()
    stages["timebound_no_reuse"] = {"prepare_again": nr.status,
                                    "wall": round(time.monotonic() - t0, 3)}
    seen_alive = False
    new_now = None
    for _ in range(15):  # bounded observation, never signal
        pids = set(subprocess.run(["pgrep", "-f", "codebase-memory-mcp"],
                                  capture_output=True, text=True).stdout.split())
        new = sorted(pids - set(pgrep_pre))
        if not new:
            break
        new_now = new
        seen_alive = True
        time.sleep(1)
    if new_now is None and not seen_alive:
        verdict = "no additional daemon observed after timeout; spawning/terminal cause unknown"
    elif not new_now:
        verdict = "owned daemon observed alive then absent (exit itself not observed)"
    else:
        verdict = f"process(es) still present at 15s observation end: {new_now}"
    stages["timebound_daemon_observation"] = verdict

    # ---------------- hygiene + receipts ----------
    pgrep_post = sorted(subprocess.run(["pgrep", "-f", "codebase-memory-mcp"],
                                       capture_output=True, text=True).stdout.split())
    capture_wall = round(sum(t["wall"] for k, t in OPS_TIMINGS.items()
                             if k.startswith("capture:")), 2)
    accept_wall = round(sum(t["wall"] for k, t in OPS_TIMINGS.items()
                            if k.startswith("accept:")), 2)
    timeout_wall = round(sum(t["wall"] for k, t in OPS_TIMINGS.items()
                             if k.startswith("timebound_native")), 2)
    stages["wall_breakdown"] = {
        "capture_wall_s": capture_wall,
        "acceptance_wall_s": accept_wall,
        "timeout_wall_s": timeout_wall,
        "all_recorded_sum_s": round(capture_wall + accept_wall + timeout_wall, 2),
        "scope": ("sums of recorded wall clocks; every wall includes Python/spawn "
                  "overhead — NOT a pure native-time breakdown; the 15s timebound "
                  "observation wait and zero-native stages are excluded")}
    stages["hygiene"] = {
        "new_pids_final": [p for p in pgrep_post if p not in pgrep_pre] or "none",
        "signals_user_or_preexisting": 0,
        "signals_owned_deadline": ("timebound prepare hit the run_command deadline: owned "
                                   "process-group SIGKILL via proc._kill_process_group — a "
                                   "signal WAS delivered, harness-facilitated, never manual"),
        "binary_sha256_unchanged": hashlib.sha256(bin_path.read_bytes()).hexdigest() == PINNED_SHA,
        "quarantined_namespaces_frozen": {
            "timebound-NEVER-CLEAR": str(prof_tb.namespace)}}
    write_json("p2-managed-acceptance-receipt.json",
               {"scratch": root, "stages": stages})

    ok = (stages["accept_prepare1"]["status"] == "ok"
          and stages["accept_prepare2"]["status"] == "ok"
          and stages["accept_sync"]["status"] == "ok"
          and all(q["status"] == "ok" for q in queries.values())
          and stages["accept_fs_invariant"] == "identical"
          and stages["timebound"]["cancel"] == "cancellation_unknown"
          and stages["timebound"]["profile_state"] == "QUARANTINED"
          and stages["timebound"]["marker_absent"]
          and stages["timebound_no_reuse"]["prepare_again"] == "runtime_refused")
    print(json.dumps(sanitize_json(stages), indent=1, default=str)[:4000])
    print("ACCEPTANCE_RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
