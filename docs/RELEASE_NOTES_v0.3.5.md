# Release Notes — v0.3.5 (2026-09)

The diff receipt closes the loop: from "what was affected" to **"what
is left unresolved"**. `sotgraph diff-impact` now carries a P7.3
resolution ledger next to its blast-radius listing.

## `diff-impact`: P7.3 resolution ledger (receipt schema 1.9)

Every post-change receipt now includes a `resolution_ledger` block with
three read-only collectors:

- **Disposition matrix** — attach a PRE-change scope receipt
  (`sotgraph diff-impact --pre-receipt <digest|file>`; MCP
  `sot_diff_impact_receipt` gained a `pre_receipt` digest param) and the
  receipt classifies each predicted direct caller and candidate test as
  `addressed` (its file was touched by the diff) or `untouched`
  (predicted impact the change never reached). Advisory: untouched
  items surface in `remaining_gaps`, never degrade the decision — the
  pre-receipt prediction is heuristic.
- **Dangling-reference sweep** — decision-grade: any hit feeds
  `unresolved_count`, forces `unresolved_over_budget`, and blocks
  closure. Three nets: `pending_edges` rows left UNRESOLVED/AMBIGUOUS
  from the diff's changed and caller files (new unresolved references
  the change introduced); pending rows pointing at pre-change symbols
  that vanished (dotted aliases like `util.help` match bare `help`);
  and the rename/delete leftover net — pre-receipt callers of a symbol
  that disappeared whose files the diff never touched. The third net is
  needed because reconcile deletes the old graph edge together with the
  removed node, so the leftover caller never re-parks as a pending row.
- **Debt markers** — TODO/FIXME/HACK/XXX/`type: ignore`/`noqa`/bare
  `except:` introduced on ADDED diff lines (deleted lines don't count).
  Declared debt: advisory. The report list is capped at 50 via the
  registered `DEBT_MARKERS_SOURCE` (SG-107 registry⇄trigger bijection
  satisfied); totals stay exact. Blind spot disclosed in the payload:
  untracked files are not scanned (git diff does not emit them).

Honesty boundaries unchanged: without a pre-receipt the dangling sweep
stays scoped to the diff's own files (the receipt never claims
repo-wide absence), and nothing in the ledger proves the absence of
semantic bugs — it proves every predicted impact was addressed or is
explicitly listed as unresolved.

## Skill descriptions sharpened across harnesses

- The four adapter templates (antigravity, omp, opencode, zcode) and
  their generated SKILL.md artifacts now lead the skill frontmatter
  description with "Use for ANY codebase structural query: …" trigger
  wording so agents reliably route structural/exploration questions to
  sotgraph; the capabilities sentence is kept as the tail.

## Verification

- 16 new tests (tests/test_resolution_ledger.py) covering the pure
  diff-text scan, disposition matrix, end-to-end rename-leftover and
  debt-marker receipts, schema 1.9 pinning, and CLI text rendering; one
  new SG-107 trigger test for DEBT_MARKERS_SOURCE.
- Full suite at faf8bdc: 2339 passed / 5 skipped / 22 failed — all 22
  within the documented pre-existing failure set; no new regressions
  (the only source delta since that run is the version literal).
  `test_adapter_docs_consistency`, red before this release cycle, now
  passes.
