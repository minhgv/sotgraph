# Independent packaging-verifier packet receipt

## Final reviewer follow-up — 2026-09-06

Status: **Frozen for independent re-review.** This section supersedes the earlier validation counts and pre-refinement subtree limitation below.

Reviewer identified that `git_blob` previously had syntax validation only. The verifier now computes SHA-1 over `b"blob " + ascii_decimal_size + b"\0" + data` for regular files and symlink target bytes, and compares it with the manifest's `git_blob`. Regular files stream once into both SHA-256 and Git blob SHA-1. Synthetic fixtures now contain proper Git blob hashes; four regressions reject well-formed but incorrect blob IDs for ordinary/executable files and file/directory symlinks. This binds manifest fields to source bytes; the trusted manifest still is not independent upstream provenance, and build reproducibility remains out of scope.

Pre-edit read-only CLI search exited **0**; pack exited **2** (`TARGET_NOT_FOUND`). Final commands from the repository root:

- `.venv/bin/python -m pytest tests/test_native_source_verifier.py -q`: exit **0**, **33 passed**, one existing Hypothesis collection warning, 0.21 seconds.
- `.venv/bin/ruff check scripts/verify_native_source.py tests/test_native_source_verifier.py`: exit **0**, all checks passed.
- `.venv/bin/python scripts/verify_native_source.py`: exit **0**, final implementation verified the actual subtree: pin `46ae198fc11cda80e817acbc5f5908d7c2de7032`, **2,050 entries**, **1,332,757,092 source bytes**, `verified: true`.
- `sot diff-impact --working-tree --json`: exit **0**, read-only without auto-reconcile; shared-working-tree/index coverage limitations remain as described below.

No native build or measurement was performed; only the three owned packet files changed. No further edits are planned pending re-review.

## Initial packet record

Date: 2026-09-06

## Scope and trust boundary

Only `scripts/verify_native_source.py`, `tests/test_native_source_verifier.py`, and this new receipt were authored for this packet. Existing unrelated working-tree changes were left alone. No workflow, runtime, package configuration, imported native source, historical evidence, or build receipt was edited. No native build, full test suite, shared database write, commit, or push was performed.

The version-controlled source manifest is legitimate trusted input. Its hashes check source consistency, not independent upstream authenticity. The verifier now explicitly requires release pin `46ae198fc11cda80e817acbc5f5908d7c2de7032`; this is release-policy enforcement, not a second provenance proof. Build digest reproducibility remains a separate question, untouched here.

## Implementation

Preserved `python3 scripts/verify_native_source.py` and its successful JSON result fields. Extracted scratch-testable `verify(source, manifest_path)`. Validate exact manifest/entry fields, totals, modes, digest syntax, nonnegative integer sizes, duplicate JSON keys and entry paths, and normalized relative paths. Reject special filesystem types and symlink roots. Resolve source links transitively and reject escapes or loops while preserving internal file/directory links and parent-relative internal targets. Hash link text, not referent bytes. Ordinary file mode verification retains Git executable-bit semantics. Assumes a quiescent checkout; does not claim protection against concurrent filesystem substitution.

## Commands and results

Executed from `/Users/giapminh79/code/GitHub/sot-graph`.

- Before editing: CLI read-only `sot search "verify_native_source" -n 3 --json` identified workflow invocation; its deliberately bounded output caused a broken-pipe diagnostic. CLI `sot pack "verify_native_source" --tokens 1500 --json` and path-qualified retry both reported `TARGET_NOT_FOUND`. No indexed core verifier symbol was available; no core runtime symbols were changed.
- Bounded manifest summary: 2,050 entries, 1,332,757,092 source bytes; modes `100644`, `100755`, `120000`.
- Initial system `python -m pytest ...` and `python -m ruff ...`: exit **1** each because those modules were absent. Used existing project `.venv` instead; installed nothing.
- Initial project scoped pytest: exit **1**, 28 passed / 1 failed. Python 3.14 non-strict resolution tolerated a link loop; fixed by strict resolution first, falling back only for missing internal targets.
- Final `.venv/bin/python -m pytest tests/test_native_source_verifier.py -q`: exit **0**, **29 passed**, one existing Hypothesis collection warning, 0.20 seconds. Includes intact synthetic inventory/internal links, byte/mode/missing/extra/type tampering, escapes/chains/loops, malformed schema/pin/JSON, and CLI success/failure.
- Final `.venv/bin/ruff check scripts/verify_native_source.py tests/test_native_source_verifier.py`: exit **0**, all checks passed.
- Actual subtree verification ran once, before the final strict loop-resolution refinement: `python scripts/verify_native_source.py`, exit **0**, `verified: true`, pin as above, 2,050 entries and 1,332,757,092 bytes. Final refinement was exercised by scoped synthetic tests; the large subtree was not rehashed.
- CLI read-only `sot diff-impact --working-tree --json`: exit **0**, envelope `COMPLETE_WITHIN_INDEX_CAPABILITY`, no fallbacks. No auto-reconcile requested. This is bounded indexed evidence over the shared working tree, not proof of isolated coverage for these newly untracked files.
