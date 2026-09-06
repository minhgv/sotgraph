import hashlib
import json
import subprocess

import pytest

from sot_graph.cli import main
from sot_graph.providers.artifacts import host_platform


@pytest.fixture
def lab(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    store = tmp_path / 'store'
    source = tmp_path / 'binary'
    source.write_bytes(b'not executable native code')
    source.chmod(0o700)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(dict(schema_version=1, name='codebase-memory',
        digest=digest, platform=host_platform(), protocol='artifacts-v1',
        engine_commit='46ae198fc11cda80e817acbc5f5908d7c2de7032')))
    def forbidden(*args, **kwargs):
        pytest.fail('artifact administration must never spawn')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    prefix = ['--root', str(repo), 'engine', '--store', str(store)]
    return prefix, source, manifest, digest, repo, store


def test_install_promote_rollback_and_status(lab, capsys):
    prefix, source, manifest, digest, repo, store = lab
    assert main(prefix + ['status']) == 1
    assert not store.exists()
    assert main(prefix + ['import', '--source', str(source), '--manifest', str(manifest)]) == 0
    assert main(prefix + ['status']) == 1
    assert main(prefix + ['promote', '--digest', digest]) == 0
    assert main(prefix + ['rollback', '--digest', digest]) == 0
    assert main(prefix + ['doctor']) == 0
    response = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert response['compatibility'] == 'not_assessed_by_artifact_administration'
    assert response['lifecycle'] == 'not_started'
    assert not (repo / '.sot').exists()
    executable = next(store.rglob('artifact'))
    before = executable.read_bytes()
    assert main(prefix + ['uninstall', '--digest', 'b' * 64]) == 2
    assert main(prefix + ['uninstall', '--digest', digest]) == 0
    assert main(prefix + ['status']) == 1
    assert executable.read_bytes() == before
    assert main(prefix + ['promote', '--digest', digest]) == 0


def test_wrong_digest_refused_and_unknown_data_preserved(lab):
    prefix, source, manifest, digest, repo, store = lab
    source.write_bytes(b'tampered')
    assert main(prefix + ['import', '--source', str(source), '--manifest', str(manifest)]) == 2
    assert main(prefix + ['promote', '--digest', digest]) == 2
    assert not (repo / '.sot').exists()


def test_search_normalizes_and_verifies_without_raw_payload(tmp_path):
    from types import SimpleNamespace
    from sot_graph.providers.admin import verified_search
    (tmp_path / 'alpha.py').write_text('def greet(name):\n    return name\n')
    payload = {'cols': ['qn', 'label', 'file', 'lines', 'rank'],
               'rows': [['repo.alpha.greet', 'Function', 'alpha.py', '1-2', 1]]}
    outcome = SimpleNamespace(ok=True, metadata={}, payload=payload)
    result = verified_search(outcome, str(tmp_path), 20)
    assert result['results'][0]['verified'] == 'VERIFIED'
    assert result['freshness'] == 'unknown'
    assert 'payload' not in result
    payload['rows'][0][3] = 12
    assert verified_search(outcome, str(tmp_path), 20)['status'] == 'abstained'
    payload['rows'] = [['short']]
    assert verified_search(outcome, str(tmp_path), 20)['status'] == 'abstained'
    payload['cols'] = ['unrecognized']
    assert verified_search(outcome, str(tmp_path), 20)['status'] == 'abstained'


@pytest.mark.parametrize('action', ['prepare', 'probe', 'sync', 'search', 'runtime-status'])
def test_operational_exit_and_multi_artifact_registry(lab, monkeypatch, action):
    from types import SimpleNamespace
    from sot_graph.providers import installation
    from sot_graph.providers.base import ProviderStatus
    from sot_graph.providers.compatibility import TestedCompatibilityRecord as Record
    prefix, source, manifest, digest, repo, store = lab
    assert main(prefix + ['import', '--source', str(source), '--manifest', str(manifest)]) == 0
    assert main(prefix + ['promote', '--digest', digest]) == 0
    registry = repo.parent / 'registry.json'
    def record(sha, fixture):
        return Record(provider_name='codebase-memory', operation='search_graph',
            artifact_sha256=sha, fixture_digest=fixture, protocol_compatibility_id='test-v1',
            engine_commit='46ae198fc11cda80e817acbc5f5908d7c2de7032',
            version='test', tested_by='unit-test', tested_at='2026-09-06T00:00:00Z').to_dict()
    selected = record(digest, 'a' * 64)
    selected['engine_commit'] = selected['engine_commit'].upper()
    registry.write_text(json.dumps([record('b' * 64, 'c' * 64), selected]))
    def factory(*args, **kwargs):
        assert kwargs['operation_fixture_digests'] == {'search_graph': 'a' * 64}
        assert len(kwargs['registry'].records()) == 1
        return SimpleNamespace(artifact=SimpleNamespace(executable=str(source)), exact_context=None,
            runtime=SimpleNamespace(prepare=lambda: {'status': 'ok'}),
            profile=SimpleNamespace(status=lambda: {'state': 'READY'}),
            provider=SimpleNamespace(probe=lambda root: ProviderStatus('test', True, True, None, ''),
                index=lambda request: {'status': 'ok'},
                search_symbols=lambda request: SimpleNamespace(ok=True, metadata={}, payload={'cols': ['qn', 'label', 'file', 'lines', 'rank'], 'rows': []})))
    monkeypatch.setattr(installation, 'create_managed_installation', factory)
    if action == 'sync':
        from sot_graph.providers import codebase_memory
        monkeypatch.setattr(codebase_memory, 'CodebaseMemoryProvider', lambda **kwargs: SimpleNamespace(index=lambda request: {'status': 'ok'}))
    args = prefix + [action, '--runtime-root', str(repo.parent / 'runtime'),
                     '--registry', str(registry), '--protocol', ' TEST-V1 ']
    if action == 'search':
        args.append('greet')
    assert main(args) == 0
    registry.write_text(json.dumps([selected, record(digest, 'd' * 64)]))
    assert main(args) == 2


@pytest.mark.parametrize('error_kind', ['busy', 'timeout', 'database', 'profile'])
def test_administration_errors_are_bounded(lab, monkeypatch, capsys, error_kind):
    import sqlite3
    from sot_graph.locking import LockBusy, LockTimeoutError
    from sot_graph.providers.runtime import ProfileRejected
    from sot_graph.providers import admin
    errors = {'busy': LockBusy, 'timeout': LockTimeoutError,
              'database': sqlite3.OperationalError, 'profile': ProfileRejected}
    def refused(*args, **kwargs):
        raise errors[error_kind]('untrusted diagnostic must not leak')
    monkeypatch.setattr(admin.ArtifactStore, 'resolve', refused)
    assert main(lab[0] + ['status']) == 2
    assert 'untrusted diagnostic' not in capsys.readouterr().out


def test_uninstall_missing_is_read_only(lab):
    prefix, source, manifest, digest, repo, store = lab
    assert main(prefix + ['uninstall', '--digest', digest]) == 2
    assert not store.exists()


def test_no_raw_execution_surface(lab):
    prefix, *_ = lab
    with pytest.raises(SystemExit):
        main(prefix + ['exec', 'search_graph'])
