"""Independent counterexamples from the October 2026 functional audit."""
from pathlib import Path
import json

import pytest

from sot_graph.db import Database
from sot_graph.mcp_service import McpService
from sot_graph.pack import build_bundle
from sot_graph.reconciler import Reconciler
from sot_graph.cli import main
from sot_graph.mcp_service import McpServiceError


@pytest.mark.parametrize("absolute", [False, True])
def test_module_gate_attributes_ruff_diagnostics(monkeypatch, absolute):
    import subprocess
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    from scripts import module_eval

    relative = "src/sot_graph/cli.py"
    filename = str(module_eval.REPO_ROOT / relative) if absolute else relative
    diagnostic = {"filename": filename, "code": "F401",
                  "message": "planted unused import", "location": {"row": 1}}
    monkeypatch.setattr(module_eval, "_run", lambda *a, **k:
                        subprocess.CompletedProcess([], 1, json.dumps([diagnostic]), ""))
    results = module_eval.run_static_gates(["surfaces", "core-storage"], {"pyright"})
    assert results["surfaces"].ruff["pass"] is False
    assert results["surfaces"].ruff["count"] == 1
    assert results["core-storage"].ruff["pass"] is True


@pytest.fixture
def indexed_project(tmp_path):
    def create(files):
        for relative, content in files.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        db = Database(str(tmp_path / ".sot" / "sot.db"))
        Reconciler(db, str(tmp_path)).reconcile(workers=1)
        return db

    databases = []

    def tracked_create(files):
        db = create(files)
        databases.append(db)
        return db

    yield tracked_create
    for db in databases:
        db.close()


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_node_cap_never_claims_complete(indexed_project, tmp_path, limit):
    db = indexed_project({
        "leaf.py": "def leaf():\n    return 1\n",
        **{f"caller{i}.py": f"from leaf import leaf\n\ndef call{i}():\n    return leaf()\n"
           for i in range(5)},
    })
    bundle = build_bundle(db, str(tmp_path), "leaf", max_nodes=limit)
    assert bundle["accounting"]["inbound_callers"]["omitted"] > 0
    assert bundle["limits"]["truncated"] is True
    assert bundle["completeness"] == "PARTIAL"
    assert bundle["absence_interpretation"]
    service = McpService(db.db_path, str(tmp_path))
    try:
        response = service.pack_context_bundle("leaf", max_nodes=limit)
        assert response["limits"]["truncated"] is True
        assert response["completeness"] == "PARTIAL"
    finally:
        service.close()


def test_typescript_closures_keep_their_enclosing_method(indexed_project):
    db = indexed_project({"stage.ts": """
export function normalizeA(v: string) { return 'A' + v; }
export function normalizeB(v: string) { return 'B' + v; }
export class Stage {
 first(s: string) {
   const inner = (v: string) => normalizeA(v);
   return inner(s);
 }
 second(s: string) {
   const inner = (v: string) => normalizeB(v);
   return inner(s);
 }
}
"""})
    calls = {tuple(row) for row in db.conn.execute(
        "SELECT s.symbol,t.symbol FROM graph_edges e "
        "JOIN graph_nodes s ON e.src=s.id JOIN graph_nodes t ON e.dst=t.id "
        "WHERE e.relation='calls'")}
    assert ("Stage.first", "Stage.first.inner") in calls
    assert ("Stage.second", "Stage.second.inner") in calls
    assert ("Stage.first.inner", "normalizeA") in calls
    assert ("Stage.second.inner", "normalizeB") in calls
    assert ("Stage.first.inner", "normalizeB") not in calls
    assert ("Stage.second.inner", "normalizeA") not in calls


def test_typed_python_receiver_stays_in_its_defining_module(indexed_project, tmp_path):
    db = indexed_project({
        "a_local.py": "class Notifier:\n    def send(self, msg):\n        return msg\n\ndef notify(base: Notifier):\n    return base.send('hi')\n",
        "z_unrelated.py": "class Notifier:\n    def send(self, msg):\n        return 'unrelated'\n",
    })
    targets = [Path(row[0]).resolve() for row in db.conn.execute(
        "SELECT t.path FROM graph_edges e JOIN graph_nodes s ON e.src=s.id "
        "JOIN graph_nodes t ON e.dst=t.id WHERE e.relation='calls' AND s.symbol='notify'")]
    assert targets == [(tmp_path / "a_local.py").resolve()]


