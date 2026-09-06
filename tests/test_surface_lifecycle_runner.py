"""Runner contract tests: subprocess fakes only; never launch native binaries."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


@pytest.fixture
def runner_module(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('surface_lifecycle_runner', scripts / 'check_surface_lifecycle.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'source_identity', lambda: {'files': {'source.py': 'fixed'}})
    monkeypatch.setattr(module, 'inventory', lambda lab: {'scratch': str(lab), 'coverage': 'fake'})
    monkeypatch.setattr(module, 'bounded_command', lambda argv: {'argv': argv, 'coverage': 'fake'})
    return module


@pytest.fixture
def inputs(tmp_path):
    binary = tmp_path / 'binary'
    binary.write_bytes(b'non-executable fake artifact')
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'records': [{'artifact_sha256': digest, 'engine_commit': 'a' * 40}]}))
    return ['--binary', str(binary), '--sha256', digest, '--native-commit', 'a' * 40,
            '--registry', str(registry), '--protocol', 'fixture-v1',
            '--output-dir', str(tmp_path / 'result')]


def fake_commands(module, monkeypatch, fail=None):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert argv[:3] == [sys.executable, '-I', '-B']
        lab = kwargs['cwd'].parent
        assert set(kwargs['env']) == {'HOME', 'XDG_CONFIG_HOME', 'TMPDIR', 'PATH', 'TERM', 'CBM_CACHE_DIR', 'CBM_RUNTIME_DIR'}
        for key in ('HOME', 'XDG_CONFIG_HOME', 'TMPDIR', 'CBM_CACHE_DIR', 'CBM_RUNTIME_DIR'):
            assert Path(kwargs['env'][key]).is_relative_to(lab)
        assert kwargs['env']['HOME'] == str(lab / 'home')
        assert kwargs['timeout_seconds'] == 180
        assert kwargs['max_output_bytes'] == 1048576
        assert kwargs['env']['PATH'] == '/usr/bin:/bin'
        assert kwargs['cwd'].name == 'repo'
        assert 'PYTHONPATH' not in kwargs['env']
        assert '--source' not in argv or argv[argv.index('engine') + 3] == 'import'
        return SimpleNamespace(returncode=9 if fail and fail in argv else 0,
                               stdout='{"fake":true}\n', stderr='', error=None,
                               timed_out=False, truncated=False)

    monkeypatch.setattr(module, 'run_command', run)
    return calls


def test_no_slot_is_blocked_without_subprocess(runner_module, inputs, monkeypatch, tmp_path):
    monkeypatch.setattr(runner_module, 'run_command', lambda *a, **k: pytest.fail('no commands allowed'))
    assert runner_module.main(inputs) == 2
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['status'] == 'BLOCKED'
    assert receipt['commands'] == []
    assert 'scratch' not in receipt


def test_full_fake_lifecycle_and_durable_receipts(runner_module, inputs, monkeypatch, tmp_path):
    calls = fake_commands(runner_module, monkeypatch)
    assert runner_module.main(inputs + ['--exclusive-slot', 'test-only']) == 0
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['status'] == 'SUPPLEMENTAL_PASS'
    assert receipt['rollback_kind'] == 'same-artifact-selection-only'
    assert receipt['persisted_cli_mcp'].startswith('BLOCKED')
    assert receipt['lifetime'].startswith('BLOCKED')
    labels = [row['label'] for row in receipt['commands']]
    assert labels == ['builtin-reconcile', 'import', 'promote', 'explicit-config-register',
                      'prepare', 'probe', 'sync', 'search', 'runtime-status', 'rollback',
                      'explicit-config-register', 'prepare', 'probe', 'search', 'runtime-status',
                      'explicit-config-disable', 'uninstall']
    assert all(row['returncode'] == 0 for row in receipt['commands'])
    for row in receipt['commands']:
        if row['label'] == 'search':
            argv = row['argv']
            assert argv[argv.index('--limit') + 1] == '20'
    assert 'private_search_outcome' in runner_module.CLI
    for row in receipt['commands']:
        for output in row['outputs'].values():
            path = tmp_path / 'result' / output['file']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == output['sha256']
    lab = Path(receipt['scratch'])
    assert lab.stat().st_mode & 0o777 == 0o700
    assert (lab / 'oldCBM/sentinel').read_bytes() == b'never adopt or remove legacy state\n'
    assert (lab / 'evidence/registry.json').read_bytes() == (tmp_path / 'registry.json').read_bytes()
    assert (lab / 'evidence/manifest-0.json').read_bytes() == (tmp_path / 'result/manifest-0.json').read_bytes()
    assert all('register' not in argv[6:9] for argv, _ in calls)


def test_actual_trusted_path_validation_on_runner_layout(runner_module, inputs, monkeypatch, tmp_path):
    # Exercise the production security validator, not a mock of registration.
    # No native binary or CLI subprocess is executed by this test.
    from sot_graph.providers.artifacts import ArtifactRejected
    from sot_graph.providers.trusted_config import _validate_paths

    calls = fake_commands(runner_module, monkeypatch)
    assert runner_module.main(inputs + ['--exclusive-slot', 'fake-layout']) == 0
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    lab = Path(receipt['scratch'])
    register = next(argv for argv, _ in calls if argv[-1] == 'register')
    repo, store, runtime, registry, _protocol, _generation, config, _action = register[-8:]
    entry = {'project_path': repo, 'store_path': store, 'runtime_root': runtime,
             'registry_path': registry}
    assert Path(config) == lab / 'config/managed.json'
    assert Path(registry) == lab / 'evidence/registry.json'
    assert (lab / 'evidence').stat().st_mode & 0o777 == 0o700
    _validate_paths(entry, Path(config))
    from sot_graph.providers.runtime import ManagedRuntimeProfile

    assert Path(runtime) == lab / 'r'
    # Constructor enforces the actual platform socket budget without native spawn.
    ManagedRuntimeProfile(runtime, repo, artifact_digest='a' * 64, generation='sur12-0')

    # Frozen v1 layout must still be rejected; production security is unchanged.
    old_registry = lab / 'config/registry.json'
    runner_module.private_write(old_registry, Path(registry).read_bytes())
    with pytest.raises(ArtifactRejected, match='disjoint'):
        _validate_paths({**entry, 'registry_path': str(old_registry)}, Path(config))


def test_failed_prepare_stops_dependents_and_keeps_outputs(runner_module, inputs, monkeypatch, tmp_path):
    fake_commands(runner_module, monkeypatch, fail='prepare')
    assert runner_module.main(inputs + ['--exclusive-slot', 'test-only']) == 1
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['status'] == 'FAILED'
    assert receipt['commands'][-1]['label'] == 'prepare'
    assert receipt['commands'][-1]['returncode'] == 9
    assert receipt['inventory_after']
    assert Path(receipt['scratch']).exists()


def test_pin_mismatch_never_allocates_scratch(runner_module, inputs, monkeypatch, tmp_path):
    fake_commands(runner_module, monkeypatch)
    inputs[inputs.index('--sha256') + 1] = '0' * 64
    assert runner_module.main(inputs + ['--exclusive-slot', 'test-only']) == 1
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['commands'] == []
    assert 'scratch' not in receipt


@pytest.mark.parametrize('case', ['oversize', 'inside-root', 'missing-records', 'commit-mismatch'])
def test_registry_refusals(runner_module, inputs, monkeypatch, tmp_path, case):
    fake_commands(runner_module, monkeypatch)
    registry = tmp_path / 'registry.json'
    if case == 'oversize':
        registry.write_bytes(b' ' * 262145)
    elif case == 'inside-root':
        monkeypatch.setattr(runner_module, 'ROOT', tmp_path)
    elif case == 'missing-records':
        registry.write_text('{}')
    else:
        payload = json.loads(registry.read_text())
        payload['records'][0]['engine_commit'] = 'b' * 40
        registry.write_text(json.dumps(payload))
    assert runner_module.main(inputs + ['--exclusive-slot', 'fake']) == 1
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['status'] == 'FAILED'
    assert not any(row['label'] == 'import' for row in receipt['commands'])


def test_validation_failure_does_not_invent_source_drift(runner_module, inputs, tmp_path):
    inputs[inputs.index('--sha256') + 1] = 'invalid'
    assert runner_module.main(inputs) == 1
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['source_drift'] == 'NOT_ASSESSED'


def test_refuses_existing_output(runner_module, inputs, tmp_path):
    (tmp_path / 'result').mkdir()
    with pytest.raises(FileExistsError):
        runner_module.main(inputs)


def test_same_artifact_second_input_rejected(runner_module, inputs):
    args = runner_module.parser().parse_args(inputs + ['--second-binary', inputs[1], '--second-sha256', inputs[3]])
    with pytest.raises(ValueError, match='distinct'):
        runner_module.validate(args)


def test_distinct_second_artifact_rolls_back_then_uninstalls_selected(runner_module, inputs, monkeypatch, tmp_path):
    calls = fake_commands(runner_module, monkeypatch)
    second = tmp_path / 'second'
    second.write_bytes(b'distinct non-executable artifact')
    digest = hashlib.sha256(second.read_bytes()).hexdigest()
    registry = tmp_path / 'registry.json'
    payload = json.loads(registry.read_text())
    payload['records'].append({'artifact_sha256': digest, 'engine_commit': 'b' * 40})
    registry.write_text(json.dumps(payload))
    assert runner_module.main(inputs + ['--exclusive-slot', 'fake', '--second-binary', str(second),
                                       '--second-sha256', digest]) == 0
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert receipt['rollback_kind'] == 'distinct-artifact'
    assert receipt['m5'].startswith('NOT_PROVEN')
    assert json.loads((tmp_path / 'result/manifest-1.json').read_text())['engine_commit'] == 'b' * 40
    uninstall = [argv for argv, _ in calls if 'uninstall' in argv]
    assert len(uninstall) == 1 and uninstall[0][-1] == inputs[3]


def test_timeout_is_durable_and_stops(runner_module, inputs, monkeypatch, tmp_path):
    def timeout(argv, **kwargs):
        return SimpleNamespace(returncode=None, stdout='', stderr='timeout retained',
                               timed_out=True, truncated=False, error='deadline exceeded')
    monkeypatch.setattr(runner_module, 'run_command', timeout)
    assert runner_module.main(inputs + ['--exclusive-slot', 'test-only']) == 1
    receipt = json.loads((tmp_path / 'result/receipt.json').read_text())
    assert len(receipt['commands']) == 1
    assert receipt['commands'][0]['timed_out'] is True
    assert receipt['commands'][0]['error'] == 'deadline exceeded'
    assert receipt['commands'][0]['returncode'] is None
    assert (tmp_path / 'result/00.stderr').read_bytes() == b'timeout retained'
