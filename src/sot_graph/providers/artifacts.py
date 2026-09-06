"""sot_graph.providers.artifacts — bounded managed-artifact lifecycle (P4).

Trusted admin-local foundation ONLY (no CLI, no network, no spawn): stage an
explicit local binary into a PRIVATE, owned, digest-addressed root after
verifying an immutable manifest pinning ``{schema_version, name, digest,
platform, protocol, engine_commit}`` under an EXACT schema (unknown/missing
fields, malformed pins, platform/protocol mismatch → refusal).
Hard scope (fail-closed): NO download / PATH lookup / global config /
upstream installer / source-checkout import — the source is one explicit
local file. Windows is explicitly unsupported (mirrors ``providers.runtime``).
The store root is admin-supplied, absolute, symlink-free and MUST live
outside the repository; repo config is never trusted to supply it. An
existing root is validated (private 0700, euid-owned, no symlinks) and NEVER
chmod-ed, pruned or rewritten: prior versions, pointers and unrelated data
are preserved. Imports stage to a unique temp inside the root, stream-copy
while hashing, verify the pinned sha256 and size, then atomically rename to
the digest-addressed immutable executable; stage failure removes ONLY the
temps this call created. A digest dir already on disk is re-verified and
never overwritten or adopted when unknown/incomplete; the no-overwrite
guarantee is scoped to cooperative WriteLock users and detected
pre-existing state — it is NOT a sandbox against a malicious same-uid
racer (no renameat2/FFI). The promotion pointer
flips atomically and ONLY via :meth:`ArtifactStore.promote`; a failed
promote keeps the old pointer.

Reuse: mutations serialize behind :class:`sot_graph.locking.WriteLock` on
``<root>/write.lock`` (same discipline as ``providers.runtime._mutation``);
sha256 normalization reuses
:func:`sot_graph.provider_contract.normalize_sha256_digest`; no process is
ever spawned.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform as _platform
import re
import shutil
import stat
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from sot_graph.locking import WriteLock
from sot_graph.provider_contract import normalize_sha256_digest

__all__ = ["ARTIFACT_PROTOCOL_VERSION", "ArtifactError", "ArtifactRejected",
           "ArtifactManifest", "ArtifactDescriptor", "ArtifactStore", "host_platform"]

ARTIFACT_PROTOCOL_VERSION, _SCHEMA_VERSION = "artifacts-v1", 1
_MANIFEST_KEYS = frozenset({"schema_version", "name", "digest", "platform",
                            "protocol", "engine_commit"})
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")
_WIN32, _CHUNK = sys.platform == "win32", 1 << 20
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)  # 0 where unavailable (POSIX-only module)
_ARTIFACT_NAME, _MANIFEST_NAME = "artifact", "manifest.json"
_ALLOWED_ENTRIES = frozenset({_ARTIFACT_NAME, _MANIFEST_NAME})


class ArtifactError(RuntimeError):
    """Base: managed-artifact lifecycle failure."""


class ArtifactRejected(ArtifactError):
    """Fail-closed security refusal (schema, ownership, platform, digest)."""


def host_platform() -> str:
    """Canonical ``<sys.platform>-<machine>`` tag; Windows/unknown → refuse."""
    if _WIN32:
        raise ArtifactRejected("managed artifacts: Windows unsupported until verified")
    machine = _platform.machine().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64",
            "x86_64": "x86_64", "amd64": "x86_64"}.get(machine)
    if arch is None:
        raise ArtifactRejected(f"unsupported machine architecture: {machine!r}")
    return f"{sys.platform}-{arch}"


@dataclass(frozen=True)
class ArtifactManifest:
    """Immutable artifact pin set; exact schema, host-pinned platform."""
    schema_version: int
    name: str
    digest: str
    platform: str
    protocol: str
    engine_commit: str

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)  # field order == exact schema key set

    def manifest_bytes(self) -> bytes:
        """Canonical on-disk ownership-manifest bytes (sorted, normalized)."""
        return (json.dumps(self.as_dict(), indent=1, sort_keys=True)
                + "\n").encode("utf-8")

    @classmethod
    def parse(cls, data: bytes) -> "ArtifactManifest":
        try:
            raw: Any = json.loads(data)
        except ValueError as exc:
            raise ArtifactRejected(f"malformed artifact manifest JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ArtifactRejected("artifact manifest is not a JSON object")
        if set(raw) != set(_MANIFEST_KEYS):
            unknown = sorted(set(raw) - set(_MANIFEST_KEYS))
            missing = sorted(set(_MANIFEST_KEYS) - set(raw))
            raise ArtifactRejected(f"artifact manifest schema mismatch "
                                   f"(unknown={unknown}, missing={missing})")
        if type(raw["schema_version"]) is not int or raw["schema_version"] != _SCHEMA_VERSION:
            raise ArtifactRejected(f"unsupported schema_version: {raw['schema_version']!r}")
        name, commit = raw["name"], raw["engine_commit"]
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ArtifactRejected(f"invalid artifact name: {name!r}")
        if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit.strip().lower()):
            raise ArtifactRejected(f"invalid engine_commit pin: {commit!r}")
        try:
            digest = normalize_sha256_digest(raw["digest"])
        except ValueError as exc:
            raise ArtifactRejected(str(exc)) from exc
        manifest = cls(_SCHEMA_VERSION, name, digest, raw["platform"],
                       raw["protocol"], commit.strip().lower())
        if manifest.platform != host_platform():
            raise ArtifactRejected(f"manifest platform {manifest.platform!r} does not "
                                   f"match host {host_platform()!r}")
        if manifest.protocol != ARTIFACT_PROTOCOL_VERSION:
            raise ArtifactRejected(f"unsupported artifact protocol: {manifest.protocol!r}")
        return manifest


@dataclass(frozen=True)
class ArtifactDescriptor:
    """Verified artifact handle; ``executable`` is an absolute local path."""
    name: str
    digest: str
    platform: str
    protocol: str
    engine_commit: str
    manifest_path: str
    executable: str


class ArtifactStore:
    """PRIVATE digest-addressed artifact root; admin-supplied, outside repo."""

    def __init__(self, root: str | os.PathLike[str], *,
                 repo_path: str | os.PathLike[str],
                 lock_timeout_ms: int = 5_000) -> None:
        if _WIN32:
            raise ArtifactRejected("managed artifacts: Windows unsupported until verified")
        raw = os.fspath(root)
        resolved = os.path.realpath(raw)
        if not os.path.isabs(raw) or resolved != os.path.abspath(raw):
            raise ArtifactRejected(f"artifact root must be absolute and symlink-free: {raw!r}")
        repo = Path(os.path.realpath(repo_path))
        if not repo.is_dir():
            raise ArtifactRejected(f"repo path is not a directory: {repo_path}")
        root_str, repo_str = resolved, str(repo)
        if (root_str == repo_str or root_str.startswith(repo_str + os.sep)
                or repo_str.startswith(root_str + os.sep)):
            raise ArtifactRejected(
                "artifact root must be disjoint from the repository "
                "(no ancestor relation in either direction)")
        self._root = Path(resolved)
        self._lock_timeout_ms = int(lock_timeout_ms)

    @property
    def root(self) -> Path:
        return self._root

    def _digest_dir(self, name: str, digest: str) -> Path:
        return self._root / "store" / name / digest

    def _pointer_path(self, name: str) -> Path:
        return self._root / "pointers" / name

    @contextmanager
    def _mutation(self) -> Iterator[None]:
        try:
            os.makedirs(self._root, mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ArtifactRejected(f"cannot create artifact root: {exc}") from exc
        else:
            try:
                os.chmod(self._root, 0o700)  # new dirs only; never chmod existing
            except OSError as exc:
                raise ArtifactRejected(f"cannot secure new artifact root: {exc}") from exc
        self._validate_private_dir(self._root)
        if os.path.realpath(self._root) != str(self._root):
            raise ArtifactRejected(f"symlink swap on artifact root: {self._root}")
        lock = WriteLock(str(self._root / "write.lock"), timeout_ms=self._lock_timeout_ms)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @staticmethod
    def _validate_private_dir(path: Path) -> None:
        info = os.lstat(path)  # FileNotFoundError propagates to caller
        if stat.S_ISLNK(info.st_mode):
            raise ArtifactRejected(f"symlink in artifact path: {path}")
        if not stat.S_ISDIR(info.st_mode):
            raise ArtifactRejected(f"not a directory: {path}")
        if info.st_uid != os.geteuid():
            raise ArtifactRejected(f"artifact path not owned by current user: {path}")
        if info.st_mode & 0o077:
            raise ArtifactRejected(f"unsafe permissions (want 0700) on: {path}")

    @classmethod
    def _ensure_new_dir(cls, path: Path) -> None:
        try:
            os.makedirs(path, mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ArtifactRejected(f"cannot create artifact dir {path}: {exc}") from exc
        else:
            try:
                os.chmod(path, 0o700)  # new dirs only; never chmod existing
            except OSError as exc:
                raise ArtifactRejected(f"cannot secure new artifact dir {path}: {exc}") from exc
        cls._validate_private_dir(path)

    @staticmethod
    def _validate_regular_file(path: Path, label: str) -> os.stat_result:
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise ArtifactRejected(f"{label} unreadable: {exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ArtifactRejected(f"{label} is a symlink: {path}")
        if not stat.S_ISREG(info.st_mode):
            raise ArtifactRejected(f"{label} is not a regular file: {path}")
        if info.st_uid != os.geteuid():
            raise ArtifactRejected(f"{label} not owned by current user: {path}")
        return info

    @staticmethod
    def _streaming_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _open_source(src: Path) -> BinaryIO:
        """O_NOFOLLOW open — closes the lstat→open symlink-swap window."""
        try:
            return open(src, "rb",
                        opener=lambda p, flags: os.open(p, flags | _O_NOFOLLOW))
        except OSError as exc:
            raise ArtifactRejected(f"source binary unusable (symlink?): {exc}") from exc

    @staticmethod
    def _read_installed_manifest(final_dir: Path) -> ArtifactManifest:
        """Read the ownership manifest ONLY after caller validated the dir."""
        mpath = final_dir / _MANIFEST_NAME
        try:
            info = os.lstat(mpath)
        except OSError as exc:
            raise ArtifactRejected(
                f"digest dir has no readable ownership manifest: {exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ArtifactRejected(f"ownership manifest is a symlink: {mpath}")
        try:
            data = mpath.read_bytes()
        except OSError as exc:
            raise ArtifactRejected(f"ownership manifest unreadable: {exc}") from exc
        return ArtifactManifest.parse(data)

    @staticmethod
    def _descriptor(manifest: ArtifactManifest, final_dir: Path) -> ArtifactDescriptor:
        return ArtifactDescriptor(
            name=manifest.name, digest=manifest.digest, platform=manifest.platform,
            protocol=manifest.protocol, engine_commit=manifest.engine_commit,
            manifest_path=str(final_dir / _MANIFEST_NAME),
            executable=str(final_dir / _ARTIFACT_NAME))

    def import_artifact(self, source: str | os.PathLike[str],
                        manifest_data: bytes) -> ArtifactDescriptor:
        """Stage-verify-atomically-install one explicit local binary.

        The WHOLE artifact + ownership manifest is built inside a unique
        owned stage dir, then atomically renamed onto the digest path: an
        ENOSPC or crash mid-stage can never wedge a partial digest dir.
        An empty dest planted mid-stage is refused via a lexists recheck
        right before rename (planted dir preserved). Failure removes ONLY
        the stage dir. Idempotent: an existing digest dir is re-verified,
        never overwritten or adopted (cooperative-WriteLock scope, not a
        same-uid adversarial sandbox).
        """
        manifest = ArtifactManifest.parse(manifest_data)
        src = Path(source)
        expect = self._validate_regular_file(src, "source binary")  # fail-fast
        with self._mutation():
            final_dir = self._digest_dir(manifest.name, manifest.digest)
            if os.path.lexists(final_dir):
                return self._verify_installed(final_dir, manifest)
            self._ensure_new_dir(self._root / "tmp")
            stage = self._root / "tmp" / f"stage.{uuid.uuid4().hex}"
            try:
                try:
                    os.mkdir(stage, mode=0o700)
                    os.chmod(stage, 0o700)  # owned by this call
                except OSError as exc:
                    raise ArtifactRejected(f"cannot create stage dir: {exc}") from exc
                self._validate_private_dir(stage)
                try:
                    out_fd = os.open(stage / _ARTIFACT_NAME,
                                     os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except OSError as exc:
                    raise ArtifactRejected(f"cannot stage artifact: {exc}") from exc
                seen, copied = hashlib.sha256(), 0
                with self._open_source(src) as fin, os.fdopen(out_fd, "wb") as out:
                    fd_stat = os.fstat(fin.fileno())  # bind to the open fd
                    if not stat.S_ISREG(fd_stat.st_mode) \
                            or fd_stat.st_uid != os.geteuid():
                        raise ArtifactRejected(f"source identity changed: {src}")
                    if (fd_stat.st_dev, fd_stat.st_ino) != \
                            (expect.st_dev, expect.st_ino):
                        raise ArtifactRejected(f"source swapped during import: {src}")
                    try:
                        for chunk in iter(lambda: fin.read(_CHUNK), b""):
                            out.write(chunk)
                            seen.update(chunk)
                            copied += len(chunk)
                    except OSError as exc:
                        raise ArtifactRejected(f"source read failed: {exc}") from exc
                if copied != fd_stat.st_size:
                    raise ArtifactRejected(f"source mutated during import: read "
                                           f"{copied} of {fd_stat.st_size} bytes")
                if seen.hexdigest() != manifest.digest:
                    raise ArtifactRejected(f"source digest mismatch: pinned "
                                           f"{manifest.digest}, got {seen.hexdigest()}")
                os.chmod(stage / _ARTIFACT_NAME, 0o500)
                try:
                    mfd = os.open(stage / _MANIFEST_NAME,
                                  os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(mfd, "wb") as out:
                        out.write(manifest.manifest_bytes())
                except OSError as exc:
                    raise ArtifactRejected(
                        f"manifest write failed (stage discarded): {exc}") from exc
                self._ensure_new_dir(self._root / "store" / manifest.name)
                # Recheck immediately before rename: an empty dest planted
                # mid-stage would otherwise be silently replaced (POSIX
                # rename allows dir -> empty-dir). Cooperative-WriteLock
                # guarantee only — not a same-uid adversarial sandbox.
                if os.path.lexists(final_dir):
                    raise ArtifactRejected(
                        f"digest dir appeared during staging (no overwrite/"
                        f"adopt): {final_dir}")
                try:
                    os.rename(stage, final_dir)  # atomic whole-dir install
                except OSError as exc:
                    raise ArtifactRejected(f"digest install refused (no overwrite/"
                                           f"adopt): {exc}") from exc
                return self._descriptor(manifest, final_dir)
            except BaseException:
                shutil.rmtree(stage, ignore_errors=True)  # owned stage ONLY
                raise

    def _verify_installed(self, final_dir: Path,
                          manifest: ArtifactManifest) -> ArtifactDescriptor:
        self._validate_private_dir(final_dir)  # symlink/owner BEFORE any read
        entries = set(os.listdir(final_dir))
        if not entries <= set(_ALLOWED_ENTRIES):
            raise ArtifactRejected(f"digest dir has unexpected entries "
                                   f"{sorted(entries - set(_ALLOWED_ENTRIES))}: {final_dir}")
        installed = self._read_installed_manifest(final_dir)
        if installed != manifest:
            raise ArtifactRejected("installed ownership manifest does not match pinned manifest")
        target = final_dir / _ARTIFACT_NAME
        self._validate_regular_file(target, "artifact executable")
        got = self._streaming_sha256(target)
        if got != manifest.digest:
            raise ArtifactRejected(f"existing artifact digest mismatch: pinned "
                                   f"{manifest.digest}, got {got} (never overwritten)")
        return self._descriptor(manifest, final_dir)

    def promote(self, name: str, digest: str) -> ArtifactDescriptor:
        """Atomically flip ``pointers/<name>``; failures keep the old pointer."""
        try:
            digest = normalize_sha256_digest(digest)
        except ValueError as exc:
            raise ArtifactRejected(str(exc)) from exc
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ArtifactRejected(f"invalid artifact name: {name!r}")
        with self._mutation():
            final_dir = self._digest_dir(name, digest)
            if not os.path.lexists(final_dir):
                raise ArtifactRejected(f"cannot promote unknown artifact: {final_dir}")
            self._validate_private_dir(final_dir)  # BEFORE any manifest read
            installed = self._read_installed_manifest(final_dir)
            if installed.name != name or installed.digest != digest:
                raise ArtifactRejected(
                    "installed ownership manifest does not match requested pin")
            target = final_dir / _ARTIFACT_NAME
            self._validate_regular_file(target, "artifact executable")
            got = self._streaming_sha256(target)
            if got != digest:
                raise ArtifactRejected(f"artifact digest mismatch before promote: "
                                       f"pinned {digest}, got {got}")
            self._ensure_new_dir(self._root / "pointers")
            tmp = self._root / "pointers" / f"pointer.{uuid.uuid4().hex}.tmp"
            try:
                pfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(pfd, "wb") as out:
                    out.write((digest + "\n").encode("utf-8"))
                try:
                    os.replace(tmp, self._pointer_path(name))  # atomic flip
                except OSError as exc:
                    raise ArtifactRejected(f"promotion pointer update failed (old "
                                           f"pointer preserved): {exc}") from exc
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            return self._descriptor(installed, final_dir)

    def uninstall(self, name: str, digest: str) -> ArtifactDescriptor:
        """Deactivate only the exact verified selected artifact.

        Uninstall is deliberately non-destructive: retain binary, ownership
        manifest, runtime namespaces, notes and evidence for rollback. No
        process is signaled and no repository/harness configuration is touched.
        """
        try:
            digest = normalize_sha256_digest(digest)
        except ValueError as exc:
            raise ArtifactRejected(str(exc)) from exc
        selected = self.resolve(name)
        if selected is None or selected.digest != digest:
            raise ArtifactRejected('uninstall requires the exact selected digest')
        with self._mutation():
            selected = self.resolve(name)
            if selected is None or selected.digest != digest:
                raise ArtifactRejected('uninstall requires the exact selected digest')
            pointer = self._pointer_path(name)
            self._validate_regular_file(pointer, 'owned promotion pointer')
            pointer.unlink()
            return selected

    def resolve(self, name: str) -> ArtifactDescriptor | None:
        """Verify and return the promoted descriptor (``None``: no pointer)."""
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ArtifactRejected(f"invalid artifact name: {name!r}")
        pointer = self._pointer_path(name)
        if not os.path.lexists(pointer):
            return None  # read-only path: never creates the root
        try:
            pinfo = os.lstat(pointer)
        except OSError as exc:
            raise ArtifactRejected(f"promotion pointer unreadable: {exc}") from exc
        if stat.S_ISLNK(pinfo.st_mode):
            raise ArtifactRejected(f"promotion pointer is a symlink: {pointer}")
        try:
            raw = pointer.read_bytes()
        except OSError as exc:
            raise ArtifactRejected(f"promotion pointer unreadable: {exc}") from exc
        try:
            digest = normalize_sha256_digest(raw.decode("utf-8").strip())
        except (ValueError, UnicodeDecodeError) as exc:
            raise ArtifactRejected(f"malformed promotion pointer: {exc}") from exc
        self._validate_private_dir(self._root)
        final_dir = self._digest_dir(name, digest)
        if not os.path.lexists(final_dir):
            raise ArtifactRejected(f"promotion pointer targets missing artifact: {final_dir}")
        self._validate_private_dir(final_dir)  # BEFORE any manifest read
        installed = self._read_installed_manifest(final_dir)
        if installed.name != name or installed.digest != digest:
            raise ArtifactRejected("ownership manifest does not match promotion pointer")
        return self._verify_installed(final_dir, installed)
