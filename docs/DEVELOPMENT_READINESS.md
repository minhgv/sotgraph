# Independent development readiness

## Repository boundary

Development now lives in private `minhgv/sotgraph`. Native source lives in
private `minhgv/sotgraph-cbm`, mounted at `engines/codebase-memory-mcp`.
The prior checkout is not a dependency and must not be modified by migration work.
The executable is now **`sotgraph`**, with no legacy alias installed. This is an
intentional command-line breaking change: update automation and regenerate
harness configuration with `sotgraph setup`. It avoids replacing the old CLI in
another environment. The distribution `sotgraph`, import `sot_graph`, `.sot`
storage, managed configuration names, MCP tool/resource identifiers and harness
skill names remain compatibility APIs.
They are not obsolete repository links.

## Reproducible Python-only onboarding

Use Git, uv, and Python >=3.10 (local acceptance below uses Python 3.12).
Authenticate to GitHub using your own credential manager; never embed a token in
clone URLs, config files, shell history, or committed receipts.

```bash
git clone https://github.com/minhgv/sotgraph.git
cd sotgraph
git switch -c feat/my-change
uv python install 3.12
uv sync --locked --all-extras --dev
.venv/bin/sotgraph --version
.venv/bin/python -c 'import sot_graph; print(sot_graph.__file__)'
uv run --locked pytest tests/ -q -ra
.venv/bin/python scripts/check_repository_identity.py
bash scripts/quality_gates.sh
uv build
```

The import path must belong to this checkout, not a separately installed old
editable environment. `uv sync --locked` refuses unreviewed dependency drift;
change dependencies with an intentional lockfile update. Quality gates run core
Ruff, Pyright, coverage floors (85% core, 90% receipts), Bandit, and pip-audit.
Security tools/advisory lookup may require network. Packaging's offline test
needs setuptools: if unavailable in the environment, set
`SOT_TEST_SETUPTOOLS_PATH` to a cached directory containing `setuptools/`.
Inspect `pytest -ra` so a skipped packaging test is never mistaken for success.

For first-run local graph work, run `.venv/bin/sotgraph reconcile`, then
`.venv/bin/sotgraph doctor --json`. Graph files remain ignored; graph findings are
scope-bounded AST evidence, not compiler-exact proof. Do not copy another
checkout's graph database or user authentication. Commit on a feature branch;
review locally and obtain approval before pushing or merging.

## Optional native development

Python development and default Python CI do not initialize private submodules.
To opt in after obtaining access to both private repositories:

```bash
git submodule update --init --recursive
.venv/bin/python scripts/verify_native_source.py
```

Current authentic pin: `46ae198fc11cda80e817acbc5f5908d7c2de7032`.
Native upstream attribution and licenses remain intact. The independent mirror
retains native history; it is not a Python package payload. See the native README
for compiler requirements. Build in scratch, without installer/UI hooks, as the
experimental workflow does. Do not run competing native measurement jobs.

To update the pin, review a commit in the controlled native mirror, check out
that exact commit in the submodule, and stage the gitlink in the parent on a
feature branch. Add a newly reviewed source manifest/evidence and update the
verifier binding as needed; never silently rewrite an old signed/hash-bound
receipt to make a new pin appear historically verified. Run source verification
and native acceptance before review. No native pin changed in this audit.

## Operator prerequisites, not configured by this change

GitHub Actions remain disabled. No workflow was dispatched, no remote settings
or secrets changed, and no changes pushed. Before enabling native CI, configure
`NATIVE_SOURCE_READ_TOKEN` as a short-lived/fine-grained credential with only
Contents: read for these two private repositories (or use a GitHub App
installation token with equivalent repository-limited permissions). The native
workflow fails with an explicit message when this secret is absent, including
fork PRs that cannot receive secrets. Checkout does not persist credentials.
Do not grant broad personal tokens or use pull_request_target to expose secrets.
Python CI requires no native token. The separate real-provider interoperability
job intentionally tests the published optional provider; it is not a dependency
on the former repository or certification of the controlled native mirror.

Publishing/package ownership, release environments, branch protections and
external service credentials must be reviewed by the operator before release.
Private repository source installs are the onboarding default; a public PyPI
package with the same compatibility name need not contain this branch's changes.
Static workflow validation does not certify remote execution or release readiness.

## Audit scope and immutable exceptions

The audit scanned Git-tracked text across active docs, translations, metadata,
workflows/actions, dev scripts, generated templates, harness configurations,
tests, benchmarks, plans and archived evidence. Native source is separately
verified and not edited; vendored licenses/upstream attribution remain intact.
Active old clone URLs, metadata links, action dogfood repository detection, and
QA preview links were corrected. Public HTMLPreview cannot read this private
repository, so the QA guide now links to the local HTML artifact. Lockfile
installs are enforced in CI; isolated package smoke checks disable project
resolution so they actually use the built artifact.

`python scripts/check_repository_identity.py` rejects old repository identity
URLs, old checkout paths (macOS/Linux), and obsolete clone-directory commands.
It also checks active implementation, scripts and harness launch commands for
obsolete executable use, while deliberately permitting public
package/import/configuration identifiers. Archived command examples in release
notes, plan/evaluation/benchmark evidence and the historical Hermes plan describe
their original executable; translate those commands to `sotgraph` for new work. Its
109 historical exceptions are individually enumerated with exact SHA-256 hashes
in `scripts/repository_reference_exceptions.json`: 102 plan artifacts, six
benchmark artifacts, and one historical release note. These old links/paths are
provenance, not instructions to use the old checkout. No archive-wide skip mask
is used; changed exception bytes fail review. The JSON is a review baseline,
not permission to add active files to the allowlist. Raw measurements, hashes,
commit identifiers, and licenses were not rewritten.

## Local validation (2026-09-06)

Independent repository and renamed CLI validation:

- Locked all-extras/dev synchronization passed on Python 3.12.12.
- Full suite after command migration: 2209 passed, four platform/privilege skips; packaging test executed
  with cached setuptools (no optional packaging skip).
- Six focused identity/workflow/metadata/console-contract tests passed.
- Core Ruff and Pyright passed; measured core coverage 88%, receipts 94%.
- Bandit passed. Dependency audit of the actual project site-packages reported
  no known vulnerabilities (not merely the isolated pip-audit tool environment).
- Wheel and sdist built; all four Project-URL fields point at this repository.
  Inspected payloads contain no engines, plan/evidence, benchmarks, evaluation,
  virtual environments, or graph databases. Isolated wheel and sdist CLI smoke passed with only the `sotgraph` entrypoint;
  editable import resolved inside this checkout. Reinstallation removed the old
  environment-local executable; no global executables were modified.
- Offline wheel install/setup/uninstall lifecycle acceptance passed.
- MCP and generated OMP template smoke checks passed in genuinely isolated
  environments (`--no-project`), using the declared supported MCP <2 bound.
  Both `python -m sot_graph` and the installed executable report `sotgraph 0.3.2`.
- Native source verifier passed: unchanged pin, 2050 entries, 1332757092 bytes.
- Graph doctor was healthy, schema v8; reconcile indexed 437 files with no
  failures. Staged diff-impact was advisory/open, reporting stale non-code
  configuration/instruction evidence (`AGENTS.md` in the final staged receipt),
  parser failures and unresolved dynamic dispatch; it is not a closed
  assurance receipt or exhaustive proof.

Logs and build artifacts are outside Git; neither `.venv`, `.sot`, credentials
nor native source payloads belong in the Python distribution.
