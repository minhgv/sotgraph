"""Independent M3b shared-dispatch contracts; inert artifacts, no native execution."""
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_trusted_managed_config import trusted_lab as _trusted_lab
from sot_graph.assurance import orchestrator as orch
from sot_graph.providers import trusted_config as config
from sot_graph.providers.codebase_memory import CodebaseMemoryProvider
from sot_graph.providers.managed import ManagedNativeRuntime
from sot_graph.providers.runtime import ManagedRuntimeProfile

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="managed artifact/runtime gate is POSIX-only by design (artifacts.py:75,155)")


trusted_lab = _trusted_lab


@pytest.fixture(autouse=True)
def no_legacy_or_writes(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("managed read attempted discovery, database construction or mutation")
    monkeypatch.delenv("SOT_PROVIDERS_ALLOW_EXTERNAL", raising=False)
    monkeypatch.setattr(orch, "federation_plan", forbidden)
    monkeypatch.setattr(CodebaseMemoryProvider, "probe", forbidden)
    monkeypatch.setattr(ManagedNativeRuntime, "sync", forbidden)
    monkeypatch.setattr(CodebaseMemoryProvider, "index", forbidden)
    monkeypatch.setattr(CodebaseMemoryProvider, "_persist_run", forbidden)
    monkeypatch.setattr("sot_graph.db.Database.__init__", forbidden)


def dispatch(lab, policy="require_external", **kwargs):
    return orch.managed_read_dispatch(str(lab.repo), "search", "target",
                                      provider_policy=policy, **kwargs)


def assert_refusal(result, policy, reason):
    assert result["status"] == ("error" if policy == "require_external" else "fallback")
    assert result["reason"] == reason
    assert bool(result["fail_message"]) == (policy == "require_external")
    assert bool(result["warnings"]) == (policy == "prefer_external")
    assert result["known_gaps"]
    for key in ("candidates", "conflicts", "providers_extra"):
        assert result[key] == []
    assert result["coverage"] == {}


def test_builtin_bypasses_all_loaders_even_corrupt_configuration(trusted_lab, monkeypatch):
    lab = trusted_lab
    lab.path.write_text("{private corrupt config")
    (lab.repo / ".sot").mkdir()
    (lab.repo / ".sot/config.toml").write_text("[broken")
    loader = Mock(side_effect=AssertionError("loader must not run"))
    monkeypatch.setattr(config, "load_managed_installation", loader)
    monkeypatch.setattr("sot_graph.config.load_config", loader)
    result = dispatch(lab, "builtin_only", limit=0)
    assert result["status"] == "builtin_only"
    assert result["reason"] is None
    assert result["candidates"] == result["warnings"] == []
    loader.assert_not_called()
    assert not lab.runtime.exists()


@pytest.mark.parametrize("policy", ["prefer_external", "require_external"])
def test_unsupported_usages_never_loads(trusted_lab, monkeypatch, policy):
    loader = Mock(side_effect=AssertionError("loader must not run"))
    monkeypatch.setattr(config, "load_managed_installation", loader)
    result = orch.managed_read_dispatch(str(trusted_lab.repo), "usages", "target",
                                       provider_policy=policy)
    assert_refusal(result, policy, "unsupported_operation")
    loader.assert_not_called()


@pytest.mark.parametrize("policy", ["prefer_external", "require_external"])
@pytest.mark.parametrize("state", ["absent", "disabled", "malformed", "oversized", "incompatible"])
def test_real_trusted_configuration_failures(trusted_lab, policy, state):
    lab = trusted_lab
    if state in {"disabled", "incompatible"}:
        config.register_managed_installation(lab.repo, **lab.kwargs)
    if state == "disabled":
        config.disable_managed_installation(lab.repo, config_path=lab.path)
    elif state == "malformed":
        lab.path.write_text("{SECRET-CONFIG-DIAGNOSTIC")
        lab.path.chmod(0o600)
    elif state == "oversized":
        lab.path.write_text(" " * 262145)
        lab.path.chmod(0o600)
    elif state == "incompatible":
        lab.registry.write_text("[]")
    result = dispatch(lab, policy)
    reason = "managed_not_configured" if state in {"absent", "disabled"} else "trusted_config_invalid"
    assert_refusal(result, policy, reason)
    assert "SECRET" not in json.dumps(result)
    assert not lab.runtime.exists()
    assert not (lab.repo / ".sot").exists()


@pytest.mark.parametrize("restriction", ["allow_external = false\n", '[providers.codebase-memory]\nenabled = false\n'])
def test_explicit_repository_denial_precedes_admin_loader(trusted_lab, monkeypatch, restriction):
    lab = trusted_lab
    (lab.repo / ".sot").mkdir()
    (lab.repo / ".sot/config.toml").write_text(restriction)
    loader = Mock(side_effect=AssertionError("denied repository loaded admin installation"))
    monkeypatch.setattr(config, "load_managed_installation", loader)
    assert_refusal(dispatch(lab), "require_external", "repository_denied")
    loader.assert_not_called()


def test_repository_cannot_grant_native_execution(trusted_lab):
    lab = trusted_lab
    (lab.repo / ".sot").mkdir()
    (lab.repo / ".sot/config.toml").write_text(
        'allow_external = true\n[providers.codebase-memory]\n'
        'enabled = true\nintegration = "cli"\ncommand = ["/evil/native"]\n'
    )
    assert_refusal(dispatch(lab), "require_external", "managed_not_configured")


@pytest.mark.parametrize("state", ["unprepared", "quarantined"])
def test_real_adapter_retains_runtime_readiness_guard(trusted_lab, monkeypatch, state):
    lab = trusted_lab
    config.register_managed_installation(lab.repo, **lab.kwargs)
    if state == "quarantined":
        monkeypatch.setattr(ManagedRuntimeProfile, "status", lambda self: {
            "state": "QUARANTINED", "reason": "SECRET-RUNTIME-DIAGNOSTIC"})
    guarded = []
    original_guard = ManagedNativeRuntime._guard_ready
    def guard(self, **kwargs):
        guarded.append(kwargs)
        return original_guard(self, **kwargs)
    monkeypatch.setattr(ManagedNativeRuntime, "_guard_ready", guard)
    before = {p: p.read_bytes() for p in lab.repo.parent.rglob("*") if p.is_file()}
    result = dispatch(lab)
    assert_refusal(result, "require_external", "managed_query_failed")
    assert guarded and all(call["require_binding"] for call in guarded)
    assert "SECRET" not in json.dumps(result)
    assert {p: p.read_bytes() for p in lab.repo.parent.rglob("*") if p.is_file()} == before
    assert not lab.runtime.exists()


@pytest.mark.parametrize("repo_override", [False, True])
def test_registered_provider_and_exact_normalization_are_reused(trusted_lab, monkeypatch, repo_override):
    lab = trusted_lab
    installation = config.register_managed_installation(lab.repo, **lab.kwargs)
    if repo_override:
        (lab.repo / ".sot").mkdir()
        (lab.repo / ".sot/config.toml").write_text(
            'allow_external = true\n[providers.codebase-memory]\n'
            'integration = "cli"\ncommand = ["/evil/native"]\n'
            'registry_path = "/evil/registry.json"\n')
    loader = Mock(return_value=installation)
    monkeypatch.setattr(config, "load_managed_installation", loader)
    outcome = SimpleNamespace(ok=True, metadata={"version_compatibility": "incompatible"},
        payload={"symbols": [{"name": "target", "path": "module.py", "is_definition": True}]})
    search = Mock(return_value=outcome)
    monkeypatch.setattr(installation.provider, "search_symbols", search)
    normalizer = Mock(wraps=orch.cbm_candidates_from_outcome)
    monkeypatch.setattr(orch, "cbm_candidates_from_outcome", normalizer)
    result = dispatch(lab)
    assert result["status"] == "ok"
    search.assert_called_once()
    assert search.call_args.args[0].repo_root == str(lab.repo)
    assert search.call_args.args[0].query == "target"
    assert search.call_args.args[0].limit == 20
    assert search.call_args.args[0].timeout_seconds == 30
    normalizer.assert_called_once_with(outcome, "search_symbols", "codebase-memory", repo_root=str(lab.repo))
    expected, _, _ = normalizer._mock_wraps(outcome, "search_symbols", "codebase-memory", repo_root=str(lab.repo))
    assert result["candidates"] == json.loads(json.dumps(expected))
    assert result["candidates"]
    assert all(c["verdict"] != "SUPPORTED" for c in result["candidates"])
    assert result["coverage"]["codebase-memory"]["scope_completeness"] == "bounded"
    assert not lab.runtime.exists()


@pytest.mark.parametrize("limit", [0, -1, True, "20"])
def test_invalid_limit_errors_without_loader(trusted_lab, monkeypatch, limit):
    loader = Mock()
    monkeypatch.setattr(config, "load_managed_installation", loader)
    result = dispatch(trusted_lab, "prefer_external", limit=limit)
    assert result["status"] == "error"
    assert result["reason"] == "invalid_request"
    loader.assert_not_called()


def test_scope_postfilter_and_limit_clamp(trusted_lab, monkeypatch):
    lab = trusted_lab
    installation = config.register_managed_installation(lab.repo, **lab.kwargs)
    monkeypatch.setattr(config, "load_managed_installation", Mock(return_value=installation))
    outcome = SimpleNamespace(ok=True, metadata={}, payload={"symbols": [
        {"name": "target", "path": "src/module.py"},
        {"name": "target", "path": "src-other/module.py"}]})
    search = Mock(return_value=outcome)
    monkeypatch.setattr(installation.provider, "search_symbols", search)
    result = dispatch(lab, scope="src", limit=100)
    assert result["status"] == "ok"
    assert [c["subject"]["path"] for c in result["candidates"]] == ["src/module.py"]
    assert result["coverage"]["codebase-memory"]["limit"] == 20
    search.assert_called_once()
    assert "20-row native page" in " ".join(result["known_gaps"])


@pytest.mark.parametrize("value", ["false", "0"])
def test_environment_deny_precedes_admin_loader(trusted_lab, monkeypatch, value):
    monkeypatch.setenv("SOT_PROVIDERS_ALLOW_EXTERNAL", value)
    loader = Mock()
    monkeypatch.setattr(config, "load_managed_installation", loader)
    assert_refusal(dispatch(trusted_lab), "require_external", "repository_denied")
    loader.assert_not_called()


@pytest.mark.parametrize("payload", ["[broken", "allow_external = 'yes'", "providers = []"])
def test_malformed_repository_config_never_loads_admin(trusted_lab, monkeypatch, payload):
    (trusted_lab.repo / ".sot").mkdir()
    (trusted_lab.repo / ".sot/config.toml").write_text(payload)
    loader = Mock()
    monkeypatch.setattr(config, "load_managed_installation", loader)
    assert_refusal(dispatch(trusted_lab), "require_external", "repository_config_invalid")
    loader.assert_not_called()


@pytest.mark.parametrize("symlink", [False, True])
def test_escaping_scope_is_invalid_without_loader(trusted_lab, monkeypatch, symlink):
    scope = "../outside"
    if symlink:
        (trusted_lab.repo / "escape").symlink_to(trusted_lab.repo.parent, target_is_directory=True)
        scope = "escape"
    loader = Mock()
    monkeypatch.setattr(config, "load_managed_installation", loader)
    result = dispatch(trusted_lab, scope=scope)
    assert result["status"] == "error"
    assert result["reason"] == "invalid_scope"
    loader.assert_not_called()


@pytest.mark.parametrize("query", [None, "", "   ", "target\u0000private", "x" * 1001])
def test_invalid_query_does_not_load_admin(trusted_lab, monkeypatch, query):
    loader = Mock()
    monkeypatch.setattr(config, "load_managed_installation", loader)
    result = orch.managed_read_dispatch(str(trusted_lab.repo), "search", query,
                                       provider_policy="require_external")
    assert result["status"] == "error"
    assert result["reason"] == "invalid_request"
    loader.assert_not_called()


@pytest.mark.parametrize("kind", ["oversized", "symlink"])
def test_unsafe_repository_config_is_not_read_as_grant(trusted_lab, monkeypatch, kind):
    lab = trusted_lab
    (lab.repo / ".sot").mkdir()
    path = lab.repo / ".sot/config.toml"
    if kind == "oversized":
        path.write_text("allow_external = true\n#" + "x" * (1024 * 1024))
    else:
        target = lab.repo.parent / "attacker.toml"
        target.write_text("allow_external = true\n")
        path.symlink_to(target)
    loader = Mock()
    monkeypatch.setattr(config, "load_managed_installation", loader)
    assert_refusal(dispatch(lab), "require_external", "repository_config_invalid")
    loader.assert_not_called()


def test_requested_limit_truncates_normalized_evidence(trusted_lab, monkeypatch):
    lab = trusted_lab
    installation = config.register_managed_installation(lab.repo, **lab.kwargs)
    monkeypatch.setattr(config, "load_managed_installation", Mock(return_value=installation))
    outcome = SimpleNamespace(ok=True, metadata={}, payload={"symbols": [
        {"name": "first", "path": "first.py"}, {"name": "second", "path": "second.py"}]})
    search = Mock(return_value=outcome)
    monkeypatch.setattr(installation.provider, "search_symbols", search)
    result = dispatch(lab, limit=1)
    assert result["status"] == "ok"
    assert len(result["candidates"]) == 1
    assert result["truncated"] is True
    assert result["coverage"]["codebase-memory"]["limit"] == 1
    search.assert_called_once()


@pytest.mark.parametrize("scope", ["", "src"])
def test_native_candidates_cannot_escape_root(trusted_lab, monkeypatch, scope):
    lab = trusted_lab
    installation = config.register_managed_installation(lab.repo, **lab.kwargs)
    monkeypatch.setattr(config, "load_managed_installation", Mock(return_value=installation))
    (lab.repo / "escape").symlink_to(lab.repo.parent, target_is_directory=True)
    outcome = SimpleNamespace(ok=True, metadata={}, payload={"symbols": [
        {"name": "target", "path": "src/good.py"},
        {"name": "target", "path": "../outside.py"},
        {"name": "target", "path": str(lab.repo.parent / "outside.py")},
        {"name": "target", "path": "escape/outside.py"}]})
    monkeypatch.setattr(installation.provider, "search_symbols", Mock(return_value=outcome))
    result = dispatch(lab, scope=scope)
    assert result["status"] == "ok"
    assert [c["subject"]["path"] for c in result["candidates"]] == ["src/good.py"]


@pytest.mark.parametrize("failure", ["exception", "outcome", "payload"])
def test_native_failure_never_leaks_diagnostic(trusted_lab, monkeypatch, failure):
    installation = config.register_managed_installation(trusted_lab.repo, **trusted_lab.kwargs)
    monkeypatch.setattr(config, "load_managed_installation", Mock(return_value=installation))
    query = Mock(side_effect=RuntimeError("SECRET-NATIVE-ARGV")) if failure == "exception" else Mock(
        return_value=SimpleNamespace(ok=failure == "payload", payload="SECRET-NATIVE-ARGV",
                                     metadata={}, error="SECRET-NATIVE-ARGV"))
    monkeypatch.setattr(installation.provider, "search_symbols", query)
    result = dispatch(trusted_lab)
    assert_refusal(result, "require_external", "invalid_provider_payload" if failure == "payload" else "managed_query_failed")
    assert "SECRET" not in json.dumps(result)
