"""Behavioral coverage for the focused MCP tool profiles (core/full/ops).

Contract under test:
- ONE immutable allowlist per profile gates BOTH discovery (list_tools)
  and invocation (call_tool): hidden tools are not reachable by direct RPC.
- Operational writes (sot_reconcile, sot_providers_sync) require the
  explicit `ops` startup; core and full never expose them.
- File writers are confined to the project root (path escape rejected).
- MCP sot_pack max_tokens matches the CLI `--tokens` budget semantics
  through the shared core pack API (one renderer, no second truncator).
- Startup resolution: --profile flag > SOT_MCP_PROFILE env > core; unknown
  values are rejected, never silently widened.
"""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from sot_graph.db import Database
from sot_graph.mcp_service import McpService, McpServiceError

CORE_TOOLS = {
    "sot_search", "sot_map", "sot_usages", "sot_pack",
    "sot_scope_receipt", "sot_diff_impact_receipt", "sot_verify_drift",
}
OPERATIONAL_TOOLS = {"sot_reconcile", "sot_providers_sync"}
FULL_TOOLS = CORE_TOOLS | {
    "sot_explore", "sot_implementations", "sot_doctor",
    "sot_architecture_report", "sot_communities", "sot_bundle",
    "sot_notes", "sot_trace", "sot_ui_tree", "sot_backend_flow",
    "sot_solution_inventory", "sot_solution_steps", "sot_solution_bundle",
    "sot_diff_impact", "sot_cross_check", "sot_git_history",
    "sot_commit_verdict",
}
ALL_TOOLS = FULL_TOOLS | OPERATIONAL_TOOLS

REPO_FILES = {
    "util.py": (
        "def base_value(x):\n"
        "    return x * 2\n"
        "\n"
        "\n"
        "def decorated(x):\n"
        "    return base_value(x) + 1\n"
    ),
    "app.py": "from util import decorated\n\n\ndef run():\n    return decorated(3)\n",
}


def _require():
    anyio = pytest.importorskip("anyio")
    pytest.importorskip("mcp")
    return anyio


def make_indexed_repo(tmp_path: Path) -> Path:
    """A tiny indexed project: two modules, one intra-module call edge."""
    root = tmp_path / "repo"
    root.mkdir()
    for name, text in REPO_FILES.items():
        (root / name).write_text(text, encoding="utf-8")
    db = Database(str(root / ".sot" / "sot.db"))
    try:
        from sot_graph.reconciler import Reconciler
        summary = Reconciler(db, str(root)).reconcile()
        assert summary.updated >= 1
    finally:
        db.close()
    return root


def make_service(root: Path) -> McpService:
    return McpService(str(root / ".sot" / "sot.db"), str(root))


@asynccontextmanager
async def mcp_client(service: McpService, profile: str = "core"):
    anyio = _require()
    from sot_graph.mcp_server import create_server

    server = create_server(service, profile)
    send, receive = anyio.create_memory_object_stream(1)
    reply, responses = anyio.create_memory_object_stream(1)
    async with anyio.create_task_group() as tg:
        tg.start_soon(server.run, receive, reply, server._sot_initialization_options)
        try:
            from mcp import ClientSession
            async with ClientSession(responses, send) as client:
                await client.initialize()
                yield client
        finally:
            tg.cancel_scope.cancel()


def error_payload(result) -> dict:
    """Extract the structured error from a failed call_tool result."""
    assert result.isError
    if isinstance(result.structuredContent, dict) and "error" in result.structuredContent:
        return result.structuredContent["error"]
    return json.loads(result.content[0].text)["error"]


# ---------------------------------------------------------------------------
# Discovery / hidden-dispatch parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile,expected", [
    ("core", CORE_TOOLS),
    ("full", FULL_TOOLS),
    ("ops", ALL_TOOLS),
])
def test_profile_discovery_lists_exactly_the_allowlist(tmp_path, profile, expected):
    _require()
    root = make_indexed_repo(tmp_path)
    async def case():
        async with mcp_client(make_service(root), profile) as client:
            listed = {t.name for t in (await client.list_tools()).tools}
        assert listed == expected
    import anyio
    anyio.run(case)


def test_hidden_tool_denied_by_direct_rpc_in_core(tmp_path):
    """A tool outside the profile is neither advertised NOR dispatchable."""
    _require()
    root = make_indexed_repo(tmp_path)
    async def case():
        async with mcp_client(make_service(root), "core") as client:
            listed = {t.name for t in (await client.list_tools()).tools}
            hidden = sorted(ALL_TOOLS - CORE_TOOLS)
            assert not (listed & set(hidden))
            for name in hidden[:6]:
                result = await client.call_tool(name, {})
                err = error_payload(result)
                assert err["code"] == "tool_disabled", (name, err)
                assert err["profile"] == "core"
                assert err["tool"] == name
            # core tools stay fully functional
            ok = await client.call_tool("sot_verify_drift", {})
            assert not ok.isError
    import anyio
    anyio.run(case)


