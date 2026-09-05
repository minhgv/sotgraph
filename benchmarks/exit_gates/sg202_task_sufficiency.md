# SG-202 exit-gate measurement — task sufficiency (PILOT)

Scope: PILOT — self-repo corpus (sot-graph); does NOT close the global exit gate

## Provenance
- git HEAD: `8b45686a0ccfc1d02a3645d920366b20ad0f41bb` worktree digest: `e590733defd8540e` (dirty entries: 37, digest truncated: False)
- snapshot binding: scores apply to exactly this HEAD+worktree (content-exact digest)

## Policy (declared)
- task_sampling: seeded sample_definitions over src/ source-tree defs (oracle production category; vendor/fixture/test excluded)
- task_universe_label: src source-tree defs (oracle production category)
- seed: 20260905
- requested_tasks: 90
- budget_tokens: 1500
- contracts_cap: 8
- contract_satisfaction: identity (callee_path, callee_name) on outbound_callees entries only; inbound/stubs never credit
- contracts_overflow_handling: task ORACLE_UNMEASURABLE, excluded from numerators, denominator published
- relevant_test_oracle: HEURISTIC reference superset (ast Name/Attribute bare-name in test module); receipt = inbound caller edge from a relevant test module
- oracle_validation: curated fixed subset, ALL cases always evaluated
- gate_floor: 0.95
- min_measurable_tasks: 30
- gate_metric_note: gate metric is measured-subset sufficiency; all-sampled sufficiency published alongside

## Denominators
- production defs universe: 961 (oracle parse failures: 8)
- attempted tasks: 90
- oracle-unmeasurable: 48 (contracts overflow: 1, no relevant test: 48)
- **measurable denominator: 42** (gate metric denominator)
- full success: 0
- curated GT-subset cases checked: 9

## Metrics
- task sufficiency over ALL sampled tasks: **0.0** (exclusions do NOT imply 95% of all tasks)
- task sufficiency over measurable subset (gate metric): **0.0** (floor 0.95)
- target receipt rate (measurable): 0.9048
- relevant-test receipt rate (measurable): 0.0
- median recomputed tokens per bundle: 1226

## Outcome counts
- MISSING_CONTRACTS: 12
- MISSING_TEST: 26
- ORACLE_UNMEASURABLE: 48
- PACK_ERROR: 4

## Failure reasons (heads)
- AMBIGUOUS_TARGET: 3
- TARGET_TOO_LARGE: 1
- contracts_overflow: 1
- missing_direct_contracts: 12
- missing_relevant_test_caller: 38
- no_relevant_test_in_corpus: 48

## Gate
- verdict: **FAIL** (metric 0.0 vs floor 0.95, denominator 42 / min 30, oracle validation: PASSED (9 curated cases checked))

## Failures
- `src/sot_graph/adapters/antigravity.py::setup_antigravity` → MISSING_CONTRACTS: missing_direct_contracts: src/sot_graph/adapters/antigravity.py::_append_gemini_rules,src/sot_graph/adapters/antigravity.py::_merge_gemini_settings; missing_relevant_test_caller
- `src/sot_graph/analytics/architecture.py::aggregate_functional_modules` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/analytics/bundle.py::_render_conformance_markdown` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/analytics/bundle.py::_generate_dependencies_and_violations` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/analytics/bundle.py::_generate_system_metrics_json` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/analytics/graph.py::AnalyticsGraph` → MISSING_TEST: missing_relevant_test_caller
- `src/sot_graph/analytics/graph.py::calculate_blast_radius` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/analytics/graph.py::_repo_path_prefix` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/analytics/graph.py::_generate_community_label` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/assurance/accounting.py::_LimitVisitor` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/assurance/coverage.py::CoverageState` → MISSING_TEST: missing_relevant_test_caller
- `src/sot_graph/assurance/coverage.py::CoverageReport` → MISSING_TEST: missing_relevant_test_caller
- `src/sot_graph/assurance/coverage.py::_language_of` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/assurance/coverage.py::build_scope_manifest` → MISSING_CONTRACTS: missing_direct_contracts: src/sot_graph/assurance/coverage.py::ScopeManifest,src/sot_graph/assurance/coverage.py::_language_of,src/sot_graph/assurance/coverage.py::_matches_exclusion,src/sot_graph/assurance/coverage.py::_normalize_rel_path; missing_relevant_test_caller
- `src/sot_graph/assurance/identity.py::identity_hash` → MISSING_CONTRACTS: missing_direct_contracts: src/sot_graph/assurance/identity.py::identity_key; missing_relevant_test_caller
- `src/sot_graph/assurance/impact_pipeline.py::as_dict` → PACK_ERROR: AMBIGUOUS_TARGET: target 'as_dict' matches 5 nodes; qualify with a FQN
- `src/sot_graph/assurance/orchestrator.py::search_rows_from_payload` → MISSING_CONTRACTS: missing_direct_contracts: src/sot_graph/assurance/orchestrator.py::_span_from_lines; missing_relevant_test_caller
- `src/sot_graph/assurance/orchestrator.py::resolve_federated_spec` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/assurance/receipts.py::_node_row` → ORACLE_UNMEASURABLE: no_relevant_test_in_corpus
- `src/sot_graph/claims.py::Claim` → MISSING_TEST: missing_relevant_test_caller
