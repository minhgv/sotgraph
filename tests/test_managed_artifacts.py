"""Managed-artifact lifecycle (P4, programmatic) — tamper/refusal guarantees.

NO real binary and NO process spawn: an autouse fixture monkeypatches every
spawn site (subprocess + os spawn/exec) so any hidden dispatch fails loudly.
Covers: exact-schema manifest pins (digest/platform/protocol/engine_commit),
staged digest verification, idempotent re-import (never overwrite/adopt),
fail-closed refusals (symlink, unowned, insecure root, traversal), atomic
promotion pointer (failure keeps old pointer), and stage-failure temp
cleanup of ONLY newly created temps.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import subprocess
import threading
from pathlib import Path

import pytest

from sot_graph.locking import LockTimeoutError, WriteLock
from sot_graph.providers import artifacts
from sot_graph.providers.artifacts import (
    ARTIFACT_PROTOCOL_VERSION,
    ArtifactRejected,
    ArtifactStore,
    host_platform,
)


@pytest.fixture(autouse=True)
def _no_process_spawn(monkeypatch):
    """Zero-spawn guard: any subprocess/os spawn attempt fails the test."""
    def _boom(*args, **kwargs):
        raise AssertionError("managed artifacts must never spawn a process")
    for site in ("Popen", "run", "call", "check_call", "check_output",
                 "getoutput", "getstatusoutput"):
        monkeypatch.setattr(subprocess, site, _boom)
    for site in ("posix_spawn", "posix_spawnp", "spawnv", "spawnve", "spawnvp",
                 "spawnvpe", "execv", "execve", "execvp", "execvpe",
                 "system", "popen"):
        if hasattr(os, site):
            monkeypatch.setattr(os, site, _boom)


@pytest.fixture
def layout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo, tmp_path / "admin" / "artifact-root"


@pytest.fixture
def store(layout):
    repo, root = layout
    return ArtifactStore(root, repo_path=repo)


def _write_source(path: Path, payload: bytes = b"#!/bin/sh\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _manifest_bytes(source: Path, **overrides) -> bytes:
    data = {
        "schema_version": 1,
        "name": "demo-engine",
        "digest": hashlib.sha256(source.read_bytes()).hexdigest(),
        "platform": host_platform(),
        "protocol": ARTIFACT_PROTOCOL_VERSION,
        "engine_commit": "a" * 40,
    }
    data.update(overrides)
    return json.dumps(data).encode("utf-8")


class _OsShim:
    """Delegating ``os`` shim injected as ``artifacts.os`` for fault tests."""

    def __init__(self, real):
        self._real = real
        self.fail_manifest = False
        self.fail_rename = 0
        self.fail_replace = 0
        self.swap_source: Path | None = None
        self.plant_empty: Path | None = None  # planted once, then normal open

    def __getattr__(self, name):
        return getattr(self._real, name)

    def open(self, path, *args, **kwargs):
        resolved = os.fspath(path)
        if self.plant_empty is not None and resolved.endswith("manifest.json"):
            planted, self.plant_empty = self.plant_empty, None
            self._real.makedirs(planted, exist_ok=True)
        if self.swap_source is not None and resolved.endswith("/engine"):
            resolved = os.fspath(self.swap_source)
        if self.fail_manifest and resolved.endswith("manifest.json"):
            raise OSError(errno.ENOSPC, "injected ENOSPC on manifest write")
        return self._real.open(resolved, *args, **kwargs)

    def rename(self, src, dst):
        if self.fail_rename:
            self.fail_rename -= 1
            raise OSError(errno.ENOSPC, "injected rename failure")
        return self._real.rename(src, dst)

    def replace(self, src, dst):
        if self.fail_replace:
            self.fail_replace -= 1
            raise OSError(errno.ENOSPC, "injected replace failure")
        return self._real.replace(src, dst)


# ------------------------------------------------------------------ #
# happy path + idempotence                                            #
# ------------------------------------------------------------------ #
def test_import_returns_absolute_verified_executable(store, tmp_path):
    src = _write_source(tmp_path / "bin" / "engine")
    desc = store.import_artifact(src, _manifest_bytes(src))
    exe = Path(desc.executable)
    assert exe.is_absolute() and exe.is_file()
    assert hashlib.sha256(exe.read_bytes()).hexdigest() == desc.digest
    assert stat.S_IMODE(exe.lstat().st_mode) & stat.S_IXUSR  # executable
    assert not stat.S_IMODE(store.root.lstat().st_mode) & 0o077  # private root
    assert Path(desc.manifest_path).is_absolute()


def test_reimport_idempotent_never_rewrites(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    first = store.import_artifact(src, _manifest_bytes(src))
    exe = Path(first.executable)
    before = (exe.lstat().st_ino, exe.lstat().st_mtime_ns, exe.read_bytes())
    second = store.import_artifact(src, _manifest_bytes(src))
    assert second == first
    after = (exe.lstat().st_ino, exe.lstat().st_mtime_ns, exe.read_bytes())
    assert after == before


def test_resolve_before_any_import_is_none_and_creates_no_root(layout):
    repo, root = layout
    assert ArtifactStore(root, repo_path=repo).resolve("demo-engine") is None
    assert not root.exists()  # read-only path must not create the root


# ------------------------------------------------------------------ #
# manifest schema / platform / protocol refusals                      #
# ------------------------------------------------------------------ #
def test_digest_mismatch_refused_and_temps_cleaned(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    manifest = _manifest_bytes(src, digest="b" * 64)
    with pytest.raises(ArtifactRejected, match="digest mismatch"):
        store.import_artifact(src, manifest)
    assert not list((store.root / "tmp").glob("*"))  # only-our-temp cleanup


def test_platform_mismatch_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    with pytest.raises(ArtifactRejected, match="does not match host"):
        store.import_artifact(src, _manifest_bytes(src, platform="haiku-riscv64"))


def test_protocol_mismatch_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    with pytest.raises(ArtifactRejected, match="protocol"):
        store.import_artifact(src, _manifest_bytes(src, protocol="artifacts-v0"))


def test_unknown_field_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    data = json.loads(_manifest_bytes(src))
    data["extra"] = 1
    with pytest.raises(ArtifactRejected, match=r"unknown=\['extra'\]"):
        store.import_artifact(src, json.dumps(data).encode())


def test_missing_field_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    data = json.loads(_manifest_bytes(src))
    del data["engine_commit"]
    with pytest.raises(ArtifactRejected, match="missing"):
        store.import_artifact(src, json.dumps(data).encode())


def test_malformed_digest_and_bad_name_and_commit_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    with pytest.raises(ArtifactRejected, match="malformed sha256"):
        store.import_artifact(src, _manifest_bytes(src, digest="deadbeef"))
    with pytest.raises(ArtifactRejected, match="invalid artifact name"):
        store.import_artifact(src, _manifest_bytes(src, name="../evil"))
    with pytest.raises(ArtifactRejected, match="invalid engine_commit"):
        store.import_artifact(src, _manifest_bytes(src, engine_commit="release-1"))


def test_bad_schema_version_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    with pytest.raises(ArtifactRejected, match="schema_version"):
        store.import_artifact(src, _manifest_bytes(src, schema_version=2))


# ------------------------------------------------------------------ #
# source / root ownership refusals                                    #
# ------------------------------------------------------------------ #
def test_symlink_source_refused(store, tmp_path):
    real = _write_source(tmp_path / "engine")
    link = tmp_path / "engine-link"
    link.symlink_to(real)
    with pytest.raises(ArtifactRejected, match="source binary is a symlink"):
        store.import_artifact(link, _manifest_bytes(real))


def test_insecure_existing_root_refused_and_untouched(layout, tmp_path):
    repo, root = layout
    root.mkdir(parents=True)
    os.chmod(root, 0o755)
    marker = root / "operator-data.txt"
    marker.write_text("keep me")
    src = _write_source(tmp_path / "engine")
    with pytest.raises(ArtifactRejected, match="unsafe permissions"):
        ArtifactStore(root, repo_path=repo).import_artifact(src, _manifest_bytes(src))
    assert stat.S_IMODE(root.lstat().st_mode) == 0o755  # never chmod existing root
    assert marker.read_text() == "keep me"
    assert not (root / "write.lock").exists()  # refused before any mutation


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0,
                    reason="chown to a different uid requires root")
def test_unowned_source_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    try:
        os.chown(src, 65534, -1)
    except OSError:
        pytest.skip("no secondary uid available")
    with pytest.raises(ArtifactRejected, match="not owned by current user"):
        store.import_artifact(src, _manifest_bytes(src))


def test_root_inside_repo_refused(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ArtifactRejected, match="disjoint"):
        ArtifactStore(repo / "store", repo_path=repo)


def test_repo_inside_root_refused(tmp_path):
    root = tmp_path / "admin" / "root"
    repo = root / "repo"
    repo.mkdir(parents=True)
    with pytest.raises(ArtifactRejected, match="disjoint"):
        ArtifactStore(root, repo_path=repo)


def test_relative_root_refused(layout):
    with pytest.raises(ArtifactRejected, match="absolute and symlink-free"):
        ArtifactStore("relative-root", repo_path=layout[0])


def test_symlinked_root_refused(layout, tmp_path):
    repo, root = layout
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = tmp_path / "root-link"
    link.symlink_to(real)
    with pytest.raises(ArtifactRejected, match="absolute and symlink-free"):
        ArtifactStore(link, repo_path=repo)


def test_windows_refused(monkeypatch, layout):
    monkeypatch.setattr(artifacts, "_WIN32", True)
    repo, root = layout
    with pytest.raises(ArtifactRejected, match="Windows"):
        ArtifactStore(root, repo_path=repo)
    with pytest.raises(ArtifactRejected, match="Windows"):
        host_platform()


# ------------------------------------------------------------------ #
# existing digest dir: never overwrite, never adopt                   #
# ------------------------------------------------------------------ #
def test_tampered_existing_artifact_refused_never_overwritten(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    desc = store.import_artifact(src, _manifest_bytes(src))
    exe = Path(desc.executable)
    os.chmod(exe, 0o700)
    exe.write_bytes(b"TAMPERED")
    with pytest.raises(ArtifactRejected, match="digest mismatch"):
        store.import_artifact(src, _manifest_bytes(src))
    assert exe.read_bytes() == b"TAMPERED"  # refusal, not repair


def test_incomplete_digest_dir_not_adopted(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    digest_dir = store.root / "store" / "demo-engine" / digest
    digest_dir.mkdir(parents=True)
    for path in (store.root, store.root / "store",
                 store.root / "store" / "demo-engine", digest_dir):
        os.chmod(path, 0o700)  # simulate a properly owned pre-existing store
    (digest_dir / "artifact").write_bytes(src.read_bytes())
    with pytest.raises(ArtifactRejected, match="no readable ownership manifest"):
        store.import_artifact(src, _manifest_bytes(src))
    assert (digest_dir / "artifact").read_bytes() == src.read_bytes()


def test_unexpected_entry_in_digest_dir_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    desc = store.import_artifact(src, _manifest_bytes(src))
    extra = Path(desc.manifest_path).parent / "dropped-payload.bin"
    extra.write_bytes(b"suspicious")
    with pytest.raises(ArtifactRejected, match="unexpected entries"):
        store.import_artifact(src, _manifest_bytes(src))
    assert extra.read_bytes() == b"suspicious"  # foreign data preserved, refused


def test_forged_ownership_manifest_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    desc = store.import_artifact(src, _manifest_bytes(src))
    manifest_path = Path(desc.manifest_path)
    forged = json.loads(manifest_path.read_bytes())
    forged["engine_commit"] = "b" * 40
    os.chmod(manifest_path, 0o600)
    manifest_path.write_bytes(json.dumps(forged).encode())
    with pytest.raises(ArtifactRejected, match="does not match pinned"):
        store.import_artifact(src, _manifest_bytes(src))


# ------------------------------------------------------------------ #
# explicit atomic promotion pointer                                   #
# ------------------------------------------------------------------ #
def test_promote_and_resolve_roundtrip(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    desc = store.import_artifact(src, _manifest_bytes(src))
    assert store.resolve("demo-engine") is None
    promoted = store.promote("demo-engine", desc.digest)
    assert promoted == desc
    resolved = store.resolve("demo-engine")
    assert resolved == desc and Path(resolved.executable).is_absolute()
    pointer = store.root / "pointers" / "demo-engine"
    assert pointer.read_text().strip() == desc.digest
    assert not list((store.root / "pointers").glob("*.tmp"))  # atomic, no litter


def test_promote_failure_keeps_old_pointer(store, tmp_path):
    s1 = _write_source(tmp_path / "e1", b"payload-one")
    d1 = store.import_artifact(s1, _manifest_bytes(s1))
    store.promote("demo-engine", d1.digest)
    s2 = _write_source(tmp_path / "e2", b"payload-two")
    d2 = store.import_artifact(s2, _manifest_bytes(s2))
    exe2 = Path(d2.executable)
    os.chmod(exe2, 0o700)
    exe2.write_bytes(b"corrupted")
    with pytest.raises(ArtifactRejected, match="digest mismatch"):
        store.promote("demo-engine", d2.digest)
    pointer = store.root / "pointers" / "demo-engine"
    assert pointer.read_text().strip() == d1.digest  # old pointer intact
    assert Path(store.resolve("demo-engine").executable) == Path(d1.executable)


def test_promote_unknown_digest_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    store.import_artifact(src, _manifest_bytes(src))
    with pytest.raises(ArtifactRejected, match="unknown artifact"):
        store.promote("demo-engine", "c" * 64)


def test_resolve_tampered_artifact_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    desc = store.import_artifact(src, _manifest_bytes(src))
    store.promote("demo-engine", desc.digest)
    os.chmod(desc.executable, 0o700)
    Path(desc.executable).write_bytes(b"rotated")
    with pytest.raises(ArtifactRejected, match="digest mismatch"):
        store.resolve("demo-engine")


def test_malformed_pointer_refused(store, tmp_path):
    src = _write_source(tmp_path / "engine")
    store.import_artifact(src, _manifest_bytes(src))
    pointers = store.root / "pointers"
    pointers.mkdir(parents=True)
    (pointers / "demo-engine").write_text("not-a-digest")
    with pytest.raises(ArtifactRejected, match="malformed promotion pointer"):
        store.resolve("demo-engine")


def test_old_version_payload_kept_across_promotions(store, tmp_path):
    s1 = _write_source(tmp_path / "e1", b"version-one")
    d1 = store.import_artifact(s1, _manifest_bytes(s1))
    s2 = _write_source(tmp_path / "e2", b"version-two")
    d2 = store.import_artifact(s2, _manifest_bytes(s2))
    store.promote("demo-engine", d2.digest)
    store.promote("demo-engine", d1.digest)  # explicit rollback pointer
    old_exe = Path(d2.executable)
    assert old_exe.is_file() and old_exe.read_bytes() == b"version-two"
    assert store.resolve("demo-engine").digest == d1.digest


# ------------------------------------------------------------------ #
# locking discipline (project WriteLock reuse)                        #
# ------------------------------------------------------------------ #
def test_import_serialized_behind_project_write_lock(store, layout, tmp_path):
    repo, root = layout
    src1 = _write_source(tmp_path / "engine")
    store.import_artifact(src1, _manifest_bytes(src1))  # creates root + lock file
    src2 = _write_source(tmp_path / "engine2", b"second")
    started, release = threading.Event(), threading.Event()

    def hold():
        with WriteLock(str(root / "write.lock"), timeout_ms=1000):
            started.set()
            release.wait(5)

    # WriteLock is re-entrant per-thread, so contention needs a second thread.
    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert started.wait(5)
        busy = ArtifactStore(root, repo_path=repo, lock_timeout_ms=50)
        with pytest.raises(LockTimeoutError):
            busy.import_artifact(src2, _manifest_bytes(src2, name="second"))
    finally:
        release.set()
        thread.join(5)
    # after the holder releases the mutation succeeds: no poison left behind
    desc = ArtifactStore(root, repo_path=repo).import_artifact(
        src2, _manifest_bytes(src2, name="second"))
    assert Path(desc.executable).is_file()


# ------------------------------------------------------------------ #
# source-open hardening: O_NOFOLLOW + fd-bound inode/type/owner/size  #
# ------------------------------------------------------------------ #
def test_open_source_nofollow_refuses_symlink(tmp_path):
    real = _write_source(tmp_path / "engine")
    link = tmp_path / "engine-link"
    link.symlink_to(real)
    with pytest.raises(ArtifactRejected, match="symlink"):
        ArtifactStore._open_source(link)


def test_source_swap_detected_by_fd_inode_bind(store, tmp_path, monkeypatch):
    src = _write_source(tmp_path / "engine", b"A" * 64)
    decoy = _write_source(tmp_path / "decoy", b"B" * 64)  # same size, other inode
    shim = _OsShim(os)
    shim.swap_source = decoy
    monkeypatch.setattr(artifacts, "os", shim)
    with pytest.raises(ArtifactRejected, match="source swapped"):
        store.import_artifact(src, _manifest_bytes(src))
    assert not (store.root / "store" / "demo-engine").exists()  # nothing installed
    shim.swap_source = None  # retry with the real source succeeds
    desc = store.import_artifact(src, _manifest_bytes(src))
    assert Path(desc.executable).read_bytes() == b"A" * 64


# ------------------------------------------------------------------ #
# whole-dir staging: ENOSPC-class faults never wedge a digest dir     #
# ------------------------------------------------------------------ #
def test_manifest_write_fault_discards_stage_and_retry_works(
        store, tmp_path, monkeypatch):
    src = _write_source(tmp_path / "engine")
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    shim = _OsShim(os)
    shim.fail_manifest = True
    monkeypatch.setattr(artifacts, "os", shim)
    with pytest.raises(ArtifactRejected, match="manifest write failed"):
        store.import_artifact(src, _manifest_bytes(src))
    assert not (store.root / "store" / "demo-engine" / digest).exists()  # no wedge
    assert not list((store.root / "tmp").iterdir())  # owned stage removed only
    shim.fail_manifest = False
    desc = store.import_artifact(src, _manifest_bytes(src))  # retry works
    assert Path(desc.executable).is_file()


def test_rename_fault_typed_refusal_and_retry_works(store, tmp_path, monkeypatch):
    src = _write_source(tmp_path / "engine")
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    shim = _OsShim(os)
    shim.fail_rename = 1
    monkeypatch.setattr(artifacts, "os", shim)
    with pytest.raises(ArtifactRejected, match="install refused"):
        store.import_artifact(src, _manifest_bytes(src))
    assert not (store.root / "store" / "demo-engine" / digest).exists()
    assert not list((store.root / "tmp").iterdir())
    desc = store.import_artifact(src, _manifest_bytes(src))
    assert Path(desc.executable).is_file()


def test_promote_replace_fault_keeps_old_pointer(store, tmp_path, monkeypatch):
    s1 = _write_source(tmp_path / "e1", b"one")
    d1 = store.import_artifact(s1, _manifest_bytes(s1))
    store.promote("demo-engine", d1.digest)
    s2 = _write_source(tmp_path / "e2", b"two")
    d2 = store.import_artifact(s2, _manifest_bytes(s2))
    shim = _OsShim(os)
    shim.fail_replace = 1
    monkeypatch.setattr(artifacts, "os", shim)
    with pytest.raises(ArtifactRejected, match="old pointer preserved"):
        store.promote("demo-engine", d2.digest)
    pointer = store.root / "pointers" / "demo-engine"
    assert pointer.read_text().strip() == d1.digest
    assert not list((store.root / "pointers").glob("*.tmp"))  # tmp cleaned
    shim.fail_replace = 0
    store.promote("demo-engine", d2.digest)  # retry flips atomically
    assert store.resolve("demo-engine").digest == d2.digest


# ------------------------------------------------------------------ #
# validate-before-read: symlinked manifest never opened (read spy)    #
# ------------------------------------------------------------------ #
def test_symlinked_manifest_refused_before_any_read(store, tmp_path, monkeypatch):
    src = _write_source(tmp_path / "engine")
    desc = store.import_artifact(src, _manifest_bytes(src))
    store.promote("demo-engine", desc.digest)
    manifest_path = Path(desc.manifest_path)
    canary = tmp_path / "canary.json"
    canary.write_bytes(manifest_path.read_bytes())
    manifest_path.unlink()
    manifest_path.symlink_to(canary)  # dir passes, file read would leak

    reads: list[str] = []
    real_rb = Path.read_bytes

    def spy(self):
        reads.append(str(self))
        return real_rb(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    with pytest.raises(ArtifactRejected, match="ownership manifest is a symlink"):
        store.promote("demo-engine", desc.digest)
    with pytest.raises(ArtifactRejected, match="ownership manifest is a symlink"):
        store.resolve("demo-engine")
    assert str(manifest_path) not in reads  # spy: manifest never opened
    assert canary.read_bytes() == real_rb(canary)  # canary untouched


# ------------------------------------------------------------------ #
# empty dest planted mid-stage: refused, preserved, pointer kept      #
# ------------------------------------------------------------------ #
def test_empty_dest_planted_during_staging_refused_and_preserved(
        store, tmp_path, monkeypatch):
    s1 = _write_source(tmp_path / "e1", b"v1")
    d1 = store.import_artifact(s1, _manifest_bytes(s1))
    store.promote("demo-engine", d1.digest)
    s2 = _write_source(tmp_path / "e2", b"v2")
    planted = store.root / "store" / "demo-engine" / \
        hashlib.sha256(b"v2").hexdigest()
    shim = _OsShim(os)
    shim.plant_empty = planted  # foreign empty dest appears mid-staging
    monkeypatch.setattr(artifacts, "os", shim)
    with pytest.raises(ArtifactRejected, match="appeared during staging"):
        store.import_artifact(s2, _manifest_bytes(s2))
    assert planted.is_dir() and not any(planted.iterdir())  # preserved, not replaced
    assert not list((store.root / "tmp").iterdir())  # only own stage cleaned
    pointer = store.root / "pointers" / "demo-engine"
    assert pointer.read_text().strip() == d1.digest  # old pointer untouched
