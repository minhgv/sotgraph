"""Interop against a byte-for-byte artifact from the actual TS indexer."""

import shutil
from pathlib import Path

from sot_graph.db import Database
from sot_graph.importer.scip import ScipImporter, parse_scip_protobuf, parse_scip_symbol
from sot_graph.export.scip import scip_symbol
from sot_graph.reconciler import Reconciler

FIXTURE = Path(__file__).parent / "fixtures/scip/compiler_typescript"


def test_actual_compiler_index_decodes_standard_symbol_fields():
    index = parse_scip_protobuf((FIXTURE / "index.scip").read_bytes())
    assert index["metadata"]["tool_info"] == {
        "name": "scip-typescript", "version": "0.4.0", "arguments": []}
    assert {d["relative_path"] for d in index["documents"]} == {"math.ts", "app.ts"}
    symbols = [s for d in index["documents"] for s in d["symbols"]]
    normalize = next(s for s in symbols if s["symbol"].endswith("/normalize()."))
    # This indexer emits signature markdown in documentation and omits
    # optional kind/display-name/signature-documentation fields.
    assert normalize["kind"] == 0
    assert normalize["documentation"]
    assert normalize["relationships"] == []
    assert "function normalize" in normalize["documentation"][0]


def test_actual_compiler_index_imports_reference_evidence(tmp_path):
    for source in FIXTURE.glob("*.ts"):
        shutil.copyfile(source, tmp_path / source.name)
    db = Database(str(tmp_path / ".sot/sot.db"))
    try:
        Reconciler(db, str(tmp_path)).reconcile(workers=1)
        result = ScipImporter(db, project_root=str(tmp_path)).import_file(str(FIXTURE / "index.scip"))
        assert result["documents_count"] == 2
        assert result["references_count"] > 0
        rows = list(db.conn.execute(
            "SELECT path,relation,line_start FROM provider_evidence "
            "WHERE target_symbol='normalize' AND relation='references'"))
        assert any(path.endswith("app.ts") and line == 2 for path, _, line in rows)
        assert not db.conn.execute("SELECT 1 FROM provider_evidence WHERE relation='calls'").fetchone()
    finally:
        db.close()


def test_standard_optional_symbol_fields_from_independent_sdk():
    index = parse_scip_protobuf((FIXTURE.parent / "standard_fields.scip").read_bytes())
    symbol = index["documents"][0]["symbols"][0]
    assert symbol["documentation"] == ["SDK-generated documentation"]
    assert symbol["kind"] == 17
    assert symbol["display_name"] == "normalize"
    assert symbol["signature_documentation"]["text"] == "function normalize(s: string): string"
    assert symbol["relationships"][0]["is_reference"] is True


def test_symbol_package_spaces_and_descriptor_backticks_roundtrip():
    symbol = scip_symbol("python", "file:///project", "symbols with space.py",
                         "my.module", "weird`name", "function")
    assert "symbols  with  space.py" in symbol
    assert "`weird``name`()." in symbol
    parsed = parse_scip_symbol(symbol)
    assert parsed["version"] == "symbols with space.py"
    assert parsed["name"] == "weird`name"
