# Drop native harness plugins/extensions — sotgraph ships MCP + CLI only

## Context
User decision: sotgraph chỉ cung cấp MCP server + CLI; không tự sinh plugin/extension vào các harness (OMP native extension, OpenCode plugin) — "phiền phức".

Phát hiện phụ: `cbm-augment.ts` KHÔNG do sotgraph sinh — do submodule `engines/codebase-memory-mcp` (pin `e477a32`, `engine-v2026.09.07`) sinh qua `cli.c:8746-8755` + `client_adapter.c:188` khi user chạy `cbm install`. Submodule → không sửa trong repo này; user tự `cbm uninstall` hoặc xóa `~/.config/opencode/plugins/cbm-augment.ts`. sotgraph chỉ spawn cbm `cli`/stdio với `CBM_CACHE_DIR` repo-local — không gọi installer.

## Scope decision (user-approved)
- Bỏ plugin/extension, GIỮ MCP config merge + skills/rules/slash-commands (auto-wire vẫn hoạt động).
- Giữ `hooks.py` (git post-merge/post-checkout/pre-commit — git-level, không phải harness plugin).
- Setup chạy lại phải DỌN artifact đã cài trước đó (marker-gated removal — chỉ xóa file có marker "SOT-Graph", không đụng file user tự viết).

## Approach
1. `migration.py`: thêm helper `remove_generated_file(path, marker)` — unlink file chỉ khi đọc được và chứa marker.
2. `omp.py`: bỏ copy `omp_extension.ts`; thay bằng marker-gated cleanup `.omp/extensions/{sotgraph,sot-graph}.ts` + `~/.omp/agent/extensions/{sotgraph,sot-graph}.ts` (marker: `Native Extension for SOT-Graph`). Giữ skill/rules/global.
3. `opencode.py`: bỏ copy `opencode_plugin.ts`; marker-gated cleanup `~/.config/opencode/plugins/{sotgraph,sot-graph}/index.ts` + rmdir nếu rỗng (marker: `Plugin for SOT-Graph`). Giữ `_merge_opencode_json` + skills.
4. Xóa file: `adapters/omp_extension.ts`, `adapters/opencode_plugin.ts`, `adapters/opencode_tools.json` (không còn consumer), `.omp/extensions/sotgraph.ts` (artifact generated ở repo root).
5. `installer.py`: cập nhật label omp/opencode (bỏ "Extension"/"Plugin").
6. `pyproject.toml`: bỏ `adapters/*.ts` khỏi package-data.
7. `scripts/adapter_docs_check.py`: cập nhật `NATIVE_TOOL_SOURCES` (xem usage trước khi sửa).
8. Tests: `tests/test_adapters.py` (assert không còn ext/plugin; legacy ext bị xóa thay vì migrate), `tests/test_omp_integration.py` (scenario 10 compile test + env vars trỏ file .ts).
9. Docs: README.md (bảng harness + mục "Native OMP/OpenCode Adapter Safety"), `docs/QA_GUIDE.md` Q8, `docs/ARCHITECTURE_REPORT.md` Module 1.3, `sot_qa_guide.html` (li OMP extension). Snapshot docs có ngày (CHANGELOGS, Report_sotgraph_archi_20260913, benchmarks reports) — giữ nguyên.

## Critical files
- `src/sot_graph/adapters/{omp,opencode,installer,migration}.py`
- `src/sot_graph/cli.py` (help text nếu nhắc extension)
- `pyproject.toml`, `scripts/adapter_docs_check.py`
- `tests/test_adapters.py`, `tests/test_omp_integration.py`
- `README.md`, `docs/QA_GUIDE.md`, `docs/ARCHITECTURE_REPORT.md`, `sot_qa_guide.html`

## Verification
- AC-01: `setup_omp`/`setup_opencode` không ghi file `.ts` nào; output list không chứa đường dẫn extension/plugin.
- AC-02: Setup chạy lại xóa artifact đã cài (file có marker) nhưng giữ file user viết (không marker).
- AC-03: MCP config merge + skill/rules vẫn được cài (`.opencode/opencode.json` mcp entry, `.omp/skills`, RULES.md).
- AC-04: `pytest tests/test_adapters.py` xanh; `test_omp_integration.py` phần liên quan pass/skip hợp lý.
- AC-05: `pip install`/build không kéo `.ts` (package-data sạch).

## Execution checklist
- [ ] T-01: migration.py helper + omp.py + opencode.py (AC-01, AC-02, AC-03)
- [ ] T-02: Xóa 4 file artifact + pyproject + installer labels + cli help (AC-01, AC-05)
- [ ] T-03: adapter_docs_check.py + tests (AC-04)
- [ ] T-04: README + QA_GUIDE + ARCHITECTURE_REPORT + sot_qa_guide.html
- [ ] T-05: Chạy focused tests qua test-runner (AC-04)

## Assumptions and contingencies
- Marker-gated removal chấp nhận rủi ro: file user tự viết có chứa "SOT-Graph" marker sẽ bị xóa — chấp nhận được vì naming là của mình; log path đã xóa trong `installed` output? (ghi vào danh sách removed riêng hoặc bỏ qua — quyết: không append vào `installed`, im lặng dọn).
- `opencode_tools.json`: xác nhận không consumer trước khi xóa.

## Evidence and handoff
- `pytest tests/test_adapters.py` → 20 passed (incl. new `test_omp_retired_extension_removed_user_file_kept`, `test_omp_legacy_extension_removed_and_rules_migrated`).
- `pytest tests/test_completion_surface_packaging.py` + adapters → 42 passed, 1 skipped (foreign `.ts` without marker preserved; idempotent snapshot holds).
- `pytest tests/test_omp_integration.py` → 9 passed (scenario 10 + PATH-safety harness removed as dead — imported the deleted .ts files).
- `python3 scripts/adapter_docs_check.py` → ✅ consistent (SKILL_MARKDOWN rewritten: `xd://` native devices → MCP tool names / `CLI only`).
- Smoke: `setup_omp`/`setup_opencode` on tmp root → zero `.ts` artifacts; outputs = skill + rules + opencode.json only.
- `.omp/` workspace artifacts regenerated via `setup_omp(workspace-only)`; `.omp/extensions/sotgraph.ts` deleted.
- Residual: stale copies at `~/.omp/agent/extensions/`, `~/.config/opencode/plugins/sotgraph/` are removed on next user `sotgraph setup` (marker-gated).
- `cbm-augment.ts` (submodule engine) untouched — user removes via `cbm uninstall` or manual delete.