def test_pack_root_alias_produces_project_relative_paths(indexed_project, tmp_path):
    db = indexed_project({"leaf.py": "def leaf():\n    return 1\n"})
    alias = tmp_path.parent / (tmp_path.name + "-alias")
    try:
        alias.symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    bundle = build_bundle(db, str(alias), "leaf")
    assert bundle["target"]["relative_path"] == "leaf.py"


@pytest.mark.parametrize("arguments", [
    ["search", "x", "--limit", "-1"],
    ["search", "x", "--threshold", "nan"],
    ["search", "x", "--threshold", "inf"],
    ["search", "x", "--threshold", "-1"],
    ["search", "x", "--threshold", "2"],
    ["explore", "x", "--depth", "-1"],
    ["pack", "x", "--max-hops", "-1"],
    ["pack", "x", "--max-nodes", "0"],
    ["pack", "x", "--max-bytes", "0"],
    ["map", "--tokens", "0"],
    ["log", "--limit", "-1"],
])
def test_cli_rejects_invalid_numbers_before_opening_database(tmp_path, capsys, arguments):
    assert main(["--root", str(tmp_path), *arguments, "--json"]) == 2
    reply = json.loads(capsys.readouterr().out)
    assert reply["ok"] is False
    assert reply["code"] == "invalid_argument"
    assert not (tmp_path / ".sot" / "sot.db").exists()


@pytest.mark.parametrize("config", ['extractor = [\n', 'allow_external = "banana"\n'])
def test_invalid_config_is_a_json_error(tmp_path, capsys, config):
    (tmp_path / ".sot").mkdir()
    (tmp_path / ".sot/config.toml").write_text(config)
    assert main(["--root", str(tmp_path), "reconcile", "--json"]) == 1
    reply = json.loads(capsys.readouterr().out)
    assert reply["ok"] is False
    assert reply["code"] == "invalid_config"


