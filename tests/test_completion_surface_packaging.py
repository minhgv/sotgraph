"""SUR-01/03/06/08/09 bounded packaging checks, not a live harness matrix."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from sot_graph.adapters.installer import install_harnesses
from sot_graph.providers.artifacts import (
    ARTIFACT_PROTOCOL_VERSION, ArtifactRejected, ArtifactStore, host_platform,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="managed artifact/runtime gate is POSIX-only by design (artifacts.py:75,155)")

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'surface_packaging', ROOT / 'scripts/check_surface_packaging.py')
assert SPEC is not None and SPEC.loader is not None
PACKAGING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGING)


@pytest.mark.parametrize('harness', ['omp', 'opencode', 'antigravity', 'claude', 'zcode'])
@pytest.mark.parametrize('global_install', [False, True])
def test_sur01_sur08_generated_setup_preserves_foreign_surface(
    tmp_path, monkeypatch, harness, global_install,
):
    """Exercise local generators, not the actual third-party harness programs."""
    home, root = tmp_path / 'home', tmp_path / 'workspace'
    home.mkdir()
    root.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / '.config'))
    for name in ('XDG_CACHE_HOME', 'XDG_DATA_HOME', 'XDG_RUNTIME_DIR'):
        monkeypatch.setenv(name, str(home / name.lower()))
    foreign = home / 'bin' / 'codebase-memory-mcp'
    foreign.parent.mkdir()
    foreign.write_bytes(b'preexisting CBM executable - never execute\n')
    completion = home / '.config/fish/completions/codebase-memory-mcp.fish'
    completion.parent.mkdir(parents=True)
    completion.write_text('# preexisting native completion\n')
    monkeypatch.setenv('PATH', str(foreign.parent) + os.pathsep + os.defpath)
    monkeypatch.setenv('CBM_KEEP_SENTINEL', 'unchanged')
    before_env = dict(os.environ)
    preserved = {foreign: foreign.read_bytes(), completion: completion.read_bytes()}
    config_paths = {
        'claude': ('.mcp.json', 'mcpServers'),
        'zcode': ('.zcode/config.json', 'mcp'),
        'opencode': ('.opencode/opencode.json', 'mcp'),
        'antigravity': ('.gemini/settings.json', 'mcpServers'),
    }
    foreign_entry = {'command': str(foreign), 'args': ['mcp'],
                     'env': {'KEEP': 'yes', 'PATH': '/preexisting/bin'}}
    config = None
    key = ''
    entries = {}
    if harness in config_paths:
        relative, key = config_paths[harness]
        config = root / relative
        config.parent.mkdir(parents=True, exist_ok=True)
        entries = {'codebase-memory': foreign_entry, 'unrelated': {'url': 'https://invalid'}}
        payload = {key: {'servers': entries} if harness == 'zcode' else entries,
                   'foreign_setting': ['preserve']}
        config.write_text(json.dumps(payload))
    else:
        extension = root / '.omp/extensions/foreign.ts'
        extension.parent.mkdir(parents=True)
        extension.write_text('// user-owned native extension\n')
        preserved[extension] = extension.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail('setup must not execute processes or open network sockets')

    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    for name in ('system', 'popen', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp',
                 'spawnl', 'spawnle', 'spawnlp', 'spawnlpe', 'spawnv', 'spawnve',
                 'spawnvp', 'spawnvpe', 'execl', 'execle', 'execlp', 'execlpe',
                 'execv', 'execve', 'execvp', 'execvpe'):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    first = install_harnesses([harness], root, global_install=global_install)
    after_first = PACKAGING.snapshot(tmp_path)
    second = install_harnesses([harness], root, global_install=global_install)
    assert second == first
    assert PACKAGING.snapshot(tmp_path) == after_first
    assert dict(os.environ) == before_env
    assert all(p.read_bytes() == content for p, content in preserved.items())
    assert set(first) == {harness}
    for path in first[harness]:
        assert Path(path).is_relative_to(tmp_path)
    if config is not None:
        result = json.loads(config.read_text())
        actual = result[key]['servers'] if harness == 'zcode' else result[key]
        assert set(actual) == set(entries) | {'sotgraph'}
        assert {k: actual[k] for k in entries} == entries
        assert result['foreign_setting'] == ['preserve']


@pytest.mark.parametrize('global_install', [False, True])
def test_sur08_omp_foreign_rules_preserved(tmp_path, monkeypatch, global_install):
    home, root = tmp_path / 'home', tmp_path / 'workspace'
    home.mkdir()
    root.mkdir()
    monkeypatch.setenv('HOME', str(home))
    rules = (home if global_install else root) / '.omp/RULES.md'
    rules.parent.mkdir()
    original = '# User rules\nNever modify my native CBM installation.\n'
    rules.write_text(original)
    install_harnesses(['omp'], root, global_install=global_install,
                      workspace_install=not global_install)
    assert original in rules.read_text()
    first = rules.read_bytes()
    install_harnesses(['omp'], root, global_install=global_install,
                      workspace_install=not global_install)
    assert rules.read_bytes() == first


def test_sur08_omp_non_utf8_rules_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    root = tmp_path / 'workspace'
    rules = root / '.omp/RULES.md'
    rules.parent.mkdir(parents=True)
    original = b'foreign prefix\xff\r\nforeign suffix\xfe\r\n'
    rules.write_bytes(original)
    install_harnesses(['omp'], root, global_install=False)
    first = rules.read_bytes()
    assert original in first
    # Add foreign bytes after the generated block as well.
    suffix = b'\nforeign trailing bytes\x80\xff\n'
    rules.write_bytes(first + suffix)
    install_harnesses(['omp'], root, global_install=False)
    assert rules.read_bytes() == first + suffix


def test_sur09_upgrade_between_uninstall_checks_preserves_new_owner(tmp_path, monkeypatch):
    """Deterministic race injection, inert artifacts: NOT native cross-version E2E."""
    repo = tmp_path / 'workspace'
    repo.mkdir()
    preserved = {}
    for name in ('source.py', 'notes.db', 'evidence.json'):
        path = repo / name
        path.write_text('user-owned sentinel ' + name)
        preserved[path] = path.read_bytes()
    store = ArtifactStore(tmp_path / 'admin/artifacts', repo_path=repo)

    def forbidden(*args, **kwargs):
        pytest.fail('artifact administration must not execute native processes')

    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    descriptors = []
    for version in (1, 2):
        source = tmp_path / f'engine-{version}'
        source.write_bytes(f'INERT NEVER EXECUTE {version}'.encode())
        preserved[source] = source.read_bytes()
        manifest = {'schema_version': 1, 'name': 'demo-engine',
                    'digest': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'platform': host_platform(), 'protocol': ARTIFACT_PROTOCOL_VERSION,
                    'engine_commit': str(version) * 40}
        descriptors.append(store.import_artifact(source, json.dumps(manifest).encode()))
    old, new = descriptors
    store.promote('demo-engine', old.digest)
    original_mutation = store._mutation

    @contextmanager
    def promote_before_lock():
        # Interleave a second administrator after uninstall's first resolve,
        # but before its critical-section revalidation.
        monkeypatch.setattr(store, '_mutation', original_mutation)
        store.promote('demo-engine', new.digest)
        with original_mutation():
            yield

    monkeypatch.setattr(store, '_mutation', promote_before_lock)
    with pytest.raises(ArtifactRejected, match='exact selected digest'):
        store.uninstall('demo-engine', old.digest)
    selected = store.resolve('demo-engine')
    assert selected is not None and selected.digest == new.digest
    store.promote('demo-engine', old.digest)
    retained = PACKAGING.snapshot(store.root)
    store.uninstall('demo-engine', old.digest)
    assert store.resolve('demo-engine') is None
    after = PACKAGING.snapshot(store.root)
    removed = set(retained) - set(after)
    assert len(removed) == 1
    assert next(iter(removed)).startswith('pointers/')
    assert all(after[key] == value for key, value in retained.items() if key not in removed)
    assert all(path.read_bytes() == content for path, content in preserved.items())


def _wheel(tmp_path, entry='sotgraph = sot_graph.cli:main', extra=None):
    wheel = tmp_path / 'sot_graph-0.3.2-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('sot_graph-0.3.2.dist-info/entry_points.txt',
                         '[console_scripts]\n' + entry + '\n')
        archive.writestr('sot_graph/__init__.py', '')
        if extra:
            archive.writestr(extra, '# forbidden payload')
    return wheel


def test_sur09_timeout_receipt_retains_command_and_partial_output(tmp_path, monkeypatch):
    output = tmp_path / 'audit'

    def timeout(args, **kwargs):
        pending = json.loads((output / 'receipt.json').read_text())
        assert pending['commands'][-1]['argv'] == args
        assert pending['commands'][-1]['state'] == 'started'
        assert kwargs['timeout_seconds'] == 120
        assert kwargs['max_output_bytes'] == 2 * 1024 * 1024
        return SimpleNamespace(returncode=None, stdout='partial output', stderr='deadline',
                               timed_out=True, truncated=False, error=None)

    monkeypatch.setattr(PACKAGING, 'run_command', timeout)
    with pytest.raises(RuntimeError, match='command failed'):
        PACKAGING.run_audit(_wheel(tmp_path), output, [])
    receipt = json.loads((output / 'receipt.json').read_text())
    assert receipt['result'] == 'BLOCKED'
    assert receipt['commands'][0]['timed_out'] is True
    assert receipt['commands'][0]['stdout'] == 'partial output'
    assert receipt['commands'][0]['stderr'] == 'deadline'


@pytest.mark.parametrize('text', ['[other]\nsotgraph = sot_graph.cli:main\n',
                                  '[console_scripts]\nSOT = sot_graph.cli:main\n'])
def test_sur03_missing_or_case_changed_console_manifest_refused(tmp_path, text):
    wheel = tmp_path / 'invalid.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('sot_graph.dist-info/entry_points.txt', text)
    with pytest.raises(ValueError, match='console entry points'):
        PACKAGING.audit_wheel(wheel)


def test_sur03_wheel_audit_requires_sot_only_entrypoints(tmp_path):
    wheel = _wheel(tmp_path)
    assert PACKAGING.audit_wheel(wheel)['entries'] == {'sotgraph': 'sot_graph.cli:main'}
    wheel = _wheel(tmp_path, 'codebase-memory-mcp = sot_graph.cli:main')
    with pytest.raises(ValueError, match='public console'):
        PACKAGING.audit_wheel(wheel)


@pytest.mark.parametrize('extra', [
    'engines/native/install.sh', 'sot_graph-0.3.2.data/scripts/cbm',
    'share/fish/completions/cbm.fish',
])
def test_sur03_wheel_audit_rejects_native_public_payload(tmp_path, extra):
    with pytest.raises(ValueError, match='public/native payload'):
        PACKAGING.audit_wheel(_wheel(tmp_path, extra=extra))


def test_sur06_python_build_does_not_execute_upstream_hooks(tmp_path):
    """Poison scratch upstream hooks and deny subprocess/network in build child.

    Tests the actual Python build boundary; NOT upstream install.sh safety when
    manually invoked, native compilation, or an OS-level process/network audit.
    Set SOT_TEST_SETUPTOOLS_PATH to an already cached backend if not installed.
    """
    backend = os.environ.get('SOT_TEST_SETUPTOOLS_PATH')
    if not backend and importlib.util.find_spec('setuptools') is None:
        pytest.skip('offline setuptools backend unavailable; set SOT_TEST_SETUPTOOLS_PATH')
    project = tmp_path / 'source'
    project.mkdir()
    for name in ('pyproject.toml', 'README.md', 'LICENSE'):
        shutil.copy2(ROOT / name, project / name)
    shutil.copytree(ROOT / 'src', project / 'src',
                    ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
    sentinel = tmp_path / 'upstream-hook-executed'
    for relative in ('install.sh', 'scripts/setup.sh', 'pkg/npm/install.js', 'install.ps1'):
        hook = project / 'engines/codebase-memory-mcp' / relative
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(f'#!/bin/sh\nprintf executed > "{sentinel}"\nexit 98\n')
        hook.chmod(0o700)
    home = tmp_path / 'home'
    home.mkdir()
    dist = tmp_path / 'dist'
    dist.mkdir()
    env = {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
           'XDG_CACHE_HOME': str(home / '.cache'), 'PATH': '/usr/bin:/bin',
           'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    if backend:
        env['PYTHONPATH'] = backend
    code = '''
import os, socket, subprocess, sys
from setuptools import build_meta

def deny(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn',
                 'os.spawn', 'os.fork', 'os.forkpty',
                 'socket.connect', 'socket.bind', 'socket.getaddrinfo'}:
        raise RuntimeError('forbidden build effect: ' + event)
sys.addaudithook(deny)
print(build_meta.build_wheel(sys.argv[1]))
'''
    result = subprocess.run([sys.executable, '-c', code, str(dist)],
                            cwd=project, env=env, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-4000:]
    assert not sentinel.exists()
    assert PACKAGING.snapshot(home) == {}
    wheels = list(dist.glob('*.whl'))
    assert len(wheels) == 1
    PACKAGING.audit_wheel(wheels[0])


def test_sur09_audit_output_never_overwrites_prior_run(tmp_path, monkeypatch):
    wheel = _wheel(tmp_path)
    output = tmp_path / 'existing'
    output.mkdir()
    receipt = output / 'receipt.json'
    receipt.write_text('preserve previous evidence')

    def forbidden(*args, **kwargs):
        pytest.fail('refusal must precede subprocess execution')

    monkeypatch.setattr(PACKAGING, 'run_command', forbidden)
    with pytest.raises(FileExistsError):
        PACKAGING.run_audit(wheel, output, [])
    assert receipt.read_text() == 'preserve previous evidence'
