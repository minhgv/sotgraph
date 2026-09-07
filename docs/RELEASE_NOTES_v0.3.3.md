# Release Notes — v0.3.3 (unreleased)

Distribution rename + trusted CBM engine bootstrap. The tool formerly
distributed as `sot-graph` is now `sotgraph` everywhere users touch it, and
the codebase-memory (CBM) extractor engine is provisioned by sotgraph itself —
no separate install, ever.

## Distribution rename: `sot-graph` → `sotgraph`

- **CLI**: `sotgraph` (unchanged since the P1 runtime work; reasserted here).
- **PyPI distribution**: `sotgraph`. The legacy project `sot-graph` (≤ 0.3.2)
  remains on PyPI as a historical record; every release from v0.3.3 on
  publishes only as `sotgraph`. PEP 503 normalization means `sot_graph-*`
  artifacts would land on the OLD project — always upload files whose names
  start with `sotgraph-`.
- **Python import package**: still `sot_graph` (internal API unchanged).
- **Repository**: `github.com/minhgv/sotgraph` (the old URL redirects).
- **MCP server key / harness artifacts**: registered as `sotgraph`
  (`sotgraph.ts`, `skills/sotgraph/`, `rules/sotgraph.md`). `sotgraph setup`
  migrates or removes provably-ours legacy `sot-graph` artifacts and never
  touches foreign files.
- **Documentation**: every user-facing doc now says `sotgraph`; historical
  release notes were swept for the same spelling.

### Migration for existing users

```bash
pip uninstall sot-graph        # if present
pipx install sotgraph          # or: uv tool install sotgraph
sotgraph setup --harness all   # re-provision adapters + engine bootstrap
```

Nothing else moves: per-repo `.sot/` databases (Schema v8), stored notes, and
`~/.sotgraph/engine-store` are preserved across the rename.

## CBM extractor via trusted engine bootstrap

- **One-shot install**: `pipx install sotgraph` + `sotgraph setup` is the
  complete provisioning path. The CBM engine binary (`codebase-memory`,
  protocol `artifacts-v1`) is pinned per platform in
  `src/sot_graph/providers/engine_pins.json` — currently `engine-v2026.09.07`
  (engine commit `e477a32`) for darwin-arm64, linux-arm64, linux-x86_64 —
  fetched at setup/explicit command time only, verified against pinned
  sha256 + size before staging, and promoted via the artifact store at
  `~/.sotgraph/engine-store` (digest-addressed, rollback-safe).
  Never pip- or npm-installed, never download-on-query.
- **Extraction tiers**: the builtin tree-sitter AST extractor
  (`AST_HEURISTIC_PARSER`) remains the always-available tier; the CBM engine
  adds external evidence for symbols, callgraph, usages, impact, and
  broad-language discovery, joined into the `provider_runs` /
  `provider_evidence` provenance tables and surfaced by `sot cross-check`.
- **Internal MCP client**: sotgraph speaks to the engine over MCP stdio with
  a per-account runtime namespace (`$TMPDIR/sotgraph-engine-<uid>`, 0700) and
  an isolated cache under the engine store.
- **Engine admin requires `--store`**: every `sotgraph engine` operation now
  names the trusted store explicitly (e.g.
  `sotgraph engine --store ~/.sotgraph/engine-store status`); without it the
  command refuses with the exact requirement instead of guessing.
- **Opt-out / auth knobs**: `SOT_ENGINE_BOOTSTRAP=off` disables automatic
  bootstrap; `SOT_ENGINE_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN` authenticate
  the pinned release download when the mirror requires it.
