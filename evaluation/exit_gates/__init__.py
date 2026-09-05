"""SG-201 / SG-202 exit-gate evaluators (measurement only, no tuning).

Contracts of this package:

- ORACLE INDEPENDENCE: ground truth is computed from source text via the
  stdlib-``ast`` oracle in ``sot_graph.holdout.evaluator`` (which never
  imports the engine) plus the locally-declared category oracle in
  ``category_oracle``. Pack/map *outputs* are only ever compared against
  these oracles — never scored by their own accounting claims.
- HONEST DENOMINATORS: every evaluator publishes its denominators,
  failure taxonomy and (when sampling is too small) an explicit
  ``INSUFFICIENT_SAMPLING`` verdict instead of a pass.
- PILOT SCOPE: results from the self-repo corpus are labelled PILOT and
  do NOT close the global exit gates.
"""
