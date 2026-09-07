# Release Runbook

`sotgraph` releases are fully automated from a git tag. There is exactly one
manual, one-time setup step (PyPI trusted-publisher registration); everything
afterwards is `git tag && git push --tags`.

## One-time setup (owner only)

Register the trusted publisher on PyPI so GitHub Actions can publish without
any stored credentials:

1. Sign in at <https://pypi.org> with the account that owns (or will create)
   the `sotgraph` project.
2. If the project does not exist yet: **Add a new project → publish via
   trusted publisher**. If it exists: **Publishing → Add a new pending
   publisher** (or manage publishers in project settings).
3. Enter exactly:
   - **PyPI project name**: `sotgraph`
   - **Owner**: `minhgv`
   - **Repository**: `sotgraph`
   - **Workflow name**: `ci.yml`
   - **Environment name**: `pypi`
4. In the GitHub repo, create the `pypi` **environment**
   (Settings → Environments → New environment → `pypi`). It can have zero
   protection rules; the workflow references it for the trusted-publisher
   audience.

Notes on the rename:

- The legacy project `sot-graph` (≤ 0.3.2, from before the distribution
  rename) already exists on PyPI. It stays untouched as a historical record;
  **all new releases publish only as `sotgraph`** (the name is currently
  unregistered). Optionally edit the old project's description/README on PyPI
  to point users at `sotgraph`.
- PEP 503 normalization collapses `_`/`.`/`-` runs to `-`, so a wheel named
  `sot_graph-*` uploads to the **old** `sot-graph` project. Always verify the
  built filenames start with `sotgraph-` before uploading — the `dist/`
  directory still holds stale pre-rename `sot_graph-0.3.2` artifacts; delete
  or ignore them and rebuild (`uv build`).

## Cutting a release

```bash
# 1. Bump __version__ in src/sot_graph/__init__.py — the single source of
#    truth; pyproject reads it dynamically ([tool.setuptools.dynamic]) and
#    every runtime surface falls back to it. Then make sure the working
#    tree is clean and pushed.
# 2. Tag and push:
git tag -a v0.3.3 -m "sotgraph 0.3.3"
git push origin main --follow-tags
```

Pushing the tag triggers `.github/workflows/ci.yml`:

| Job | What it does |
| :-- | :-- |
| `lint` / `test` / `accuracy-oracle` / `quality-gates` / `module-eval` / `real-cbm-e2e` / `package-smoke` | Full gate matrix (now including Python 3.13/3.14 and the accuracy oracle as a release dependency) |
| `release` | `uv build` + GitHub Release with artifacts and generated notes |
| `publish-pypi` | Rebuild + publish sdist/wheel to PyPI via OIDC trusted publishing (with attestations) |

All gates must pass — `release.needs` includes `accuracy-oracle`, and
`module-eval --strict-probes` fails closed on probe crashes.

## Manual publish (while Actions are disabled)

GitHub Actions are currently disabled on the private mirror, so the automated
tag-driven pipeline does not run. Publish by hand until it is re-enabled:

```bash
# 1. Clean tree at the tagged commit, then build:
uv build --out-dir dist-clean          # filenames MUST start with "sotgraph-"

# 2. Metadata sanity check:
uvx twine check dist-clean/*

# 3. Upload (API token from pypi.org → Account settings → API tokens):
uvx twine upload dist-clean/sotgraph-*
#    username: __token__   password: pypi-<api-token>
```

Never upload `dist/sot_graph-*` leftovers — they normalize to the legacy
`sot-graph` project (see the rename note above).

## After the first release

- Flip the README "From PyPI" note (remove the "once the first `v*` tag is
  pushed" caveat).
- Add a `docs/RELEASE_NOTES_vX.Y.Z.md` for user-visible changes.

## Unreleased

- New command `sotgraph arch` renders architecture and flow views as a single
  self-contained, deterministic HTML file (zero dependencies, offline).
  - `sotgraph arch [-o architecture.html] [--scope <dir>]` — tiered layout by
    module role.
  - `sotgraph arch --flow "<target>" [--depth N] [--max-nodes M]
    [--lanes module] [-o flow.html]` — top-down flow with step numbers,
    decision branches, and optional module swimlanes.
  - Interactions: `/` search, click-to-inspect node passports, dark/light
    toggle. Unknown flow targets exit 2 without writing a file; truncated
    views carry a shown/total badge.
