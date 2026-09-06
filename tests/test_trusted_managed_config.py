"""Independent trusted configuration boundary tests; never execute native code."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from sot_graph.providers import trusted_config as config
from sot_graph.providers.artifacts import ArtifactManifest, ArtifactStore, host_platform
from sot_graph.providers.compatibility import TestedCompatibilityRecord as Record
from sot_graph.providers.managed import QUERY_OPERATIONS, ManagedNativeRuntime
from sot_graph.providers.runtime import ManagedRuntimeProfile


@pytest.fixture
def trusted_lab(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("trusted configuration administration must never spawn or prepare")
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("shutil.which", forbidden)
    monkeypatch.setattr(ManagedNativeRuntime, "prepare", forbidden)
    monkeypatch.setattr(ManagedRuntimeProfile, "initialize", forbidden)
    root = tmp_path.resolve()
    repo = root / "repo"
    repo.mkdir()
    private = root / "private"
    private.mkdir(mode=0o700)
    path = private / "managed.json"
    source = root / "native"
    source.write_bytes(b"inert fixture, not a native program\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = ArtifactStore(root / "artifacts", repo_path=repo)
    manifest = ArtifactManifest(1, "codebase-memory", digest, host_platform(),
                                "artifacts-v1", "a" * 40)
    artifact = store.import_artifact(source, manifest.manifest_bytes())
    store.promote(artifact.name, artifact.digest)
    runtime = Path(os.path.realpath(tempfile.mkdtemp(prefix="tc-", dir="/tmp")))
    shutil.rmtree(runtime)
    registry = root / "registry.json"
    operations = QUERY_OPERATIONS | {"config_set_auto_watch", "config_get_auto_watch", "index_repository"}
    records = [Record(provider_name="codebase-memory", operation=op,
                      artifact_sha256=digest, fixture_digest="f" * 64,
                      protocol_compatibility_id="cbm-cli-json-v1",
                      engine_commit="a" * 40).to_dict() for op in sorted(operations)]
    registry.write_text(json.dumps(records))
    registry.chmod(0o600)
    kwargs = dict(store_path=store.root, artifact_name=artifact.name,
                  runtime_root=runtime, registry_path=registry,
                  native_protocol_id="cbm-cli-json-v1", config_path=path)
    monkeypatch.setattr(config, "default_config_path", lambda: path)
    yield SimpleNamespace(repo=repo, path=path, private=private, store=store,
                          artifact=artifact, runtime=runtime, registry=registry,
                          records=records, kwargs=kwargs)
    shutil.rmtree(runtime, ignore_errors=True)


def test_missing_configuration_is_default_off_without_mkdir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = tmp_path / "absent" / "managed.json"
    assert config.load_managed_installation(repo, config_path=path) is None
    assert config.disable_managed_installation(repo, config_path=path) is False
    config.managed_config_status(repo, config_path=path)
    assert not path.parent.exists()
    assert not (repo / ".sot").exists()


def test_registration_survives_reload_with_canonical_project_binding(trusted_lab):
    lab = trusted_lab
    registered = config.register_managed_installation(lab.repo, **lab.kwargs)
    data = json.loads(lab.path.read_text())
    key = hashlib.sha256(str(lab.repo.resolve()).encode()).hexdigest()
    assert data["schema_version"] == 1
    entry = data["projects"][key]
    assert entry["project_path"] == str(lab.repo.resolve())
    assert entry["artifact_digest"] == lab.artifact.digest
    assert entry["enabled"] is True
    alias = lab.repo.parent / "repo-alias"
    alias.symlink_to(lab.repo, target_is_directory=True)
    loaded = config.load_managed_installation(alias, config_path=lab.path)
    assert loaded is not None
    assert loaded.artifact == registered.artifact
    assert loaded.profile.namespace == registered.profile.namespace
    assert not lab.runtime.exists()
    assert lab.path.stat().st_mode & 0o077 == 0
    other = lab.repo.parent / "other"
    other.mkdir()
    assert config.load_managed_installation(other, config_path=lab.path) is None


@pytest.mark.parametrize("payload", ["{", "[]", "null", '{"schema_version":2,"projects":{}}',
                                     '{"schema_version":1,"projects":[]}', " " * 262145])
def test_malformed_or_oversized_configuration_fails_closed(trusted_lab, payload):
    lab = trusted_lab
    lab.path.write_text(payload)
    lab.path.chmod(0o600)
    with pytest.raises(config.TrustedConfigError):
        config.load_managed_installation(lab.repo, config_path=lab.path)
    assert not lab.runtime.exists()


@pytest.mark.parametrize("target", ["config", "parent", "registry"])
def test_symlink_trust_inputs_are_rejected(trusted_lab, target):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    original = {"config": lab.path, "parent": lab.private, "registry": lab.registry}[target]
    moved = original.with_name(original.name + "-real")
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(config.TrustedConfigError):
        config.load_managed_installation(lab.repo, config_path=lab.path)


@pytest.mark.parametrize("target,mode", [("config", 0o666), ("parent", 0o777), ("registry", 0o666)])
def test_unsafe_permissions_are_rejected(trusted_lab, target, mode):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    path = {"config": lab.path, "parent": lab.private, "registry": lab.registry}[target]
    path.chmod(mode)
    with pytest.raises(config.TrustedConfigError):
        config.load_managed_installation(lab.repo, config_path=lab.path)


@pytest.mark.parametrize("field", ["project_path", "artifact_digest"])
def test_persisted_binding_tampering_fails_closed(trusted_lab, field):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    data = json.loads(lab.path.read_text())
    entry = next(iter(data["projects"].values()))
    entry[field] = str(lab.repo.parent / "other") if field == "project_path" else "b" * 64
    lab.path.write_text(json.dumps(data))
    with pytest.raises(config.TrustedConfigError):
        config.load_managed_installation(lab.repo, config_path=lab.path)


@pytest.mark.parametrize("field", ["config_path", "registry_path", "runtime_root", "store_path"])
def test_repository_cannot_contain_trusted_paths(trusted_lab, field):
    lab = trusted_lab
    kwargs = dict(lab.kwargs)
    kwargs[field] = lab.repo / "untrusted"
    if field == "registry_path":
        kwargs[field].write_text(json.dumps(lab.records))
        kwargs[field].chmod(0o600)
    with pytest.raises(config.TrustedConfigError):
        config.register_managed_installation(lab.repo, **kwargs)
    assert not lab.path.exists()


@pytest.mark.parametrize("mismatch", ["protocol", "digest", "executable"])
def test_real_artifact_and_registry_mismatches_fail_closed(trusted_lab, mismatch):
    lab = trusted_lab
    kwargs = dict(lab.kwargs)
    if mismatch == "protocol":
        kwargs["native_protocol_id"] = "artifacts-v1"
    elif mismatch == "digest":
        for record in lab.records:
            record["artifact_sha256"] = "b" * 64
        lab.registry.write_text(json.dumps(lab.records))
    else:
        executable = Path(lab.artifact.executable)
        executable.chmod(0o700)
        executable.write_bytes(b"tampered")
        executable.chmod(0o500)
    with pytest.raises(config.TrustedConfigError):
        config.register_managed_installation(lab.repo, **kwargs)
    assert not lab.path.exists()
    assert not lab.runtime.exists()


def test_disable_preserves_repository_evidence_and_does_not_resolve(trusted_lab, monkeypatch):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    sot = lab.repo / ".sot"
    sot.mkdir()
    for name in ("sot.db", "notes.json", "evidence.json", "index.scip"):
        (sot / name).write_bytes(b"opaque existing data " + name.encode())
    before = {p: p.read_bytes() for p in lab.repo.parent.rglob("*")
              if p.is_file() and p != lab.path}
    def forbidden(*args, **kwargs):
        pytest.fail("disable and disabled reads must not resolve artifacts")
    monkeypatch.setattr(ArtifactStore, "resolve", forbidden)
    assert config.disable_managed_installation(lab.repo, config_path=lab.path) is True
    assert config.load_managed_installation(lab.repo, config_path=lab.path) is None
    config.managed_config_status(lab.repo, config_path=lab.path)
    after = {p: p.read_bytes() for p in lab.repo.parent.rglob("*")
             if p.is_file() and p != lab.path}
    assert after == before


def test_default_path_uses_account_home_not_environment(tmp_path, monkeypatch):
    import pwd
    home = tmp_path.resolve() / "account-home"
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(home)))
    monkeypatch.setenv("HOME", str(tmp_path / "attacker-home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "attacker-config"))
    assert config.default_config_path() == home / ".config" / "sot-graph" / "managed.json"
    assert not home.exists()


@pytest.mark.parametrize("target", ["config", "registry"])
def test_foreign_file_owner_is_rejected(trusted_lab, monkeypatch, target):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    victim = lab.path if target == "config" else lab.registry
    original = Path.lstat
    def foreign_stat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == victim:
            return SimpleNamespace(st_mode=info.st_mode, st_uid=os.getuid() + 1,
                                   st_nlink=info.st_nlink)
        return info
    monkeypatch.setattr(Path, "lstat", foreign_stat)
    with pytest.raises(config.TrustedConfigError):
        config.load_managed_installation(lab.repo, config_path=lab.path)


@pytest.mark.parametrize("target", ["config", "registry"])
def test_hardlinked_trust_file_is_rejected(trusted_lab, target):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    victim = lab.path if target == "config" else lab.registry
    os.link(victim, victim.with_name(victim.name + ".alias"))
    with pytest.raises(config.TrustedConfigError):
        config.load_managed_installation(lab.repo, config_path=lab.path)


def test_changed_promoted_digest_requires_explicit_registration(trusted_lab):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    source = lab.repo.parent / "replacement"
    source.write_bytes(b"another inert artifact")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = ArtifactManifest(1, lab.artifact.name, digest, host_platform(),
                                "artifacts-v1", "a" * 40)
    artifact = lab.store.import_artifact(source, manifest.manifest_bytes())
    lab.store.promote(artifact.name, artifact.digest)
    with pytest.raises(config.TrustedConfigError):
        config.load_managed_installation(lab.repo, config_path=lab.path)
    assert not lab.runtime.exists()


@pytest.mark.parametrize("unsupported", ["os", "pwd"])
def test_unsupported_platform_defaults_off_but_explicit_admin_refuses(trusted_lab, monkeypatch, unsupported):
    lab = trusted_lab
    # Replace only this module's os binding; changing os.name globally breaks pathlib.
    if unsupported == "os":
        proxy = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        proxy.name = "nt"
        monkeypatch.setattr(config, "os", proxy)
    else:
        monkeypatch.setattr(config, "pwd", None)
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported platform must not inspect the filesystem")
    with monkeypatch.context() as local:
        local.setattr(Path, "lstat", forbidden)
        local.setattr(Path, "stat", forbidden)
        assert config.load_managed_installation(lab.repo) is None
        with pytest.raises(config.TrustedConfigError, match="unsupported"):
            config.load_managed_installation(lab.repo, config_path=lab.path)
        with pytest.raises(config.TrustedConfigError, match="unsupported"):
            config.register_managed_installation(lab.repo, **lab.kwargs)
        with pytest.raises(config.TrustedConfigError, match="unsupported"):
            config.disable_managed_installation(lab.repo, config_path=lab.path)
        for options in ({}, {"config_path": lab.path}):
            status = config.managed_config_status(lab.repo, **options)
            assert status["schema_version"] == 2
            assert status["status"] == "refused"
            assert status["reason"] == "unsupported_platform"
            assert status["ready"] is False
            assert status["runtime_status"] == "NOT_ASSESSED"
            assert status["query_permission"] == "not_assessed"


@pytest.mark.parametrize("unsupported", ["os", "pwd"])
def test_default_config_path_reports_unsupported_platform(monkeypatch, unsupported):
    if unsupported == "os":
        proxy = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        proxy.name = "nt"
        monkeypatch.setattr(config, "os", proxy)
    else:
        monkeypatch.setattr(config, "pwd", None)
    with pytest.raises(config.TrustedConfigError, match="unsupported"):
        config.default_config_path()


def test_unavailable_fcntl_refuses_before_filesystem_mutation(trusted_lab, monkeypatch):
    import builtins
    lab = trusted_lab
    original = builtins.__import__
    def missing_lock(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("fixture lock support unavailable")
        return original(name, *args, **kwargs)
    kwargs = dict(lab.kwargs)
    path = lab.repo.parent / "not-created" / "managed.json"
    kwargs["config_path"] = path
    monkeypatch.setattr(builtins, "__import__", missing_lock)
    with pytest.raises(config.TrustedConfigError):
        config.register_managed_installation(lab.repo, **kwargs)
    assert not path.parent.exists()
    assert not lab.runtime.exists()


def test_existing_public_config_ancestor_with_private_final_parent_is_supported(trusted_lab):
    lab = trusted_lab
    ancestor = lab.repo.parent / ".config"
    ancestor.mkdir(mode=0o755)
    ancestor.chmod(0o755)
    parent = ancestor / "sot-graph"
    parent.mkdir(mode=0o700)
    path = parent / "managed.json"
    kwargs = dict(lab.kwargs, config_path=path)
    config.register_managed_installation(lab.repo, **kwargs)
    assert config.load_managed_installation(lab.repo, config_path=path) is not None
    assert parent.stat().st_mode & 0o777 == 0o700
    assert ancestor.stat().st_mode & 0o777 == 0o755
    assert not lab.runtime.exists()


@pytest.mark.parametrize("home", ["", "relative/home", None, 42])
def test_invalid_account_home_never_falls_back_to_cwd(monkeypatch, home):
    import pwd
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=home))
    def forbidden(*args, **kwargs):
        pytest.fail("invalid account home must be rejected before resolving paths")
    monkeypatch.setattr(Path, "resolve", forbidden)
    with pytest.raises(config.TrustedConfigError):
        config.default_config_path()


@pytest.mark.parametrize("competing_mode", [0o700, 0o755, 0o777])
def test_initial_directory_creation_race_revalidates_permissions(trusted_lab, monkeypatch, competing_mode):
    lab = trusted_lab
    parent = lab.repo.parent / "raced-config"
    path = parent / "managed.json"
    kwargs = dict(lab.kwargs, config_path=path)
    original = Path.mkdir
    raced = []
    def competing_mkdir(directory, *args, **options):
        if directory == parent and not raced:
            raced.append(directory)
            original(directory, mode=competing_mode)
            directory.chmod(competing_mode)
        return original(directory, *args, **options)
    monkeypatch.setattr(Path, "mkdir", competing_mkdir)
    if competing_mode == 0o700:
        config.register_managed_installation(lab.repo, **kwargs)
        assert config.load_managed_installation(lab.repo, config_path=path) is not None
    else:
        with pytest.raises(config.TrustedConfigError):
            config.register_managed_installation(lab.repo, **kwargs)
        assert not path.exists()
        assert parent.stat().st_mode & 0o777 == competing_mode
    assert raced == [parent]
    assert not lab.runtime.exists()


def test_malformed_unrelated_project_blocks_load_and_disable_without_rewriting(trusted_lab, monkeypatch):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    data = json.loads(lab.path.read_text())
    unrelated = str(lab.repo.parent / "unrelated")
    key = hashlib.sha256(unrelated.encode()).hexdigest()
    data["projects"][key] = {"project_path": unrelated, "enabled": True}
    corrupt = json.dumps(data, indent=3).encode() + b"\n"
    lab.path.write_bytes(corrupt)
    def forbidden(*args, **kwargs):
        pytest.fail("invalid configuration authority must not resolve any artifact")
    monkeypatch.setattr(ArtifactStore, "resolve", forbidden)
    for operation in (config.load_managed_installation, config.disable_managed_installation):
        with pytest.raises(config.TrustedConfigError):
            operation(lab.repo, config_path=lab.path)
        assert lab.path.read_bytes() == corrupt
    status = config.managed_config_status(lab.repo, config_path=lab.path)
    assert status["status"] == "refused"
    assert status["reason"] == "config_refused"
    assert status["ready"] is False
    assert status["runtime_status"] == "NOT_ASSESSED"
    assert status["query_permission"] == "not_assessed"
    assert lab.path.read_bytes() == corrupt
    assert not lab.runtime.exists()


def test_repository_config_cannot_self_enable_or_select_registry(trusted_lab):
    lab = trusted_lab
    sot = lab.repo / ".sot"
    sot.mkdir()
    (sot / "config.json").write_text(json.dumps({"managed": {"enabled": True,
        "registry_path": str(lab.registry), "config_path": str(lab.path)},
        "providers": {"codebase-memory": {"enabled": True, "managed": True}}}))
    assert config.load_managed_installation(lab.repo, config_path=lab.path) is None
    assert not lab.path.exists()
    assert not lab.runtime.exists()
