# M1 measured receipt — pending independent review

- Freeze commit: `53a8c123d4369ebc5cb5f5ea1182977fd18662d1`; measurement exit 0 (main), three pairs. Runner/manifest were not modified after freeze.
- Ownership: executor runner/protocol/summary; independent tester `agent_22a1bdd6-e821-4866-85ce-42409727d278`; reviewer `agent_576ff545-0d9a-485c-9354-318e3b823da3`; main exclusive measurement/commit. Measurement review pending.
- **M1 INCONCLUSIVE; M2 BLOCKED pending review.** Repeatability accepted; specific safe latency fix not established. This is not a G6 benchmark or speed-win claim.

| Pair | Managed query s | Native envelope s | Direct s | Managed outside envelope s |
|---|---:|---:|---:|---:|
| 0 | 8.818214 | 8.672337 | 8.678324 | 0.145877 |
| 1 | 8.840371 | 8.692770 | 8.681153 | 0.147601 |
| 2 | 8.802995 | 8.653396 | 8.925299 | 0.149599 |

Median managed `8.818214s`, direct `8.681153s`; median native fraction `98.33%`. Factory and admin pre-resolution are separately recorded; inclusive nested spans are not summed. `summary.json` preserves absolute UTC/monotonic direct and managed timelines, exact end/start spans, and all samples, including slower third direct run.

Native identity: source pin `46ae198fc11cda80e817acbc5f5908d7c2de7032`, artifact `2412e017268bef8f847f38d1b0f79f63185b38c27fe6fba637067bfc87c0eedf`. Source verifier previously verified 2,050 entries against pin, not enclosing Git HEAD. New-run daemon log copied byte-for-byte to `native-logs/cbm-daemon.log`: 65 lines, 8 starts, 8 stops, 8 last-client-disconnect stops, 0 timestamped lines. Lifecycle exists; startup/request/close cost remains unallocated. Seven bounded scratch inventories cannot prove absence of escaped/transient processes. Changed cache paths are listed in summary; no cache-invariance or true-cold claim.

Historical 26.7426s causal gap unavailable. OS cache and descendant resource coverage UNKNOWN; no idle inference. `/tmp` scratch is ephemeral; copied log plus recorded inventories/hashes are durable. No processes killed or existing stores changed by summarization.

Validation reported by main: full suite 1,978 passed / 4 skipped; new-file Ruff/Pyright pass. Full quality gate **FAIL** on ten pre-existing core type errors, untouched. Exact commands/exits remain in `acceptance/`; exact measurement command is frozen in `manifest.json`.

Hashes and new checkpoint allowlist: `summary.json`, `receipt.md`, `native-logs/cbm-daemon.log` (plus main-owned raw measurement/acceptance files as separately authorized). Result SHA256 `531856d58ed6055dae1d27da46c094bf3b43fd59cd7016948e8c8c02c023f611`; copied log SHA256 `cf5a588d8f532ddbca80a350c352eb707ade8818be7dc0cc86f5392963ffbcf3`. Summary binds manifest/runner hashes. Rollback: retain evidence, no production change. Next: independent verdict review and main receipt checkpoint; M3 may then proceed independently. M2 requires native phase evidence, potentially a separately approved instrumented artifact—not speculative optimization.
