"""P2 managed native executor — unit tests (FAKED run_command; NO native
binary, NO network, NO shell).

Receipt shapes faked here are the exact observed ones (evidence:
``plan/python-c-monorepo/evidence/p2-runtime-controls.md``, release 46ae198f):
``config set auto_watch false`` rc=0 (fake persists ``_config.db`` inside
CBM_CACHE_DIR like the release binary does); ``config get auto_watch`` ->
``false``; ``cli index_repository --repo-path R`` -> plain JSON object with
``project`` + ``status == "indexed"``; ``cli list_projects`` -> one project
whose root_path is the bound repo. 0-byte rc=0 stdout is the documented
silent-no-op failure and must be refused.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.locking import LockTimeoutError, WriteLock  # noqa: E402
from sot_graph.proc import RunResult  # noqa: E402
from sot_graph.provider_contract import (  # noqa: E402
    Capability,
    IntegrationMode,
    ProviderIdentity,
)
from sot_graph.providers.codebase_memory import ExactCompatibilityContext  # noqa: E402
from sot_graph.providers.compatibility import (  # noqa: E402
    CompatibilityRegistry,
    TestedCompatibilityRecord,
)
from sot_graph.providers.managed import QUERY_OPERATIONS  # noqa: E402
from sot_graph.providers.managed import ManagedNativeRuntime  # noqa: E402
from sot_graph.providers.runtime import (  # noqa: E402
    ManagedRuntimeProfile,
    ProfileRejected,
)

FIXTURE = "b" * 64
PROTOCOL = "cbm-cli-json-v1"
VERSION = "0.10.8"
PROVIDER = "codebase-memory"
ALL_OPS = sorted(
    QUERY_OPERATIONS | {"config_set_auto_watch", "config_get_auto_watch",
                        "index_repository"})
ENV_KEYS = {"HOME", "CBM_CACHE_DIR", "CBM_RUNTIME_DIR", "XDG_CONFIG_HOME",
            "TMPDIR", "PATH", "TERM"}


# ------------------------------------------------------------- fake machinery

class FakeNative:
    """Stands in for sot_graph.proc.run_command; records every call and
    simulates the native's observable FILESYSTEM effects only (the config db
    persistence) — no process is ever spawned."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._handler = None
        self.repo: str | None = None
        self._env: dict[str, str] = {}

    def __call__(self, argv, cwd=None, env=None, timeout_seconds=None,
                 max_output_bytes=None, **_kw):
        args_content = None
        if "--args-file" in argv:  # the native reads the file DURING the call
            path = Path(argv[argv.index("--args-file") + 1])
            args_content = path.read_text(encoding="utf-8") if path.exists() else None
        self.calls.append({"argv": list(argv), "cwd": cwd,
                           "env": dict(env or {}), "timeout": timeout_seconds,
                           "args_content": args_content})
        self._env = dict(env or {})
        handler = self._handler or self._receipts
        return handler(list(argv))

    # -- built-in observed receipts ------------------------------------------

    def _receipts(self, argv: list[str]) -> RunResult:
        if argv[1:3] == ["config", "set"]:
            self._persist_config_db()
            return _rc0("auto_watch=false\n")
        if argv[1:3] == ["config", "get"]:
            return _rc0("false\n")
        if argv[1:3] == ["cli", "index_repository"]:
            return _rc0(json.dumps({"project": "proj", "nodes": 1, "edges": 2,
                                    "status": "indexed"}) + "\n")
        if argv[1:3] == ["cli", "list_projects"]:
            return _rc0(json.dumps(
                {"projects": [{"name": "proj", "root_path": self.repo}],
                 "has_more": False}) + "\n")
        return _rc0(json.dumps({"rows": [], "has_more": False}) + "\n")

    def _persist_config_db(self) -> None:
        """The release binary persists auto_watch into ``_config.db`` inside
        CBM_CACHE_DIR (provenance-upstream.md; cli.h:397-401)."""
        cache = self._env.get("CBM_CACHE_DIR")
        if not cache:
            return
        db = Path(cache) / "_config.db"
        for sidecar in ("-wal", "-shm"):
            Path(str(db) + sidecar).unlink(missing_ok=True)
        db.unlink(missing_ok=True)
        conn = sqlite3.connect(db)
        try:
            # EXACT schema of the release v0.10.8 store (scratch _config.db)
            conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO config VALUES ('auto_watch', 'false')")
            conn.commit()
        finally:
            conn.close()