def test_unknown_tool_is_unknown_tool_not_disabled(tmp_path):
    _require()
    root = make_indexed_repo(tmp_path)
    async def case():
        async with mcp_client(make_service(root), "ops") as client:
            err = error_payload(await client.call_tool("sot_nonesuch", {}))
        assert err["code"] == "unknown_tool"
    import anyio
    anyio.run(case)


# ---------------------------------------------------------------------------
# Operational write separation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", ["core", "full"])
def test_reconcile_hidden_without_ops_profile(tmp_path, profile):
    _require()
    root = make_indexed_repo(tmp_path)
    async def case():
        async with mcp_client(make_service(root), profile) as client:
            listed = {t.name for t in (await client.list_tools()).tools}
            assert not (listed & OPERATIONAL_TOOLS)
            for name in sorted(OPERATIONAL_TOOLS):
                err = error_payload(await client.call_tool(name, {}))
                assert err["code"] == "tool_disabled", (profile, err)
    import anyio
    anyio.run(case)


def test_ops_reconcile_actually_synchronizes(tmp_path):
    """sot_reconcile is a REAL write in ops: a drifted file is re-indexed
    through the shared writer funnel and the drift audit comes back clean.
    """
    _require()
    root = make_indexed_repo(tmp_path)
    # Introduce drift: mutate + delete + add.
    (root / "util.py").write_text(
        REPO_FILES["util.py"] + "\n\ndef added_later(x):\n    return x\n",
        encoding="utf-8")
    (root / "app.py").unlink()
    (root / "extra.py").write_text("def extra():\n    return 42\n", encoding="utf-8")
    async def case():
        async with mcp_client(make_service(root), "ops") as client:
            before = (await client.call_tool("sot_verify_drift", {}))
            assert not before.isError
            assert before.structuredContent["drift"], "expected drift before reconcile"
            result = await client.call_tool("sot_reconcile", {})
            assert not result.isError, result.content
            payload = result.structuredContent
            assert payload["status"] == "success", payload
            assert payload["project_root"] == str(root)
            after = await client.call_tool("sot_verify_drift", {})
            assert not after.isError
            assert not after.structuredContent["drift"]
    import anyio
    anyio.run(case)


def test_reconcile_request_cannot_redirect_the_root(tmp_path):
    """No arbitrary repo path from the request: extra arguments violate
    the input schema (additionalProperties: false) and never reach a
    reconcile of another directory."""
    _require()
    root = make_indexed_repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "stray.py").write_text("def stray():\n    return 1\n", encoding="utf-8")
    stray_before = sorted(p.name for p in elsewhere.iterdir())
    async def case():
        async with mcp_client(make_service(root), "ops") as client:
            try:
                result = await client.call_tool(
                    "sot_reconcile", {"root": str(elsewhere)})
            except Exception:
                # Client-side schema validation may reject before dispatch.
                return
            payload = result.structuredContent or {}
            assert "status" not in payload or payload.get("project_root") == str(root)
    import anyio
    anyio.run(case)
    # The stray project was never indexed by the reconcile call.
    assert sorted(p.name for p in elsewhere.iterdir()) == stray_before
    assert not (elsewhere / ".sot" / "sot.db").exists()


def test_service_reconcile_is_project_bounded_and_idempotent(tmp_path):
    root = make_indexed_repo(tmp_path)
    service = make_service(root)
    try:
        first = service.reconcile()
        assert first["status"] == "success"
        assert first["project_root"] == str(root)
        second = service.reconcile()
        assert second["status"] == "success"
    finally:
        service.close()


# ---------------------------------------------------------------------------
# Path confinement of the file writers (full profile)
# ---------------------------------------------------------------------------


def test_bundle_output_escape_is_rejected(tmp_path):
    _require()
    root = make_indexed_repo(tmp_path)
    async def case():
        async with mcp_client(make_service(root), "full") as client:
            for tool, args in (
                ("sot_bundle", {"output_dir": "../escaped_bundle"}),
                ("sot_bundle", {"output_dir": str(tmp_path / "outside_bundle")}),
                ("sot_solution_bundle", {"output_file": str(tmp_path / "outside.md")}),
                ("sot_solution_inventory", {"output_file": "../../outside_inv.md"}),
            ):
                result = await client.call_tool(tool, args)
                err = error_payload(result)
                assert err["code"] == "path_traversal", (tool, args, err)
        assert not (tmp_path / "escaped_bundle").exists()
        assert not (tmp_path / "outside_bundle").exists()
        assert not (tmp_path / "outside.md").exists()
    import anyio
    anyio.run(case)


