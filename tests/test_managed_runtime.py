"""P2 managed runtime profile — unit tests (pure filesystem, NO native runs).

Controls under test (evidence: plan/python-c-monorepo/evidence/p2-runtime-controls.md,
release 46ae198f): fail-closed identity/ownership, UI pre-seed before any native
start, 7-key replacement launch env for ``proc.run_command(env=...)``, derived
(read-only) tamper/quarantine reporting, explicit-mutation-only persistence,
owner-instance+thread sync semantics, NO recovery API (frozen namespaces;
recovery = fresh generation), compact ``m-<24hex>`` namespaces, the native
IPC sun_path byte-budget preflight (long/unicode roots typed-rejected, no
native), and zero writes into the source repo.

Roots MUST be short (the native socket path budget is measured from the root),
so tests create roots under a short symlink-free temp base instead of pytest's
deep ``tmp_path``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sot_graph.locking import LockBusy, WriteLock  # noqa: E402
from sot_graph.providers.runtime import (  # noqa: E402
    ManagedRuntimeError,
    ManagedRuntimeProfile,
    ProfileQuarantined,
    ProfileRejected,
)

DIGEST = "a" * 64
_SHORT_BASES = ("/private/tmp", "/tmp")


def _short_base() -> str:
    for base in _SHORT_BASES:
        if os.path.isdir(base) and not os.path.islink(base):
            return base
    pytest.skip("no short symlink-free temp base available")


def _budget() -> int:
    """Exact max root UTF-8 bytes: 103 - 35(ns+runtime) - (38 + uid digits)."""
    return 30 - len(str(os.getuid()))


@pytest.fixture
def make_root():
    """Factory for short random roots (pytest tmp_path is too long for IPC)."""
    created: list[Path] = []

    def _make() -> Path:
        root = Path(_short_base()) / f"mr{uuid.uuid4().hex[:10]}"
        created.append(root)
        return root

    yield _make
    for root in created:
        shutil.rmtree(root, ignore_errors=True)


def _mk_repo(base: Path) -> Path:
    repo = base / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".sot" / "notes").mkdir(parents=True)
    (repo / ".sot" / "notes" / "n.md").write_text("note\n", encoding="utf-8")
    return repo


def _profile(root, repo, digest: str = DIGEST, generation: str = "initial") -> ManagedRuntimeProfile:
    return ManagedRuntimeProfile(str(root), str(repo), artifact_digest=digest,
                                 generation=generation)


def _manifest(profile: ManagedRuntimeProfile) -> dict:
    return json.loads((profile.namespace / "manifest.json").read_bytes())


def _ns_state(profile: ManagedRuntimeProfile) -> tuple[bytes, set[str]]:
    return ((profile.namespace / "manifest.json").read_bytes(),
            {p.name for p in profile.namespace.iterdir()})


def test_readonly_status_never_creates(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    before = dict(os.environ)
    status = _profile(root, repo).status()
    assert status["initialized"] is False
    assert status["state"] == "UNINITIALIZED"
    assert not root.exists()  # pure read created nothing at all
    assert os.environ == before


def test_initialize_creates_private_dirs_and_ui_seed(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    status = profile.initialize()
    assert status["state"] == "READY" and status["ui_seed_ok"] is True
    for path in profile.paths.values():
        assert path.is_dir() and os.stat(path).st_mode & 0o777 == 0o700
    assert os.stat(root).st_mode & 0o777 == 0o700
    seed = profile.paths["cache"] / "config.json"
    assert os.stat(seed).st_mode & 0o777 == 0o600
    assert json.loads(seed.read_bytes()) == {"ui_enabled": False}  # pre-seed, UI off
    assert set(profile.environment()) == {
        "HOME", "CBM_CACHE_DIR", "CBM_RUNTIME_DIR", "XDG_CONFIG_HOME", "TMPDIR",
        "PATH", "TERM"}


def test_compact_namespace_format_no_generation_literal(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    assert re.fullmatch(r"m-[0-9a-f]{24}", profile.namespace.name)
    assert "initial" not in profile.namespace.name  # generation is hashed, not literal
    assert profile.namespace == _profile(root, repo).namespace  # stable for identity
    assert _profile(root, repo, generation="g2").namespace != profile.namespace
    assert _profile(root, repo, digest="b" * 64).namespace != profile.namespace
    assert _profile(make_root(), repo).namespace != profile.namespace  # root differs
    # same artifact, different generation: distinct namespace, old stays frozen
    assert profile.initialize()["state"] == "READY"
    fresh = _profile(root, repo, generation="g2")
    assert fresh.initialize()["state"] == "READY"
    assert profile.status()["state"] == "READY"  # independent namespaces coexist


def test_long_or_unicode_root_typed_rejection_no_native(tmp_path, make_root) -> None:
    repo = _mk_repo(tmp_path / "w")
    base = Path(_short_base())
    budget = _budget()
    # root exactly at budget: accepted
    at_budget = base / ("m" * (budget - (len(str(base)) + 1)))
    assert _profile(at_budget, repo).initialize()["state"] == "READY"
    # one byte over budget: typed rejection telling the admin to shorten
    over = base / ("m" * (budget + 1 - (len(str(base)) + 1)))
    with pytest.raises(ProfileRejected) as exc:
        _profile(over, repo)
    assert "shorter root" in str(exc.value) and "sun_path" in str(exc.value)
    assert not over.exists()  # preflight before any native start, nothing created
    # unicode root: small char count but UTF-8 bytes over budget
    uni = base / ("mré" * 5)
    assert len(uni.name) < budget < len(uni.name.encode("utf-8")) + len(str(base)) + 1
    with pytest.raises(ProfileRejected):
        _profile(uni, repo)
    assert not uni.exists()


def test_reuse_exact_identity_ready(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    first = _profile(root, repo)
    first.initialize()
    before = _ns_state(first)
    assert _profile(root, repo).initialize()["state"] == "READY"
    assert _ns_state(first) == before  # reuse wrote nothing


def test_identity_mismatch_refused_manifest_intact(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    profile.initialize()
    manifest = _manifest(profile)
    manifest["artifact_digest"] = "b" * 64  # foreign writer in THIS namespace
    (profile.namespace / "manifest.json").write_bytes(json.dumps(manifest).encode())
    with pytest.raises(ProfileRejected):
        profile.initialize()
    assert _profile(root, repo).status()["state"] == "QUARANTINED"  # fail closed
    # a different digest never collides: it gets its own namespace by design
    other = _profile(root, repo, digest="b" * 64)
    assert other.namespace != profile.namespace
    assert other.initialize()["state"] == "READY"


def test_preexisting_unowned_namespace_refused_no_overwrite(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    os.makedirs(root, mode=0o700)
    os.makedirs(profile.namespace, mode=0o700)  # pre-existing, but unrecorded
    with pytest.raises(ProfileRejected):
        profile.initialize()
    assert list(profile.namespace.iterdir()) == []  # nothing written into it


def test_seed_tamper_env_refuses_with_no_writes(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    profile.initialize()
    seed = profile.paths["cache"] / "config.json"
    seed.write_bytes(b'{"ui_enabled": true}\n')  # tamper
    before = _ns_state(profile)
    with pytest.raises(ProfileQuarantined):
        profile.environment()  # derived refusal — environment never persists
    assert _ns_state(profile) == before  # manifest untouched, no tmp files added
    status = _profile(root, repo).status()  # derived from checks, still fails closed
    assert status["state"] == "QUARANTINED" and status["ui_seed_ok"] is False
    assert seed.read_bytes() == b'{"ui_enabled": true}\n'  # never auto-rewritten


def test_launch_env_allowlist_isolated_no_global_mutation(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    profile.initialize()
    before = dict(os.environ)
    env = profile.environment()
    assert os.environ == before  # no global env mutation
    assert env["PATH"] == "/usr/bin:/bin" and env["TERM"] == "dumb"
    assert env["CBM_CACHE_DIR"] == str(profile.paths["cache"])
    assert env["HOME"] == str(profile.paths["home"])
    env["HOME"] = "mutated"  # caller-side mutation must not leak into next call
    assert profile.environment()["HOME"] == str(profile.paths["home"])


def test_symlinks_rejected(tmp_path, make_root) -> None:
    repo = _mk_repo(tmp_path / "w")
    target = tmp_path / "elsewhere"
    target.mkdir()
    root_link = tmp_path / "root-link"
    os.symlink(target, root_link)
    with pytest.raises(ProfileRejected):  # root itself is a symlink
        _profile(root_link, repo)
    root = make_root()
    os.makedirs(root, mode=0o700)
    profile = _profile(root, repo)
    ns_target = tmp_path / "ns-target"
    ns_target.mkdir()
    os.symlink(ns_target, profile.namespace)
    with pytest.raises(ProfileRejected):  # namespace pre-placed as symlink
        profile.initialize()
    # intermediate symlink swap AFTER init: realpath recheck must catch it
    root2 = make_root()
    good = _profile(root2, repo)
    good.initialize()
    frozen, decoy = good.namespace.with_name("ns.frozen"), tmp_path / "decoy"
    os.rename(good.namespace, frozen)
    decoy.mkdir()
    os.symlink(decoy, good.namespace)
    status = _profile(root2, repo).status()
    assert status["state"] == "QUARANTINED"  # derived, not persisted
    assert "symlink" in (status["reason"] or "")
    with pytest.raises(ProfileRejected):
        _profile(root2, repo).environment()
    assert decoy.is_dir() and not any(decoy.iterdir())  # nothing written via swap


def test_quarantine_blocks_query_and_persists(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    profile.initialize()
    payload = profile.quarantine("unknown cancel outcome")
    assert payload["state"] == "QUARANTINED" and payload["reason"] == "unknown cancel outcome"
    with pytest.raises(ProfileQuarantined):
        profile.environment()
    fresh = _profile(root, repo)  # new object: persisted quarantine survives restart
    assert fresh.status()["state"] == "QUARANTINED"
    with pytest.raises(ProfileQuarantined):
        fresh.environment()


def test_no_recovery_api_and_unknown_state_quarantines(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    profile.initialize()
    assert not hasattr(ManagedRuntimeProfile, "recover")  # tautological proof removed
    profile.quarantine("frozen")
    assert _profile(root, repo).status()["state"] == "QUARANTINED"  # stays frozen
    # UNKNOWN manifest state must derive QUARANTINED, never READY
    manifest = _manifest(profile)
    manifest["state"] = "WEIRD"
    (profile.namespace / "manifest.json").write_bytes(json.dumps(manifest).encode())
    status = _profile(root, repo).status()
    assert status["state"] == "QUARANTINED" and "unknown manifest state" in (status["reason"] or "")
    with pytest.raises(ProfileQuarantined):
        profile.environment()


def test_begin_sync_owner_only_environment(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    owner = _profile(root, repo)
    owner.initialize()
    stranger = _profile(root, repo)
    owner.begin_sync()
    assert owner.status()["state"] == "SYNCING"  # owning instance sees BUSY
    assert owner.environment()  # owner may launch AFTER begin_sync
    with pytest.raises(ManagedRuntimeError):  # no second mutation while syncing
        owner.begin_sync()
    with pytest.raises(ProfileQuarantined):  # unknown/other owner refused
        stranger.environment()
    assert stranger.status()["state"] == "QUARANTINED"  # derived: interrupted
    with pytest.raises(ProfileRejected):  # stranger cannot finish what it lacks
        stranger.complete_sync(True, True)
    assert owner.complete_sync(True, True)["state"] == "READY"
    assert stranger.environment()  # terminal success visible to every instance


@pytest.mark.parametrize("confirmed,success", [(True, False), (False, True), (False, False)])
def test_unconfirmed_complete_quarantines(tmp_path, make_root, confirmed, success) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    profile.initialize()
    profile.begin_sync()
    payload = profile.complete_sync(confirmed, success)
    assert payload["state"] == "QUARANTINED"
    with pytest.raises(ProfileQuarantined):
        profile.environment()
    with pytest.raises(ProfileRejected):  # no owned sync left to finish
        profile.complete_sync(True, True)


def test_sync_thread_ownership(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    profile.initialize()
    started, release = threading.Event(), threading.Event()
    errors: list[Exception] = []

    def owner_thread() -> None:
        try:
            profile.begin_sync()
        except Exception as exc:  # noqa: BLE001 - surfaced via assert below
            errors.append(exc)
        started.set()
        release.wait(10)  # stay alive: idents recycle after exit, must not here
        try:
            profile.complete_sync(True, True)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread_a = threading.Thread(target=owner_thread)
    thread_a.start()
    assert started.wait(10)
    outcome: dict[str, str] = {}

    def stranger_thread() -> None:
        try:
            profile.environment()
            outcome["env"] = "served"
        except ProfileQuarantined as exc:
            outcome["env"] = str(exc)
        try:
            profile.complete_sync(True, True)
            outcome["complete"] = "completed"
        except ProfileRejected:
            outcome["complete"] = "refused"

    thread_b = threading.Thread(target=stranger_thread)
    thread_b.start()
    thread_b.join(10)
    assert "interrupted" in outcome["env"]  # SYNCING env only for owning thread
    assert outcome["complete"] == "refused"  # one thread cannot finish another's sync
    assert _manifest(profile)["state"] == "SYNCING"  # still pending, untouched
    release.set()
    thread_a.join(10)
    assert not errors  # owning thread completed its own sync
    assert profile.status()["state"] == "READY"
    assert profile.environment()  # terminal success visible to all


def test_tamper_persisted_by_mutations_never_ready(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    profile.initialize()
    # begin_sync is an explicit mutation: derived tamper must PERSIST quarantine
    (profile.paths["cache"] / "config.json").write_bytes(b'{"ui_enabled": true}\n')
    with pytest.raises(ProfileQuarantined):
        profile.begin_sync()
    assert _manifest(profile)["state"] == "QUARANTINED"  # persisted, not just derived
    assert "tampered" in (_manifest(profile)["quarantine_reason"] or "")

    # tamper appearing BETWEEN begin and complete must not yield READY
    profile2 = _profile(root, repo, generation="g2")
    profile2.initialize()
    profile2.begin_sync()
    (profile2.paths["cache"] / "config.json").write_bytes(b'{"ui_enabled": true}\n')
    payload = profile2.complete_sync(True, True)  # confirmed success BUT tampered
    assert payload["state"] == "QUARANTINED"  # never READY through tamper
    assert _manifest(profile2)["state"] == "QUARANTINED"  # persisted fail-closed
    assert _manifest(profile2)["last_complete"] == {"terminal_confirmed": True,
                                                    "success": True}  # diagnostics
    with pytest.raises(ProfileQuarantined):
        profile2.environment()

    # read-only calls still never write: refusal leaves the manifest byte-identical
    before = (profile2.namespace / "manifest.json").read_bytes()
    with pytest.raises(ProfileQuarantined):
        profile2.environment()
    assert (profile2.namespace / "manifest.json").read_bytes() == before


def test_two_digests_coexist_independent_namespaces(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    pa, pb = _profile(root, repo, digest="a" * 64), _profile(root, repo, digest="b" * 64)
    # 24-hex collision-resistant composite (NOT an absolute guarantee; the
    # manifest identity check is what actually gates every use).
    assert re.fullmatch(r"m-[0-9a-f]{24}", pa.namespace.name)
    assert pa.namespace != pb.namespace  # digest composite avoids collisions
    assert pa.initialize()["state"] == "READY"
    assert pb.initialize()["state"] == "READY"
    pa.quarantine("a only")
    assert pa.status()["state"] == "QUARANTINED"
    assert pb.status()["state"] == "READY"
    assert pb.environment()["CBM_CACHE_DIR"] == str(pb.paths["cache"])


def test_fresh_generation_same_artifact_leaves_old_frozen(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    old = _profile(root, repo)  # default generation "initial"
    old.initialize()
    old.quarantine("interrupted: frozen")
    frozen_ns, frozen_manifest = old.namespace, _manifest(old)
    fresh = _profile(root, repo, generation="g2")  # explicit admin generation
    assert fresh.namespace != old.namespace and fresh.namespace.parent == root
    assert fresh.initialize()["state"] == "READY"  # no deletion of the old one
    assert old.namespace == frozen_ns and (frozen_ns / "manifest.json").exists()
    assert _manifest(old) == frozen_manifest  # old quarantine remains untouched
    assert old.status()["state"] == "QUARANTINED"
    assert fresh.environment()


def test_generation_must_be_identifier(tmp_path, make_root) -> None:
    repo = _mk_repo(tmp_path / "w")
    with pytest.raises(ProfileRejected):
        _profile(make_root(), repo, generation="../evil")
    with pytest.raises(ProfileRejected):
        _profile(make_root(), repo, generation="")
    with pytest.raises(ProfileRejected):
        _profile(make_root(), repo, generation="x" * 65)


def test_existing_root_mode_unchanged_on_rejection(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    os.makedirs(root, mode=0o750)  # pre-existing private-ish but NOT 0700
    with pytest.raises(ProfileRejected):
        _profile(root, repo).initialize()
    assert stat.S_IMODE(os.stat(root).st_mode) == 0o750  # never chmod existing


def test_source_repo_and_notes_untouched(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")

    def snapshot(base: Path) -> dict[str, bytes]:
        return {str(p.relative_to(base)): p.read_bytes()
                for p in sorted(base.rglob("*")) if p.is_file()}

    before = snapshot(repo)
    profile = _profile(root, repo)
    profile.initialize()
    profile.environment()
    profile.begin_sync()
    profile.complete_sync(True, True)
    profile.quarantine("drill")  # frozen; recovery is a new generation, not a write
    _profile(root, repo, generation="g2").initialize()
    assert snapshot(repo) == before  # zero writes into source repo / notes


def test_independent_repo_namespaces(tmp_path, make_root) -> None:
    root = make_root()
    repo_a, repo_b = _mk_repo(tmp_path / "a"), _mk_repo(tmp_path / "b")
    pa, pb = _profile(root, repo_a), _profile(root, repo_b)
    pa.initialize()
    pb.initialize()
    assert pa.namespace != pb.namespace
    pa.quarantine("a only")
    assert pa.status()["state"] == "QUARANTINED"
    assert pb.status()["state"] == "READY"
    assert pb.environment()["CBM_CACHE_DIR"] == str(pb.paths["cache"])


def test_root_must_be_absolute_and_outside_repo(tmp_path, make_root) -> None:
    repo = _mk_repo(tmp_path / "w")
    with pytest.raises(ProfileRejected):
        ManagedRuntimeProfile("relative-root", str(repo), artifact_digest=DIGEST)
    with pytest.raises(ProfileRejected):  # admin root inside the source repo
        _profile(repo / "admin-root", repo)


def test_concurrent_initialize_serialized_by_write_lock(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profiles = [_profile(root, repo) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: p.initialize(), profiles))
    assert all(r["state"] == "READY" for r in results)
    assert _profile(root, repo).status()["ui_seed_ok"] is True


def test_lock_contention_fails_closed(tmp_path, make_root) -> None:
    root, repo = make_root(), _mk_repo(tmp_path / "w")
    profile = _profile(root, repo)
    profile.initialize()
    holder = WriteLock(str(root / "managed.lock"), timeout_ms=200)
    holder.acquire()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(profile.quarantine, "contended")
            with pytest.raises(LockBusy):  # bounded backoff, never blocks forever
                future.result(timeout=10)
    finally:
        holder.release()
    assert profile.status()["state"] == "READY"  # pure read never blocked
    assert profile.quarantine("after contention")["state"] == "QUARANTINED"
