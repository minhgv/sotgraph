"""User-admin managed opt-in. Reads never create directories or start engines.

Only trusted callers may supply ``config_path``; repository and MCP input must
never be forwarded to it. The OS account database, not HOME/XDG, selects the
normal location. Registration is independent of query dispatch policy.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    import pwd
except ImportError:  # Windows: builtin/default-off queries remain available.
    pwd = None

from .artifacts import ArtifactStore
from .compatibility import CompatibilityRegistry, TestedCompatibilityRecord, normalize_protocol_id
from .installation import ManagedInstallation, _require_disjoint, create_managed_installation

MAX_CONFIG_BYTES = 262144
_ENTRY_KEYS = frozenset({"project_path", "enabled", "store_path", "artifact_name",
                         "runtime_root", "registry_path", "native_protocol_id",
                         "generation", "artifact_digest"})


class TrustedConfigError(ValueError):
    """Invalid, unsafe, stale, or incompatible administrator registration."""


def _supported_platform() -> bool:
    return os.name == 'posix' and pwd is not None


def _require_supported_platform():
    if not _supported_platform():
        raise TrustedConfigError('managed configuration is unsupported on this platform')


def default_config_path() -> Path:
    """Ignore environment-selected homes and repository configuration."""
    _require_supported_platform()
    assert pwd is not None
    home = pwd.getpwuid(os.getuid()).pw_dir
    if not isinstance(home, str) or not home or '\x00' in home or not os.path.isabs(home):
        raise TrustedConfigError('OS account home must be a nonempty absolute path')
    return Path(home).resolve() / '.config/sot-graph/managed.json'


@contextmanager
def _errors():
    try:
        yield
    except TrustedConfigError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError) as exc:
        raise TrustedConfigError('trusted managed configuration refused') from exc


def _path(value, *, private_file=False) -> Path:
    raw = os.fspath(value)
    path = Path(raw)
    if not path.is_absolute() or str(path) != os.path.realpath(raw):
        raise TrustedConfigError('paths must be absolute, canonical and symlink-free')
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise TrustedConfigError('symlink path component refused')
        if info.st_uid not in {0, os.getuid()}:
            raise TrustedConfigError('path component has an untrusted owner')
        # Sticky system temporary directories are safe ancestors, not endpoints.
        sticky_ancestor = part != path and info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if info.st_mode & 0o022 and not sticky_ancestor:
            raise TrustedConfigError('group/world-writable path component refused')
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise TrustedConfigError('non-directory path ancestor')
        if part == path and private_file:
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise TrustedConfigError('configuration must be an owned, singly linked regular file')
    return path


def _project(repo_path) -> tuple[str, str]:
    if not Path(repo_path).is_absolute():
        raise TrustedConfigError('project path must be absolute')
    project = str(Path(repo_path).resolve(strict=True))
    if not Path(project).is_dir():
        raise TrustedConfigError('project must be a directory')
    return project, hashlib.sha256(project.encode('utf-8')).hexdigest()


def _location(repo_path, config_path):
    _require_supported_platform()
    project, key = _project(repo_path)
    config = _path(default_config_path() if config_path is None else config_path, private_file=True)
    _require_disjoint(project, str(config.parent), 'configuration directory and repository')
    return project, key, config


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TrustedConfigError('duplicate JSON key')
        result[key] = value
    return result


def _read_json(path):
    _path(path, private_file=True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONFIG_BYTES
                or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022):
            raise TrustedConfigError('JSON must be an owned, safe, bounded regular file')
        data = stream.read(MAX_CONFIG_BYTES + 1)
    if len(data) > MAX_CONFIG_BYTES:
        raise TrustedConfigError('JSON exceeds size limit')
    return json.loads(data, object_pairs_hook=_unique_object)


def _read(config):
    try:
        payload = _read_json(config)
    except FileNotFoundError:
        return {'schema_version': 1, 'projects': {}}
    if (not isinstance(payload, dict) or set(payload) != {'schema_version', 'projects'}
            or type(payload['schema_version']) is not int or payload['schema_version'] != 1
            or not isinstance(payload['projects'], dict)):
        raise TrustedConfigError('invalid managed configuration schema')
    for key, entry in payload['projects'].items():
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS or type(entry['enabled']) is not bool:
            raise TrustedConfigError('invalid project registration schema')
        if any(not isinstance(entry[field], str) or not entry[field] for field in _ENTRY_KEYS - {'enabled'}):
            raise TrustedConfigError('invalid registration field')
        project = entry['project_path']
        if not os.path.isabs(project) or os.path.realpath(project) != project:
            raise TrustedConfigError('invalid canonical project binding')
        if key != hashlib.sha256(project.encode('utf-8')).hexdigest():
            raise TrustedConfigError('project hash binding mismatch')
        digest = entry['artifact_digest']
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise TrustedConfigError('invalid pinned artifact digest')
        _validate_paths(entry, config)
    return payload


def _validate_paths(entry, config):
    paths = [entry['project_path'], str(config.parent)]
    for field in ('store_path', 'runtime_root', 'registry_path'):
        paths.append(str(_path(entry[field], private_file=field == 'registry_path')))
    for index, left in enumerate(paths):
        for right in paths[index + 1:]:
            _require_disjoint(left, right, 'managed registration paths')


def _installation(entry, config, *, pin=True):
    _validate_paths(entry, config)
    store = ArtifactStore(entry['store_path'], repo_path=entry['project_path'])
    selected = store.resolve(entry['artifact_name'])
    if selected is None or (pin and selected.digest != entry['artifact_digest']):
        raise TrustedConfigError('promoted artifact differs from registration; register explicitly again')
    _path(selected.executable, private_file=True)
    protocol = normalize_protocol_id(entry['native_protocol_id'])
    payload = _read_json(Path(entry['registry_path']))
    if isinstance(payload, dict):
        if set(payload) != {'records'}:
            raise TrustedConfigError('invalid registry envelope')
        payload = payload['records']
    if not isinstance(payload, list):
        raise TrustedConfigError('registry records must be a list')
    registry = CompatibilityRegistry()
    digests = {}
    for item in payload:
        record = TestedCompatibilityRecord.from_dict(item)
        if (record.provider_name != 'codebase-memory'
                or record.artifact_sha256 != selected.digest
                or (record.engine_commit or '').strip().lower() != selected.engine_commit.lower()
                or record.protocol_compatibility_id != protocol):
            continue
        if record.operation in digests:
            raise TrustedConfigError('duplicate exact operation evidence')
        registry.register(record)
        digests[record.operation] = record.fixture_digest
    return create_managed_installation(
        store, artifact_name=entry['artifact_name'], repo_path=entry['project_path'],
        runtime_root=entry['runtime_root'], registry=registry,
        operation_fixture_digests=digests, native_protocol_id=protocol,
        generation=entry['generation'])


@contextmanager
def _admin_lock(config):
    try:
        import fcntl
    except ImportError as exc:
        raise TrustedConfigError('managed administration is unsupported on this platform') from exc
    missing = []
    parent = config.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)
    _path(config, private_file=True)
    if config.parent.stat().st_uid != os.getuid() or config.parent.stat().st_mode & 0o077:
        raise TrustedConfigError('configuration parent must be user-owned mode 0700')
    fd = os.open(config.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _persist(config, payload):
    data = (json.dumps(payload, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    if len(data) > MAX_CONFIG_BYTES:
        raise TrustedConfigError('configuration exceeds size limit')
    # Revalidate existing content before replacement; never clobber unrelated JSON.
    _read(config)
    fd, temporary = tempfile.mkstemp(prefix='.managed-', dir=config.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, config)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_managed_installation(repo_path, *, config_path=None) -> ManagedInstallation | None:
    """Read-only reconstruction; absence/disabled is off, invalid data raises."""
    if config_path is None and not _supported_platform():
        return None
    with _errors():
        project, key, config = _location(repo_path, config_path)
        entry = _read(config)['projects'].get(key)
        if entry is None or not entry['enabled']:
            return None
        if entry['project_path'] != project:
            raise TrustedConfigError('project binding mismatch')
        return _installation(entry, config)


def register_managed_installation(repo_path, *, store_path, artifact_name,
                                  runtime_root, registry_path, native_protocol_id,
                                  generation='initial', config_path=None) -> ManagedInstallation:
    """Explicit administrator opt-in; validates evidence without native execution."""
    with _errors():
        project, key, config = _location(repo_path, config_path)
        entry = dict(project_path=project, enabled=True, store_path=os.fspath(store_path),
                     artifact_name=artifact_name, runtime_root=os.fspath(runtime_root),
                     registry_path=os.fspath(registry_path), native_protocol_id=native_protocol_id,
                     generation=generation, artifact_digest='0' * 64)
        if any(not isinstance(entry[field], str) or not entry[field]
               for field in _ENTRY_KEYS - {'enabled'}):
            raise TrustedConfigError('registration fields must be nonempty strings')
        installation = _installation(entry, config, pin=False)
        entry['artifact_digest'] = installation.artifact.digest
        with _admin_lock(config):
            payload = _read(config)
            payload['projects'][key] = entry
            _persist(config, payload)
        return installation


def disable_managed_installation(repo_path, *, config_path=None) -> bool:
    """Disable this binding only; preserve artifacts, runtime, indexes and notes."""
    with _errors():
        _, key, config = _location(repo_path, config_path)
        if key not in _read(config)['projects']:
            return False
        with _admin_lock(config):
            payload = _read(config)
            entry = payload['projects'].get(key)
            if entry is None or not entry['enabled']:
                return False
            entry['enabled'] = False
            _persist(config, payload)
        return True


def managed_config_status(repo_path, *, config_path=None) -> dict:
    """Read-only operational observation, never query authorization or repair.

    Keep the strict dispatch loader separate: diagnostic failures are fixed
    codes, not exception text or instructions sourced from native state.
    """
    from .artifacts import ArtifactError
    from .runtime import ManagedRuntimeError

    result = dict(schema_version=2, status='disabled', enabled=False,
                  registration='unknown', reason=None, project_path=None,
                  project_key=None, artifact_digest=None,
                  current_artifact_digest=None, generation=None, namespace=None,
                  runtime_status='NOT_ASSESSED', ready=False,
                  query_permission='not_assessed', lifecycle='not_started',
                  remediation=[])

    def refuse(reason, *operations):
        result.update(status='refused', enabled=False, ready=False, reason=reason,
                      remediation=['sotgraph engine ' + operation for operation in operations])
        return result

    if not _supported_platform():
        return refuse('unsupported_platform', 'config-status')
    try:
        with _errors():
            project, key, config = _location(repo_path, config_path)
            result.update(project_path=project, project_key=key)
            entry = _read(config)['projects'].get(key)
    except TrustedConfigError:
        return refuse('config_refused', 'config-status')
    if entry is None or not entry['enabled']:
        result.update(registration='missing' if entry is None else 'disabled',
                      reason='registration_missing' if entry is None else 'registration_disabled',
                      remediation=['sotgraph engine register'])
        return result
    result.update(registration='enabled', artifact_digest=entry['artifact_digest'])
    if entry['project_path'] != project:
        return refuse('config_refused', 'config-status')
    try:
        selected = ArtifactStore(entry['store_path'], repo_path=project).resolve(entry['artifact_name'])
        if selected is None:
            return refuse('artifact_missing', 'promote', 'rollback', 'register', 'disable')
        _path(selected.executable, private_file=True)
        result['current_artifact_digest'] = selected.digest
    except (ArtifactError, TrustedConfigError, OSError, ValueError, TypeError, KeyError,
            RuntimeError, RecursionError):
        return refuse('artifact_refused', 'promote', 'rollback', 'disable')
    if selected.digest != entry['artifact_digest']:
        return refuse('artifact_mismatch', 'register', 'rollback', 'disable')
    try:
        installation = _installation(entry, config)
    except (ArtifactError, ManagedRuntimeError, OSError, ValueError, TypeError, KeyError,
            RuntimeError, RecursionError):
        return refuse('installation_incompatible', 'register', 'rollback', 'disable')
    # _installation resolves again; never report a raced promotion as validated.
    if installation.artifact.digest != entry['artifact_digest']:
        return refuse('artifact_mismatch', 'register', 'rollback', 'disable')
    result.update(generation=installation.profile.identity['generation'],
                  namespace=str(installation.profile.namespace))
    try:
        runtime = installation.profile.status()
    except (ManagedRuntimeError, OSError, ValueError, TypeError, KeyError,
            RuntimeError, RecursionError):
        return refuse('runtime_refused', 'runtime-status', 'register', 'disable')
    state = runtime.get('state')
    if state not in {'UNINITIALIZED', 'READY', 'SYNCING', 'QUARANTINED'}:
        return refuse('runtime_refused', 'runtime-status', 'disable')
    result['runtime_status'] = state
    if state == 'QUARANTINED':
        return refuse('runtime_quarantined', 'runtime-status', 'register', 'disable')
    result.update(status='enabled', enabled=True, ready=state == 'READY',
                  reason={'READY': 'runtime_ready', 'UNINITIALIZED': 'runtime_uninitialized',
                          'SYNCING': 'runtime_syncing'}[state],
                  remediation=['sotgraph engine ' + operation for operation in
                               ({'READY': ('probe', 'sync'),
                                 'UNINITIALIZED': ('prepare', 'probe', 'sync'),
                                 'SYNCING': ('runtime-status', 'disable')}[state])])
    return result
