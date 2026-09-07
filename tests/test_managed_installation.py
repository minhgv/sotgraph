"""Narrow opt-in assembly tests: real artifact resolver, no native process."""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from sot_graph.providers.artifacts import (
    ARTIFACT_PROTOCOL_VERSION,
    ArtifactManifest,
    ArtifactRejected,
    ArtifactStore,
    host_platform,
)
from sot_graph.providers.codebase_memory import CodebaseMemoryProvider
from sot_graph.providers.compatibility import (
    CompatibilityRecordError,
    CompatibilityRegistry,
    TestedCompatibilityRecord,
)
from sot_graph.providers.installation import create_managed_installation
from sot_graph.providers.managed import QUERY_OPERATIONS, ManagedNativeRuntime
from sot_graph.providers.runtime import ManagedRuntimeProfile

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="managed artifact/runtime gate is POSIX-only by design (artifacts.py:75,155)")

OPS = QUERY_OPERATIONS | {
    "config_set_auto_watch", "config_get_auto_watch", "index_repository",
}
PROTOCOL = "cbm-cli-json-v1"
FIXTURE = "f" * 64


@pytest.fixture(autouse=True)
def no_spawn(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("factory must not spawn, discover executables, or prepare")
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("shutil.which", forbidden)
    monkeypatch.setattr(ManagedNativeRuntime, "prepare", forbidden)
    monkeypatch.setattr(ManagedRuntimeProfile, "initialize", forbidden)


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = tmp_path / "native"
    source.write_bytes(b"not a native executable\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = ArtifactStore(tmp_path / "artifacts", repo_path=repo)
    manifest = ArtifactManifest(
        1, "codebase-memory", digest, host_platform(),
        ARTIFACT_PROTOCOL_VERSION, "a" * 40,
    )
    artifact = store.import_artifact(source, manifest.manifest_bytes())
    store.promote(artifact.name, artifact.digest)
    # Darwin's native socket budget requires a genuinely short root.
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix="mi-", dir="/tmp")))
    shutil.rmtree(root)
    registry = CompatibilityRegistry()
    for op in OPS:
        registry.register(TestedCompatibilityRecord(
            provider_name="codebase-memory", operation=op,
            artifact_sha256=digest, fixture_digest=FIXTURE,
            protocol_compatibility_id=PROTOCOL,
        ))
    args = dict(
        artifact_name=artifact.name, repo_path=repo, runtime_root=root,
        registry=registry, operation_fixture_digests=dict.fromkeys(OPS, FIXTURE),
        native_protocol_id=PROTOCOL,
    )
    yield store, artifact, args
    shutil.rmtree(root, ignore_errors=True)


def test_identity_wiring_and_zero_writes(setup):
    store, artifact, args = setup
    before = {p: p.read_bytes() for p in store.root.parent.rglob("*") if p.is_file()}
    result = create_managed_installation(store, **args)
    assert result.artifact == artifact
    identity = result.exact_context.runtime_identity
    assert identity.artifact_sha256 == artifact.digest
    assert identity.engine_commit == artifact.engine_commit
    assert identity.protocol_compatibility_id == PROTOCOL
    assert artifact.protocol == ARTIFACT_PROTOCOL_VERSION != PROTOCOL
    assert result.provider.command == (artifact.executable,)
    assert result.provider._managed is result.runtime
    assert result.runtime._profile is result.profile
    assert result.runtime._provider._exact is result.exact_context
    assert result.provider._exact is result.exact_context
    assert result.provider._db is None
    assert not args["runtime_root"].exists()
    after = {p: p.read_bytes() for p in store.root.parent.rglob("*") if p.is_file()}
    assert after == before
    args["operation_fixture_digests"].clear()
    assert set(result.exact_context.operation_fixture_digests) == OPS


def test_artifact_protocol_is_not_implicitly_native_protocol(setup):
    store, _, args = setup
    args["native_protocol_id"] = ARTIFACT_PROTOCOL_VERSION
    with pytest.raises(CompatibilityRecordError):
        create_managed_installation(store, **args)


def test_host_mismatch_refuses(setup, monkeypatch):
    store, _, args = setup
    monkeypatch.setattr("sot_graph.providers.installation.host_platform", lambda: "other")
    with pytest.raises(ArtifactRejected, match="runtime host"):
        create_managed_installation(store, **args)