def _rc0(stdout: str, argv: tuple[str, ...] = ()) -> RunResult:
    return RunResult(argv=argv, returncode=0, stdout=stdout, stderr="",
                     timed_out=False, truncated=False, error=None)


def _timeout(argv: tuple[str, ...] = ()) -> RunResult:
    return RunResult(argv=argv, returncode=None, stdout="", stderr="",
                     timed_out=True, truncated=False, error=None)


def _mk_repo(base: Path) -> Path:
    repo = base / "repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    return repo


def _make_exe(directory: Path, body: bytes = b"#!/bin/fake-cbm\n") -> tuple[str, str]:
    """A plain artifact FILE — never executed (run_command is faked); it only
    needs exact on-disk bytes for the compat gate to hash every dispatch."""
    path = directory / "cbm-fake"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return str(path), hashlib.sha256(body).hexdigest()


def _context(artifact: str, ops=ALL_OPS, fixture: str = FIXTURE) -> ExactCompatibilityContext:
    registry = CompatibilityRegistry()
    for operation in ops:
        registry.register(TestedCompatibilityRecord(
            provider_name=PROVIDER, operation=operation,
            artifact_sha256=artifact, fixture_digest=fixture,
            protocol_compatibility_id=PROTOCOL, version=VERSION))
    return ExactCompatibilityContext(
        registry=registry,
        runtime_identity=ProviderIdentity(
            name=PROVIDER, version=VERSION, mode=IntegrationMode.FEDERATED_CLI,
            capability=Capability.SYMBOLS, artifact_sha256=artifact,
            protocol_compatibility_id=PROTOCOL),
        operation_fixture_digests={op: fixture for op in ops},
        protocol_compatibility_id=PROTOCOL)


def _runtime(tmp_path: Path, native: FakeNative, *, ops=ALL_OPS):
    """Profile + executor whose pinned digest is the fake artifact's digest."""
    root, repo = tmp_path / "root", _mk_repo(tmp_path / "w")
    exe, exe_digest = _make_exe(tmp_path / "bin")
    profile = ManagedRuntimeProfile(str(root), str(repo),
                                    artifact_digest=exe_digest)
    runtime = ManagedNativeRuntime(profile, str(repo), (exe,),
                                   _context(exe_digest, ops=ops))
    native.repo = str(repo)
    return runtime, profile, repo, exe


def _prepared(tmp_path: Path, native: FakeNative):
    """Runtime taken through prepare AND sync (verified project binding)."""
    runtime, profile, repo, exe = _runtime(tmp_path, native)
    assert runtime.prepare().status == "ok"
    assert runtime.sync(str(repo)).status == "ok"
    native.calls.clear()
    return runtime, profile, repo, exe


def _config_db(profile: ManagedRuntimeProfile) -> Path:
    return profile.paths["cache"] / "_config.db"


@pytest.fixture()
def native(monkeypatch):
    fake = FakeNative()
    import sot_graph.providers.managed as managed
    monkeypatch.setattr(managed, "run_command", fake)
    return fake


# ------------------------------------------------------- constructor guards

def test_ctor_rejects_profile_context_digest_mismatch(tmp_path) -> None:
    root, repo = tmp_path / "root", _mk_repo(tmp_path / "w")
    exe, exe_digest = _make_exe(tmp_path / "bin")
    profile = ManagedRuntimeProfile(str(root), str(repo),
                                    artifact_digest="a" * 64)  # != exe digest
    with pytest.raises(ValueError, match="does not match"):
        ManagedNativeRuntime(profile, str(repo), (exe,), _context(exe_digest))


def test_ctor_rejects_missing_fixture_digests(tmp_path) -> None:
    root, repo = tmp_path / "root", _mk_repo(tmp_path / "w")
    exe, exe_digest = _make_exe(tmp_path / "bin")
    profile = ManagedRuntimeProfile(str(root), str(repo),
                                    artifact_digest=exe_digest)
    with pytest.raises(ValueError, match="fixture digest"):
        ManagedNativeRuntime(profile, str(repo), (exe,),
                             _context(exe_digest, ops=["search_graph"]))


