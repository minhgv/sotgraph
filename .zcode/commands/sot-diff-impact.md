---
description: Analyze git diff blast radius, upstream inward callers, API contract impacts, and affected tests
---

Run SOT-Graph diff impact analysis across git revisions or working tree:

```bash
sotgraph diff-impact $ARGUMENTS
```

- Target can be a revision (e.g. `HEAD~1`, `main...HEAD`, commit hash).
- Useful flags: `--depth <n>` (default 2), `--staged`, `--working-tree`, `--auto-reconcile`.