def test_fresh_generation_is_explicit_and_uninitialized(setup):
    store, _, args = setup
    first = create_managed_installation(store, **args)
    second = create_managed_installation(store, **args, generation="fresh-2")
    assert first.profile.namespace != second.profile.namespace
    assert not first.profile.namespace.exists()
    assert not second.profile.namespace.exists()


def test_missing_pointer_refuses_without_creating_root(setup):
    _, _, args = setup
    store = ArtifactStore(args["repo_path"].parent / "missing", repo_path=args["repo_path"])
    with pytest.raises(ArtifactRejected, match="promoted"):
        create_managed_installation(store, **args)
    assert not store.root.exists()
    assert not args["runtime_root"].exists()


def test_resolver_detects_tampered_executable(setup):
    store, artifact, args = setup
    executable = Path(artifact.executable)
    executable.chmod(0o700)
    executable.write_bytes(b"tampered")
    executable.chmod(0o500)
    with pytest.raises(ArtifactRejected):
        create_managed_installation(store, **args)
    assert not args["runtime_root"].exists()


@pytest.mark.parametrize("field,value", [
    ("provider_name", "other"), ("artifact_sha256", "b" * 64),
    ("protocol_compatibility_id", "other-v1"), ("fixture_digest", "c" * 64),
])
def test_mismatched_registry_identity_refuses(setup, field, value):
    store, artifact, args = setup
    registry = CompatibilityRegistry()
    for op in OPS:
        fields = dict(provider_name="codebase-memory", operation=op,
                      artifact_sha256=artifact.digest, fixture_digest=FIXTURE,
                      protocol_compatibility_id=PROTOCOL)
        fields[field] = value
        registry.register(TestedCompatibilityRecord(**fields))
    args["registry"] = registry
    with pytest.raises(CompatibilityRecordError):
        create_managed_installation(store, **args)
    assert not args["runtime_root"].exists()


@pytest.mark.parametrize("change", ["empty", "missing", "invalid", "protocol", "registry"])
def test_incomplete_context_fails_closed(setup, change):
    store, _, args = setup
    if change == "empty":
        args["operation_fixture_digests"] = {}
    elif change == "missing":
        args["operation_fixture_digests"].pop("index_repository")
    elif change == "invalid":
        args["operation_fixture_digests"]["search_graph"] = "invalid"
    elif change == "protocol":
        args["native_protocol_id"] = None
    else:
        args["registry"] = None
    with pytest.raises((TypeError, ValueError)):
        create_managed_installation(store, **args)
    assert not args["runtime_root"].exists()


def test_builtin_mode_does_not_resolve_promoted_artifact(setup, monkeypatch):
    from sot_graph.assurance import federation_plan

    _, _, args = setup

    def forbidden(*args, **kwargs):
        pytest.fail("builtin mode must not resolve managed artifacts")

    monkeypatch.setattr(ArtifactStore, "resolve", forbidden)
    plan = federation_plan("builtin", str(args["repo_path"]), "usages")
    assert plan["mode"] == "builtin"
    assert plan["provider"] is None
    assert plan["fail_message"] is None
    assert not args["runtime_root"].exists()


@pytest.mark.parametrize("overlap", [
    "repo_contains_store", "repo_is_store", "store_contains_repo",
    "runtime_is_store", "runtime_inside_store", "runtime_contains_store",
    "runtime_is_repo", "runtime_inside_repo", "runtime_contains_repo",
    "repo_alias_contains_store",
])
def test_path_overlap_refused_before_resolve_without_writes(setup, monkeypatch, overlap):
    store, _, args = setup
    repo = args["repo_path"]
    if overlap == "repo_contains_store":
        args["repo_path"] = store.root.parent
    elif overlap == "repo_is_store":
        args["repo_path"] = store.root
    elif overlap == "store_contains_repo":
        args["repo_path"] = store.root / "store"
    elif overlap == "repo_alias_contains_store":
        alias = repo / "alias"
        alias.symlink_to(store.root.parent, target_is_directory=True)
        args["repo_path"] = alias
    elif overlap == "runtime_is_store":
        args["runtime_root"] = store.root
    elif overlap == "runtime_inside_store":
        args["runtime_root"] = store.root / "runtime"
    elif overlap == "runtime_contains_store":
        args["runtime_root"] = store.root.parent
    elif overlap == "runtime_is_repo":
        args["runtime_root"] = repo
    elif overlap == "runtime_inside_repo":
        args["runtime_root"] = repo / "runtime"
    else:
        args["runtime_root"] = repo.parent

    def snapshot():
        return {
            str(p): (p.lstat().st_mode, p.read_bytes() if p.is_file() else None)
            for p in store.root.parent.rglob("*")
        }

    before = snapshot()

    def forbidden(*args, **kwargs):
        pytest.fail("invalid path layout must be rejected before artifact resolution")

    monkeypatch.setattr(ArtifactStore, "resolve", forbidden)
    with pytest.raises(ArtifactRejected, match="disjoint"):
        create_managed_installation(store, **args)
    assert snapshot() == before


