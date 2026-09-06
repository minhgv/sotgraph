## Summary

<!-- One or two sentences: what and why. Reference SG-XXX / #issue if applicable. -->

## Checks

- [ ] Targeted tests pass locally (`uv run pytest tests/<suite>.py -q`); full suite (`uv run pytest tests/ -q`) if behavior changed
- [ ] `uv run sotgraph claims lint` passes; `claims/registry.yaml` updated in this PR if measured numbers changed
- [ ] No new unhedged absolute claims in README / AGENTS.md / docs