def test_ctor_rejects_non_context(tmp_path) -> None:
    root, repo = tmp_path / "root", _mk_repo(tmp_path / "w")
    exe, exe_digest = _make_exe(tmp_path / "bin")
    profile = ManagedRuntimeProfile(str(root), str(repo),
                                    artifact_digest=exe_digest)
    with pytest.raises(ValueError, match="exact_context"):
        ManagedNativeRuntime(profile, str(repo), (exe,), None)  # type: ignore[arg-type]


# ------------------------------------------------------- missing prepare

def test_query_missing_prepare_no_filesystem(tmp_path, native) -> None:
    runtime, _profile, _repo, _exe = _runtime(tmp_path, native)
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "not_prepared"
    assert not (tmp_path / "root").exists()  # pure-read refusal created nothing
    assert native.calls == []


# ------------------------------------------------------- prepare

def test_prepare_exact_argv_env_and_marker(tmp_path, native, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "leak-me")
    runtime, profile, _repo, exe = _runtime(tmp_path, native)
    result = runtime.prepare()
    assert result.status == "ok" and result.runtime_state == "READY"
    assert [c["argv"] for c in native.calls] == [
        [exe, "config", "set", "auto_watch", "false"],
        [exe, "config", "get", "auto_watch"]]
    for call in native.calls:  # 7-key replacement env; no inherited secrets
        assert set(call["env"]) == ENV_KEYS
        assert call["env"]["PATH"] == "/usr/bin:/bin"
        assert "SECRET_TOKEN" not in call["env"]
    marker = profile.namespace / "managed-ready.json"
    info = marker.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_mode & 0o777 == 0o600
    content = json.loads(marker.read_bytes())
    assert content["config"] == {"auto_watch": False}
    assert len(content["config_fingerprint"]) == 64  # db+wal+shm binding
    assert "project" not in content  # binding only after a verified sync


def test_prepare_idempotent_reuse_valid_marker_no_respawn(tmp_path, native) -> None:
    runtime, _profile, _repo, _exe = _runtime(tmp_path, native)
    assert runtime.prepare().status == "ok"
    assert len(native.calls) == 2
    assert runtime.prepare().status == "ok"
    assert len(native.calls) == 2  # reused the trusted marker, no re-dispatch


def test_prepare_readback_true_quarantines_no_marker(tmp_path, native) -> None:
    def handler(argv):
        if argv[1:3] == ["config", "set"]:
            return native._receipts(argv)  # db persisted, output not trusted
        return _rc0("true\n")  # observed-shape violation: readback is not false

    native._handler = handler
    runtime, profile, _repo, _exe = _runtime(tmp_path, native)
    result = runtime.prepare()
    assert result.status == "runtime_refused"
    assert "not false" in (result.error or "")
    assert not (profile.namespace / "managed-ready.json").exists()
    assert profile.status()["state"] == "QUARANTINED"


def test_prepare_db_field_verification_failure_quarantines(tmp_path, native) -> None:
    runtime, profile, _repo, _exe = _runtime(tmp_path, native)

    def handler(argv):
        if argv[1:3] == ["config", "set"]:
            native._receipts(argv)  # native claims rc=0 but persists a lie
            conn = sqlite3.connect(_config_db(profile))
            try:
                conn.execute("UPDATE config SET value='true' WHERE key='auto_watch'")
                conn.commit()
            finally:
                conn.close()
            return _rc0("auto_watch=false\n")
        if argv[1:3] == ["config", "get"]:
            return _rc0("false\n")  # readback agrees; the persisted db disagrees
        return _rc0(json.dumps({"rows": []}) + "\n")

    native._handler = handler
    result = runtime.prepare()
    assert result.status == "runtime_refused"
    assert "does not verify" in (result.error or "")
    assert not (profile.namespace / "managed-ready.json").exists()
    assert profile.status()["state"] == "QUARANTINED"


