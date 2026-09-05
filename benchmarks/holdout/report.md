# SG-204 holdout benchmark report

- repos measured: **11** (pinned, licenses declared)
- presence precision (macro / min): **1.0** / 1.0
- false absence total: **0**
- impact recall (macro, supported static scope): **0.9798**
- test-selection recall (macro, measured repos only: 10/11): **1.0** — unmeasurable: jsonschema (no tests reference changed symbols)
- retrieval Hit@1 / Hit@5 / MRR (reported, not gated): 0.7879 / 0.9515 / 0.8548
- abstention accuracy: 1.0

All macro scores are computed over the MEASURED denominator only; unmeasurable and excluded tasks are published below, never folded into a score.

| repo | presence | false-abs | impact | test-sel |
|---|---|---|---|---|
| itsdangerous | 1.0 | 0 | 1.0 | 1.0 |
| click | 1.0 | 0 | 1.0 | 1.0 |
| structlog | 1.0 | 0 | 1.0 | 1.0 |
| tenacity | 1.0 | 0 | 0.96 | 1.0 |
| python-slugify | 1.0 | 0 | 0.838 | 1.0 |
| freezegun | 1.0 | 0 | 1.0 | 1.0 |
| schedule | 1.0 | 0 | 1.0 | 1.0 |
| pexpect | 1.0 | 0 | 1.0 | 1.0 |
| requests | 1.0 | 0 | 1.0 | 1.0 |
| jsonschema | 1.0 | 0 | 0.98 | unmeasurable (no tests reference changed symbols) |
| markdown-it-py | 1.0 | 0 | 1.0 | 1.0 |

Denominators (universe / measured / excluded — scores cover the measured slice only):

| metric | universe | measured | excluded | out-of-scope | unmeasurable repos |
|---|---|---|---|---|---|
| presence_precision | 6725 | 6725 | – | – | – |
| false_absence | 5707 | 5707 | – | unsupported_syntax_file: 8 | – |
| impact_recall | 592 | 228 | sample_cap_25: 364 | ambiguous_callee_name: 27 | – |
| test_selection_recall | 23 | 23 | – | attribute_only_reference_not_modelable: 10 | jsonschema: no tests reference changed symbols |
| abstention_accuracy | 220 | 220 | – | – | – |

gates: **ALL PASS**