def test_bundle_write_confined_to_project_root(tmp_path):
    """The honest flip side: inside the root, the write really happens."""
    _require()
    root = make_indexed_repo(tmp_path)
    out_dir = root / "reports"
    async def case():
        async with mcp_client(make_service(root), "full") as client:
            result = await client.call_tool(
                "sot_bundle", {"output_dir": "reports"})
            assert not result.isError, result.content
            payload = result.structuredContent
            assert payload["ok"] is True
            assert payload["output_dir"] == str(out_dir)
    import anyio
    anyio.run(case)
    files = list(out_dir.glob("*.md")) + list(out_dir.glob("*.json"))
    assert len(files) == 5


# ---------------------------------------------------------------------------
# Token budget parity: MCP sot_pack vs CLI pack --tokens
# ---------------------------------------------------------------------------


def test_pack_max_tokens_matches_cli(tmp_path, capsys):
    from sot_graph.cli import main as cli_main
    root = make_indexed_repo(tmp_path)
    service = make_service(root)
    budget = 1200  # above this repo's metadata floor, so both surfaces render
    try:
        mcp_payload = service.pack_context_bundle("decorated", max_tokens=budget)
        assert mcp_payload["ok"] is True, mcp_payload
    finally:
        service.close()
    rc = cli_main(["--root", str(root), "pack", "decorated",
                   "--tokens", str(budget), "--json"])
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)
    data = envelope.get("data") or envelope
    cli_limits = data.get("limits") or envelope["limits"]
    assert cli_limits["max_tokens"] == budget
    assert cli_limits["tokens_estimate"] == mcp_payload["limits"]["tokens_estimate"]
    assert cli_limits["truncated"] == mcp_payload["limits"]["truncated"]


def test_pack_rejects_invalid_budget_values(tmp_path):
    _require()
    root = make_indexed_repo(tmp_path)
    service = make_service(root)
    try:
        for kwargs in ({"max_tokens": 0}, {"max_tokens": -5},
                       {"max_bytes": 0}, {"max_tokens": "big"}):
            with pytest.raises(Exception) as excinfo:
                service.pack_context_bundle("decorated", **kwargs)
            assert "must be a positive integer" in str(excinfo.value), kwargs
    finally:
        service.close()
    async def case():
        async with mcp_client(make_service(root), "core") as client:
            result = await client.call_tool(
                "sot_pack", {"target": "decorated", "max_tokens": 0})
        # Either rejection layer is a clean rejection: the SDK validates
        # the schema minimum client-side (structuredContent None), and a
        # raw RPC that reaches the service gets invalid_argument.
        if result.structuredContent is None:
            assert result.isError
            assert "validation" in result.content[0].text.lower()
        else:
            err = error_payload(result)
            assert err["code"] == "invalid_argument", err
    import anyio
    anyio.run(case)


# ---------------------------------------------------------------------------
# Startup profile resolution: flag > env > core; invalid values rejected
# ---------------------------------------------------------------------------


def test_resolve_profile_validation():
    from sot_graph.mcp_server import resolve_profile
    assert resolve_profile(None) == "core"
    assert resolve_profile("") == "core"
    assert resolve_profile("core") == "core"
    assert resolve_profile("full") == "full"
    assert resolve_profile("OPS") == "ops"
    with pytest.raises(ValueError):
        resolve_profile("everything")
    with pytest.raises(ValueError):
        resolve_profile("core,full")


def test_main_profile_flag_beats_env_and_invalid_is_rejected(monkeypatch, tmp_path):
    import sot_graph.mcp_server as ms

    seen = {}

    async def fake_run_stdio(service, profile="core"):
        seen["profile"] = profile

    monkeypatch.setattr(ms, "run_stdio", fake_run_stdio)
    monkeypatch.chdir(tmp_path)

    monkeypatch.setenv("SOT_MCP_PROFILE", "full")
    assert ms.main(["--profile", "core"]) == 0
    assert seen["profile"] == "core"  # explicit flag wins

    monkeypatch.delenv("SOT_MCP_PROFILE")
    assert ms.main([]) == 0
    assert seen["profile"] == "core"  # default

    monkeypatch.setenv("SOT_MCP_PROFILE", "ops")
    assert ms.main([]) == 0
    assert seen["profile"] == "ops"  # env fallback when no flag

    monkeypatch.setenv("SOT_MCP_PROFILE", "bogus")
    assert ms.main([]) == 2  # invalid env rejected, not silently widened

    monkeypatch.setenv("SOT_MCP_PROFILE", "ops")
    assert ms.main(["--profile", "bogus"]) == 2  # invalid flag rejected


def test_cli_mcp_command_passes_profile():
    from sot_graph.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["mcp", "--profile", "ops"])
    assert args.profile == "ops"
    args_default = parser.parse_args(["mcp"])
    assert args_default.profile is None