def test_prepare_timeout_no_success_no_marker_no_retry(tmp_path, native) -> None:
    native._handler = lambda argv: _timeout(tuple(argv))
    runtime, profile, _repo, _exe = _runtime(tmp_path, native)
    result = runtime.prepare()
    assert result.status == "runtime_refused"
    assert result.cancellation_state == "cancellation_unknown"
    assert not (profile.namespace / "managed-ready.json").exists()
    assert profile.status()["state"] == "QUARANTINED"
    before = len(native.calls)
    assert runtime.query("search_graph", {"query": "x"}).status == "runtime_refused"
    assert len(native.calls) == before  # quarantined profile: no retry spawn


def test_prepare_gate_refusal_before_any_launch(tmp_path, native) -> None:
    runtime, profile, _repo, exe = _runtime(tmp_path, native)
    os.unlink(exe)  # artifact not readable -> digest gate UNKNOWN
    result = runtime.prepare()
    assert result.status == "gate_refused"
    assert native.calls == []  # guarded BEFORE the first mutation launch
    assert not (profile.namespace / "managed-ready.json").exists()
    assert profile.status()["state"] == "READY"  # evidence absence is not tamper


def test_marker_write_failure_persists_quarantine(tmp_path, native, monkeypatch) -> None:
    runtime, profile, _repo, _exe = _runtime(tmp_path, native)
    real_replace = os.replace

    def failing_replace(src, dst, *a, **k):
        if str(dst).endswith("managed-ready.json"):
            raise OSError("marker commit refused")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", failing_replace)
    result = runtime.prepare()
    assert result.status == "runtime_refused"
    assert "marker write failed" in (result.error or "")
    assert not (profile.namespace / "managed-ready.json").exists()
    assert profile.status()["state"] == "QUARANTINED"
    assert not [p for p in profile.namespace.iterdir() if p.name.endswith(".tmp")]


# ------------------------------------------------------- query

def test_query_dispatch_args_file_env_and_cleanup(tmp_path, native, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "leak-me")
    runtime, profile, repo, exe = _prepared(tmp_path, native)
    result = runtime.query("search_graph", {"query": "run_command"})
    assert result.status == "ok"
    assert result.payload == {"rows": [], "has_more": False}
    assert result.runtime_state == "READY" and result.cancellation_state is None
    call = native.calls[0]
    assert call["argv"] == [exe, "cli", "search_graph", "--args-file",
                            call["argv"][-1]]
    # the verified binding is INJECTED plus the adapter-verified search wire
    assert json.loads(call["args_content"]) == {
        "query": "run_command", "project": "proj",
        "format": "json", "limit": 20}
    args_file = Path(call["argv"][-1])
    assert not args_file.exists()  # cleaned up after the dispatch
    assert args_file.parent == profile.paths["tmp"]
    assert call["cwd"] == str(repo)
    assert set(call["env"]) == ENV_KEYS and "SECRET_TOKEN" not in call["env"]


def test_query_requires_verified_project_binding(tmp_path, native) -> None:
    runtime, profile, repo, _exe = _runtime(tmp_path, native)
    assert runtime.prepare().status == "ok"
    native.calls.clear()
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "runtime_refused"
    assert "project binding" in (result.error or "")
    assert native.calls == []  # never spawn a query without the binding
    assert runtime.sync(str(repo)).status == "ok"  # binding established
    assert runtime.query("search_graph", {"query": "x"}).status == "ok"


def test_query_denies_mutations_unknown_ops_and_overrides(tmp_path, native) -> None:
    runtime, _profile, _repo, _exe = _runtime(tmp_path, native)
    assert runtime.prepare().status == "ok"
    native.calls.clear()
    for operation, args in (("index_repository", {}), ("config_set_auto_watch", {}),
                            ("delete_index", {}), ("", {}),
                            ("trace_path", {"query": "x"}),
                            ("search_graph", {}),  # missing required query
                            ("search_graph", {"query": "x", "repo_path": "/etc"}),
                            ("search_graph", {"query": "x", "repo-path": "/etc"}),
                            ("search_graph", {"query": "x", "project": "proj"}),
                            ("search_graph", {"query": "x", "executable": "/bin/sh"}),
                            ("search_graph", {"query": "x", "persist": True})):
        result = runtime.query(operation, args)
        assert result.status == "denied_operation"
    assert native.calls == []


