# SG-201 exit-gate — independent non-self corpus measurement

Scope: independent non-self corpus: all repos of the development-regression manifest benchmarks/holdout/manifest.json, each pinned to a full 40-hex SHA; automated contamination half only — NOT the self-repo pilot and NOT the human landmark gate

## Corpus (predeclared)
- manifest: `/Users/giapminh79/code/GitHub/sot-graph/benchmarks/holdout/manifest.json` (role: development-regression; repos declared: 11)
- budgets: [1024, 2048] tokens; min rendered symbols: 50; floor: fixture+vendor < 2% of rendered symbols (all unchanged)
- frozen holdout_unseen split: refused (split governance); production map: untouched (temp indexes only)
- pin verification: HEAD == pinned SHA AND clean worktree (no tracked edits, no untracked source; benign `.sot/` cache exempt) checked BEFORE and AFTER each measurement; changed inputs rejected

## Aggregate gate (fail-closed)
- verdict: **PASS** — repos PASS=11 FAIL=0 INSUFFICIENT_SAMPLING=0 NOT_EVALUABLE=0 ERROR=0 (measured 11/11)
- precedence: measured FAIL > incomplete coverage (NOT_EVALUABLE) > undersampled (INSUFFICIENT_SAMPLING) > PASS; anything other than full-coverage PASS never passes

## Per-repo verdicts

| repo | pinned SHA | pin ok (before+after) | verdict | rendered syms @ budgets (default filter) |
|---|---|---|---|---|
| itsdangerous | `c294b2fb4744…` | yes | PASS | 45@1024 73@2048 |
| click | `a6256bfb5971…` | yes | PASS | 44@1024 94@2048 |
| structlog | `f194271d998e…` | yes | PASS | 48@1024 107@2048 |
| tenacity | `949dcfa6c0a4…` | yes | PASS | 59@1024 108@2048 |
| python-slugify | `26b81c2e224e…` | yes | PASS | 90@1024 98@2048 |
| freezegun | `c9bf52c5aa12…` | yes | PASS | 65@1024 96@2048 |
| schedule | `4386f4562df3…` | yes | PASS | 62@1024 62@2048 |
| pexpect | `aa989594e1e4…` | yes | PASS | 91@1024 191@2048 |
| requests | `6f205ff422bc…` | yes | PASS | 46@1024 103@2048 |
| jsonschema | `bb947f1e2cb4…` | yes | PASS | 69@1024 145@2048 |
| markdown-it-py | `3b4ff6ddd368…` | yes | PASS | 58@1024 124@2048 |

## Actual rendered denominators per repo per budget

