# Contributing to sot-graph

Thanks for your interest in contributing. sot-graph is a single-maintainer
project today; outside PRs are welcome. This document describes how the
project is actually built and gated — it mirrors the CI workflows and the
`scripts/quality_gates.sh` entry point rather than a generic template.

Agent-authored contributions: [`AGENTS.md`](AGENTS.md) at the repo root
governs agent behavior and the SOT-Graph knowledge-reuse protocols. Read it
before letting a coding agent touch this repository.

## Development setup

Requirements: git, [uv](https://docs.astral.sh/uv/), Python >= 3.10
(CI exercises 3.12 and newer).

```bash
git clone https://github.com/minhgv/sotgraph.git
cd sotgraph
uv sync --locked --all-extras --dev
```

`--all-extras --dev` matches what CI installs and pulls in the tree-sitter
grammar extras used by polyglot tests.

See [independent development readiness](docs/DEVELOPMENT_READINESS.md) for private native access, historical evidence, and operator prerequisites.

## Running tests

Full suite (what CI's `test` job runs):

```bash
uv run pytest tests/ -v --strict-markers
```

Targeted run while iterating (faster inner loop):

```bash
uv run pytest tests/test_sg110_claims.py -q
```

Some evaluation suites (real-repo holdout, module evaluation, benchmarks) run
through `scripts/` entry points and are wired into dedicated CI jobs; plain
`pytest tests/` is the expected local loop.

## Quality gates

`scripts/quality_gates.sh` is the release-grade gate. It fails closed on the
first failing gate, in order:

1. `ruff check` over core modules (`src/sot_graph/assurance/`,
   `src/sot_graph/providers/`, `diff_impact.py`, `db.py`, `snapshot.py`,
   `providers_registry.py`, `mcp_service.py`, `mcp_server.py`, `claims.py`).
2. `pyright` over the same core modules.
3. Coverage floors measured over the whole test suite: core modules >= 85%,
   `assurance/receipts.py` >= 90%.
4. `bandit` security scan using the reviewed config in `bandit.yaml`.
5. `pip-audit` against the PyPI advisory database (the only gate that needs
   network access).

```bash
bash scripts/quality_gates.sh
```

## Claims discipline

sot-graph makes verified trust claims about itself, tracked in two places:

- `claims/registry.yaml` — every public trust claim, with a same-commit
  artifact trace (benchmark JSON or enforcing test) and a stated ceiling.
- `uv run sotgraph claims lint` — validates artifact/provenance consistency,
  docs <-> registry drift, and scans `README.md`, `AGENTS.md`, and
  `docs/*.md` for unhedged absolute phrases ("100%", "guarantee",
  "authoritative") that no registry entry covers.

Practical rules:

- If you change a measured number in docs, update the matching registry
  entry and its artifact in the same commit.
- Write claims with hedges and ceilings ("measured on synthetic corpus,
  top-k=10") instead of absolutes; prefer rewording over adding `allow:`
  exemptions to the registry.
- Provenance checks require the cited commits to be ancestors of HEAD, so CI
  checks out full git history. A shallow or squashed local clone will fail
  provenance — keep a normal clone with history.

## Commit messages

Conventional Commits, with an optional scope, mirroring the existing log:

```
feat(providers): canonical cross-provider identity joins (SG-203)
fix(claims): keep cross_check fail-closed on provider errors
test(bench): provider-identity oracle fixtures
docs(plan): add reassessment roadmap
ci: fetch full git history — claims-linter provenance needs commits beyond depth-1
```

Reference the work item (`SG-XXX` from `plan/`, or `Closes #N`) in the
subject or body when applicable.

## Pull requests

- One logical change per PR; include tests for behavior changes.
- CI must pass: lint, test suite, claims lint, and the PR-level gates
  (diff-impact runs in advisory mode on PRs).
- No new unhedged trust claims; if your PR changes measured behavior, update
  `claims/registry.yaml` in the same PR.
- Fill in the PR template checklist.

## Changelog and releases

There is no separate `CHANGELOG.md`; the convention lives in
[`docs/RELEASE.md`](docs/RELEASE.md):

- The version lives in `__version__` in `src/sot_graph/__init__.py`
  (pyproject reads it dynamically) — that is the single place to bump.
- Release tags conventionally use annotated `vX.Y.Z` tags. Actions are currently
  disabled in this private repository; a tag alone does not establish publishing
  readiness. See the operator prerequisites in the development readiness guide.
- User-visible changes are documented in a `docs/RELEASE_NOTES_vX.Y.Z.md`
  file per release (see v0.3.0–v0.3.2 for the format).

## License

By contributing, you agree that your contributions are licensed under the
MIT License covering this repository.
