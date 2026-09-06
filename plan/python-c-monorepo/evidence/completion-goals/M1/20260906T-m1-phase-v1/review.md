# Independent measured review — main adjudication

Frozen checkpoint `53a8c12` preceded the exclusive three-pair run (exit 0). Independent review verified 109 events, seven point-in-time inventories and matching replay transport. Managed median 8.818 s; direct median 8.681 s; managed native envelope median 8.672 s. Wrapper contributes approximately 0.15 s; native envelope dominates.

The initial reviewer interpretation suggested persistent IPC could amortize a fixed per-spawn cost. Main challenged that causal inference: the run does not directly timestamp native startup/request/close, and reaped-child CPU omits detached descendant work. Reviewer explicitly withdrew the fixed-per-spawn attribution. The wall-minus-child-CPU remainder cannot be classified as idle or startup overhead.

Final reviewed verdict: **M1 INCONCLUSIVE; M2 implementation BLOCKED on attribution**. Batching/persistent IPC is a candidate, not a demonstrated specific safe fix. A separately identified instrumented native build or equivalent direct internal timestamps is needed before selecting an optimization. Historical 26.7 s versus 8.8 s discrepancy remains unexplained. No source pin edits, timeout increase, integrity bypass or G6 claim.

M1's inconclusive exit branch is recorded as complete diagnostic work, not performance acceptance. M3/M4 remain independent and may proceed. M5 live cross-version/schema proof still requires genuinely distinct verified artifacts; two digests of the same source do not qualify.