def test_query_trace_path_explicitly_denied_no_spawn(tmp_path, native) -> None:
    # trace_path's real native parameters were never observed; fabricated
    # arguments are refused until a future wire exists.
    runtime, _profile, _repo, _exe = _prepared(tmp_path, native)
    result = runtime.query("trace_path", {"query": "x"})
    assert result.status == "denied_operation"
    assert "trace_path" in (result.error or "")
    assert native.calls == []


def test_query_malformed_receipt_never_succeeds(tmp_path, native) -> None:
    runtime, _profile, _repo, _exe = _prepared(tmp_path, native)
    for stdout in ("[1, 2]", '"scalar"', "junk", "total: 1\nresults: x"):
        native._handler = lambda argv, s=stdout: _rc0(s)
        result = runtime.query("search_graph", {"query": "x"})
        assert result.status == "receipt_invalid", stdout
        assert result.payload is None  # non-dict receipts are never ok


def test_query_refuses_legacy_wrapped_envelope(tmp_path, native) -> None:
    runtime, _profile, _repo, _exe = _prepared(tmp_path, native)
    wrapped = json.dumps({"content": [{"type": "text", "text": "{}"}],
                          "isError": False, "structuredContent": {}})
    native._handler = lambda argv: _rc0(wrapped)
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "receipt_invalid"
    assert "wrapped" in (result.error or "")


def test_query_empty_stdout_silent_noop_refused(tmp_path, native) -> None:
    runtime, _profile, _repo, _exe = _prepared(tmp_path, native)
    native._handler = lambda argv: _rc0("")  # 0-byte stdout rc=0 (documented)
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "receipt_invalid"
    assert native.calls[0]["argv"][2:4] == ["search_graph", "--args-file"]


def test_query_timeout_conservative_quarantine(tmp_path, native) -> None:
    runtime, profile, _repo, _exe = _prepared(tmp_path, native)
    native._handler = lambda argv: _timeout(tuple(argv))
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "timeout"
    assert result.cancellation_state == "cancellation_unknown"
    assert profile.status()["state"] == "QUARANTINED"  # conservative, sticky


def test_query_gate_digest_swap_refused_no_spawn(tmp_path, native) -> None:
    runtime, profile, _repo, exe = _prepared(tmp_path, native)
    Path(exe).write_bytes(b"#!/bin/swapped\n")  # new bytes = new digest
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "gate_refused"
    assert native.calls == []
    assert profile.status()["state"] == "READY"  # refusal, not tamper


def test_config_db_tamper_refused_no_spawn(tmp_path, native) -> None:
    runtime, profile, _repo, _exe = _prepared(tmp_path, native)
    with open(_config_db(profile), "ab") as handle:  # store changed post-prepare
        handle.write(b"tampered")
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "runtime_refused"
    assert "config db changed" in (result.error or "")
    assert native.calls == []  # no launch before bad config is resolved
    assert profile.status()["state"] == "QUARANTINED"


def test_config_wal_appearance_refused_no_spawn(tmp_path, native) -> None:
    runtime, profile, _repo, _exe = _prepared(tmp_path, native)
    Path(str(_config_db(profile)) + "-wal").write_bytes(b"wal-bytes")
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "runtime_refused"  # wal is part of the fingerprint
    assert native.calls == []


# ------------------------------------------------------- sync

def test_sync_rejects_wrong_repo_no_state_change(tmp_path, native) -> None:
    runtime, profile, repo, _exe = _runtime(tmp_path, native)
    runtime.prepare()
    other = _mk_repo(tmp_path / "other")
    result = runtime.sync(str(other))
    assert result.status == "denied_operation"
    assert native.calls[-1]["argv"][1:3] == ["config", "get"]  # no index spawn
    assert profile.status()["state"] == "READY"