def test_shared_store_with_unrelated_actual_repo_allowed_without_writes(setup):
    store, _, args = setup
    actual_repo = args["repo_path"].with_name("repo-b")
    actual_repo.mkdir()
    args["repo_path"] = actual_repo
    before = {p: p.read_bytes() for p in store.root.parent.rglob("*") if p.is_file()}
    result = create_managed_installation(store, **args)
    assert result.runtime._repo == str(actual_repo.resolve())
    assert result.provider._managed_repo == str(actual_repo.resolve())
    assert not args["runtime_root"].exists()
    assert list(actual_repo.iterdir()) == []
    assert before == {
        p: p.read_bytes() for p in store.root.parent.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("tail", ["", "missing/deeper"])
def test_case_variant_store_overlap_refused_before_resolve(setup, monkeypatch, tail):
    store, _, args = setup
    alias = store.root.with_name(store.root.name.upper())
    try:
        identical = os.path.samefile(store.root, alias)
    except FileNotFoundError:
        identical = False
    if not identical:
        pytest.skip("artifact filesystem is case-sensitive")
    args["runtime_root"] = alias / tail if tail else alias
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("case alias must be rejected before resolution")

    monkeypatch.setattr(ArtifactStore, "resolve", forbidden)
    with pytest.raises(ArtifactRejected, match="disjoint"):
        create_managed_installation(store, **args)
    assert before == {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert not (alias / "missing").exists()


def test_mocked_inode_alias_in_missing_tail_refused(setup, monkeypatch):
    store, _, args = setup
    alias = store.root.with_name("inode-alias")
    args["runtime_root"] = alias / "missing" / "deeper"
    original = os.path.samefile
    checked = []

    def samefile(left, right):
        checked.append((str(left), str(right)))
        if str(left) == str(store.root) and str(right) == str(alias):
            return True
        return original(left, right)

    def forbidden(*args, **kwargs):
        pytest.fail("inode alias must be rejected before resolution")

    monkeypatch.setattr(os.path, "samefile", samefile)
    monkeypatch.setattr(ArtifactStore, "resolve", forbidden)
    with pytest.raises(ArtifactRejected, match="disjoint"):
        create_managed_installation(store, **args)
    assert (str(store.root), str(alias)) in checked
    assert not alias.exists()


def test_samefile_permission_error_fails_closed(setup, monkeypatch):
    store, _, args = setup

    def denied(*args, **kwargs):
        raise PermissionError("injected identity lookup denial")

    def forbidden(*args, **kwargs):
        pytest.fail("identity lookup error must refuse before resolution")

    monkeypatch.setattr(os.path, "samefile", denied)
    monkeypatch.setattr(ArtifactStore, "resolve", forbidden)
    with pytest.raises(PermissionError, match="lookup denial"):
        create_managed_installation(store, **args)
    assert not args["runtime_root"].exists()


def test_case_distinct_directories_allowed_on_sensitive_filesystem(setup):
    store, _, args = setup
    repo = args["repo_path"].with_name("ARTIFACTS")
    if repo.exists():
        pytest.skip("artifact filesystem is case-insensitive")
    repo.mkdir()
    args["repo_path"] = repo
    result = create_managed_installation(store, **args)
    assert result.runtime._repo == str(repo)
    assert not args["runtime_root"].exists()


def test_factory_is_opt_in_legacy_constructor_unchanged():
    provider = CodebaseMemoryProvider()
    assert provider._managed is None
    assert provider._exact is None
    assert provider.command == ("codebase-memory-mcp",)