# ---------------------------------------------------------------------------
# Doctor: same substantive health logic as the CLI, read-only
# ---------------------------------------------------------------------------


def test_doctor_matches_cli_health_logic(tmp_path):
    root = make_indexed_repo(tmp_path)
    service = make_service(root)
    try:
        mcp_diag = service.doctor()
    finally:
        service.close()
    db = Database(str(root / ".sot" / "sot.db"))
    try:
        from sot_graph.mcp_service import collect_doctor_diagnostics
        cli_diag = collect_doctor_diagnostics(db, str(root))
    finally:
        db.close()
    assert mcp_diag["ok"] == cli_diag["ok"] is True
    assert mcp_diag["quick_check"] == cli_diag["quick_check"] == "ok"
    assert mcp_diag["stats"]["nodes"] == cli_diag["stats"]["nodes"]
    assert mcp_diag["stats"]["paths"] == cli_diag["stats"]["paths"]
    # No engine store is bound in the fixture repo.
    assert mcp_diag["engine_readthrough"] is None


def test_doctor_tool_is_read_only_diagnostic(tmp_path):
    _require()
    root = make_indexed_repo(tmp_path)
    async def case():
        async with mcp_client(make_service(root), "full") as client:
            result = await client.call_tool("sot_doctor", {})
            assert not result.isError, result.content
            payload = result.structuredContent
            assert payload["ok"] is True
            assert payload["quick_check"] == "ok"
        # Read-only proof: doctor did not touch the journal generation.
        service = make_service(root)
        try:
            gen_before = service.graph_generation()["generation"]
            service.doctor()
            gen_after = service.graph_generation()["generation"]
        finally:
            service.close()
        assert gen_before == gen_after
    import anyio
    anyio.run(case)


# ---------------------------------------------------------------------------
# Honest annotations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile,expected", [
    ("core", CORE_TOOLS),
    ("full", FULL_TOOLS),
    ("ops", ALL_TOOLS),
])
def test_annotations_do_not_claim_readonly_for_writers(tmp_path, profile, expected):
    _require()
    root = make_indexed_repo(tmp_path)
    async def case():
        async with mcp_client(make_service(root), profile) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
        read_only = {n for n, t in tools.items()
                     if t.annotations and t.annotations.readOnlyHint}
        # Writers must never claim read-only: operational writes, the JIT
        # freshness carriers, the receipt store writer and the file writers.
        for name in (OPERATIONAL_TOOLS
                     | {"sot_search", "sot_usages", "sot_pack", "sot_map",
                        "sot_diff_impact", "sot_diff_impact_receipt",
                        "sot_scope_receipt",
                        "sot_bundle", "sot_solution_inventory",
                        "sot_solution_bundle"}):
            if name in tools:
                assert name not in read_only, name
        # Audit-pure reads may claim it.
        for name in ("sot_verify_drift", "sot_doctor"):
            if name in tools:
                assert name in read_only, name
    import anyio
    anyio.run(case)


# ---------------------------------------------------------------------------
# PRE receipt persistence: MCP scope -> returned digest -> POST binds
# ---------------------------------------------------------------------------


def test_mcp_scope_receipt_persists_returned_digest_for_post(tmp_path, monkeypatch):
    """Real scope-to-POST chain over the service: the digest returned by
    MCP scope_receipt must be loadable by a later POST — never not_found."""
    root = make_indexed_repo(tmp_path)
    import subprocess

    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "sotgraph-test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "sotgraph-test@example.com")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)

    service = make_service(root)
    try:
        pre = service.scope_receipt("decorated", kind_of_change="local-body")
        digest = pre["digest"]
        assert isinstance(digest, str) and len(digest) == 64
        # The digest is the address: the real store now holds it, so the
        # POST binds it in the resolution ledger instead of answering
        # not_found. No CLI seeding, no fallback acceptance.
        post = service.diff_impact_receipt(target="HEAD", pre_receipt=digest)
        assert digest in json.dumps(post)
    finally:
        service.close()


def test_mcp_scope_receipt_surfaces_storage_failure(tmp_path):
    """A receipt-store write failure is a structured service error — the
    caller never receives a success digest that POST cannot load."""
    root = make_indexed_repo(tmp_path)
    # A regular file where the store directory belongs makes every store
    # initialization fail for real (mkdir exist_ok on a file raises).
    (root / ".sot" / "receipts").write_text("not a directory", encoding="utf-8")
    service = make_service(root)
    try:
        with pytest.raises(McpServiceError) as failed:
            service.scope_receipt("decorated", kind_of_change="local-body")
        assert failed.value.as_dict()["code"] == "receipt_store_write_failed"
    finally:
        service.close()
