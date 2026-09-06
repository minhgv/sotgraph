"""Independent CLI/MCP contracts; managed execution is never started here."""
import json
import subprocess
import sqlite3
from unittest.mock import Mock

import pytest

from sot_graph import cli
from sot_graph.assurance import orchestrator
from sot_graph.db import Database
from sot_graph.mcp_service import McpService, McpServiceError
from sot_graph.reconciler import Reconciler


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text(
        "def target():\n    return 1\n\ndef caller():\n    return target()\n"
    )
    db = Database(str(tmp_path / ".sot" / "sot.db"))
    Reconciler(db, str(tmp_path)).reconcile()
    db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.conn.execute("PRAGMA journal_mode=DELETE")
    db.close()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    original_popen = subprocess.Popen

    def git_only(args, *positional, **kwargs):
        assert args[0] == "git", f"unexpected native spawn: {args[0]}"
        return original_popen(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", git_only)
    return tmp_path


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def service(root):
    return McpService(str(root / ".sot" / "sot.db"), str(root))


def outcome(kind, policy, status="fallback", reason: str | None = "provider_not_configured"):
    return {"policy": policy, "operation": kind, "status": status,
            "reason": reason, "warnings": ["bounded managed evidence"],
            "fail_message": "external unavailable" if status == "error" else None,
            "candidates": [], "conflicts": [], "providers_extra": [],
            "coverage": {}, "known_gaps": [], "truncated": False}


def dispatch(monkeypatch, response):
    mock = Mock(return_value=response)
    monkeypatch.setattr(orchestrator, "managed_read_dispatch", mock)
    return mock


def run_cli(root, kind, capsys, *options):
    rc = cli.main(["--root", str(root), kind, "target", "--json", *options])
    # Legacy builtin CLI opens a writer and switches to WAL. Restore the
    # fixture journal mode before byte comparisons of later read-only calls.
    if "--provider-policy" not in options or "builtin_only" in options:
        with sqlite3.connect(root / ".sot" / "sot.db") as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("PRAGMA journal_mode=DELETE")
    return rc, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("kind", ["search", "usages"])
def test_builtin_never_dispatches_or_loads_managed_config(repo, monkeypatch, capsys, kind):
    forbidden = Mock(side_effect=AssertionError("managed path entered"))
    monkeypatch.setattr(orchestrator, "managed_read_dispatch", forbidden)
    monkeypatch.setattr("sot_graph.config.load_config", forbidden)
    assert run_cli(repo, kind, capsys, "--provider-policy", "builtin_only")[0] == 0
    before = snapshot(repo)
    result = getattr(service(repo), kind)("target")
    assert result["policy"]["provider_policy"] == "builtin_only"
    assert result["policy"]["builtin_only"] is True
    assert "managed" not in result
    forbidden.assert_not_called()
    assert snapshot(repo) == before


@pytest.mark.parametrize("kind,reason", [
    ("search", "provider_not_configured"),
    ("search", "provider_unavailable"),
    ("usages", "unsupported_operation"),
])
@pytest.mark.parametrize("policy", ["prefer_external", "require_external"])
def test_fallback_and_fail_closed_parity(repo, monkeypatch, capsys, kind, reason, policy):
    required = policy == "require_external"
    managed = outcome(kind, policy, "error" if required else "fallback", reason)
    mock = dispatch(monkeypatch, managed)
    before = snapshot(repo)
    rc, cli_result = run_cli(repo, kind, capsys, "--provider-policy", policy)
    assert rc == (2 if required else 0)
    assert cli_result["managed"] == managed
    assert cli_result["policy"]["reason"] == reason
    # Historical field describes requested policy, not the execution outcome.
    assert cli_result["policy"]["builtin_only"] is False
    assert cli_result["managed"]["status"] == ("error" if required else "fallback")
    svc = service(repo)
    if required:
        assert "error" in cli_result
        assert "data" not in cli_result and "results" not in cli_result
        monkeypatch.setattr(svc, "_run", Mock(side_effect=AssertionError("builtin read")))
        with pytest.raises(McpServiceError) as exc:
            getattr(svc, kind)("target", provider_policy=policy)
        assert exc.value.code == "policy_unsatisfiable"
    else:
        result = getattr(svc, kind)("target", provider_policy=policy)
        assert result["managed"] == managed
        assert result["policy"] == cli_result["policy"]
        assert set(result["policy"]) == {"provider_policy", "builtin_only", "note", "reason"}
    assert mock.call_count == 2
    assert snapshot(repo) == before


def test_search_evidence_does_not_promote_builtin_trust(repo, monkeypatch, capsys):
    svc = service(repo)
    baseline = svc.search("target")
    _, cli_baseline = run_cli(repo, "search", capsys)
    managed = outcome("search", "prefer_external", "ok", None)
    managed["candidates"] = [{"symbol": "external_only", "provider": "fake", "path": "app.py"}]
    mock = dispatch(monkeypatch, managed)
    before = snapshot(repo)
    result = svc.search("target", provider_policy="prefer_external")
    rc, cli_result = run_cli(repo, "search", capsys, "--provider-policy", "prefer_external")
    assert rc == 0
    assert result["results"] == baseline["results"]
    assert cli_result["data"]["results"] == cli_baseline["data"]["results"]
    assert result["managed"] == cli_result["managed"] == managed
    assert result["policy"] == cli_result["policy"]
    assert result["policy"]["builtin_only"] is False
    assert mock.call_count == 2
    assert snapshot(repo) == before


@pytest.mark.parametrize("kind", ["search", "usages"])
@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"budget": 0}, {"limit": "bad"},
                                    {"scope": "../escape"}, {"scope": "x" * 4097}])
