# SG-201 human landmark study — executable protocol (status: PENDING HUMAN EVIDENCE)

Issue #8 exit gate: **"Landmark precision@20 ≥ 90% as judged by a human reviewer."**

This gate CANNOT be closed by an agent or by automated scoring. This document
is the executable protocol; the automation below only prepares materials and
aggregates human verdicts. **No human reviewer data exists yet — the gate is
PENDING, not passed.** Any automated proxy output is labelled `proxy` and is
never a substitute.

## Materials

- Worksheet generator (renders the top of the ACTUAL default map, within the
  declared token budget, into a reviewer CSV):

  ```
  .venv/bin/python scripts/bench_sg201_sg202_exit_gates.py landmark-materials \
      --root . --budget-tokens 1024 \
      --out benchmarks/exit_gates/landmark/worksheet.csv
  ```

- Aggregator with strict validation (incomplete or ambiguous reviews are
  rejected, never partially counted):

  ```
  .venv/bin/python scripts/bench_sg201_sg202_exit_gates.py landmark-aggregate \
      --dir benchmarks/exit_gates/landmark
  ```

## Reviewer procedure

1. Run the worksheet generator at the declared budget (default 1024 tokens).
   The worksheet lists the top 20 file groups of the rendered map in
   appearance order, with the symbol stubs as rendered. The generator also
   writes `manifest.json` (rank + path identity of the rendered top map);
   reviewer CSVs are validated against it.
2. For each row, decide whether the listed file/symbols are a **landmark** of
   the repository: something a developer would consider genuinely central to
   understanding or operating this codebase (entrypoints, core modules, key
   public APIs). Verdicts:
   - `landmark` — central, would expect it in a good task-oriented map;
   - `not_landmark` — peripheral, generated, vendored, test-fixture, or a
     trivial leaf that does not help a newcomer;
   - `unsure` — genuinely cannot decide (max 20% of rows; more invalidates
     the review). Unsure rows count in the denominator as explicit
     non-positives until adjudicated.
3. Fill in every row's `verdict` and `reviewer_note`, plus the attestation
   columns: `reviewer_name`, `reviewed_at`, and `attestation` starting with
   "I personally reviewed". Rows without attestation are invalid.
4. Save the filled CSV as `benchmarks/exit_gates/landmark/reviewer-<name>.csv`.
5. A review is valid only if: exactly the 20 manifest rows are present (rank
   1..20, no duplicates, paths matching the manifest), every verdict is one
   of the three values, attestation columns are filled, and at most 4 rows
   (20%) are `unsure`.

## Scoring and gate

- Per reviewer: precision@20 = `landmark` rows / **20** (full denominator;
  `unsure` never inflates the score).
- Aggregate: mean precision@20 across valid reviewers, and the reviewer
  count versus the protocol minimum (≥ 3).
- The aggregator reports an **informational** score only and ALWAYS sets
  `acceptance_status: PENDING_MANUAL_VERIFICATION` — CSVs alone are
  `supplied_not_verified` evidence. A maintainer closes the landmark gate by
  explicit adjudication of the aggregate report (checking reviewer
  identities and the worksheet manifest), never by running a script.
- Current status fields in the aggregate JSON: `min_reviewers_met`,
  `informational_verdict`, `human_evidence: "supplied_not_verified"`.

## Relationship to the automated contamination measurement

`sg201` (contamination < 2%) is fully automated with a declared oracle — it
can pass or fail on its own. The landmark half of SG-201 is separate and
human-only. Reports from `sg201` restate this; they never claim landmark
precision.

## Current status (2026-09-05)

- Protocol and materials: DONE (this file + generator/aggregator).
- Human reviews: **NONE — PENDING_HUMAN_EVIDENCE.**
- Landmark gate: **NOT MET (pending), regardless of the automated
  contamination number.**