| repo | budget | control(all) | rendered syms | rendered files | contam syms | contam % | truncated | rendered sha256 |
|---|---|---|---|---|---|---|---|---|
| itsdangerous | 1024 | no | 45 | 8 | 0 | 0.0% | True | `7b4548a32400f310` |
| itsdangerous | 1024 | yes | 54 | 12 | 0 | 0.0% | True | `n/a` |
| itsdangerous | 2048 | no | 73 | 8 | 0 | 0.0% | False | `2a9fc6e465eb4f2d` |
| itsdangerous | 2048 | yes | 111 | 13 | 0 | 0.0% | True | `n/a` |
| click | 1024 | no | 44 | 14 | 0 | 0.0% | True | `94279d0094e850f6` |
| click | 1024 | yes | 40 | 15 | 0 | 0.0% | True | `n/a` |
| click | 2048 | no | 94 | 17 | 0 | 0.0% | True | `138a2e5dc9d1d068` |
| click | 2048 | yes | 75 | 18 | 0 | 0.0% | True | `n/a` |
| structlog | 1024 | no | 48 | 16 | 0 | 0.0% | True | `01166632db1b7a9d` |
| structlog | 1024 | yes | 50 | 19 | 0 | 0.0% | True | `n/a` |
| structlog | 2048 | no | 107 | 20 | 0 | 0.0% | True | `484ffa88ce488b06` |
| structlog | 2048 | yes | 122 | 25 | 0 | 0.0% | True | `n/a` |
| tenacity | 1024 | no | 59 | 9 | 0 | 0.0% | True | `32c352a6b23b5458` |
| tenacity | 1024 | yes | 62 | 11 | 0 | 0.0% | True | `n/a` |
| tenacity | 2048 | no | 108 | 10 | 0 | 0.0% | True | `80e233095876b8a2` |
| tenacity | 2048 | yes | 130 | 17 | 0 | 0.0% | True | `n/a` |
| python-slugify | 1024 | no | 90 | 5 | 0 | 0.0% | True | `8b7a0fcc4e880aaf` |
| python-slugify | 1024 | yes | 92 | 5 | 0 | 0.0% | True | `n/a` |
| python-slugify | 2048 | no | 98 | 5 | 0 | 0.0% | False | `6e53c0e0af4df5be` |
| python-slugify | 2048 | yes | 98 | 5 | 0 | 0.0% | False | `n/a` |
| freezegun | 1024 | no | 65 | 4 | 0 | 0.0% | True | `89ef623a26bd025c` |
| freezegun | 1024 | yes | 68 | 13 | 0 | 0.0% | True | `n/a` |
| freezegun | 2048 | no | 96 | 4 | 0 | 0.0% | False | `e3d25e204649b57e` |
| freezegun | 2048 | yes | 133 | 14 | 0 | 0.0% | True | `n/a` |
| schedule | 1024 | no | 62 | 2 | 0 | 0.0% | False | `e387c91b67dfccc2` |
| schedule | 1024 | yes | 102 | 3 | 0 | 0.0% | True | `n/a` |
| schedule | 2048 | no | 62 | 2 | 0 | 0.0% | False | `e387c91b67dfccc2` |
| schedule | 2048 | yes | 127 | 3 | 0 | 0.0% | False | `n/a` |
| pexpect | 1024 | no | 91 | 20 | 0 | 0.0% | True | `8b6c439f467ece05` |
| pexpect | 1024 | yes | 80 | 20 | 0 | 0.0% | True | `n/a` |
| pexpect | 2048 | no | 191 | 27 | 0 | 0.0% | True | `eb5ae65f5be9c3cc` |
| pexpect | 2048 | yes | 176 | 37 | 0 | 0.0% | True | `n/a` |
| requests | 1024 | no | 46 | 13 | 0 | 0.0% | True | `4c8ba425762e2650` |
| requests | 1024 | yes | 47 | 12 | 0 | 0.0% | True | `n/a` |
| requests | 2048 | no | 103 | 13 | 0 | 0.0% | True | `7d35a823af66e659` |
| requests | 2048 | yes | 97 | 16 | 0 | 0.0% | True | `n/a` |
| jsonschema | 1024 | no | 69 | 10 | 0 | 0.0% | True | `5b26236a1fa48c59` |
| jsonschema | 1024 | yes | 71 | 14 | 0 | 0.0% | True | `n/a` |
| jsonschema | 2048 | no | 145 | 10 | 0 | 0.0% | True | `311bdc9b2f65d88f` |
| jsonschema | 2048 | yes | 154 | 18 | 0 | 0.0% | True | `n/a` |
| markdown-it-py | 1024 | no | 58 | 19 | 0 | 0.0% | True | `0c9f325fa4b25f10` |
| markdown-it-py | 1024 | yes | 60 | 19 | 0 | 0.0% | True | `n/a` |
| markdown-it-py | 2048 | no | 124 | 31 | 0 | 0.0% | True | `916791fe2f2056a8` |
| markdown-it-py | 2048 | yes | 115 | 28 | 0 | 0.0% | True | `n/a` |

## Control sensitivity (why controls can be 0%)
- on-disk fixture/vendor files across the corpus: fixture=45 vendor=0 (extensions: {'.md': 44, '.txt': 1})
- controls open the category filter (``all``). Fixture/vendor files on disk here are non-code data files that produce no indexable symbols, so 0% controls are a genuine corpus property; oracle sensitivity to real renderable contamination is covered by synthetic tests (tests/test_sg201_sg202_exit_gates.py), not by this corpus.

## Tool provenance
- sot-graph HEAD: `8b45686a0ccfc1d02a3645d920366b20ad0f41bb` worktree digest: `1dcba5097d2a235f` (dirty entries: 82, truncated: False)

## Human landmark half — NOT measured here
- landmark precision@20 >= 90% requires >= 3 REAL human reviewers (plan/sg201-landmark-study-protocol.md); status **PENDING_HUMAN_EVIDENCE**; this automated corpus run never closes or substitutes it.

> Reproduce: `python3 scripts/bench_sg201_external_corpus.py --gate` (uses `.holdout-cache/` pinned checkouts; clones are NOT created automatically).