def test_mcp_invalid_bounds_precede_dispatch(repo, monkeypatch, kind, kwargs):
    mock = dispatch(monkeypatch, outcome(kind, "prefer_external"))
    before = snapshot(repo)
    with pytest.raises(McpServiceError) as exc:
        getattr(service(repo), kind)("target", provider_policy="prefer_external", **kwargs)
    assert exc.value.code == "invalid_argument"
    mock.assert_not_called()
    assert snapshot(repo) == before


@pytest.mark.parametrize("kind", ["search", "usages"])
def test_mcp_clamps_limit_and_budget_before_dispatch(repo, monkeypatch, kind):
    mock = dispatch(monkeypatch, outcome(kind, "prefer_external"))
    getattr(service(repo), kind)("target", limit=10000, budget=3, scope="app.py",
                                provider_policy="prefer_external")
    mock.assert_called_once_with(str(repo), kind, "target", provider_policy="prefer_external",
                                 limit=3, scope="app.py")


@pytest.mark.parametrize("kind", ["search", "usages"])
@pytest.mark.parametrize("provider", ["builtin", "codebase-memory:prefer"])
def test_cli_explicit_legacy_provider_conflicts(repo, monkeypatch, capsys, kind, provider):
    mock = dispatch(monkeypatch, outcome(kind, "prefer_external"))
    before = snapshot(repo)
    if kind == "search":
        # Search has no legacy --provider option; it must not abbreviate
        # --provider-policy or start the shared dispatcher.
        with pytest.raises(SystemExit) as exc:
            run_cli(repo, kind, capsys, "--provider-policy", "prefer_external",
                    "--provider", provider)
        assert exc.value.code == 2
    else:
        rc, result = run_cli(repo, kind, capsys, "--provider-policy", "prefer_external",
                             "--provider", provider)
        assert rc == 2
        assert result["managed"]["reason"] == "conflicting_provider_options"
        assert "error" in result
    mock.assert_not_called()
    assert snapshot(repo) == before


@pytest.mark.parametrize("options", [("--limit", "0"), ("--limit", "-1"),
                                      ("--scope", "../escape")])
def test_cli_invalid_search_bounds_precede_trusted_loader(repo, monkeypatch, capsys, options):
    mock = Mock(side_effect=AssertionError("trusted loader before validation"))
    monkeypatch.setattr("sot_graph.providers.trusted_config.load_managed_installation", mock)
    before = snapshot(repo)
    try:
        rc, _ = run_cli(repo, "search", capsys, "--provider-policy", "prefer_external", *options)
    except SystemExit as exc:
        rc = exc.code
    assert rc == 2
    mock.assert_not_called()
    assert snapshot(repo) == before


@pytest.mark.parametrize("kind", ["search", "usages"])
@pytest.mark.parametrize("missing", [False, True])
def test_cli_external_never_reconciles_or_creates_database(repo, monkeypatch, capsys, kind, missing):
    root = repo / "empty" if missing else repo
    root.mkdir(exist_ok=True)
    managed = outcome(kind, "prefer_external")
    mock = dispatch(monkeypatch, managed)
    monkeypatch.setattr(Reconciler, "reconcile", Mock(side_effect=AssertionError("reconcile")))
    before = snapshot(root)
    rc, result = run_cli(root, kind, capsys, "--provider-policy", "prefer_external")
    assert rc == (1 if missing else 0)
    assert result["managed"] == managed
    if missing:
        assert "error" in result
    mock.assert_called_once()
    assert snapshot(root) == before


def test_builtin_error_serialization_remains_code_message_only(repo):
    assert McpServiceError("example", "original message").as_dict() == {
        "code": "example", "message": "original message"}
    with pytest.raises(McpServiceError) as exc:
        service(repo).usages("missing_symbol")
    assert exc.value.as_dict() == {
        "code": "not_found", "message": "symbol was not found"}


def test_external_missing_target_retains_policy_and_managed(repo, monkeypatch):
    managed = outcome("usages", "prefer_external", reason="unsupported_operation")
    dispatch(monkeypatch, managed)
    before = snapshot(repo)
    with pytest.raises(McpServiceError) as exc:
        service(repo).usages("missing_symbol", provider_policy="prefer_external")
    error = exc.value.as_dict()
    assert error["code"] == "not_found"
    assert error["message"] == "symbol was not found"
    assert error["details"]["managed"] == managed
    assert error["details"]["policy"] == cli._managed_policy_metadata(managed)
    assert error["details"]["policy"]["builtin_only"] is False
    assert snapshot(repo) == before


@pytest.mark.parametrize("required", [False, True])
def test_external_error_diagnostics_are_safe_and_metadata_retained(repo, monkeypatch, required):
    policy = "require_external" if required else "prefer_external"
    managed = outcome("usages", policy, "error" if required else "fallback")
    dispatch(monkeypatch, managed)
    svc = service(repo)
    secret = "private backend diagnostic /secret/config credential=hidden"
    runner = Mock(side_effect=McpServiceError("internal_backend_error", secret))
    monkeypatch.setattr(svc, "_run", runner)
    before = snapshot(repo)
    with pytest.raises(McpServiceError) as exc:
        svc.usages("target", provider_policy=policy)
    error = exc.value.as_dict()
    assert error["code"] == ("policy_unsatisfiable" if required else "query_failed")
    if required:
        runner.assert_not_called()
    else:
        runner.assert_called_once()
        assert error["message"] == "graph query failed"
    assert secret not in json.dumps(error)
    assert "internal_backend_error" not in json.dumps(error)
    assert error["details"]["managed"] == managed
    assert error["details"]["policy"] == cli._managed_policy_metadata(managed)
    assert error["details"]["policy"]["builtin_only"] is False
    assert snapshot(repo) == before
