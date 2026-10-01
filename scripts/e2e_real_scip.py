#!/usr/bin/env python3
"""Compile a fresh TypeScript SCIP index and verify both directions of interop.

Requires Node/npm and network access. Dependencies and artifacts stay in a
temporary project. The default pytest suite uses the checked-in compiler
artifact; this CI gate additionally regenerates it with scip-typescript 0.4.0
and decodes sotgraph exports with that package's independent protobuf SDK.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sot_graph.db import Database  # noqa: E402
from sot_graph.export.scip import export_scip  # noqa: E402
from sot_graph.importer.scip import ScipImporter, parse_scip_protobuf  # noqa: E402
from sot_graph.reconciler import Reconciler  # noqa: E402


def main() -> None:
    fixture = REPO / "tests/fixtures/scip/compiler_typescript"
    with tempfile.TemporaryDirectory(prefix="sot-scip-") as temp:
        root = Path(temp) / "compiler project space"
        shutil.copytree(fixture, root)
        (root / "index.scip").unlink()
        package = json.loads((root / "package.json").read_text())
        package["devDependencies"] = {"@sourcegraph/scip-typescript": "0.4.0"}
        (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
        subprocess.run(["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"],
                       cwd=root, check=True, timeout=180)
        subprocess.run([str(root / "node_modules/.bin/scip-typescript"), "index",
                        "--infer-tsconfig", "--output", "index.scip"],
                       cwd=root, check=True, timeout=180)
        index = parse_scip_protobuf((root / "index.scip").read_bytes())
        assert index["metadata"]["tool_info"]["name"] == "scip-typescript"
        assert {d["relative_path"] for d in index["documents"]} == {"math.ts", "app.ts"}

        # Also exercise URI encoding, descriptor escaping and documentation.
        (root / "symbols with space.py").write_text(
            'def café():\n    """exported documentation"""\n    return 1\n', encoding="utf-8")
        db = Database(str(root / ".sot/sot.db"))
        try:
            Reconciler(db, str(root)).reconcile(workers=1)
            summary = ScipImporter(db, project_root=str(root)).import_file(str(root / "index.scip"))
            assert summary["documents_count"] == 2 and summary["references_count"] > 0
            references = list(db.conn.execute(
                "SELECT path,line_start FROM provider_evidence "
                "WHERE target_symbol='normalize' AND relation='references'"))
            assert any(Path(path).name == "app.ts" and line == 2 for path, line in references)
            assert not db.conn.execute("SELECT 1 FROM provider_evidence WHERE relation='calls'").fetchone()
            export_scip(db, str(root), str(root / "export.scip"))
        finally:
            db.close()

        decoder = r'''
const fs = require('fs'), assert = require('assert');
const {scip} = require(process.argv[1]);
const index = scip.Index.deserialize(fs.readFileSync(process.argv[2])).toObject();
assert(index.metadata.project_root.includes('compiler%20project%20space'));
assert(index.documents.length >= 3);
let docs = 0, references = 0, relations = 0;
for (const document of index.documents) {
  assert(document.language);
  for (const occurrence of document.occurrences) {
    assert([3, 4].includes(occurrence.range.length));
    assert(occurrence.range.every(n => n >= 0));
    if (!(occurrence.symbol_roles & 1)) references++;
  }
  for (const symbol of document.symbols) {
    docs += symbol.documentation.length;
    relations += symbol.relationships.length;
  }
}
assert(docs > 0 && references > 0 && relations > 0);
console.log(JSON.stringify({documents: index.documents.length, documentation: docs,
                           references, relationships: relations}));
'''
        sdk = root / "node_modules/@sourcegraph/scip-typescript/dist/src/scip.js"
        result = subprocess.run(["node", "-e", decoder, str(sdk), str(root / "export.scip")],
                                cwd=root, check=True, capture_output=True, text=True, timeout=30)
        print("Independent SDK decoded export:", result.stdout.strip())
        print("Fresh compiler import and independent export interop: PASS")


if __name__ == "__main__":
    main()