def test_sync_index_receipt_status_indexed_completes(tmp_path, native) -> None:
    runtime, profile, repo, exe = _runtime(tmp_path, native)
    runtime.prepare()
    native.calls.clear()
    result = runtime.sync(str(repo))
    assert result.status == "ok"
    assert result.payload is not None and result.payload["status"] == "indexed"
    assert native.calls[0]["argv"] == [exe, "cli", "index_repository",
                                       "--repo-path", str(repo)]
    assert native.calls[0]["timeout"] == 300.0
    assert native.calls[1]["argv"][2:3] == ["list_projects"]  # binding verified
    manifest = json.loads((profile.namespace / "manifest.json").read_bytes())
    assert manifest["state"] == "READY"  # synchronous receipt completed the sync
    assert manifest["last_complete"] == {"terminal_confirmed": True,
                                         "success": True}
    marker = json.loads((profile.namespace / "managed-ready.json").read_bytes())
    assert marker["project"] == "proj"  # verified binding owned by the marker


def test_sync_unverifiable_project_binding_fails(tmp_path, native) -> None:
    def handler(argv):
        if argv[1:3] in (["config", "set"], ["config", "get"]):
            return native._receipts(argv)
        if argv[1:3] == ["cli", "index_repository"]:
            return _rc0(json.dumps({"project": "proj",
                                    "status": "indexed"}) + "\n")
        if argv[1:3] == ["cli", "list_projects"]:  # binding escapes the root
            return _rc0(json.dumps(
                {"projects": [{"name": "proj", "root_path": "/somewhere/else"}],
                 "has_more": False}) + "\n")
        return _rc0(json.dumps({"rows": []}) + "\n")

    native._handler = handler
    runtime, profile, repo, _exe = _runtime(tmp_path, native)
    runtime.prepare()
    native.calls.clear()
    result = runtime.sync(str(repo))
    assert result.status == "receipt_invalid"
    assert "project binding" in (result.error or "")
    manifest = json.loads((profile.namespace / "manifest.json").read_bytes())
    assert manifest["state"] == "QUARANTINED"
    marker = json.loads((profile.namespace / "managed-ready.json").read_bytes())
    assert "project" not in marker  # no unverified binding is ever recorded


def test_sync_rc0_without_indexed_receipt_quarantines(tmp_path, native) -> None:
    def handler(argv):
        if argv[1:3] in (["config", "set"], ["config", "get"]):
            return native._receipts(argv)
        return _rc0("{}\n")  # rc=0 but no status=indexed receipt

    native._handler = handler
    runtime, profile, repo, _exe = _runtime(tmp_path, native)
    runtime.prepare()
    native.calls.clear()
    result = runtime.sync(str(repo))
    assert result.status == "receipt_invalid"
    manifest = json.loads((profile.namespace / "manifest.json").read_bytes())
    assert manifest["state"] == "QUARANTINED"  # rc=0 alone never proves success


def test_sync_timeout_persists_cancellation_unknown(tmp_path, native) -> None:
    def handler(argv):
        if argv[1:3] in (["config", "set"], ["config", "get"]):
            return native._receipts(argv)
        return _timeout(tuple(argv))

    native._handler = handler
    runtime, profile, repo, _exe = _runtime(tmp_path, native)
    runtime.prepare()
    native.calls.clear()
    result = runtime.sync(str(repo))
    assert result.status == "timeout"
    assert result.cancellation_state == "cancellation_unknown"
    manifest = json.loads((profile.namespace / "manifest.json").read_bytes())
    assert manifest["state"] == "QUARANTINED"  # never claim terminal from logs


def test_complete_sync_failure_is_nonok_and_quarantines(tmp_path, native,
                                                        monkeypatch) -> None:
    runtime, profile, repo, _exe = _runtime(tmp_path, native)
    runtime.prepare()
    native.calls.clear()

    def broken_complete(terminal_confirmed, success):
        raise ProfileRejected("no sync owned by this thread")

    monkeypatch.setattr(profile, "complete_sync", broken_complete)
    result = runtime.sync(str(repo))
    assert result.status == "runtime_refused"  # NEVER error-with-ok
    assert result.status != "ok" and "completion failed" in (result.error or "")
    assert profile.status()["state"] == "QUARANTINED"


