"""Slot-gated, three-sample diagnostic; never alters frozen benchmarks.

Run ONLY after committed protocol and explicit coordinator exclusive approval.
All artifact, compatibility, and output identities must be supplied explicitly.
No default execution, daemon administration, inherited native environment, or
stat-based digest caching. Scratch remains ephemeral /tmp for short socket paths; durable results copy
inventory evidence. Retention is not archival preservation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import functools
import hashlib
import json
import os
from pathlib import Path
import platform
from datetime import datetime, timezone
import sys
import tempfile
import time
import subprocess
import stat
import traceback

try:
    import resource
except ImportError:  # Windows: rusage accounting unavailable; rest of script works.
    resource = None

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EVENTS = []
STACK = []
PHASE = 'setup'


@contextmanager
def span(name, **detail):
    start, cpu = time.perf_counter(), time.process_time()
    parent = STACK[-1] if STACK else None
    index = len(EVENTS)
    row = dict(name=name, phase=PHASE, parent=parent,
               start_monotonic_s=start, start_utc=datetime.now(timezone.utc).isoformat(),
               **detail)
    EVENTS.append(row)
    STACK.append(index)
    try:
        yield row
    except BaseException as exc:
        row['exception'] = type(exc).__name__
        raise
    finally:
        end = time.perf_counter()
        row.update(end_monotonic_s=end,
                   end_utc=datetime.now(timezone.utc).isoformat(),
                   wall_s=end-start,
                   python_process_cpu_s=time.process_time()-cpu)
        STACK.pop()


def instrument(owner, name, label, path_arg=None):
    original = getattr(owner, name)
    descriptor = vars(owner).get(name)
    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        detail = {}
        if path_arg is not None:
            path = Path(args[path_arg])
            detail = {'path': str(path), 'bytes': path.stat().st_size}
        with span(label, **detail):
            return original(*args, **kwargs)
    setattr(owner, name, staticmethod(wrapped) if isinstance(descriptor, staticmethod) else wrapped)


def fingerprint_cache(profile):
    """Content hashes are evidence only, never substituted into security gates."""
    with span('diagnostic_cache_content_snapshot'):
        return {str(p.relative_to(profile.namespace)): {
            'bytes': p.stat().st_size,
            'sha256': digest_file(p),
        } for p in sorted(profile.paths['cache'].rglob('*')) if p.is_file() and not p.is_symlink()}


def digest_file(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def bounded_command(argv):
    """Read-only inspection; bounded retained output, deadline, no shell."""
    with tempfile.TemporaryFile() as stream:
        try:
            result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=5, check=False)
            stream.seek(0)
            data = stream.read(65537)
            return {'argv': argv, 'exit_code': result.returncode,
                    'text': data[:65536].decode(errors='replace'),
                    'truncated': len(data) > 65536}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {'argv': argv, 'status': 'UNKNOWN', 'error': type(exc).__name__}


def source_identity():
    return {'files': {str(p.relative_to(ROOT)): digest_file(p)
                      for p in sorted((ROOT / 'src' / 'sot_graph').rglob('*.py'))
                      if not p.is_symlink()},
            'git_head': bounded_command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']),
            'git_status': bounded_command(['git', '-C', str(ROOT), 'status', '--porcelain=v1',
                                           '--untracked-files=normal']),
            'coverage': 'Python source content; git status bounded; not compiler identity'}


def inventory(lab):
    """Snapshots do not prove lifetime or absence of escaped descendants."""
    rows = []
    truncated = False
    if lab is not None:
        for base, dirs, files in os.walk(lab, followlinks=False):
            dirs.sort()
            for name in sorted(dirs + files):
                path = Path(base) / name
                try:
                    info = path.lstat()
                    rows.append({'path': str(path.relative_to(lab)), 'mode': info.st_mode,
                                 'bytes': info.st_size, 'socket': stat.S_ISSOCK(info.st_mode)})
                except OSError as exc:
                    rows.append({'path': str(path), 'status': 'UNKNOWN',
                                 'error': type(exc).__name__})
                if len(rows) >= 256:
                    truncated = True
                    break
            if truncated:
                break
    return {'utc': datetime.now(timezone.utc).isoformat(),
            'monotonic_s': time.perf_counter(), 'scratch': str(lab) if lab else None,
            'files': rows, 'files_truncated': truncated,
            'processes': bounded_command(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,comm=']),
            'scratch_open_files': bounded_command(['/usr/sbin/lsof', '-nP', '+D', str(lab)])
                                  if lab else {'status': 'UNKNOWN', 'reason': 'scratch not allocated'},
            'coverage': 'POINT_IN_TIME_PARTIAL: process names only; lsof scratch open files; '
                        'escaped descendants and transient listeners UNKNOWN; no kill performed'}


@contextmanager
def failure_receipt(output_dir, context=None):
    state: dict[str, Path | None] = {'scratch': None}
    try:
        yield state
    except BaseException as exc:
        receipt = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}',
                   'traceback': traceback.format_exc(),
                   'utc': datetime.now(timezone.utc).isoformat(),
                   'events': EVENTS,
                   'leftover_inventory': inventory(state['scratch']),
                   'context': dict(context or {})}
        (output_dir / 'failure.json').write_text(json.dumps(receipt, indent=2) + '\n')
        raise


def main():
    global PHASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exclusive-slot', required=True,
                        help='Explicit coordinator approval identifier; not automatic scheduling')
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--native-commit', required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--protocol', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=3)
    args = parser.parse_args()
    if args.samples < 3:
        parser.error('at least three paired samples required')
    if len(args.sha256) != 64 or any(c not in '0123456789abcdef' for c in args.sha256):
        parser.error('sha256 must be 64 lowercase hexadecimal characters')
    if len(args.native_commit) != 40 or any(c not in '0123456789abcdef' for c in args.native_commit):
        parser.error('native-commit must be a full lowercase commit identity')
    BINARY = args.binary.resolve(strict=True)
    PIN, COMMIT, PROTOCOL = args.sha256, args.native_commit, args.protocol
    REGISTRY = args.registry.resolve(strict=True)
    if not args.exclusive_slot.strip():
        parser.error('nonempty exclusive-slot approval required')
    if sys.gettrace() is not None or sys.getprofile() is not None:
        raise SystemExit('Refusing traced/profiled timing process')
    suspect = {k: v for k, v in os.environ.items()
               if any(s in k.upper() for s in ('COVERAGE', 'PROFILE', 'PYTEST', 'PYTHONPATH', 'PYTHONSTARTUP'))}
    if suspect:
        raise SystemExit('Refusing instrumentation-related environment keys: ' + ','.join(suspect))
    if sys.flags.optimize:
        parser.error('optimized Python disables diagnostic safety assertions')
    if not PROTOCOL.strip():
        parser.error('nonempty protocol required')
    # Refuse overwrite, including an existing empty directory or symlink.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with failure_receipt(args.output_dir, context={
            'output_dir': str(args.output_dir), 'binary': str(BINARY),
            'sha256': PIN, 'native_commit': COMMIT, 'protocol': PROTOCOL,
            'registry': str(REGISTRY), 'slot': args.exclusive_slot,
            'samples': args.samples,
    }) as failure_state:
        EVENTS.clear()
        STACK.clear()
        PHASE = 'setup'
        sys.path.insert(0, str(ROOT / 'src'))
        from sot_graph.providers import artifacts, codebase_memory, installation, managed, runtime
        from sot_graph.providers.compatibility import CompatibilityRegistry, TestedCompatibilityRecord
        from sot_graph.proc import run_command

        lab = Path(tempfile.mkdtemp(prefix='dl-', dir='/tmp')).resolve()
        failure_state['scratch'] = lab
        os.chmod(lab, 0o700)
        repo = lab / 'repo'
        repo.mkdir(mode=0o700)
        (repo / 'alpha.py').write_text('def greet(name):\n    return "hello " + name\n')
        output = {'slot': args.exclusive_slot, 'scratch': str(lab), 'n': args.samples,
                  'python': sys.executable, 'python_version': sys.version,
                  'gettrace': repr(sys.gettrace()), 'getprofile': repr(sys.getprofile()),
                  'instrumentation_env': suspect, 'binary': str(BINARY),
                  'binary_bytes': BINARY.stat().st_size,
                  'binary_sha256': PIN, 'native_commit': COMMIT, 'protocol': PROTOCOL,
                  'registry_sha256': digest_file(REGISTRY),
                  'script_sha256': digest_file(Path(__file__)),
                  'hardware': {'machine': platform.machine(), 'system': platform.platform(),
                               'cpu_count': os.cpu_count()},
                  'parent_env_allowlist': {k: os.environ[k] for k in
                                          ('LANG', 'LC_ALL', 'TZ', 'PYTHONMALLOC', 'PYTHONHASHSEED', 'PYTHONWARNINGS') if k in os.environ},
                  'native_env_keys': ['HOME', 'CBM_CACHE_DIR', 'CBM_RUNTIME_DIR',
                                      'XDG_CONFIG_HOME', 'TMPDIR', 'PATH', 'TERM'],
                  'native_internal_phases': {'startup': 'UNINSTRUMENTED',
                                             'query': 'UNINSTRUMENTED',
                                             'teardown': 'UNINSTRUMENTED'},
                  'daemon_inventory': 'POINT_IN_TIME_PARTIAL; see inventories; lifetime UNKNOWN',
                  'python_xoptions': {k: sys._xoptions[k] for k in
                                      ('dev', 'utf8', 'warn_default_encoding', 'no_debug_ranges',
                                       'frozen_modules', 'gil') if k in sys._xoptions},
                  'python_xoption_names': sorted(sys._xoptions),
                  'source_identity': source_identity(),
                  'scratch_durability': 'EPHEMERAL /tmp; inventories copied into durable result; retained, not cleaned',
                  'inventories': [],
                  'os_cache': 'UNKNOWN: no eviction; scratch index prepared once',
                  'events': EVENTS, 'samples': [],
                  'limits': ['Instrumented nested wall times are inclusive, not additive.',
                             'Python CPU excludes native descendants; no idle inference.',
                             'run_command includes spawn/poll/pipe-drain, not pure native CPU.',
                             'OS page cache UNKNOWN; no eviction; no promotion inference.',
                             'Current vendored source is not assumed identical to signed release.']}
        result_path = args.output_dir / 'diagnostic-result.json'
        def save():
            temporary = result_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(output, indent=2) + '\n')
            temporary.replace(result_path)
        try:
            with span('signed_release_full_hash'):
                assert digest_file(BINARY) == PIN, 'signed release pin mismatch'
            instrument(artifacts.ArtifactStore, '_streaming_sha256', 'artifact_full_sha', 0)
            instrument(codebase_memory, '_file_sha256', 'dispatch_full_sha', 0)
            instrument(installation, 'create_managed_installation', 'factory')
            instrument(runtime.ManagedRuntimeProfile, 'status', 'profile_status')
            instrument(runtime.ManagedRuntimeProfile, 'environment', 'profile_environment')
            instrument(managed.ManagedNativeRuntime, '_guard_ready', 'guard')
            instrument(managed.ManagedNativeRuntime, '_config_fingerprint', 'config_content_fingerprint')
            instrument(managed.ManagedNativeRuntime, '_gate', 'compatibility_gate')
            captured = []
            def observed_run(argv, **kwargs):
                env = kwargs.get('env')
                expected = {'HOME', 'CBM_CACHE_DIR', 'CBM_RUNTIME_DIR', 'XDG_CONFIG_HOME',
                            'TMPDIR', 'PATH', 'TERM'}
                assert env is not None and set(env) == expected, 'native environment must be replacement seven-key env'
                assert env['PATH'] == '/usr/bin:/bin' and env['TERM'] == 'dumb'
                for key in expected - {'PATH', 'TERM'}:
                    assert Path(env[key]).resolve().is_relative_to(lab), key
                assert Path(kwargs['cwd']).resolve() == repo
                captured.append((list(argv), dict(kwargs)))
                # Copy ephemeral JSON transport while it exists for same-command comparison.
                if '--args-file' in argv:
                    captured[-1] += (Path(argv[argv.index('--args-file')+1]).read_text(),)
                with span('run_command_native_envelope', argv=argv) as row:
                    before = (resource.getrusage(resource.RUSAGE_CHILDREN)
                              if resource is not None else None)
                    result = run_command(argv, **kwargs)
                    after = (resource.getrusage(resource.RUSAGE_CHILDREN)
                             if resource is not None else None)
                    reaped_cpu = ((after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)
                                  if before is not None and after is not None else None)
                    row.update(returncode=result.returncode, timed_out=result.timed_out,
                               stdout_bytes=len(result.stdout), stderr_bytes=len(result.stderr),
                               reaped_children_cpu_s=reaped_cpu,
                               cpu_scope='RUSAGE_CHILDREN only; detached/unreaped daemon accounting incomplete')
                    return result
            managed.run_command = observed_run
            store = artifacts.ArtifactStore(lab / 'store', repo_path=repo)
            manifest = dict(schema_version=1, name='codebase-memory', digest=PIN,
                            platform=artifacts.host_platform(), protocol='artifacts-v1', engine_commit=COMMIT)
            store.import_artifact(BINARY, json.dumps(manifest).encode())
            store.promote('codebase-memory', PIN)
            registry = CompatibilityRegistry()
            digests = {}
            for item in json.loads(REGISTRY.read_text())['records']:
                record = TestedCompatibilityRecord.from_dict(item)
                if record.artifact_sha256 == PIN and record.engine_commit == COMMIT and record.protocol_compatibility_id == PROTOCOL:
                    registry.register(record)
                    digests[record.operation] = record.fixture_digest
            def factory():
                return installation.create_managed_installation(
                    store, artifact_name='codebase-memory', repo_path=repo,
                    runtime_root=lab / 'rt', registry=registry,
                    operation_fixture_digests=digests, native_protocol_id=PROTOCOL)
            current = factory()
            for operation in ('prepare', 'sync'):
                with span('setup_' + operation):
                    outcome = current.runtime.prepare() if operation == 'prepare' else current.runtime.sync(str(repo))
                    assert outcome.status == 'ok', (operation, outcome.status, outcome.error)
            output['cache_before'] = fingerprint_cache(current.profile)
            for sample in range(args.samples):
                output['inventories'].append({'sample': sample, 'boundary': 'before',
                                              'inventory': inventory(lab)})
                PHASE = f'sample_{sample}'
                with span('admin_preresolve'):
                    store.resolve('codebase-memory')
                current = factory()
                with span('explicit_profile_status'):
                    state = current.profile.status()
                    assert state['state'] == 'READY', state
                with span('managed_query'):
                    outcome = current.runtime.query('search_graph', {'query': 'greet'})
                    assert outcome.status == 'ok', (outcome.status, outcome.error)
                argv, kwargs, transport = captured[-1]
                # No guard bypass: perform real guard and full compatibility hash first.
                assert current.runtime._guard_ready(require_binding=True) is None
                assert current.runtime._gate('search_graph') is None
                replay = current.profile.paths['tmp'] / 'diagnostic-query.json'
                replay.write_text(transport)
                argv = list(argv)
                argv[argv.index('--args-file')+1] = str(replay)
                try:
                    with span('direct_native_same_transport'):
                        direct = observed_run(argv, **kwargs)
                        assert not direct.timed_out and direct.returncode == 0
                        payload = json.loads(direct.stdout)
                        assert isinstance(payload, dict), 'invalid direct native receipt'
                finally:
                    replay.unlink()
                output['inventories'].append({'sample': sample, 'boundary': 'after',
                                              'inventory': inventory(lab)})
                output['samples'].append({'sample': sample, 'managed_status': outcome.status,
                                          'native_returncode': direct.returncode})
                save()
            PHASE = 'after'
            output['cache_after'] = fingerprint_cache(current.profile)
            output['final_status'] = current.profile.status()
            output['status'] = 'complete'
            output['verdict'] = 'PENDING_ANALYSIS'
            output['m2'] = 'NOT_AUTHORIZED: requires measured-cost attribution and independent review'
            output['historical_comparison'] = (
                'Not controlled against historical 26.7426s run; cannot attribute discrepancy')
        except BaseException as exc:
            output['status'] = 'failed'
            output['error'] = f'{type(exc).__name__}: {exc}'
            output['traceback'] = traceback.format_exc()
            raise
        finally:
            output['inventories'].append({'boundary': 'finally', 'inventory': inventory(lab)})
            save()
        print(json.dumps({'status': output['status'], 'result': str(result_path), 'scratch': str(lab)}))


if __name__ == '__main__':
    main()
