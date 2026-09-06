# P6 exploratory matched measurement — 2026-09-06

No G6 promotion. Corrected real sequential matched workload completed: `evidence/continuation-native/run-matched.py`, `matched-v2-protocol.json`, `matched-v2-raw.json`, `matched-v2-summary.json`, `matched-v2.log`. Same frozen two-file Python corpus, query greet, 1 warmup + 30 measured queries each, alternating builtin SOT search (no JIT) and source-verified managed SOT search. No concurrent tests during corrected run. Exit 0 and zero command failures in both arms.

| Path | n | p50 seconds | p95 seconds |
|---|---:|---:|---:|
| builtin | 30 | 0.104124 | 0.135051 |
| managed | 30 | 26.742612 | 27.267466 |

There is **no performance win**, and no preference rollout. Managed lifecycle/IPC dominates this tiny corpus but attribution beyond measured end-to-end timings remains inference. Initial invalid builtin argument run was aborted and its raw failures retained separately; it is excluded.

Later four-cell implementation completed: `four-corpus-frozen.json`, `run-four-corpus.py`, `four-corpus-v2-raw.json`, `four-corpus-v2-summary.json`, `four-corpus-v2-exit.json`. Python/TS/C/polyglot each five index calls and one warmup + thirty query calls per provider, 292 command records, zero completed-command failures. Query p50 builtin/managed seconds: Python .1172/27.3706; TS .1187/27.4592; C .1119/26.8407; polyglot .1055/26.7827. Performance threshold **FAIL in every measured cell**. CPU and time-l RSS recorded; detached native workers may be omitted from process accounting. Initial long socket-root failures retained as v1; v2 corrected only scratch root names. Tool killed v2 after275 records; missing17 resumed, interrupted call excluded and polyglot cache discontinuity explicit.

Limits: warm OS cache only; controlled synthetic cells rather than representative external repositories; five index invocations are first empty-native-cache then unchanged incremental, not five independent cold/full builds; no precision/recall oracle matrix. Same corpus does not make response semantics identical: builtin ranked graph output and managed verified subjects differ, documented in raw outputs. No numeric quality/support claim. G6 blocked both by predecessors and unmet performance/full protocol evidence.