def test_quarantine_failure_still_nonok(tmp_path, native, monkeypatch) -> None:
    """Even when persisting quarantine itself fails, outcomes stay non-ok."""

    def failing_quarantine(reason):
        raise OSError("manifest unwritable")

    # (1) prepare failure routed through the safe _quarantine helper
    runtime, profile, _repo, _exe = _runtime(tmp_path, native)
    monkeypatch.setattr(profile, "quarantine", failing_quarantine)

    def handler(argv):
        if argv[1:3] == ["config", "set"]:
            return native._receipts(argv)
        return _rc0("true\n")  # readback violation -> prepare must fail

    native._handler = handler
    assert runtime.prepare().status == "runtime_refused"  # no raise

    # (2) sync completion failure where the quarantine write also fails
    native._handler = None  # observed receipts again
    runtime2, profile2, repo2, _exe2 = _runtime(tmp_path, native)
    assert runtime2.prepare().status == "ok"
    monkeypatch.setattr(profile2, "quarantine", failing_quarantine)

    def broken_complete(terminal_confirmed, success):
        raise ProfileRejected("no sync owned by this thread")

    monkeypatch.setattr(profile2, "complete_sync", broken_complete)
    result = runtime2.sync(str(repo2))
    assert result.status == "runtime_refused"
    assert result.status != "ok"


def test_sync_lock_busy_refused_without_state_change(tmp_path, native,
                                                     monkeypatch) -> None:
    runtime, profile, repo, _exe = _runtime(tmp_path, native)
    runtime.prepare()
    manifest_before = (profile.namespace / "manifest.json").read_bytes()
    marker_before = (profile.namespace / "managed-ready.json").read_bytes()
    calls_before = len(native.calls)

    def held(self):
        raise LockTimeoutError("Could not acquire write lock (held by test)")

    monkeypatch.setattr(WriteLock, "acquire", held)
    result = runtime.sync(str(repo))
    assert result.status == "runtime_refused"
    assert "lock busy" in (result.error or "")
    assert len(native.calls) == calls_before  # no spawn under contention
    assert (profile.namespace / "manifest.json").read_bytes() == manifest_before
    assert (profile.namespace / "managed-ready.json").read_bytes() == marker_before


def test_query_lock_busy_refused_no_spawn(tmp_path, native, monkeypatch) -> None:
    runtime, _profile, _repo, _exe = _prepared(tmp_path, native)

    def held(self):
        raise LockTimeoutError("Could not acquire write lock (held by test)")

    monkeypatch.setattr(WriteLock, "acquire", held)
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "runtime_refused"
    assert "lock busy" in (result.error or "")
    assert native.calls == []


# ------------------------------------------------------- tamper

def test_marker_tamper_refuses_and_persists_quarantine(tmp_path, native) -> None:
    runtime, profile, _repo, _exe = _prepared(tmp_path, native)
    marker = profile.namespace / "managed-ready.json"
    tampered = json.loads(marker.read_bytes())
    tampered["artifact_sha256"] = "c" * 64
    marker.write_bytes(json.dumps(tampered).encode())
    native.calls.clear()
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "runtime_refused"
    assert native.calls == []
    assert profile.status()["state"] == "QUARANTINED"


def test_marker_loose_permissions_refused(tmp_path, native) -> None:
    runtime, profile, _repo, _exe = _prepared(tmp_path, native)
    os.chmod(profile.namespace / "managed-ready.json", 0o644)
    result = runtime.query("search_graph", {"query": "x"})
    assert result.status == "runtime_refused"
    assert profile.status()["state"] == "QUARANTINED"


# ------------------------------------------------------- G2

def test_g2_source_tree_untouched_by_all_flows(tmp_path, native) -> None:
    runtime, _profile, repo, _exe = _runtime(tmp_path, native)

    def tree_digest() -> str:
        return hashlib.sha256(b"".join(
            p.read_bytes() for p in sorted(repo.rglob("*")) if p.is_file())
        ).hexdigest()

    before = tree_digest()
    runtime.prepare()
    runtime.sync(str(repo))
    runtime.query("search_graph", {"query": "x"})
    runtime.query("search_graph", {"query": "x"})
    assert tree_digest() == before  # quarantine/marker writes stay in the namespace
    assert not list(repo.rglob("managed-ready.json"))