def test_corrupt_database_is_reported_without_modifying_it(tmp_path, capsys):
    path = tmp_path / ".sot/sot.db"
    path.parent.mkdir()
    content = b"not a sqlite database"
    path.write_bytes(content)
    assert main(["--root", str(tmp_path), "doctor", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "database_error"
    assert path.read_bytes() == content


def test_missing_pre_receipt_is_a_json_error(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "diff-impact", "--pre-receipt",
                 str(tmp_path / "missing.json"), "--json", "--no-auto-reconcile"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "io_error"


def test_pack_failure_is_a_json_error(indexed_project, tmp_path, capsys):
    indexed_project({"leaf.py": "def leaf():\n    return 1\n"})
    assert main(["--root", str(tmp_path), "pack", "leaf", "--tokens", "1",
                 "--json", "--reconcile", "off"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "BUDGET_TOO_SMALL"


@pytest.mark.parametrize("value", [True, False, 1.5, float("nan"), float("inf"), -1, 0])
def test_mcp_numeric_domains_are_strict(indexed_project, tmp_path, value):
    db = indexed_project({"leaf.py": "def leaf():\n    return 1\n"})
    service = McpService(db.db_path, str(tmp_path))
    try:
        for operation in (
            lambda: service.search("leaf", limit=value, auto_reconcile="off"),
            lambda: service.explore("leaf", depth=value, auto_reconcile="off"),
            lambda: service.pack_context_bundle("leaf", max_nodes=value, auto_reconcile="off"),
            lambda: service.pack_context_bundle("leaf", max_hops=value, auto_reconcile="off"),
        ):
            with pytest.raises(McpServiceError) as exc:
                operation()
            assert exc.value.code == "invalid_argument"
    finally:
        service.close()


@pytest.mark.parametrize("git_repo", [False, True])
def test_uncollectable_diff_never_claims_low_risk(indexed_project, tmp_path, capsys, git_repo):
    import subprocess
    if git_repo:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    indexed_project({"leaf.py": "def leaf():\n    return 1\n"})
    assert main(["--root", str(tmp_path), "diff-impact", "does-not-exist",
                 "--json", "--no-auto-reconcile"]) == 1
    reply = json.loads(capsys.readouterr().out)["data"]
    receipt = reply
    assert receipt["assurance"]["status"] == "UNVERIFIABLE"
    assert any(w.startswith("collection_error:git_diff:") for w in receipt["warnings"])
    assert reply["summary"]["risk_level"] == "UNKNOWN"
    assert receipt["safe_commit"]["verdict"] == "block"


@pytest.mark.parametrize("files,expected", [
    ({"crypto.rs": "pub fn hash_data(s: &str) -> String { s.to_owned() }\n",
      "alias.rs": "use crate::crypto::hash_data as hd;\npub fn digest(s: &str) -> String { hd(s) }\n"},
     ("digest", "hash_data")),
    ({"shape.rs": "pub struct Circle;\nimpl Circle {\n fn area(&self) -> f64 { 1.0 }\n"
      " pub fn describe(&self) -> String { format!(\"area={}\", self.area()) }\n}\n"},
     ("Circle.describe", "Circle.area")),
    ({"core/Validator.java": "package core;\npublic class Validator {\n public static boolean isValid(String x) { return x != null; }\n}\n",
      "UseStatic.java": "import static core.Validator.isValid;\npublic class UseStatic {\n public boolean check(String x) { return isValid(x); }\n}\n"},
     ("UseStatic.check", "Validator.isValid")),
])
def test_polyglot_static_bindings(indexed_project, files, expected):
    db = indexed_project(files)
    calls = {tuple(row) for row in db.conn.execute(
        "SELECT s.symbol,t.symbol FROM graph_edges e "
        "JOIN graph_nodes s ON e.src=s.id JOIN graph_nodes t ON e.dst=t.id "
        "WHERE e.relation='calls'")}
    assert expected in calls


def test_polymorphic_parameter_does_not_claim_a_runtime_target(indexed_project):
    db = indexed_project({"dispatch.py": """
class Notifier:
 def send(self, msg): return msg
class LoudNotifier(Notifier):
 def send(self, msg): return msg.upper()
def notify(base: Notifier, msg):
 return base.send(msg)
def concrete(msg):
 base = Notifier()
 return base.send(msg)
"""})
    calls = {tuple(row) for row in db.conn.execute(
        "SELECT s.symbol,t.symbol FROM graph_edges e "
        "JOIN graph_nodes s ON e.src=s.id JOIN graph_nodes t ON e.dst=t.id "
        "WHERE e.relation='calls'")}
    assert not any(src == "notify" for src, _ in calls)
    assert ("concrete", "Notifier.send") in calls
    assert db.conn.execute("SELECT COUNT(*) FROM pending_edges WHERE call_kind='DECLARED_RECEIVER'").fetchone()[0] == 1


def test_receiver_types_do_not_leak_across_functions_or_blocks(indexed_project):
    db = indexed_project({"scopes.ts": """
class A { read() { return 'a'; } }
class B { read() { return 'b'; } }
function first() { const v = new A(); return v.read(); }
function unknown(v: any) { return v.read(); }
function blocks() {
 const v = new A();
 { const v = new B(); v.read(); }
 return v.read();
}
"""})
    calls = {(s, t, line) for s, t, line in db.conn.execute(
        "SELECT s.symbol,t.symbol,e.line FROM graph_edges e "
        "JOIN graph_nodes s ON e.src=s.id JOIN graph_nodes t ON e.dst=t.id "
        "WHERE e.relation='calls'")}
    assert not any(s == "unknown" for s, _, _ in calls)
    assert ("blocks", "B.read", 8) in calls
    assert ("blocks", "A.read", 9) in calls
    assert ("blocks", "B.read", 9) not in calls


@pytest.mark.parametrize("arguments,code", [
    (["providers", "cross-check", "--json"], "database_error"),
    (["providers", "cross-check", "--receipt"], "database_error"),
    (["diff-impact", "--test-report", "missing-report.json", "--json", "--no-auto-reconcile"], "invalid_test_report"),
])
def test_secondary_json_error_boundaries(tmp_path, capsys, arguments, code):
    assert main(["--root", str(tmp_path), *arguments]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["code"] == code
    assert "Traceback" not in output.err


def test_legacy_schema_reset_diagnostics_do_not_break_json(tmp_path, capsys, monkeypatch):
    import sqlite3
    monkeypatch.setenv("SOT_EXTRACTOR", "builtin")
    monkeypatch.setenv("SOT_ENGINE_BOOTSTRAP", "off")
    path = tmp_path / ".sot/sot.db"
    path.parent.mkdir()
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version = 99")
        db.execute("CREATE TABLE graph_nodes (id TEXT, kind TEXT)")
    assert main(["--root", str(tmp_path), "doctor", "--json"]) == 0
    output = capsys.readouterr()
    assert isinstance(json.loads(output.out), dict)
    assert "LEGACY SCHEMA RESET" in output.err


def test_receipt_path_argument_does_not_enable_json_errors(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "receipt", "show", "missing.json"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "missing" in output.err
