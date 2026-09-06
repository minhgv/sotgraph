# Security Policy

## Supported versions

Only the current `0.3.x` release line receives security fixes. Older lines
and pre-releases are not supported; please upgrade to the latest 0.3.x
release before reporting.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

1. **Preferred:** use GitHub's private vulnerability reporting for this
   repository (**Security** tab -> **Report a vulnerability**). This reaches
   the maintainer without public disclosure.
2. **Alternative:** email `MAINTAINER-EMAIL-UNCONFIRMED` — placeholder;
   pending maintainer confirmation of the address to publish here.

Include a description, the affected version or commit, and minimal
reproduction steps (a failing command is ideal). This is a single-maintainer
project; expect an initial response within a few days, potentially longer
during busy periods.

## Scope and trust model

sotgraph is a local developer tool: it indexes repositories on your machine
and stores the knowledge graph in a local SQLite database (`.sot/sot.db`).
Indexed source code should be treated as untrusted input, and trust verdicts
about that code are advisory, bounded by documented limitations.

Known analytical limitations that affect verdict trustworthiness — dynamic
metaprogramming, cross-language boundaries, stale SCIP evidence — are
tracked in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md). Reports about
those limitations belong in regular issues, not security reports.
