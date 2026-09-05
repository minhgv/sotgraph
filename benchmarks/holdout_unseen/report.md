# SG-204 holdout benchmark report

- repos measured: **10** (pinned, licenses declared)
- presence precision (macro / min): **1.0** / 1.0
- false absence total: **0**
- impact recall (macro, supported static scope): **0.9909**
- test-selection recall (macro, measured repos only: 10/10): **1.0**
- retrieval Hit@1 / Hit@5 / MRR (reported, not gated): 0.8233 / 0.9467 / 0.873
- abstention accuracy: 1.0

All macro scores are computed over the MEASURED denominator only; unmeasurable and excluded tasks are published below, never folded into a score.

| repo | presence | false-abs | impact | test-sel |
|---|---|---|---|---|
| attrs | 1.0 | 0 | 0.96 | 1.0 |
| filelock | 1.0 | 0 | 1.0 | 1.0 |
| iniconfig | 1.0 | 0 | 1.0 | 1.0 |
| more-itertools | 1.0 | 0 | 1.0 | 1.0 |
| platformdirs | 1.0 | 0 | 1.0 | 1.0 |
| pluggy | 1.0 | 0 | 0.96 | 1.0 |
| pyflakes | 1.0 | 0 | 1.0 | 1.0 |
| python-dateutil | 1.0 | 0 | 1.0 | 1.0 |
| soupsieve | 1.0 | 0 | 1.0 | 1.0 |
| sqlparse | 1.0 | 0 | 0.9894 | 1.0 |

Denominators (universe / measured / excluded — scores cover the measured slice only):

| metric | universe | measured | excluded | out-of-scope | unmeasurable repos |
|---|---|---|---|---|---|
| presence_precision | 9306 | 9306 | – | – | – |
| false_absence | 8246 | 8246 | – | – | – |
| impact_recall | 601 | 217 | sample_cap_25: 384 | ambiguous_callee_name: 26 | – |
| test_selection_recall | 19 | 19 | – | attribute_only_reference_not_modelable: 2 | – |
| abstention_accuracy | 200 | 200 | – | – | – |

gates: **ALL PASS**
