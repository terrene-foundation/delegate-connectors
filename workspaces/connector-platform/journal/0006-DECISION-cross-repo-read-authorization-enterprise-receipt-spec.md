---
type: DECISION
date: 2026-06-03
created_at: 2026-06-03T11:00:00Z
author: human
session_id: term-21832
session_turn: 60
project: connector-platform
phase: analyze
topic: User-authorized cross-repo read of the private enterprise receipt spec for issue #26 consolidation
tags:
  [
    cross-repo-authorization,
    issue-26,
    consolidation,
    eatp-profile,
    repo-scope-discipline,
  ]
---

cross-repo-authorized: terrene-foundation/delegate-connectors-enterprise

## Context

Issue `terrene-foundation/delegate-connectors#26` (authored by the owner, Jack Hong, 2026-06-03)
directs consolidating the Delegate connector-receipt protocol into ONE open CC BY 4.0 spec in this
repo, positioned as an EATP profile. The normative source content (v2-core per-signer chain,
two-layer reconciliation, per-issuer head mechanism, §8.9 TOFU state machine, §8.9.9 residuals)
lives in the PRIVATE repo `delegate-connectors-enterprise`, file
`specs/delegate-receipt-model.md`. Issue #26's comment requires §8.9.9 residuals be carried
**verbatim** — which cannot be done faithfully from the issue summary alone (would paraphrase
clauses required verbatim, violating `rules/spec-accuracy.md`). Reading that file is a cross-repo
read against a private repo, gated by `rules/repo-scope-discipline.md` § User-Authorized Exception.

## Decision — authorization receipt (all five conditions)

1. **User-initiated:** owner authored issue #26 + issued the in-session instruction below.
2. **Explicit + specific:** the target repo + exact file are named; the bounded action is a
   read-only fetch of ONLY that one file.
3. **Confirmed:** the agent restated the exact action (read-only `gh api` fetch of
   `delegate-connectors-enterprise/specs/delegate-receipt-model.md`, that file only, to consolidate
   its severable content into a new open `specs/delegate-receipt-two-layer.md`) and the owner
   replied "approved" BEFORE any cross-repo command ran.
4. **Journaled before acting:** this entry + the `cross-repo-authorized:` marker land BEFORE the
   `gh api` fetch.
5. **Scoped exactly:** read-only; one file; no writes/branches/issues/PRs against the enterprise
   repo; no incidental reads of other enterprise files.

**Verbatim owner instruction (this session):** "please check the latest issues from gh first then
consolidate" → (after the agent restated the read-only single-file fetch) "approved".

## Scope of the authorized action

- ALLOWED: `gh api repos/terrene-foundation/delegate-connectors-enterprise/contents/specs/delegate-receipt-model.md`
  (read-only raw fetch), used to author the open spec in THIS repo with the four leak-classes
  stripped per #26's comment (proprietary file:line paths; provenance pointers; primitive NAMES
  like `M4`; enterprise framing).
- NOT ALLOWED under this receipt: any write to the enterprise repo; reading any other enterprise
  file; filing issues/PRs there. A separate authorization is required to later demote
  `delegate-receipt-model.md` (the authority-inversion step #26 sequences AFTER the open spec
  freezes, "in the enterprise repo, with maintainer go-ahead").

## Consequences

- The open spec `specs/delegate-receipt-two-layer.md` will be authored in delegate-connectors and
  brought to the owner as an outline for approval before writing (plan-gated, per #26's "maintainer
  go-ahead, one at a time").
- P0-10a (the connector_builder factory) is parked: `host/src/delegate_connectors_host/trust_primitives.py`
  is written + uncommitted on `main`; the factory design awaited owner confirm. The consolidation
  is spec-only and will not collide with it.

## For Discussion

1. The boundary test in #26's comment ("a clause enters the open spec IFF a standalone
   public-key-only verifier can act on it using ONLY the receipt/head's signed bytes + the §8.9
   state machine") is the severability oracle. Are there clauses where that test is genuinely
   ambiguous — and if so, does the safe default (keep proprietary) risk under-specifying the open
   verifier, or is under-inclusion always the correct conservative error here?
2. If the enterprise spec has drifted from this repo's frozen `canonical-signing-bytes.md` Layer-1
   (e.g. an integer-domain difference — the protocol-spec §11 once said `[-(2^63-1), 2^64-1]` while
   the frozen core says `[-(2^53-1), 2^53-1]`), which wins for the open spec — the frozen open
   Layer-1, or the enterprise text — and how is the divergence recorded?
3. Reading a private sibling's spec to author an open standard inverts the usual flow (open →
   consumer). Does consolidating enterprise-authored normative text into a CC BY 4.0 spec create
   any provenance/attribution obligation, or is the Foundation-owned-IP model (independence.md)
   sufficient that severable protocol clauses are simply Foundation standard content?
