"""P2 managed native-runtime profile (security fail-closed).

Controls source-verified in ``plan/python-c-monorepo/evidence/p2-runtime-controls.md``
(release 46ae198f). The admin caller supplies ``root`` (absolute, outside every
indexed repo — never auto-derived, never under ``.sot``). ``initialize`` creates
private dirs (0700) plus the mandatory UI-off pre-seed ``cache/config.json`` =
``{"ui_enabled": false}`` BEFORE any native start; ``environment`` hands the
7-key replacement env for ``proc.run_command(env=...)`` (no inheritance, fixed
PATH).

IPC length budget (measured): the native daemon binds
``$CBM_RUNTIME_DIR/cbm-daemon-<uid>/cbm-<16hex>.sock`` and a Unix socket
``sun_path`` holds at most 104 bytes, so the full path must stay <= 103
UTF-8 bytes. With CBM_RUNTIME_DIR = ``<root>/m-<24hex>/runtime`` the fixed
overhead after ``root`` is 35 bytes, and the native suffix is
38 + len(str(uid)) bytes — the constructor PREFLIGHTS this arithmetic and
REJECTS (typed, before any native start) a root whose socket path would
reach 104 bytes, telling the admin to choose a shorter root. There is no
silent fallback to a shared/global IPC directory. Exact budget:
``max_root_utf8_bytes = 103 - 35 - (38 + len(str(os.getuid())))``
(= 27 for a 3-digit uid such as macOS 501).

Read-only honesty: ``environment`` and ``status`` DETECT tamper/unknown state
and refuse, but never persist anything — a QUARANTINED report derived from a
read-only call is NOT sticky. Only explicit mutation paths
(initialize/begin_sync/complete_sync/quarantine) write the manifest; when an
explicit mutation meets live tamper it persists the quarantine (fail-closed
correction) instead of leaving invalid state.

State label honesty: READY means the LOCAL FILESYSTEM profile is initialized
and verified (dirs + UI seed + ownership). The adapter's explicit prepare
(e.g. ``config set auto_watch false`` through the runner) happens later and is
tracked by the adapter — READY here is NOT a managed/worker-ready claim.

Sync ownership: ``begin_sync`` binds the sync to THIS instance AND thread
(``threading.get_ident``); ``environment`` during SYNCING is served only to
that owning thread (to launch AFTER begin_sync) and ``complete_sync`` only
completes on it. Other instances/threads derive QUARANTINED "interrupted".
The main adapter may use threads, but only the owning thread drives a sync.

Terminal attestation honesty: ``terminal_confirmed``/``success`` are INTERNAL
adapter attestations — not a public-user proof and not magic; they are simply
recorded verbatim in the manifest (``last_complete``) for diagnostics.

Recovery policy: there is NO recovery API — nothing in a manifest can prove a
worker reached a terminal state (a nonce/digest re-read from the manifest is a
tautology). A quarantined namespace stays frozen; explicit recovery is the
admin creating a FRESH namespace via a new ``generation`` (same repo+artifact
allowed), leaving the old one untouched. Unknown manifest states derive
QUARANTINED, never READY.

Namespace format (experimental, unreleased — no migration needed; older
long-format namespaces are simply never referenced): ``m-<24hex>`` where the
combined hash covers repo realpath + protocol + generation + artifact digest.
The generation is INSIDE the hash, not a literal in the name; the full
identity stays in the manifest and is re-checked on every use (collision
detection is the identity check, the hash is only collision-resistant
addressing).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sot_graph.locking import WriteLock

__all__ = ["PROTOCOL_VERSION", "ManagedRuntimeError", "ManagedRuntimeProfile",
           "ProfileQuarantined", "ProfileRejected"]

PROTOCOL_VERSION = "p2-v1"
GENERATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_STATE_READY, _STATE_SYNCING, _STATE_QUARANTINED = "READY", "SYNCING", "QUARANTINED"
_UI_SEED = {"ui_enabled": False}
_UI_SEED_BYTES = json.dumps(_UI_SEED, separators=(",", ":")).encode("utf-8") + b"\n"
_PROFILE_DIRS = ("home", "cache", "runtime", "config", "tmp")
_LAUNCH_PAIRS = (("HOME", "home"), ("CBM_CACHE_DIR", "cache"), ("CBM_RUNTIME_DIR", "runtime"),
                 ("XDG_CONFIG_HOME", "config"), ("TMPDIR", "tmp"))
_LOCK_NAME = "managed.lock"
_FIXED_PATH = "/usr/bin:/bin"
_WIN32 = sys.platform == "win32"
# Native IPC socket: $CBM_RUNTIME_DIR/cbm-daemon-<uid>/cbm-<16hex>.sock
_NS_PREFIX, _NS_HASH_HEX = "m-", 24
_SUN_PATH_LIMIT = 104  # bytes; the bound path must be strictly shorter (<= 103)
_SOCK_DAEMON_DIR, _SOCK_NAME = "/cbm-daemon-", "/cbm-" + "0" * 16 + ".sock"


class ManagedRuntimeError(RuntimeError):
    """Base: managed-runtime profile refusal."""


class ProfileRejected(ManagedRuntimeError):
    """Fail-closed security refusal (identity, ownership, platform, length)."""


class ProfileQuarantined(ManagedRuntimeError):
    """Quarantined (persisted or derived): no launch env, no mutation."""


class ManagedRuntimeProfile:
    """Immutable per-repo+artifact workspace under an admin-owned root.

    Namespace: ``<root>/m-<24hex>`` (combined hash of repo realpath, protocol,
    generation, artifact digest — generation is hashed, not literal). The full
    identity lives in the manifest and is re-verified on every use. The
    runtime dir ``<ns>/runtime`` becomes ``CBM_RUNTIME_DIR``; the constructor
    prefights the native socket ``sun_path`` byte budget (see module doc) and
    rejects long roots with the exact per-uid byte allowance.
    """

    def __init__(self, root: str | os.PathLike[str], repo_path: str | os.PathLike[str], *,
                 artifact_digest: str, generation: str = "initial") -> None:
        if _WIN32:
            raise ProfileRejected("managed runtime: Windows unsupported until verified")
        digest = str(artifact_digest or "").strip()
        if not digest:
            raise ProfileRejected("artifact_digest is required for profile identity")
        self._artifact_digest = digest
        self._generation = str(generation)
        if not GENERATION_RE.fullmatch(self._generation):
            raise ProfileRejected(f"generation must be a short identifier: {generation!r}")
        self._repo = Path(os.path.realpath(repo_path))
        if not self._repo.is_dir():
            raise ProfileRejected(f"repo path is not a directory: {repo_path}")
        raw = os.fspath(root)
        resolved = os.path.realpath(raw)
        if not os.path.isabs(raw) or resolved != os.path.abspath(raw):
            raise ProfileRejected(f"runtime root must be absolute and symlink-free: {raw!r}")
        repo_str = str(self._repo)
        if resolved == repo_str or resolved.startswith(repo_str + os.sep):
            raise ProfileRejected("runtime root must live outside the repository")
        self._root = Path(resolved)
        self._repo_hash = hashlib.sha256(repo_str.encode("utf-8")).hexdigest()
        combined = hashlib.sha256("\0".join(
            ("sot-managed-runtime", PROTOCOL_VERSION, self._generation,
             repo_str, digest)).encode("utf-8")).hexdigest()[:_NS_HASH_HEX]
        self._ns = self._root / f"{_NS_PREFIX}{combined}"
        self._manifest_path = self._ns / "manifest.json"
        self._paths: dict[str, Path] = {name: self._ns / name for name in _PROFILE_DIRS}
        self._preflight_socket_bytes(raw)
        self._syncing = False  # in-memory sync ownership (this instance, one thread)
        self._sync_thread: int | None = None

    def _preflight_socket_bytes(self, root_str: str) -> None:
        """Reject long roots BEFORE any native start (no shared/global IPC fallback).

        Native socket = CBM_RUNTIME_DIR + "/cbm-daemon-<uid>/cbm-<16hex>.sock";
        its UTF-8 byte length must stay strictly under ``_SUN_PATH_LIMIT``.
        """
        runtime_dir = f"{root_str}{os.sep}{_NS_PREFIX}{'0' * _NS_HASH_HEX}{os.sep}runtime"
        sock_bytes = (len(runtime_dir.encode("utf-8")) + len(_SOCK_DAEMON_DIR)
                      + len(str(os.getuid())) + len(_SOCK_NAME.encode("utf-8")))
        if sock_bytes >= _SUN_PATH_LIMIT:
            budget = (_SUN_PATH_LIMIT - 1 - len(_SOCK_DAEMON_DIR) - len(str(os.getuid()))
                      - len(_SOCK_NAME) - (1 + len(_NS_PREFIX) + _NS_HASH_HEX + len("/runtime")))
            raise ProfileRejected(
                f"runtime root too long for native IPC: computed socket path is "
                f"{sock_bytes} UTF-8 bytes (sun_path limit {_SUN_PATH_LIMIT}); "
                f"max root is {budget} UTF-8 bytes for uid {os.getuid()} — "
                f"choose a shorter root (no shared/global IPC fallback exists)")

    @property
    def identity(self) -> dict[str, str]:
        return {"protocol_version": PROTOCOL_VERSION, "generation": self._generation,
                "repo_hash": self._repo_hash, "artifact_digest": self._artifact_digest}

    @property
    def namespace(self) -> Path:
        return self._ns

    @property
    def paths(self) -> dict[str, Path]:
        return dict(self._paths)

    def initialize(self) -> dict[str, Any]:
        """Create the profile, or reuse it only on exact identity match."""
        with self._mutation():
            manifest = self._read_manifest()
            if manifest is None:
                if os.path.lexists(self._ns):
                    self._validate_private_dir(self._ns)
                    raise ProfileRejected("pre-existing namespace has no ownership manifest")
                return self._create()
            if not self._identity_ok(manifest) or manifest.get("repo") != str(self._repo):
                raise ProfileRejected("identity mismatch (cross-version or foreign profile)")
            return self._reuse(manifest)

    def environment(self) -> dict[str, str]:
        """7-key replacement env for ``proc.run_command(env=...)``; READ-ONLY.

        Served for READY, or SYNCING only to the owning thread (to launch
        AFTER ``begin_sync``). Tamper/unknown-state derives refusal here —
        nothing is persisted by this method.
        """
        self._validate_chain()
        manifest = self._require_owned_manifest()
        state, reason = self._derived_state(manifest)
        if state == _STATE_QUARANTINED:
            raise ProfileQuarantined(f"refusing launch: {reason}")
        env = {key: str(self._paths[name]) for key, name in _LAUNCH_PAIRS}
        env["PATH"] = _FIXED_PATH
        env["TERM"] = "dumb"
        return env

    def status(self) -> dict[str, Any]:
        """Pure read: tamper/quarantine derived from live checks; no writes."""
        try:
            self._validate_chain()
            manifest = self._read_manifest()
        except ProfileRejected as exc:
            return self._payload(_STATE_QUARANTINED, str(exc))
        if manifest is None:
            return {"initialized": False, "state": "UNINITIALIZED", "reason": None,
                    "namespace": str(self._ns), "identity": self.identity, "ui_seed_ok": None}
        if not self._identity_ok(manifest) or manifest.get("repo") != str(self._repo):
            return self._payload(_STATE_QUARANTINED, "identity mismatch or foreign profile")
        state, reason = self._derived_state(manifest)
        return self._payload(state, reason)

    def begin_sync(self) -> dict[str, Any]:
        """Persist the pending marker BEFORE any launch; binds this thread.

        Explicit mutation: live tamper found here is PERSISTED as quarantine
        (fail-closed) before refusing.
        """
        with self._mutation():
            manifest = self._require_owned_manifest()
            state, reason = self._derived_state(manifest)
            if state != _STATE_READY:
                if reason and "tampered" in reason and manifest.get("state") != _STATE_QUARANTINED:
                    manifest["state"] = _STATE_QUARANTINED
                    manifest["pending"] = False
                    manifest["quarantine_reason"] = reason
                    self._write_manifest(manifest)
                raise ProfileQuarantined(
                    f"cannot begin sync from {state}" + (f": {reason}" if reason else ""))
            manifest["state"] = _STATE_SYNCING
            manifest["pending"] = True
            self._syncing = True
            self._sync_thread = threading.get_ident()
            self._write_manifest(manifest)
            return self._payload(_STATE_SYNCING, None)

    def complete_sync(self, terminal_confirmed: bool, success: bool) -> dict[str, Any]:
        """Complete only for the owning thread; re-verifies live checks.

        Confirmed terminal success still refuses READY through live tamper
        (persisted quarantine instead). ``terminal_confirmed``/``success``
        are internal adapter attestations recorded in the manifest
        (``last_complete``) for diagnostics — not a public-user proof.
        """
        with self._mutation():
            manifest = self._require_owned_manifest()
            if (manifest.get("state") != _STATE_SYNCING or not self._syncing
                    or self._sync_thread != threading.get_ident()):
                raise ProfileRejected("no sync owned by this thread")
            tamper = self._live_tamper()
            if terminal_confirmed and success and tamper is None:
                manifest["state"] = _STATE_READY
                manifest["quarantine_reason"] = None
            elif tamper is not None:
                manifest["state"] = _STATE_QUARANTINED
                manifest["quarantine_reason"] = tamper
            else:
                manifest["state"] = _STATE_QUARANTINED
                manifest["quarantine_reason"] = "sync ended without confirmed terminal success"
            manifest["pending"] = False
            manifest["last_complete"] = {"terminal_confirmed": bool(terminal_confirmed),
                                         "success": bool(success)}
            self._syncing = False
            self._sync_thread = None
            self._write_manifest(manifest)
            return self._payload(manifest["state"], manifest["quarantine_reason"])

    def quarantine(self, reason: str) -> dict[str, Any]:
        """Explicitly persist QUARANTINED; frozen — the only way back is a new
        ``generation`` namespace (no recovery API, by design)."""
        with self._mutation():
            manifest = self._require_owned_manifest()
            manifest["state"] = _STATE_QUARANTINED
            manifest["pending"] = False
            manifest["quarantine_reason"] = str(reason)
            self._syncing = False
            self._sync_thread = None
            self._write_manifest(manifest)
            return self._payload(_STATE_QUARANTINED, str(reason))

    @contextmanager
    def _mutation(self) -> Iterator[None]:
        try:
            os.makedirs(self._root, mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ProfileRejected(f"cannot create runtime root: {exc}") from exc
        else:
            try:
                os.chmod(self._root, 0o700)  # new dirs only; never chmod existing
            except OSError as exc:
                raise ProfileRejected(f"cannot secure new runtime root: {exc}") from exc
        self._validate_private_dir(self._root)
        self._validate_chain()
        lock = WriteLock(str(self._root / _LOCK_NAME), timeout_ms=5_000)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def _validate_chain(self) -> None:
        """Re-check root/ns are still lexical (no intermediate symlink swap)."""
        for expected in (str(self._root), str(self._ns)):
            if os.path.realpath(expected) != expected:
                raise ProfileRejected(f"symlink swap on profile path: {expected}")

    def _live_tamper(self) -> str | None:
        """Live (read-only) tamper check over profile dirs + UI seed."""
        try:
            for path in self._paths.values():
                self._validate_private_dir(path)
        except (ProfileRejected, OSError) as exc:
            return f"profile path tampered: {exc}"
        if not self._seed_ok():
            return "ui pre-seed config tampered or missing"
        return None

    def _derived_state(self, manifest: dict[str, Any]) -> tuple[str, str | None]:
        """Derive the honest state from manifest + live checks (READ-ONLY)."""
        state = manifest.get("state")
        if state == _STATE_QUARANTINED:
            return _STATE_QUARANTINED, manifest.get("quarantine_reason") or "quarantined"
        if state == _STATE_SYNCING and not (
                self._syncing and self._sync_thread == threading.get_ident()):
            return _STATE_QUARANTINED, "interrupted: sync owned by another instance/thread"
        if state not in (_STATE_READY, _STATE_SYNCING):
            return _STATE_QUARANTINED, f"unknown manifest state: {state!r}"
        tamper = self._live_tamper()
        if tamper is not None:
            return _STATE_QUARANTINED, tamper
        return state, None

    def _read_manifest(self) -> dict[str, Any] | None:
        try:
            raw = self._manifest_path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ProfileRejected(f"ownership manifest unreadable: {exc}") from exc
        try:
            manifest = json.loads(raw)
        except ValueError as exc:
            raise ProfileRejected(f"corrupt ownership manifest: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ProfileRejected("ownership manifest is not a JSON object")
        return manifest

    def _require_owned_manifest(self) -> dict[str, Any]:
        manifest = self._read_manifest()
        if manifest is None:
            raise ProfileRejected("profile is not initialized")
        if not self._identity_ok(manifest) or manifest.get("repo") != str(self._repo):
            raise ProfileRejected("identity mismatch (cross-version or foreign profile)")
        return manifest

    def _identity_ok(self, manifest: dict[str, Any]) -> bool:
        return (manifest.get("protocol_version"), manifest.get("generation"),
                manifest.get("repo_hash"), manifest.get("artifact_digest")) == (
            PROTOCOL_VERSION, self._generation, self._repo_hash, self._artifact_digest)

    def _create(self) -> dict[str, Any]:
        for path in (self._ns, *self._paths.values()):
            self._ensure_new_dir(path)
        seed = self._paths["cache"] / "config.json"
        if os.path.lexists(seed):
            raise ProfileRejected("refusing to overwrite existing config.json")
        fd = os.open(seed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(_UI_SEED_BYTES)
        if not self._seed_ok():
            raise ProfileRejected("ui pre-seed readback failed")
        manifest: dict[str, Any] = dict(self.identity)
        manifest.update({"repo": str(self._repo), "state": _STATE_READY, "pending": False,
                         "quarantine_reason": None,
                         "paths": {k: str(v) for k, v in self._paths.items()}})
        self._write_manifest(manifest)
        return self._payload(_STATE_READY, None)

    def _reuse(self, manifest: dict[str, Any]) -> dict[str, Any]:
        recorded = manifest.get("paths")
        if not isinstance(recorded, dict) or any(
                recorded.get(name) != str(path) for name, path in self._paths.items()):
            raise ProfileRejected("recorded profile paths drifted from this namespace")
        state, reason = self._derived_state(manifest)
        if state == _STATE_QUARANTINED:
            raise ProfileRejected(f"refusing reuse: {reason}")
        return self._payload(state, reason)

    @staticmethod
    def _ensure_new_dir(path: Path) -> None:
        try:
            os.makedirs(path, mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ProfileRejected(f"cannot create profile dir {path}: {exc}") from exc
        else:
            try:
                os.chmod(path, 0o700)  # new dirs only; never chmod existing
            except OSError as exc:
                raise ProfileRejected(f"cannot secure profile dir {path}: {exc}") from exc
        ManagedRuntimeProfile._validate_private_dir(path)

    @staticmethod
    def _validate_private_dir(path: Path) -> None:
        info = os.lstat(path)  # FileNotFoundError propagates to caller
        if stat.S_ISLNK(info.st_mode):
            raise ProfileRejected(f"symlink in profile path: {path}")
        if not stat.S_ISDIR(info.st_mode):
            raise ProfileRejected(f"not a directory: {path}")
        if info.st_uid != os.geteuid():
            raise ProfileRejected(f"profile path not owned by current user: {path}")
        if info.st_mode & 0o077:
            raise ProfileRejected(f"unsafe permissions (want 0700) on: {path}")

    def _seed_ok(self) -> bool:
        try:
            data = (self._paths["cache"] / "config.json").read_bytes()
            return json.loads(data) == _UI_SEED
        except (OSError, ValueError):
            return False

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        tmp = self._ns / f"manifest.json.{uuid.uuid4().hex}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
        os.replace(tmp, self._manifest_path)

    def _payload(self, state: str, reason: str | None) -> dict[str, Any]:
        return {"initialized": True, "state": state, "reason": reason,
                "namespace": str(self._ns), "identity": self.identity,
                "ui_seed_ok": self._seed_ok()}
