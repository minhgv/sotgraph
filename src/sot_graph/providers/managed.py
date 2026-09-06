"""P2 managed native executor (INTERNAL — not yet a public API).

Not installed by default and not wired into the CLI/adapter yet; the adapter
follow-up integrates this module after review. One executor owns exactly one
``ManagedRuntimeProfile`` and dispatches the native one-shot CLI through the
digest-gated exact-compatibility context (``CodebaseMemoryProvider`` ctor +
``CompatibilityRegistry`` machinery reused — no second subprocess runner;
``sot_graph.proc.run_command`` remains the only spawn primitive).

Dispatch argv forms come from the OBSERVED plain-CLI receipts (evidence:
``plan/python-c-monorepo/evidence/p2-runtime-controls.md``, release 46ae198f):
``config set/get auto_watch``, ``cli index_repository --repo-path``. The
``--json`` global flag is a documented silent no-op (rc=0, 0-byte stdout), so
a wrapped MCP envelope is refused as a receipt violation. HONESTY: the
``--args-file`` query transport is NOT yet verified against the release
binary — it stays unwired until a safe live acceptance; validation today is
source-level (per-op argument allowlisting below). The ``config set`` call's
rc=0 output is NOT treated as proof of the mutation — the ``config get``
readback parsing to JSON ``false`` is the SOLE prepare proof, and the
persisted ``_config.db`` (inside ``CBM_CACHE_DIR``, per provenance-upstream)
is re-verified directly.

Whole-flow execution lock: prepare and sync hold ONE reentrant namespace lock
across gate -> spawn -> marker commit (query per dispatch); contention refuses
with NO marker or manifest state change. rc=0 alone never proves success:
every dispatch requires non-empty stdout, and the sync receipt must be a
plain JSON object with ``status == "indexed"`` plus a project binding derived
from ``list_projects`` (exactly one entry whose ``root_path`` realpath equals
the bound repo) — queries reject repo/project/runtime overrides outright and
inject only the verified binding.

Honesty scopes (explicit design): quarantine writes touch ONLY the runtime
profile namespace — never the SOT ledger, source tree, or provider index
(G2). ANY timed-out dispatch persists quarantine and reports
``cancellation_state="cancellation_unknown"``; daemon terminal state is never
claimed from logs. No per-query native ``config get`` (a stray config read
could race validation): the marker binds a db+wal+shm fingerprint computed
after prepare and it is re-verified before every dispatch — a changed config
store refuses the launch.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from sot_graph.locking import WriteLock
from sot_graph.proc import run_command
from sot_graph.provider_contract import normalize_sha256_digest

from .codebase_memory import CodebaseMemoryProvider, ExactCompatibilityContext
from .runtime import PROTOCOL_VERSION, ManagedRuntimeError, ManagedRuntimeProfile

__all__ = ["ManagedResult", "ManagedNativeRuntime", "QUERY_OPERATIONS"]

#: Native READ tools a managed query may dispatch; everything else is denied
#: without spawn. ``trace_path`` is EXPLICITLY excluded until a future wire:
#: its real native parameters (function_name etc.) were never observed, so
#: dispatching it with fabricated arguments is refused.
QUERY_OPERATIONS = frozenset({"search_graph", "index_status", "list_projects"})
#: Source-level per-op argument allowlist: caller args must be a subset.
#: project/repo_path/repo-path/runtime/executable/config keys are never
#: accepted from callers — the executor injects only the verified binding
#: plus the adapter-verified search wire (format=json, bounded limit).
_QUERY_ARG_KEYS: dict[str, frozenset[str]] = {
    "search_graph": frozenset({"query"}),
    "index_status": frozenset(),
    "list_projects": frozenset(),
}
#: ``SymbolRequest.limit`` default in the existing adapter.
_SEARCH_DEFAULT_LIMIT = 20
_SET_OP, _GET_OP = "config_set_auto_watch", "config_get_auto_watch"
_INDEX_OP = "index_repository"
_REQUIRED_OPS = QUERY_OPERATIONS | {_SET_OP, _GET_OP, _INDEX_OP}
_MARKER_NAME, _EXEC_LOCK = "managed-ready.json", "execution.lock"
_CONFIG_DB = "_config.db"  # persisted config store inside CBM_CACHE_DIR
_CONFIG_SIDECARS = ("-wal", "-shm")
#: EXACT schema pinned from the release v0.10.8 scratch store (read via
#: sqlite mode=ro, never mutated):
#: /tmp/sot-p0-scratch/p2-Dyk1ROQZ/home/.cache/codebase-memory-mcp/_config.db
#:   CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)
#:   row ('auto_watch', 'false')
_CONFIG_TABLE, _CONFIG_KEY_COL, _CONFIG_VAL_COL = "config", "key", "value"
#: Accepted persisted representations of "auto_watch is off".
_FALSE_VALUES = (False, 0, "false", "False", "0")
_QUERY_TIMEOUT, _INDEX_TIMEOUT = 30.0, 300.0


@dataclass(frozen=True)
class ManagedResult:
    """Outcome of one managed dispatch; native diagnostics stay withheld."""

    status: str  # ok | not_prepared | denied_operation | gate_refused |
    # runtime_refused | receipt_invalid | timeout
    payload: dict[str, Any] | None = None
    error: str | None = None
    cancellation_state: str | None = None  # None | "cancellation_unknown"
    runtime_state: str = "UNINITIALIZED"


class ManagedNativeRuntime:
    """Bounded executor over one owned profile; never spawns unverified."""

    def __init__(self, profile: ManagedRuntimeProfile, repo_path: str,
                 command: list[str] | tuple[str, ...],
                 exact_context: ExactCompatibilityContext) -> None:
        if not isinstance(exact_context, ExactCompatibilityContext):
            raise ValueError("exact_context is required (no default registry trust)")
        # Reuses the provider's strict ctor validation (single absolute exe,
        # context type checks) plus its per-dispatch digest gate + registry.
        self._provider = CodebaseMemoryProvider(
            command=command, exact_context=exact_context)
        identity = exact_context.runtime_identity
        if identity is None or identity.artifact_sha256 is None:
            raise ValueError("exact context needs a runtime identity with artifact_sha256")
        pinned = normalize_sha256_digest(profile.identity["artifact_digest"])
        if pinned != normalize_sha256_digest(identity.artifact_sha256):
            raise ValueError("profile artifact digest does not match the exact context")
        digests = exact_context.operation_fixture_digests or {}
        missing = sorted(_REQUIRED_OPS - set(digests))
        if missing:
            raise ValueError(f"no fixture digest supplied for operations: {missing}")
        self._profile = profile
        self._repo = os.path.realpath(repo_path)
        self._exe = self._provider.command[0]
        self._marker = profile.namespace / _MARKER_NAME
        self._tmp = profile.paths["tmp"]

    # -------------------------------------------------- public API

    def prepare(self) -> ManagedResult:
        """Create the profile (UI seed) then disable auto_watch with proof.

        The sole proof of the mutation is the ``config get`` readback parsing
        to JSON ``false`` PLUS direct read-only verification of the persisted
        ``_config.db``; the set call's rc=0 output is never trusted. The
        resulting db+wal+shm fingerprint is bound into the readiness marker.
        Idempotent via a valid marker; guards and the marker commit all run
        under one reentrant execution lock. Any failure after initialize
        persists quarantine — a half-prepared profile must never look ready.
        """
        try:
            self._profile.initialize()
        except ManagedRuntimeError as exc:
            return self._result("runtime_refused", error=str(exc))
        with self._locked() as held:
            if not held:
                return self._result("runtime_refused", error=(
                    "execution lock busy (another native call in flight)"))
            verdict, _marker = self._marker_state()
            if verdict == "valid":
                return self._result("ok")
            if verdict == "invalid":
                return self._quarantine("managed-ready marker tampered or foreign")
            for operation in (_SET_OP, _GET_OP):  # gates INSIDE the lock
                refused = self._gate(operation)
                if refused is not None:
                    return refused
            outcome = self._dispatch(_SET_OP,
                                     [self._exe, "config", "set", "auto_watch", "false"],
                                     _QUERY_TIMEOUT, guarded=False)
            if outcome.status != "ok":
                return self._fail_prepare(outcome)
            outcome = self._dispatch(_GET_OP,
                                     [self._exe, "config", "get", "auto_watch"],
                                     _QUERY_TIMEOUT, guarded=False)
            if outcome.status != "ok" or outcome.payload is not None \
                    or outcome.error is not None:
                return self._fail_prepare(outcome, "auto_watch readback not false")
            fields = self._config_fields()
            if fields is None or fields.get("auto_watch") not in _FALSE_VALUES:
                return self._fail_prepare(outcome, "config db does not verify auto_watch=false")
            fingerprint = self._config_fingerprint()
            if fingerprint is None:
                return self._fail_prepare(outcome, "config db fingerprint unavailable")
            if not self._write_marker(fingerprint):
                return self._quarantine("managed-ready marker write failed")
            return self._result("ok")

    def query(self, operation: str, args: Mapping[str, Any]) -> ManagedResult:
        """Read-only native query bound to the verified project binding."""
        if operation not in QUERY_OPERATIONS:
            return self._result("denied_operation",
                                error=f"operation not a managed read: {operation!r}")
        if not isinstance(args, Mapping):
            return self._result("denied_operation", error="args must be a mapping")
        extra = set(args) - _QUERY_ARG_KEYS[operation]
        if extra:
            return self._result("denied_operation", error=(
                f"arguments outside the {operation} allowlist: {sorted(extra)}; "
                "repo/project/runtime overrides are refused"))
        if operation == "search_graph" and "query" not in args:
            return self._result("denied_operation",
                                error="search_graph requires a query argument")
        refused = self._guard_ready(require_binding=True)
        if refused is not None:  # fail-fast before any lock/tmp filesystem use
            return refused
        with self._locked() as held:
            if not held:
                return self._result("runtime_refused", error=(
                    "execution lock busy (another native call in flight)"))
            refused = self._guard_ready(require_binding=True) or self._gate(operation)
            if refused is not None:
                return refused
            payload_args = dict(args)
            if operation != "list_projects":
                # list_projects is global-scoped and takes NO project key
                # (release 46ae source-confirmed); the private namespace's
                # cache can only hold this repo via sync. search_graph /
                # index_status carry the verified binding.
                payload_args["project"] = self._bound_project()
            if operation == "search_graph":  # adapter-verified search wire
                payload_args["format"] = "json"
                payload_args["limit"] = _SEARCH_DEFAULT_LIMIT
            outcome = self._args_dispatch(operation, payload_args, _QUERY_TIMEOUT)
            if operation == "list_projects" and outcome.status == "ok":
                outcome = self._filter_listing(outcome)
            if outcome.status == "timeout":
                # Conservative: a timed-out read normally cannot mutate the
                # index, but an unknown writer cannot be excluded.
                self._profile.quarantine("query deadline expired; possible unknown writer")
                return self._result(outcome.status, outcome.payload, outcome.error,
                                    outcome.cancellation_state)
            return outcome

    def sync(self, repo_path: str) -> ManagedResult:
        """Explicit index of the BOUND repo only; fixed argv, no overrides."""
        if os.path.realpath(repo_path) != self._repo:
            return self._result("denied_operation",
                                error="sync repo does not match the bound profile repo")
        with self._locked() as held:
            if not held:
                return self._result("runtime_refused", error=(
                    "execution lock busy (another native call in flight)"))
            refused = self._guard_ready(require_binding=False) or self._gate(_INDEX_OP)
            if refused is not None:
                return refused
            try:
                self._profile.begin_sync()
            except ManagedRuntimeError as exc:
                return self._result("runtime_refused", error=str(exc))
            argv = [self._exe, "cli", _INDEX_OP, "--repo-path", self._repo]
            outcome = self._dispatch(_INDEX_OP, argv, _INDEX_TIMEOUT, guarded=False)
            # rc=0 alone never proves completion: the synchronous receipt must
            # say status=indexed (observed A1 baseline) and yield a project
            # binding verified via list_projects/root_path, or the sync fails.
            indexed = (outcome.status == "ok" and isinstance(outcome.payload, dict)
                       and outcome.payload.get("status") == "indexed")
            project = self._bind_project(outcome.payload) if indexed else None
            status, error = outcome.status, outcome.error
            if indexed:
                if project is None:
                    indexed, status, error = False, "receipt_invalid", (
                        "index receipt project binding could not be verified "
                        "via list_projects/root_path")
                else:
                    status, error = "ok", None
                    fingerprint = self._config_fingerprint()
                    if fingerprint is None or not self._write_marker(
                            fingerprint, project=project):
                        indexed, status, error = False, "runtime_refused", (
                            "managed-ready marker update failed")
            elif outcome.status == "ok":
                status, error = "receipt_invalid", (
                    "index receipt missing status=indexed; rc=0 alone never "
                    "proves success")
            try:
                self._profile.complete_sync(indexed, indexed)
            except ManagedRuntimeError:
                # completion failure is NEVER reported as ok: safe quarantine
                self._quarantine("sync completion failed; state unproven")
                return self._result("runtime_refused", payload=outcome.payload,
                                    error="sync completion failed; native diagnostic withheld",
                                    cancellation_state=outcome.cancellation_state)
            return self._result(status, payload=outcome.payload, error=error,
                                cancellation_state=outcome.cancellation_state)

    # -------------------------------------------------- internals

    @contextmanager
    def _locked(self) -> Iterator[bool]:
        """Reentrant namespace execution lock; False on contention."""
        lock = WriteLock(str(self._profile.namespace / _EXEC_LOCK), timeout_ms=5_000)
        try:
            lock.acquire()  # nests when this thread already holds it
        except Exception:
            yield False
            return
        try:
            yield True
        finally:
            lock.release()

    def _result(self, status: str, payload: dict[str, Any] | None = None,
                error: str | None = None,
                cancellation_state: str | None = None) -> ManagedResult:
        return ManagedResult(status, payload, error, cancellation_state,
                             self._profile.status()["state"])

    def _quarantine(self, reason: str) -> ManagedResult:
        """Safe helper: persist quarantine if possible, never raise."""
        try:
            self._profile.quarantine(reason)
        except (ManagedRuntimeError, OSError):
            pass  # already refused; report the refusal honestly either way
        return self._result("runtime_refused", error=reason)

    def _fail_prepare(self, outcome: ManagedResult,
                      detail: str | None = None) -> ManagedResult:
        detail = detail or outcome.error or "config dispatch failed"
        self._quarantine(f"prepare failed: {detail}")  # safe helper, never raises
        return self._result("runtime_refused", error=detail,
                            cancellation_state=outcome.cancellation_state)

    def _guard_ready(self, *, require_binding: bool) -> ManagedResult | None:
        """READY + trusted-marker + config-fingerprint check; tamper persists."""
        state = self._profile.status()
        if state["state"] != "READY":
            reason = state.get("reason") or state["state"]
            if "tampered" in reason or "seed" in reason:
                return self._quarantine(reason)
            if state["state"] == "UNINITIALIZED":
                return self._result("not_prepared",
                                    error="prepare() has not run for this profile")
            return self._result("runtime_refused", error=reason)
        verdict, marker = self._marker_state()
        if verdict == "invalid":
            return self._quarantine("managed-ready marker tampered or foreign")
        if verdict == "absent":
            return self._result("not_prepared",
                                error="prepare() has not confirmed this profile")
        if marker is None:
            return self._quarantine("managed-ready marker missing from valid verdict")
        if marker.get("config_fingerprint") != self._config_fingerprint():
            return self._quarantine(
                "config db changed since prepare; auto_watch state unverified")
        if require_binding and not isinstance(marker.get("project"), str):
            return self._result("runtime_refused",
                                error="no verified project binding; run sync() first")
        return None

    def _gate(self, operation: str) -> ManagedResult | None:
        """Exact-compatibility gate: re-hashes the exe, consults the registry."""
        assessment = self._provider._compat_gate(operation)
        if assessment.verdict.value == "compatible":
            return None
        return self._result("gate_refused", error=(
            f"{operation} refused before dispatch: exact-compatibility "
            f"{assessment.verdict.value}; native diagnostic withheld"))

    def _args_dispatch(self, operation: str, args: dict[str, Any],
                       timeout: float) -> ManagedResult:
        """One dispatch with JSON args-file in the private profile tmp."""
        handle, args_file = tempfile.mkstemp(prefix="managed-args-", suffix=".json",
                                             dir=self._tmp)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fp:
                json.dump(args, fp, ensure_ascii=False)
            argv = [self._exe, "cli", operation, "--args-file", args_file]
            return self._dispatch(operation, argv, timeout, guarded=False)
        finally:
            try:
                os.unlink(args_file)
            except OSError:  # pragma: no cover - best-effort cleanup
                pass

    def _dispatch(self, operation: str, argv: list[str], timeout: float,
                  *, guarded: bool = True) -> ManagedResult:
        """Gate (when guarded) + spawn under the reentrant execution lock."""
        with self._locked() as held:
            if not held:
                return self._result("runtime_refused", error=(
                    "execution lock busy (another native call in flight)"))
            if guarded:
                refused = self._guard_ready(require_binding=False) or self._gate(operation)
                if refused is not None:
                    return refused
            try:
                env = self._profile.environment()
            except ManagedRuntimeError as exc:
                return self._result("runtime_refused", error=str(exc))
            return self._run(operation, argv, timeout, env)

    def _run(self, operation: str, argv: list[str], timeout: float,
             env: dict[str, str] | None = None) -> ManagedResult:
        """The single spawn site; classifies the receipt, never raises."""
        result = run_command(argv, cwd=self._repo, env=env,
                             timeout_seconds=timeout, max_output_bytes=8 << 20)
        if result.timed_out:
            return self._result("timeout", error=f"{operation} deadline expired; "
                                "native diagnostic withheld",
                                cancellation_state="cancellation_unknown")
        if result.error is not None:
            return self._result("receipt_invalid",
                                error=f"{operation} could not be spawned; diagnostic withheld")
        if result.returncode != 0 or not result.stdout.strip():
            return self._result("receipt_invalid", error=(
                f"{operation} native receipt invalid (rc={result.returncode}); "
                "native diagnostic withheld"))
        if operation == _SET_OP:
            return self._result("ok")  # set output is NOT proof; readback is
        if operation == _GET_OP:
            try:
                parsed = json.loads(result.stdout)
            except ValueError:
                return self._result("receipt_invalid",
                                    error="auto_watch readback is not plain JSON")
            if parsed is not False:
                return self._result("receipt_invalid",
                                    error="auto_watch readback is not false")
            return self._result("ok")
        try:
            parsed = json.loads(result.stdout)
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            # non-empty garbage / JSON scalars / text tables are NOT success
            return self._result("receipt_invalid", error=(
                f"{operation} receipt is not a plain JSON object; "
                "native diagnostic withheld"))
        if "content" in parsed and "isError" in parsed:
            return self._result("receipt_invalid", error=(
                "legacy MCP-wrapped envelope refused; plain CLI JSON required"))
        return self._result("ok", parsed)

    def _filter_listing(self, outcome: ManagedResult) -> ManagedResult:
        """Public list_projects payload is filtered to the bound repo:
        entries whose root_path realpath is not exactly the bound repo are
        rejected from the response (the owned cache can only hold this repo
        via sync, so a surviving foreign entry would mean foreign data)."""
        payload = outcome.payload or {}
        projects = payload.get("projects")
        if not isinstance(projects, list):
            return outcome
        bound = [p for p in projects
                 if isinstance(p, Mapping) and isinstance(p.get("name"), str)
                 and isinstance(p.get("root_path"), str)
                 and os.path.realpath(p["root_path"]) == self._repo]
        return self._result(outcome.status, {**payload, "projects": bound},
                            outcome.error, outcome.cancellation_state)

    def _bind_project(self, receipt: Any) -> str | None:
        """Verified project binding: exactly one list_projects entry whose
        root_path realpath equals the bound repo; a receipt-claimed project
        must agree. Mirrors the adapter's never-guess resolution."""
        claimed = receipt.get("project") if isinstance(receipt, dict) else None
        outcome = self._args_dispatch("list_projects", {"limit": 50, "offset": 0},
                                      _QUERY_TIMEOUT)
        payload = outcome.payload if isinstance(outcome.payload, dict) else {}
        projects = payload.get("projects")
        if outcome.status != "ok" or payload.get("has_more") \
                or not isinstance(projects, list):
            return None
        matches = sorted({p["name"] for p in projects
                          if isinstance(p, Mapping) and isinstance(p.get("name"), str)
                          and isinstance(p.get("root_path"), str)
                          and os.path.realpath(p["root_path"]) == self._repo})
        if len(matches) != 1 or (claimed is not None and claimed != matches[0]):
            return None
        return matches[0]

    def _config_fields(self) -> dict[str, Any] | None:
        """Read-only field verification of the persisted config store.

        db+wal+shm are COPIED to the private tmp and read from the copy, so
        the live store is never opened for write (WAL recovery side effects).
        EXACT trusted schema (pinned from the release v0.10.8 scratch store,
        see module constants): ``SELECT value FROM config WHERE key = ?``."""
        db = self._profile.paths["cache"] / _CONFIG_DB
        if not db.is_file():
            return None
        with tempfile.TemporaryDirectory(dir=self._tmp) as work:
            for suffix in ("", "-wal", "-shm"):
                src = db.with_name(db.name + suffix)
                if src.is_file():
                    shutil.copy2(src, os.path.join(work, db.name + suffix))
            try:
                conn = sqlite3.connect(os.path.join(work, db.name))
            except sqlite3.Error:
                return None
            try:
                row = conn.execute(
                    f'SELECT "{_CONFIG_VAL_COL}" FROM "{_CONFIG_TABLE}" '
                    f'WHERE "{_CONFIG_KEY_COL}" = ?',
                    ("auto_watch",)).fetchone()
            except sqlite3.Error:
                return None
            finally:
                conn.close()
            return {"auto_watch": row[0]} if row else None
        return None

    def _config_fingerprint(self) -> str | None:
        """sha256 over db+wal+shm presence-and-content (order-stable).

        A harmless WAL checkpoint still flips the fingerprint, which is the
        conservative direction: changed store => no launch until re-prepare."""
        digest = hashlib.sha256()
        for suffix in ("", *_CONFIG_SIDECARS):
            path = (self._profile.paths["cache"] / _CONFIG_DB).with_name(
                _CONFIG_DB + suffix)
            file_hash = hashlib.sha256()
            try:
                with open(path, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1 << 20), b""):
                        file_hash.update(chunk)
            except FileNotFoundError:
                if suffix == "":
                    return None  # the store itself must exist after prepare
                continue  # absent wal/shm is ordinary
            except OSError:
                return None
            digest.update(f"{path.name}\0{file_hash.hexdigest()}\0".encode())
        return digest.hexdigest()

    def _marker_state(self) -> tuple[str, dict[str, Any] | None]:
        """(absent|valid|invalid, marker) — ownership, perms, digest, config."""
        try:
            info = os.lstat(self._marker)
        except FileNotFoundError:
            return "absent", None
        except OSError:
            return "invalid", None
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            return "invalid", None
        try:
            marker = json.loads(self._marker.read_bytes())
            digest_ok = (normalize_sha256_digest(str(marker.get("artifact_sha256")))
                         == normalize_sha256_digest(
                             self._profile.identity["artifact_digest"]))
            valid = (digest_ok
                     and marker.get("protocol_version") == PROTOCOL_VERSION
                     and marker.get("repo") == self._repo
                     and isinstance(marker.get("config"), dict)
                     and marker["config"].get("auto_watch") is False
                     and isinstance(normalize_sha256_digest(
                         str(marker.get("config_fingerprint"))), str))
        except (OSError, ValueError, TypeError):
            return "invalid", None
        return ("valid", marker) if valid else ("invalid", None)

    def _bound_project(self) -> str:
        """Marker-bound project (guard already validated the marker)."""
        marker = json.loads(self._marker.read_bytes())
        project = marker.get("project")
        return project if isinstance(project, str) else ""

    def _write_marker(self, fingerprint: str,
                      project: str | None = None) -> bool:
        """Atomic 0600 marker commit via unique tempfile; False on failure."""
        marker: dict[str, Any] = {
            "protocol_version": PROTOCOL_VERSION,
            "artifact_sha256": self._profile.identity["artifact_digest"],
            "repo": self._repo, "config": {"auto_watch": False},
            "config_fingerprint": fingerprint, "prepared_at": int(time.time())}
        if project is not None:
            marker["project"] = project
        tmp = self._marker.with_name(f".{_MARKER_NAME}.{uuid.uuid4().hex}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, json.dumps(marker, sort_keys=True).encode("utf-8"))
            finally:
                os.close(fd)
            os.replace(tmp, self._marker)
            return True
        except OSError:
            try:
                os.unlink(tmp)  # never leave temp litter in the namespace
            except OSError:
                pass
            return False
