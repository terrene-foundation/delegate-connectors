# Workspace — Connector Platform ("the n8n killer")

The pivot from four maintained PyPI packages to a **trust-native connector marketplace**:
thousands of contributor-authored connectors, discovered by entry-point, the common case
authored as declarative manifests, untrusted code contained by the Delegate signed-envelope +
capability + sandbox substrate.

## Read order

1. [`briefs/00-vision-brief.md`](briefs/00-vision-brief.md) — the vision + the 3 owner decisions.
2. [`journal/0001-DECISION-pivot-to-connector-platform.md`](journal/0001-DECISION-pivot-to-connector-platform.md) — the decision record + forensic provenance.
3. [`01-analysis/00-market-research-dossier.md`](01-analysis/00-market-research-dossier.md) — the cited market study (n8n, Airbyte, HACS, Terraform, Pipedream, Python plugin mechanics, supply-chain trust).
4. [`02-plans/01-architecture.md`](02-plans/01-architecture.md) — **the architecture** (Architecture C, threat-sequenced) + phased rollout + migration + contributor DX.

## Status

**PROPOSED — awaiting owner review of `02-plans/01-architecture.md` before any code.**
Phase 0 (decoupling foundation) is gated on that approval.

## One-line summary

Lead with a **declarative-manifest tier** that is credential-blind and capability-bounded _by
construction_; gate **code connectors** behind a provenance allowlist until an out-of-process
sandbox lands; market only the **true subset** of the trust claim until the mechanism exists.
