# 0001 — DECISION — Pivot to a trust-native connector marketplace

**Date:** 2026-06-01
**Decider:** user (explicit, this session)
**Type:** DECISION

## Context

The four OSS connectors (`delegate-connector-{email,slack,telegram,whatsapp}`) had been
published to PyPI at 0.1.0 as four independently-versioned packages. The user challenged
the packaging: _"why 4 packages and not 1 package with 4 plugins? Didn't we agree on the
latter?"_

A forensic sweep (workflow `wf_5de63490-39b`, two adversarial verifiers + synthesis) found:

- **No** user-authored record of a one-package-four-plugins agreement anywhere.
- The four-package model was set by the scaffold + `specs/monorepo-layout.md` ("v0 decision:
  per-connector independent packages — simplest"), justified as agent/spec prose, **never
  put to the user as an explicit choice.** The closest user-authored anchor (README.md:83,
  the co-owner's scaffold commit, co-authored with Claude) describes the Airbyte/dbt
  N-separate-packages model — the opposite of plugins.
- The only explicit "Decider: user" entry (`workspaces/email/journal/0003`) covers
  build-to-shipped-API + defer-conformance, **silent on packaging.**

The user then supplied the missing intent: **"given that we may end up with thousands of
plugins created by contributors, it's not possible to maintain packages for each of them.
We need an easy way to write plugins. … I see this as the n8n killer."**

This reframes packaging into product architecture. A package-per-connector cannot scale to
thousands of contributor connectors (it is n8n's own `n8n-nodes-base` monorepo bottleneck).

## Research

11-agent adversarial market study (workflow `wf_d3f9341a-899`): n8n, Airbyte, Home
Assistant/HACS, WordPress, VS Code, Terraform Registry, Pipedream; Python plugin mechanics
(entry-points / pluggy / stevedore) + untrusted-code sandboxing; supply-chain provenance
(Sigstore, PEP 740, SLSA). Three adversaries attacked the recommendation on supply-chain
security (verdict: **needs major revision**), scale/maintenance (**sound with fixes**), and
contributor DX (**sound with fixes**). Full dossier: `01-analysis/00-market-research-dossier.md`.

The security adversary verified **in source** that the headline trust claim is currently
half-false: connectors read raw `os.environ` credentials, hold the raw Ed25519 signing key
(can forge receipts), the capability set is a bind-time string check (not egress-enforced),
and `NeverRevokedChannel` returns `False` always. The substrate **attests** but does not yet
**contain**.

## Decision

Adopt **Architecture C (Hybrid), threat-sequenced** (`02-plans/01-architecture.md`):
entry-point discovery + declarative-manifest easy tier (safe-by-construction default) +
code-tier escape hatch (allowlist-gated until a sandbox lands) + one signed registry + a
versioned factory + a credential broker + an out-of-process sandbox.

### Owner choices (verbatim, this session)

1. **Direction:** _"Yes — commit, write it up first."_ → Architecture spec authored before any
   code; Phase 0 gated on owner review of this write-up.
2. **Trust posture:** _"Ship the true subset only."_ → Until containment ships, claim only
   _"every action signed + audited"_ + _"allowlisted publishers only."_ Do **not** claim
   "credential-blind / run any community connector" until Phase 0 + Phase 3 land.
3. **Published packages:** _"Yank and restart clean."_ → Yank the four 0.1.0 packages from
   PyPI (yank, not delete — keep names reserved against typosquatting); re-introduce the
   connectors under the plugin model from scratch as official-tier reference plugins.

## Consequences

- `specs/monorepo-layout.md` is superseded once Phase 0 lands (until then it accurately
  describes the shipped-but-being-retired state).
- 0.1.1 doc-fix PR (#18) closed as moot — the four READMEs are rewritten wholesale in Phase 0.
- PyPI yank is an owner web-UI action (upload token cannot yank) — handed off.
- Build sequence: Phase 0 (decoupling) → 1 (declarative tier) → 2 (gated code discovery) →
  3 (sandbox) → 4 (operational). Each phase ships real, safe value.

## Receipts

- Forensics: workflow `wf_5de63490-39b` (packaging-decision-forensics).
- Market study: workflow `wf_d3f9341a-899` (connector-plugin-architecture-research),
  11 agents, ~1.43M tokens, verdicts recorded in the dossier.
