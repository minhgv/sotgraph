"""Slot-gated, three-sample diagnostic; never alters frozen benchmarks.

Run ONLY after explicit coordinator benchmark-exclusive approval:
  .venv/bin/python plan/python-c-monorepo/evidence/parallel-latency/diagnose.py \
      --exclusive-slot COORDINATOR_APPROVAL_ID
No default execution, daemon administration, inherited native environment, or
stat-based digest caching. Scratch is retained for scoped follow-up inspection.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import functools
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BINARY = Path('/tmp/sot-p0-scratch/rel-extract/codebase-memory-mcp')
PIN = '2412e017268bef8f847f38d1b0f79f63185b38c27fe6fba637067bfc87c0eedf'
COMMIT = '46ae198fc11cda80e817acbc5f5908d7c2de7032'
PROTOCOL = 'p4-release-2412e017-measured-v1'
REGISTRY = Path('/private/tmp/a-u8mldiy1/registry.json')
EVENTS = []
STACK = []
PHASE = 'setup'


@contextmanager
def span(name, **detail):
    start, cpu = time.perf_counter(), time.process_time()
    parent = STACK[-1] if STACK else None
    index = len(EVENTS)
    row = dict(name=name, phase=PHASE, parent=parent, **detail)
    EVENTS.append(row)
    STACK.append(index)
    try:
        yield row
    except BaseException as exc:
        row['exception'] = type(exc).__name__
        raise
    finally:
        row.update(wall_s=time.perf_counter()-start,
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
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    global PHASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exclusive-slot', required=True,
                        help='Explicit coordinator approval identifier; not automatic scheduling')
    args = parser.parse_args()
    if not args.exclusive_slot.strip():
        parser.error('nonempty exclusive-slot approval required')
    if sys.gettrace() is not None or sys.getprofile() is not None:
        raise SystemExit('Refusing traced/profiled timing process')
    suspect = {k: v for k, v in os.environ.items()
               if any(s in k.upper() for s in ('COVERAGE', 'PROFILE', 'PYTEST', 'PYTHONPATH', 'PYTHONSTARTUP'))}
    if suspect:
        raise SystemExit('Refusing instrumentation-related environment keys: ' + ','.join(suspect))
    sys.path.insert(0, str(ROOT / 'src'))
    from sot_graph.providers import artifacts, codebase_memory, installation, managed, runtime
    from sot_graph.providers.compatibility import CompatibilityRegistry, TestedCompatibilityRecord
    from sot_graph.proc import run_command

    lab = Path(tempfile.mkdtemp(prefix='dl-', dir='/tmp')).resolve()
    os.chmod(lab, 0o700)
    repo = lab / 'repo'
    repo.mkdir(mode=0o700)
    (repo / 'alpha.py').write_text('def greet(name):\n    return "hello " + name\n')
    output = {'slot': args.exclusive_slot, 'scratch': str(lab), 'n': 3,
              'python': sys.executable, 'python_version': sys.version,
              'gettrace': repr(sys.gettrace()), 'getprofile': repr(sys.getprofile()),
              'instrumentation_env': suspect, 'binary': str(BINARY),
              'binary_bytes': BINARY.stat().st_size,
              'events': EVENTS, 'samples': [],
              'limits': ['Instrumented nested wall times are inclusive, not additive.',
                         'Python CPU excludes native descendants; no idle inference.',
                         'run_command includes spawn/poll/pipe-drain, not pure native CPU.',
                         'OS page cache warm; no eviction; no promotion inference.',
                         'Current vendored source is not assumed identical to signed release.']}
    result_path = HERE / 'diagnostic-result.json'
    def save():
        result_path.write_text(json.dumps(output, indent=2) + '\n')
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
            assert set(env or {}) == expected, 'native environment must be replacement seven-key env'
            assert env['PATH'] == '/usr/bin:/bin' and env['TERM'] == 'dumb'
            for key in expected - {'PATH', 'TERM'}:
                assert Path(env[key]).resolve().is_relative_to(lab), key
            assert Path(kwargs['cwd']).resolve() == repo
            captured.append((list(argv), dict(kwargs)))
            # Copy ephemeral JSON transport while it exists for same-command comparison.
            if '--args-file' in argv:
                captured[-1] += (Path(argv[argv.index('--args-file')+1]).read_text(),)
            with span('run_command_native_envelope', argv=argv) as row:
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                result = run_command(argv, **kwargs)
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                row.update(returncode=result.returncode, timed_out=result.timed_out,
                           stdout_bytes=len(result.stdout), stderr_bytes=len(result.stderr),
                           reaped_children_cpu_s=(after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime),
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
        for sample in range(3):
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
            output['samples'].append({'sample': sample, 'managed_status': outcome.status,
                                      'native_returncode': direct.returncode})
            save()
        PHASE = 'after'
        output['cache_after'] = fingerprint_cache(current.profile)
        output['final_status'] = current.profile.status()
        output['status'] = 'complete'
    except BaseException as exc:
        output['status'] = 'failed'
        output['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        save()
    print(json.dumps({'status': output['status'], 'result': str(result_path), 'scratch': str(lab)}))


if __name__ == '__main__':
    main()
