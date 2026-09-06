"""SUR-12 scratch CLI lifecycle; mocked native boundary, not native acceptance."""
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from sot_graph.adapters.installer import install_harnesses
from sot_graph.cli import main
from sot_graph.providers.artifacts import host_platform
from sot_graph.providers.base import ProviderStatus
from sot_graph.providers.compatibility import TestedCompatibilityRecord as Record


def test_sur12_sot_only_upgrade_recovery_and_uninstall(tmp_path, monkeypatch, capsys):
    from sot_graph.providers import codebase_memory, installation

    repo = tmp_path / 'repo'
    repo.mkdir()
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / '.config'))

    def forbidden(*args, **kwargs):
        pytest.fail('mocked lifecycle must never spawn native commands')

    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    install_harnesses(['claude'], repo, global_install=False)
    config_before = (repo / '.mcp.json').read_bytes()
    assert set(json.loads(config_before)['mcpServers']) == {'sotgraph'}
    (repo / 'alpha.py').write_text('def greet(name):\n    return name\n')
    preserved = repo / 'user-notes.txt'
    preserved.write_text('user-owned evidence and notes')
    store = tmp_path / 'store'
    prefix = ['--root', str(repo), 'engine', '--store', str(store)]
    registry = tmp_path / 'registry.json'
    records = []
    digests = []
    commit = 'a' * 40
    calls = []
    state = {'healthy': True}

    def command(args, expected=0):
        assert main(prefix + args) == expected
        return json.loads(capsys.readouterr().out.splitlines()[-1])

    for version in ('one', 'two'):
        source = tmp_path / ('binary-' + version)
        source.write_bytes(('mock native ' + version).encode())
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        digests.append(digest)
        manifest = tmp_path / ('manifest-' + version + '.json')
        manifest.write_text(json.dumps(dict(
            schema_version=1, name='codebase-memory', digest=digest,
            platform=host_platform(), protocol='artifacts-v1', engine_commit=commit,
        )))
        command(['import', '--source', str(source), '--manifest', str(manifest)])
        records.append(Record(
            provider_name='codebase-memory', operation='search_graph',
            artifact_sha256=digest, fixture_digest='f' * 64,
            protocol_compatibility_id='surface-v1', engine_commit=commit,
            version=version, tested_by='mock-surface-test', tested_at='2026-09-06T00:00:00Z',
        ).to_dict())
    registry.write_text(json.dumps(records))

    def factory(artifact_store, **kwargs):
        artifact = artifact_store.resolve(kwargs['artifact_name'])
        assert artifact.digest in digests
        assert kwargs['repo_path'] == str(repo)
        assert kwargs['operation_fixture_digests'] == {'search_graph': 'f' * 64}
        assert {r.artifact_sha256 for r in kwargs['registry'].records()} == {artifact.digest}
        calls.append(('assemble', artifact.digest))

        def prepare():
            calls.append(('prepare', artifact.digest))
            state['healthy'] = True
            return {'status': 'ok'}

        def probe(root):
            assert root == str(repo)
            calls.append(('probe', artifact.digest))
            return ProviderStatus('codebase-memory', True, state['healthy'], None, '')

        def search(request):
            assert request.query == 'greet'
            assert request.repo_root == str(repo)
            calls.append(('search', artifact.digest))
            return SimpleNamespace(ok=True, metadata={}, payload={
                'cols': ['qn', 'label', 'file', 'lines', 'rank'],
                'rows': [['repo.alpha.greet', 'Function', 'alpha.py', '1-2', 1]],
            })

        return SimpleNamespace(
            artifact=artifact, exact_context=artifact.digest,
            runtime=SimpleNamespace(prepare=prepare),
            profile=SimpleNamespace(status=lambda: {'state': 'READY'}),
            provider=SimpleNamespace(probe=probe, search_symbols=search),
        )

    def ledger_provider(**kwargs):
        assert kwargs['db'] is not None
        assert kwargs['exact_context'] in digests
        assert kwargs['command'][0].startswith(str(store))

        def index(request):
            assert request.repo_root == str(repo)
            calls.append(('sync', kwargs['exact_context']))
            return {'status': 'ok'}

        return SimpleNamespace(index=index)

    monkeypatch.setattr(installation, 'create_managed_installation', factory)
    monkeypatch.setattr(codebase_memory, 'CodebaseMemoryProvider', ledger_provider)
    options = ['--runtime-root', str(tmp_path / 'runtime'), '--registry', str(registry),
               '--protocol', 'surface-v1']
    for digest in digests:
        command(['promote', '--digest', digest])
        assert command(['status'])['artifact']['digest'] == digest
        command(['prepare', *options])
        command(['probe', *options])
        command(['sync', *options])
        result = command(['search', *options, 'greet'])['result']
        assert result['results'][0]['verified'] == 'VERIFIED'
        assert 'payload' not in result
        command(['runtime-status', *options])
    state['healthy'] = False
    command(['probe', *options], expected=1)
    command(['prepare', *options])
    command(['probe', *options])
    command(['rollback', '--digest', digests[0]])
    assert command(['status'])['artifact']['digest'] == digests[0]
    command(['search', *options, 'greet'])
    before_uninstall = {str(p): p.read_bytes() for p in repo.rglob('*') if p.is_file()}
    command(['uninstall', '--digest', digests[1]], expected=2)
    assert command(['status'])['artifact']['digest'] == digests[0]
    command(['uninstall', '--digest', digests[0]])
    command(['status'], expected=1)
    assert {str(p): p.read_bytes() for p in repo.rglob('*') if p.is_file()} == before_uninstall
    assert (repo / '.mcp.json').read_bytes() == config_before
    assert preserved.read_text() == 'user-owned evidence and notes'
    for digest in digests:
        assert all((operation, digest) in calls for operation in ('prepare', 'probe', 'sync', 'search'))
