# Feature-branch quality gate — 2026-09-06

User decision: keep work on `feat/python-c-monorepo-phased`; do not merge into `main` or push. This receipt is not release certification.

## Tested baseline

- Full-suite and package source: `cf8d03143ab75c7dd5f500476ad2061c4e546831`.
- Follow-up test-only lint correction: `9c117dc` (two test files; production unchanged).
- Bounded independent review of seven changed production files found no concrete blocking regression. Managed activation remains explicit/internal; this does not certify all platforms.

## Full default suite

Command: `.venv/bin/python -m pytest tests/ -v --strict-markers -ra --junitxml=/tmp/sot-baseline-8mtq68mh/pytest.xml -o cache_dir=/tmp/sot-baseline-8mtq68mh/pytest-cache`.

Environment overrides: `PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/tmp/sot-baseline-8mtq68mh`. External subprocess deadline: 600 seconds.

Result: exit 0, 192.03 seconds wall; **1,848 tests passed, 176 subtests passed, 3 skipped, 4 warnings**. Skips: root-only ownership test and two Windows-only Job Object tests. Separate opt-in real-CBM E2E script was not run in this gate.

Session-local log: `/tmp/sot-baseline-8mtq68mh/pytest.log`. These scratch paths are not durable repository artifacts.

## Offline packaging

Built a `git archive HEAD` copy with existing cached setuptools backend, without installing dependencies or accessing the network. `setuptools.build_meta.build_sdist` and `build_wheel` both completed, exit 0. Archive integrity checked; both include `providers/artifacts.py`.

Scratch outputs:
- `/tmp/sot-baseline-8mtq68mh/dist/sot_graph-0.3.2-py3-none-any.whl`
- `/tmp/sot-baseline-8mtq68mh/dist/sot_graph-0.3.2.tar.gz`

This proves Python packaging on the measured host, not native build/distribution or G4 completion.

## Lint repair

Initial scoped Ruff check found six F811 errors in `test_cbm_contract_parity.py` and two E731 errors in `test_monorepo_snapshot_adversarial.py`. Fixed by fixture alias registration and equivalent local functions. Both files: 12 tests passed, exit 0, 3.70 seconds under an external 90-second deadline.

Main reran Ruff over all seven changed production files and thirteen added Python test files: exit 0, all checks passed. Full default suite was not rerun after this test-only delta. A broader changed-test check also identified a pre-existing F841 in `test_cbm_adapter.py`, verified on `main`; it remains outside the new-test lint repair.

## Limits

No merge, push, global configuration modification, or native installer was performed. P2/G2 and P3/G3 retain their documented scoped verdicts. P4 source import, native packaging/license/platform validation and P5–P7 remain incomplete. The unrelated untracked user plan is preserved.
