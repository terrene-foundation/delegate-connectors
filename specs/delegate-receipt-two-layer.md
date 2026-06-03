# Delegate Receipt Model — Two-Layer Normative Spec (open standard)

**Status:** DRAFT (freezes on maintainer approval).
**License:** CC BY 4.0 — Terrene Foundation open standard.
**Conformance language:** MUST / SHOULD / MAY per RFC 2119.
**Audience:** any implementation that produces or verifies Delegate connector receipts — in any
language, open or proprietary — and any external party verifying a receipt with only a public key.

This is the single open, normative contract for the Delegate connector-receipt protocol's
**two-layer model**, its **v2-core per-signer receipt chain**, and the **per-issuer head**
mechanism. It consolidates the protocol contract that was previously split between this repo's
frozen byte core and a downstream implementation's spec; the contract now lives here, and every
implementation — including any enterprise tier — is a CONSUMER of this spec, authoring no parallel
normative spec.

## 0. Positioning — a profile of EATP + PACT (normative references, not re-derivation)

This spec is a **profile / binding** of two Terrene Foundation standards; it specifies the concrete
wire format and verification discipline and normatively references the standards for the trust
semantics, rather than re-deriving trust theory:

- **EATP (Enterprise Agent Trust Protocol)** — the receipt's two-tier verification (offline,
  public-key-only Layer 1 vs residency-internal Layer 2) is EATP's **verification gradient**
  instantiated for connector side effects: authenticity is verifiable everywhere; completeness is a
  graduated property of what the verifier holds and where it sits. Trust-attestation semantics are
  EATP's; this spec pins the bytes.
- **PACT (Principled Architecture for Constrained Trust)** — the constraint envelope a receipt is
  produced under is PACT's **Operating Envelope**; the signer/attester identity and its scope follow
  PACT's D/T/R addressing. This spec does not redefine the envelope; it references PACT.

This spec is therefore NOT a new standalone standard. It is the connector-receipt profile of the
Trinity (CARE/EATP/CO) + PACT, adding only the concrete receipt/head wire format and the verifier
state machine that the EATP verification gradient requires at this layer.

Layer 1's byte rules are defined in this repo's frozen `specs/canonical-signing-bytes.md` (FROZEN
v1) and referenced by the Delegate Connector Plugin Protocol §1–§3. This spec does NOT restate those
byte rules (`.claude/rules/specs-authority.md` Rule 9); it requires conformance to them and
specifies Layer 2, the binding, the v2-core chain, the head, and the §8 safety clauses.

## 1. The two-layer model (normative)

A Delegate receipt comprises **two layers** with disjoint purposes, wire forms, and conformance
disciplines. An implementation MUST NOT collapse them into one, and MUST NOT apply one layer's
conformance discipline to the other.

|                | **Layer 1 — Connector Receipt**                                  | **Layer 2 — Audit Witness**                                           |
| -------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------- |
| Purpose        | Cross-org / offline / marketplace verification                   | Internal audit; completeness against a malicious issuer               |
| Wire form      | Raw 64-byte Ed25519 detached sig over a canonical-JSON pre-image | Append-only hash-chained audit-ledger entry (implementation-internal) |
| Verifier needs | Only the signer's public key (offline)                           | Residency access to the audit ledger / its witnessed cross-anchor     |
| Conformance    | **Byte-exact** (`canonical-signing-bytes.md` §6 vectors)         | **Behavioural** (outcome, not byte-identity)                          |

## 2. Layer 1 — connector receipt (conforms to the frozen core)

- The pre-images, canonical-JSON rules, signature wire form, key/fingerprint, and §6 test vectors
  are normatively defined in `specs/canonical-signing-bytes.md` (frozen v1) and referenced by the
  protocol spec §1–§3. Every implementation MUST conform **byte-for-byte** and MUST pass the §5 two
  gates (byte reproduction of vectors A–E + the cross-implementation verification matrix) and the
  reject suite. No implementation may invent or relax any covered field.
- **Integer domain is `[-(2^53-1), 2^53-1]`** (JS-safe) per `canonical-signing-bytes.md` §1.3 — the
  authoritative frozen value. (NOTE: the Delegate Connector Plugin Protocol §11's edge-case bullet
  still says `[-(2^63-1), 2^64-1]`; that prose is stale and is reconciled to `2^53` as the upstream
  sequencing in §6 below — the frozen file is authoritative.)
- The serializer MUST emit `observed_at` as fixed-width 6-digit microseconds with literal `+00:00`
  (never `Z` / variable precision); key order by Unicode code point / UTF-8 byte order (never RFC
  8785/JCS); reject floats, NaN/Infinity, lone surrogates, out-of-range integers (producer side) and
  duplicate keys (verifier side). Raw 64-byte Ed25519 detached signature.

## 3. Layer 2 — audit witness (boundary only)

- Layer 2 is an **append-only hash-chained audit ledger** that is **implementation-internal**: this
  spec describes the BOUNDARY a Layer-1 receipt reconciles against, NOT the ledger engine. An
  implementation CONSUMES its own audit substrate; this spec does not specify, and an implementation
  MUST NOT expose externally, the ledger's internal structure.
- Layer 2 is the counterpart to the SDK **dispatch audit-event** (128-hex signature over
  `{event_type, event_payload, signer_delegate_id}`, protocol spec §2/§3). Both are "Layer 2 audit"
  with genuinely different mechanisms (hash-chain vs hex-sig). **Cross-implementation Layer-2
  conformance is BEHAVIOURAL, never byte-identity** — two implementations MUST NOT be byte-compared
  on the audit layer (byte-comparing engine internals is a category error and a leak of internals
  that are out of scope for this open contract).

## 4. The binding — residency-internal reconciliation (normative)

The two layers are bound by **residency-internal reconciliation**, NOT an external inclusion proof.

- **External verifier** (marketplace / counterparty / browser; public key only, no residency
  access): completeness rests on Layer 1's own signed chain (§6) + an optional published per-issuer
  head (§8.9). An implementation MUST NOT require an external Merkle inclusion proof tying a portable
  receipt to the audit ledger.
- **Internal verifier** (auditor WITH residency access): the on-prem audit ledger + a
  **residency-internal witness anchor** provide completeness against a malicious issuer. That anchor
  publishes only a **salted, non-invertible** head digest; it is a privacy-preserving witnessed
  head-seal, NOT a transparency log. An implementation MUST NOT extend the anchor to emit per-entry
  inclusion paths (it would defeat the residency no-metadata-leak invariant).
- This aligns with the protocol spec §11 Item 5 (transparency-log publish downgraded to SHOULD until
  a concrete log is provisioned — the dead-dependency anti-pattern). No tier mandates an external
  inclusion proof at v1.

## 5. Conformance split + the type firewall (normative)

- Layer 1 is a published wire format → **byte-exact** conformance (a vector harness reproducing the
  frozen `canonical-signing-bytes.md` §6 vectors — v1 A–E plus the v2-core set in §6.1). Layer 2 is
  an engine internal → **behavioural** conformance only.
- These two disciplines MUST live in **separately-named types with separate harnesses**. The
  behavioural-conformance surface MUST be structurally incapable of importing the Layer-1 receipt
  type as a byte-comparison key (this is the firewall that prevents an implementation from silently
  byte-comparing Layer-2 audit internals through a Layer-1 type).
- **Type-name distinctness (REQUIRED of every implementation).** Where an implementation's audit
  substrate already uses the names a receipt would (`SignedActionEnvelope` / `AttestedReadReceipt`),
  the implementation MUST keep the Layer-1 receipt type and the Layer-2 audit type DISTINCT (rename
  or namespace one), so a Layer-1 conformance claim cannot be satisfied by an audit-layer type. Any
  such rename of a published API MUST follow a deprecation cycle + CHANGELOG migration
  (`zero-tolerance` Rule 6a).

## 6. Versioning — v2-core is a +4-field per-signer chain (normative)

**v2-core (`protocol_version` = 2)** adds FOUR signed fields to the Layer-1 pre-image — `seq`,
`prev_receipt_hash`, `protocol_version`, `key_id` — making the connector receipt a **per-signer hash
chain**. It is a `protocol_version` 1→2 bump (additive field-set change per
`canonical-signing-bytes.md` §7). The pre-image break + cross-implementation migration is paid ONCE;
all four land together at v2-core (a v1-then-v2 two-step would pay it twice).

- **`seq`** — ONE monotonic chain per `signer_delegate_id`, INTERLEAVING write- and read-receipts
  (NOT per-resource, NOT per-type; the equivocation adversary is a _signer_). Start `0` at genesis,
  `+1` exactly per subsequent receipt. Bare JSON integer in the frozen non-negative sub-range
  `[0, 2^53-1]` (inherits the existing producer/verifier out-of-range reject). Overflow at `2^53` →
  producer MUST refuse-and-rotate (typed key-exhaustion error), NEVER wrap/saturate/reset (wrapping
  manufactures a second genesis = re-opens equivocation).
- **`prev_receipt_hash`** — 64-lowercase-hex SHA-256 (full 256-bit, **no truncation** — SHA-256
  pinned MUST) of the prior receipt's EXACT canonical pre-image BYTES (the bytes Ed25519-signed).
  Hash of the prior PRE-IMAGE, not the signature. Transitively commits to the prior `seq` (so `seq`
  is NOT hashed separately). Verifier MUST reject `/^[0-9a-f]{64}$/` failures BEFORE sig-verify;
  link comparison is byte-exact (case-sensitive). Computation discipline: §8.5.
- **`protocol_version`** — bare signed integer `2` (never `"2"`, never an enum-as-string). v1
  receipts have NO `protocol_version` key; absence is the v1 discriminant. Signing it blocks the
  downgrade attack (the unsigned field-presence fallback is REJECTED).
- **`key_id`** — bare JS-safe-integer signed key-epoch (selects the signing key-version; rotation =
  new epoch = fresh chain at `seq 0`). Revocation-honoring is SHOULD, contingent on a published key
  directory (§8.4).

**Canonical key orderings (code-point sorted; MUST be machine-verified before freeze — §8.8):**
write `{action_id, key_id, observed_at, payload, prev_receipt_hash, protocol_version, seq,
signer_delegate_id}`; read `{attester_delegate_id, key_id, manifest, observed_at, prev_receipt_hash,
protocol_version, read_id, seq}`. All four fields are INSIDE the signed pre-image, never envelope
metadata.

**The per-issuer head (§8.9) is a fifth canonical object** subject to the same machine-verified
ordering gate. Its key set `{head_hash, key_id, max_seq, signer_delegate_id}` MUST be confirmed by
the §8.8 emit-and-diff gate BEFORE freeze; this spec MUST NOT carry a hand-derived code-point
ordering for it (cite the serializer, never the hand-derivation). The head's conformance vectors are
HV-1..HV-6 (§8.9.11), DISJOINT from the V2-1..V2-16 receipt set.

**v1 ↔ v2 COEXISTENCE.** v1 vectors A–E stay frozen and mandatory for any v1 producer/verifier;
v2-core adds a DISJOINT vector set; the conformance gate is the UNION (a v2-capable implementation
reproduces ALL v1 AND ALL v2 vectors byte-for-byte) with **version routing** (§8.5). v1 never
retires while a v1 producer exists.

**Per-issuer head — path-scoped graduation.** A signed head is the object `{head_hash, key_id,
max_seq, signer_delegate_id}` (§8.9.1). Graduation is **path-scoped**: the **verifier-side
pin/compare obligation is MUST** (it consumes only heads its audience already received — no channel
dependency, §8.10), while **producer publication stays SHOULD for both the standalone and
envelope-embedded paths** until a concrete audience-scoped delivery channel is specified (a
MUST-publish to an unspecified channel is the dead-dependency anti-pattern §4/§8.1 forbid; a forced
publish would also compel the cleartext `max_seq` leak §8.9.10 forbids compelling for count-sensitive
connectors). Head-absence is fail-closed (`completeness: none`, §8.2/§8.9.7). The head closes — ONLY
for a verifier that rendezvouses ≥2 times — tail-truncation and the head-emitted equivocation forks
(§8.9.5); it does NOT close parallel-chain audience-splitting, rotation-as-amputation, or
single-rendezvous tail-truncation (§8.9.9, disclosed open). See §8.9 for the full mechanism.

**Upstream sequencing (the v2 freeze depends on it).** `canonical-signing-bytes.md` MUST add the v2
pre-images (4 fields + machine-verified key orderings + the §7 1→2 entry + the §11 integer-domain
reconciliation to `2^53`) and this repo's reference encoder MUST generate the real `canonical_bytes`
and Ed25519 signatures over the fixed test key BEFORE any implementation reproduces them. This is the
FIRST real `protocol_version` increment — treat the migration as greenfield. NO concrete v2 byte/sig
vector lands in any spec until the reference encoder generates it; this spec specifies WHAT each
vector pins (V2-1..V2-16 + the v1 reject-suite re-run), never byte strings (`spec-accuracy.md` Rule
1).

### 6.1 v2-core conformance vector set (WHAT each pins; bytes generated by the reference encoder per §8.8)

ACCEPT vectors: **V2-1** genesis-write (seq=0, sentinel, all four fields signed); **V2-2**
chain-of-2-write (seq=1 `prev` = SHA-256 of V2-1's pre-image — the prev-hash byte-linkage, requires
a 2-receipt entry in the cross-verify matrix); **V2-3** interleaved read-after-write (read's `prev`
points at the prior WRITE pre-image — pins the single-interleaved-per-signer chain); **V2-4**
genesis-read + read-chain-of-2 (read-side sentinel + link); **V2-5** key_id/protocol_version ordering
(pins their exact code-point byte positions — the silent-transposition guard); **V2-16**
genesis-sentinel byte-exact fixture (the two-key sentinel pre-image + its SHA-256).

REJECT vectors: **V2-6** prev_receipt_hash mismatch (chain-break); **V2-7** seq out-of-range (`2^53`)

- seq-reuse + non-`(seq-1)` predecessor; **V2-8** fork/equivocation (two receipts sharing one
  `(signer, prev_receipt_hash)` with different payloads → verifier flags + emits the proof artifact;
  byte portion in the byte-exact harness, outcome portion MUST NOT leak the receipt type into the
  behavioural surface); **V2-9** malformed-genesis (seq=0 but `prev` ≠ recompute — closes 64-zeros /
  omitted / bare-uuid); **V2-11** genesis-at-seq>0 (the reverse biconditional direction); **V2-12**
  cross-signer confusion (prev resolves to another signer's pre-image — reject even though SHA-256 +
  local Ed25519 verify); **V2-13** uppercase/non-64-char prev_receipt_hash (non-canonical, reject
  before sig-verify); **V2-14** version-routing ambiguity (bytes validating under two shapes → reject;
  v2-to-v1-only-verifier → reject); **V2-15** non-canonical-predecessor launder (reject at the prior's
  canonicality gate, not via re-serialize). Plus **V2-10** seq-gap suppression-signal (contiguous-
  expecting verifier surfaces it) and the **v1 reject-suite re-run** (float / NaN / `2^53` / non-string
  key / lone surrogate / duplicate key) UNCHANGED against the v2 canonicalizer.

## 7. Authority + scope

This spec is **authoritative** for the two-layer reconciliation, the v2-core chain, and the head
mechanism. It binds every conforming implementation; an implementation MUST be complete for the
frozen version (no stubs, per `zero-tolerance` Rule 6) and MUST satisfy the §8 safety clauses.

- **Layer 1 authority:** `specs/canonical-signing-bytes.md` (frozen v1) + protocol spec §1–§3. This
  spec does not restate those byte rules; it requires conformance to them.
- **Layer 2 authority:** the implementation's own audit ledger, consumed not re-specified here
  (behavioural conformance only, §3).
- **Two-layer reconciliation + v2-core + head authority:** this spec.
- Implementation tracking (which repo lands which surface, version bumps, migration tasks) is NOT
  spec content (`spec-accuracy.md` Rule 4); it lives in the owning repo's workspace/issues.

## 8. Implementation safety clauses (MUST — from adversarial security review)

The happy-path bytes (§2/§6) are necessary but NOT sufficient. The clauses below bind the _claims and
verification discipline_ around the receipt; an implementation that conforms to §2/§6 but violates §8
is non-conforming.

### 8.1 No externally-uncheckable anchoring claims (anti-theatre)

A Layer-1 receipt MUST NOT carry any field asserting ledger inclusion, anchor position, chain index,
or completeness that an external (public-key-only, no residency access) verifier cannot independently
verify from the receipt's own signed bytes. Any such assertion MUST be confined to the Layer-2
surface (unreachable externally per §1). This is the structural firewall that keeps the
residency-internal binding (§4) a sound privacy property rather than security theatre.

### 8.2 Equivocation/suppression closure is conditional — implementations MUST disclose, MUST NOT over-claim

- **v1** has NO equivocation/suppression defense: no `seq`/`prev_receipt_hash`; `action_id` carries
  NO uniqueness guarantee; `observed_at` is signer-controlled and is NOT a replay defense.
- **v2-core** makes equivocation **detectable-with-portable-proof for any party holding ≥2 of a
  signer's receipts spanning a fork** — BOTH the same-`seq` fork AND the same-`prev_receipt_hash` fork
  (two receipts sharing one parent hash = a fork at that parent). This does NOT "close equivocation"
  unconditionally. The verification surface MUST return `equivocation_detectable` as a function of
  receipts-held; for the **single-receipt holder — the common marketplace case — it returns FALSE,
  identical to v1** (an irreducible Layer-1 boundary). A surface MUST NOT advertise a single received
  receipt as "equivocation-protected."
- **Gap detection is for a CONTIGUOUS-EXPECTING verifier only.** A sparse multi-counterparty holding
  (seq 3, 7, 12 — the intervening seqs went to other counterparties) MUST NOT be flagged as
  suppression (cry-wolf); completeness there rests on the head's `max_seq`, not on the gap. The
  hash-bound contiguity check (§8.5) is the enforceable rule; a raw seq jump is not, on its own, proof
  of suppression.
- **Head-absence is fail-closed.** A v2 verifier presented a chain with NO signed head MUST report
  `completeness: none` / `suppression_detectable: false` (head-absence = unverifiable, not safe).
- **NOT closed by chaining alone.** The per-issuer head (§8.9) + a **rendezvous where two heads, or a
  head and a held receipt, can be compared** closes SOME of these; others remain open even WITH the
  head. CLOSED only for a verifier that rendezvouses ≥2 times under one `(signer, key_id)`:
  **tail-truncation** (§8.9.5 T2) and the head-emitted equivocation forks (§8.9.5 T3 two-head, T5
  head-vs-chain) — DISTINCT from the same-`seq`/same-`prev_receipt_hash` chain fork the receipt CHAIN
  already closes for any ≥2-receipt holder with no head. A verifier that rendezvouses exactly once —
  the common single-receipt marketplace case — gets NO truncation detection (§8.9.9); first-sight is
  baselined-pending-second-sighting, NOT closure. NOT closed even WITH the head: **parallel-chain
  audience-splitting** (requires a shared substrate two verifiers both read — §8.9.9),
  **rotation-as-amputation** (the per-`(signer, key_id)` pin cannot witness a tail abandoned under a
  prior `key_epoch` — §8.9.9), **splice-onto-phantom-predecessor** for the single-/zero-receipt holder
  (detection deferred to full-chain acquisition — §8.9.2), **single-receipt offline holder**
  (`equivocation_detectable` FALSE, identical to v1). Implementations MUST disclose every NOT-closed
  item as open, not paper over them. A head a verifier receives ONCE and never compares is inert
  (§8.9).
- **Equivocation-proof artifact (detection MUST feed action, §8.1):** on fork detection a verifier
  MUST emit a canonical, independently-re-verifiable `{signer_delegate_id, key_id, receipt_a
(bytes+sig), receipt_b (bytes+sig)}` where `a.prev_receipt_hash == b.prev_receipt_hash` (or
  `a.seq == b.seq`) AND `content(a) != content(b)`. Named consumer: key-directory revocation of the
  `key_id` + marketplace de-listing.
- Implementations MUST NOT advertise `action_id` as a replay-prevention nonce.

### 8.3 Layer-1 signing is type-enforced to the Layer-1 pre-image

The Layer-1 signing function MUST accept ONLY the Layer-1 pre-image type — never an arbitrary
JSON value, a string, or the Layer-2 audit-event shape `{event_type, event_payload,
signer_delegate_id}`. The audit-event shape MUST be unconstructable as a Layer-1 signing input at the
type level. The §5 type-name-distinctness requirement is a BLOCKING precondition for ANY Layer-1
conformance claim — not a parallel workstream.

### 8.4 Key model — authority precedence + rotation/revocation

- **Authority precedence:** for AUTHENTICITY the Layer-1 signature is authoritative everywhere; for
  COMPLETENESS the Layer-2 ledger is authoritative inside the residency boundary; neither overrides
  the other's domain. An implementation MUST NOT treat a valid Layer-1 signature as proof of ledger
  inclusion, nor a ledger entry as proof of external authenticity.
- **`key_id` lands at v2-core.** It is a signed bare-integer key-epoch in the v2 pre-image; an
  external verifier reads it from the receipt's own bytes and selects the correct public key. Rotation
  = a new `key_epoch` starts a FRESH chain at `seq 0` with a genesis sentinel bound to BOTH
  `signer_delegate_id` AND `key_epoch` (§8.7).
- **Revocation-honoring is SHOULD, contingent on a published key directory** (the same
  dead-dependency discipline as the head — `verify-resource-existence.md` MUST-3). Do NOT over-claim
  "verifies fully offline AND detects a revoked key": offline with no directory, the disposition is
  **"authenticity verified, revocation UNKNOWN"** (a degraded-trust signal the surface reports, NEVER
  "valid"). A compromised-then-rotated key can still sign a chain that verifies offline under its old
  public key until the verifier obtains revocation data. Revoking `key_id=N` flags "signed under a
  revoked key" DISTINCTLY from "chain broken" (the `seq`/`prev_receipt_hash` ordering still holds).

### 8.5 Verify over received bytes + the verifier chain-walk MUST-clauses

- **Signature path:** Layer-1 verification MUST verify the Ed25519 signature over the RECEIVED
  pre-image bytes, THEN assert those bytes are canonical per `canonical-signing-bytes.md` §1. MUST NOT
  parse-to-map-and-re-serialize (a re-serialize round-trip masks a non-canonical encoding).
- **Hash path (the §8.5 discipline extended to the chain link):** `prev_receipt_hash` MUST be computed
  as SHA-256 over the predecessor's ORIGINAL RECEIVED bytes AFTER they pass the canonicality assertion
  — reusing the single canonical-encoder output, NEVER a separate struct re-serialization (a generic
  `derive(Serialize)`-style struct serializer does NOT guarantee code-point key order and silently
  diverges from the sorted-keys encoder while signatures still verify; this surfaces only at the
  cross-implementation cross-verify of a 2+ receipt chain). A non-canonical predecessor MUST be
  rejected at its own canonicality gate, never laundered into a valid link via re-serialize.
- **Chain-walk MUSTs (the equivocation closure is vacuous without all four):**
  1. **Same-signer linkage** — assert `prior.signer_delegate_id == current.signer_delegate_id` AND the
     predecessor Ed25519-verified under the SAME public key. The hash committing to the prior signer
     id is necessary but NOT sufficient; the verifier MUST actively compare. (Closes cross-signer
     chain confusion — a HIGH attack.)
  2. **Seq-contiguity bound to the hash** — the predecessor that `prev_receipt_hash` resolves to MUST
     carry `seq == current.seq - 1`; a non-`(seq-1)` predecessor is a REJECT, not a soft "gap
     observed." (Closes skip-and-claim-reads-were-dropped.)
  3. **Version routing FIRST (§8.5-respecting):** try-each-shape-then-unique over the RECEIVED bytes —
     valid IFF EXACTLY ONE supported pre-image shape both canonically-validates AND signature-verifies;
     zero or two matches → REJECT. Never parse-to-decide-then-verify. A v2 receipt presented to a
     v1-only verifier → REJECT (unverifiable), never silently accepted as v1.
  4. **v1-XOR-v2 per signer** — once a `signer_delegate_id` emits any v2 receipt, a v1 receipt from
     that signer → `completeness: none` + possible-downgrade. (Closes dual-sign-across-versions, the
     v1-plane equivocation escape under coexistence — a HIGH attack.)

### 8.6 Boundary-integer interop is a HARD v2-core precondition

The integer domain is `[-(2^53-1), 2^53-1]` per `canonical-signing-bytes.md` §1.3 (authoritative).
The protocol spec §11 prose drift (`[-(2^63-1), 2^64-1]`) is a cross-implementation interop landmine.
At v2-core this is no longer merely an interop nit: `seq` makes the boundary
**security-load-bearing** — an oversized or wrapped `seq` manufactures a second genesis or
false-positives a fork. Reconciling the §11 prose to `2^53` MUST land BEFORE the v2 freeze. Verifier
MUST reject `seq == 2^53` (`9007199254740992`) as non-canonical before signature verification.

### 8.7 Genesis sentinel + chain-state durability + concurrency

- **Genesis sentinel.** The genesis receipt (`seq == 0`) carries `prev_receipt_hash` = lowercase-hex
  SHA-256 of the strict-UTF-8 canonical-JSON bytes of the domain-separated, key-epoch-bound object
  `{"delegate_connector_receipt_genesis_v2": signer_delegate_id, "key_epoch": N}` (two keys;
  code-point order: the domain key `0x64` BEFORE `key_epoch` `0x6b`; `key_epoch` a bare integer in the
  frozen domain). NOT 64 zeros (every signer's genesis would be identical → any receipt could be
  relabeled genesis to amputate predecessors), NOT omitted (a conditional key-set breaks canonical
  key-set invariance), NOT a bare `sha256(uuid)` (the domain separator + version tag prevent
  cross-protocol collision and version the construction). Binding `key_epoch` from day one avoids a
  silent sentinel-value change when rotation is first exercised. The domain string is a NORMATIVE
  constant in a domain-separation-tag registry; the sentinel pre-image + its SHA-256 ship as a frozen
  byte-exact ACCEPT fixture (V2-16).
- **Genesis biconditional (verifier-enforced, BOTH directions):** `seq == 0` IFF `prev_receipt_hash ==
recompute_sentinel(signer_delegate_id, key_epoch)`. A receipt at `seq > 0` carrying the sentinel
  MUST be rejected (claims to be both root and non-root); a `seq == 0` receipt whose `prev` ≠
  recompute MUST be rejected (forged/malformed genesis). Two distinct `seq == 0` receipts under one
  signer = a same-seq fork (closes audience-split-at-genesis for a ≥2 holder).
- **Chain-state durability.** `(max_seq, head_hash, key_epoch)` is the signer's REQUIRED durable
  state, persisted with the SAME durability guarantee as the signing key (lose-key == lose-chain).
  State-loss disposition is FAIL-CLOSED: refuse to sign until state is recovered, OR rotate to a fresh
  `key_epoch` starting a new chain at `seq 0`. NEVER re-issue a `seq` (re-issue manufactures a false
  same-seq fork the design's own detector flags as equivocation against the honest connector — a
  false-accusation DoS).
- **Concurrency.** `seq` assignment MUST be serialized through one monotonic counter per (connector
  instance, signer key) at sign time. Horizontal scaling shards by `key_epoch` (each replica/leader
  owns its own epoch + chain) so concurrency does not serialize all reads+writes on one counter — this
  is WHY `key_epoch` is in the pre-image at v2-core.

### 8.8 Cross-implementation byte-determinism gate (no hand-derived orderings, no phantom vectors)

- The v2 canonical key orderings MUST be confirmed by EMITTING through each conforming
  implementation's serializer AND this repo's reference encoder and diffing against a hand-authored
  fixture BEFORE freezing any v2 vector (`verify-resource-existence.md` MUST-2 — cite the serializer,
  not the hand-derivation). Pin the result as a normative byte vector; add a cross-implementation
  byte-equality test (an ordering transposition fails CI loudly, not as a phantom conformance break).
  A single transposed key pair silently breaks 100% of cross-implementation chain links (signatures
  verify, links do not — surfaces only at the 2-receipt cross-verify).
- NO v2 byte-exact vector with concrete `canonical_bytes`/signature/digest lands in any spec until the
  `canonical-signing-bytes.md` v2 re-freeze + reference-encoder generation complete and the fixtures
  are vendored with the generating commit-SHA + release-tag provenance (`spec-accuracy.md` Rule 1 — no
  phantom/hand-computed byte vectors). This spec specifies WHAT each vector pins; never concrete byte
  strings.

### 8.9 Per-issuer head publishing mechanism + the TOFU head-pin verifier state machine

This subsection is **authoritative** for the head mechanism. Head pre-images and fixtures (HV-1..HV-6)
are generated by the reference encoder per §8.8; this clause specifies WHAT each head vector pins,
never byte strings; treat the head as **greenfield until the `canonical-signing-bytes.md` v2 re-freeze
and reference-encoder generation complete** (`spec-accuracy.md` Rule 1).

The per-issuer head (§6) closes residuals chaining alone cannot — but ONLY via a **rendezvous where
two heads, or a head and a held receipt, can be compared**. This clause specifies the verifier-side
trust-on-first-use (TOFU) head-pin state machine that IS that rendezvous primitive. The state machine
is the **transport-independent, fully-specified half** of the head mechanism; it depends ONLY on
frozen-v2-core inputs (the receipt pre-image, the per-signer chain, the genesis sentinel of §8.7, the
§8.5 chain-walk MUSTs) plus the head's own canonical shape. It does NOT depend on the
transport-envelope binding (§8.10) and MAY be implemented against the standalone head artifact.

#### 8.9.1 The head's own signed canonical shape (MUST)

A signed head is the canonical object `{head_hash, key_id, max_seq, signer_delegate_id}`,
Ed25519-signed as a raw 64-byte detached signature over its own canonical pre-image bytes, under the
public key the `key_id` selects for that signer's receipt chain. It MUST conform to the frozen
canonical-JSON discipline (`canonical-signing-bytes.md` §1 — code-point key order, float ban, reject
NaN/Inf/lone-surrogate/duplicate-key/out-of-range-int). `max_seq` is a bare integer in the frozen
non-negative sub-range `[0, 2^53-1]`. All four values are INSIDE the signed pre-image; none are
envelope metadata. The head carries NO field asserting completeness, latest-ness, or inclusion that a
public-key-only verifier cannot recompute from its own bytes (§8.1).

#### 8.9.2 `head_hash` definition (MUST)

`head_hash` MUST be the 64-lowercase-hex SHA-256 over the EXACT canonical pre-image bytes of the
receipt at `max_seq` — computed identically to the `prev_receipt_hash` the `max_seq+1` receipt would
carry (§6, §8.5 hash-path). It commits to the **tip receipt's pre-image**, NOT to the signature and
NOT to a whole-chain digest. A whole-chain digest is REJECTED: it is not recomputable by a sparse
single-receipt holder (the §8.2 "seq 3, 7, 12" case) and would render the head externally-uncheckable
theatre for the common marketplace case (§8.1). Because the tip pre-image transitively commits to its
predecessor hash (recursively to genesis, §8.7), `head_hash` pins the entire chain spine up to
`max_seq` while remaining recomputable by any public-key-only holder of the single `max_seq` receipt.
**Splice/phantom-predecessor detection via `head_hash` is therefore DEFERRED to full-chain
acquisition** — a verifier who later obtains the full chain detects a spliced phantom predecessor via
the §8.7 genesis biconditional + the §8.5 seq-contiguity-bound-to-hash walk; the single-/zero-receipt
holder cannot detect it at first sight (the disclosed §8.2 single-receipt boundary, not a new gap).

#### 8.9.3 Pin granularity (MUST)

The verifier MUST pin per `(signer_delegate_id, key_id)`, NEVER per signer alone. Rotation = a new
`key_epoch` = a fresh chain at `seq 0` under a genesis sentinel bound to BOTH signer and `key_epoch`
(§8.4/§8.7); a post-rotation `seq 0` under a new `key_id` MUST NOT be evaluated as a regression against
the prior epoch's `max_seq`. Each pin persists: `pinned_max_seq`; `pinned_head_hash`; the head's
received bytes + signature (retained so the pin re-verifies and so a fork yields a portable proof); a
verifier-local `first_sight_at` (the verifier's own wall-clock — NOT the signer-controlled
`observed_at`, which is NOT a trust anchor per §8.2); a `provenance` enum (`embedded` | `standalone` |
`derived_from_receipt`); and `highest_held_receipt_seq` (tracked independently of the head so §8.9.6
composition runs). Pin state is the verifier's local trust memory; it is NOT synchronized to other
verifiers. Pin-state loss degrades the verifier to first-sight on next contact — safe-but-weaker,
never a false positive (TOFU's guarantee is monotonic-since-first-sight, not absolute).

#### 8.9.4 Precondition for every transition (MUST)

Before evaluating ANY transition, the verifier MUST (a) run version routing FIRST (§8.5 MUST #3) — a
head presented alongside a v1 receipt from a signer known to have emitted any v2 receipt is REJECTED
at the v1-XOR-v2 gate (§8.5 MUST #4) BEFORE the head is pinned; then (b) verify the head's Ed25519
signature over the RECEIVED pre-image bytes AND assert those bytes are canonical (§8.5 —
verify-over-received-bytes; MUST NOT parse-to-map-and-re-serialize). A head failing version routing,
signature, or canonicality MUST be DISCARDED with the pin UNCHANGED — it is an invalid artifact, NEVER
a regression or fork signal (this prevents an attacker injecting malformed heads to manufacture false
suppression/equivocation verdicts against an honest signer).

#### 8.9.5 Transitions on a valid new head H for an already-pinned (signer, key_id) (MUST)

- **(T1) `H.max_seq > pinned_max_seq`** — normal advance. IF the verifier holds receipts that
  contradict the advance (the old pinned tip is NOT an ancestor of the new tip), that is a
  rewrite-fork → `equivocation_detectable: true`, `completeness: none` + emit the rewrite-fork proof.
  ELSE accept: update `pinned_max_seq`, `pinned_head_hash`, bytes+sig; verdict `completeness:
bounded`.
- **(T2) `H.max_seq < pinned_max_seq`** — tail-truncation / rotation-as-amputation / stale-head replay
  signal. Verdict `suppression_detectable: true`, `completeness: none`. Retain BOTH the pinned head
  and `H` as a portable **truncation-proof pair**. The pin MUST NOT be regressed (accepting the lower
  value would let a signer walk the pin backward and re-baseline a truncated view).
- **(T3) `H.max_seq == pinned_max_seq` AND `H.head_hash != pinned_head_hash`** — head fork (the signer
  signed two tips at one sequence position). Verdict `equivocation_detectable: true`, `completeness:
none`. Emit the **two-head equivocation proof** `{signer_delegate_id, key_id, head_a(bytes+sig),
head_b(bytes+sig)}` where `a.max_seq == b.max_seq` AND `a.head_hash != b.head_hash` — self-contained,
  re-verifiable by anyone with the signer's public key, requires no held receipt (the strongest TOFU
  verdict).
- **(T4) same `max_seq` and same `head_hash`** — idempotent re-receipt; no state change.
- **(T5) held receipts chain-walk (§8.5) to a tip at `seq == H.max_seq` whose recomputed pre-image
  hash ≠ `H.head_hash`** — the head names a tip different from the held chain. Verdict
  `equivocation_detectable: true`, `completeness: none`. Emit the **head-vs-chain proof**
  `{head(bytes+sig), receipt_at_max_seq(bytes+sig)}` where `recompute(receipt.pre_image) !=
head.head_hash` AND `receipt.seq == head.max_seq`.

#### 8.9.6 Held-receipt-vs-pin composition (MUST)

For a held receipt at `seq == N` (signature-valid, canonical, chain-linked under `(signer, key_id)`)
and pin `max_seq == M`:

- **(C1) `N > M`** — held receipt newer than head → tail-truncation evidence; advance the pin to N
  ONLY IF the receipt chain-walks back through the pinned tip (its ancestor at M recomputes to
  `pinned_head_hash`), else rewrite-fork → `equivocation_detectable: true`, `completeness: none`.
  Retain the receipt as the truncation counter-witness.
- **(C2) `N == M`** — `H.head_hash` MUST equal `recompute(receipt.pre_image)`. Match → `completeness:
bounded` (head and receipt mutually verify entirely offline — the strongest non-fork positive);
  mismatch → T5 head-vs-chain fork.
- **(C3) `N < M`** — a sparse multi-counterparty gap (the intervening seqs went to other
  counterparties). It MUST NOT be flagged as suppression (cry-wolf forbidden, §8.2). Report
  `completeness: bounded` / `suppression_detectable: false`. Only a CONTIGUOUS-EXPECTING verifier
  treats the gap as a suppression signal, and only via the §8.5 hash-bound contiguity check (the
  predecessor `prev_receipt_hash` resolves to a receipt with `seq == current.seq - 1`), NEVER a raw seq
  jump.

#### 8.9.7 Fail-closed semantics (MUST)

- **First-sight (no prior pin).** The verifier pins the baseline and reports `completeness: bounded`,
  `equivocation_detectable` as a function of receipts-held (FALSE for the single-receipt holder — the
  common marketplace case, §8.2), `suppression_detectable: false`. A first-sight pin establishes a
  BASELINE and provides NO truncation detection: `suppression_detectable: false` at first sight means
  **UNVERIFIED, not safe**, and `completeness: bounded` at first sight MUST NOT be surfaced as
  completeness-confirmed — it is **completeness-baselined-pending-second-sighting** (the truthful claim
  is "nothing is hidden BELOW the single `max_seq` I was shown; I cannot know if that `max_seq` is
  itself truncated"). A first-sight pin MUST NOT be advertised as equivocation-protected.
- **Head-absence.** A v2 verifier presented a chain or a single receipt with NO signed head, and no
  prior pin for `(signer, key_id)`, MUST report `completeness: none` / `suppression_detectable: false`
  (unverifiable, NOT safe, §8.2). `completeness: none` is a degraded-trust signal the surface reports;
  it does NOT BLOCK a consumer that elects to proceed on an authenticity-valid receipt, and it does NOT
  authorize the producer to omit the head.
- **`derived_from_receipt` provenance.** A pseudo-pin synthesized from the highest held receipt with NO
  head ever received MAY be recorded for the verifier's own forward bookkeeping but MUST NEVER report
  `suppression_detectable: true` (a self-derived pin has no signer attestation of completeness and
  cannot witness truncation).
- **Head-only / zero-receipt holder.** A verifier holding a head but NO receipt under `(signer,
key_id)` MUST report `completeness: bounded` with an explicit note that `head_hash` is
  **UNVERIFIED-against-a-held-tip**: the head's signed `max_seq` authenticity is checkable, but its
  `head_hash` binding to a real chain tip is NOT until a receipt at `max_seq` is obtained. This holder
  MUST NOT be advertised as having any tip-binding assurance — only signed-`max_seq` authenticity (the
  §8.1 boundary, symmetric with the single-receipt carve-out).
- **Invalid head / state-loss.** An invalid head (bad sig / non-canonical / version-routing reject) is
  discarded with the pin unchanged. Verifier-side pin-state loss degrades to first-sight —
  safe-but-weaker, never a false positive.

#### 8.9.8 Verdict surface (MUST — extends §8.2)

The verifier MUST return, per `(signer_delegate_id, key_id)`:

- `equivocation_detectable: bool` — TRUE only when the verifier holds portable fork proof (T3
  two-head, T5 head-vs-chain, T1/C1 rewrite-fork, or a receipt-level §8.2 fork). FALSE for the
  single-receipt / single-head first-sight holder (identical to v1, §8.2).
- `completeness: none | bounded` — `bounded` when a pin exists AND the latest sighting is
  monotonic-consistent with it; `none` on head-absence, on any detected fork, and on confirmed
  truncation (T2). **NEVER `full`** — TOFU proves completeness-since-first-sight, not absolute
  completeness.
- `suppression_detectable: bool` — TRUE only on confirmed tail-truncation (T2 pin-regression, C1
  held-receipt-newer-than-head with established contiguity) for a contiguous-expecting verifier. FALSE
  for sparse holdings (C3), first-sight, head-absence, and `derived_from_receipt`.
- `proof_artifact: optional` — the canonical, independently re-verifiable equivocation / truncation /
  head-vs-chain proof when one was emitted. **Named consumer:** key-directory revocation of the
  `key_id` + marketplace de-listing. A lone truncation-proof pair (T2) is portable EVIDENCE, not an
  automatic revocation trigger: because a NETWORK adversary (not the signer) could replay a
  genuinely-old-but-validly-signed head to manufacture a false `suppression_detectable: true` against
  an honest signer, the revocation consumer MUST corroborate before acting and SHOULD rate-limit /
  require quorum on revocation triggers to resist replay-driven false-accusation (the same
  false-accusation-DoS class §8.7 warns about for seq-reuse).

#### 8.9.9 Open residuals the head + TOFU do NOT close (MUST disclose)

Implementations MUST disclose each of the following as open; MUST NOT advertise any as closed; and
MUST NOT soften any of these MUST-disclose clauses to SHOULD in a future edit.

- **Parallel-chain audience-splitting is NOT closed.** A signer running two divergent chains under one
  `(signer, key_id)` — chain-A to verifier V1, chain-B to V2 — presents each a self-consistent,
  monotonic, fork-free view; no transition (T1..T5) fires because neither verifier ever sees the
  other's head. T3 (the catch) requires ONE verifier to hold BOTH same-`max_seq` heads, which happens
  only if V1 and V2 COMPARE pins — and TOFU provides no inter-verifier channel. **First-sight pin
  poisoning** is a special case: poisoning a verifier that never sees the honest head is
  audience-splitting under another name (a verifier that LATER sees the honest head at the same
  `max_seq` catches it via T3). Closing audience-splitting REQUIRES a shared rendezvous/gossip
  substrate (verifiers exchanging pinned heads, or a common log both read), which the bounded-trust
  model would have to justify separately.
- **Rotation-as-amputation is NOT closed.** Per-`(signer, key_id)` pin granularity closes
  post-rotation false-flagging (§8.9.3) but the SAME granularity lets a signer rotate `key_epoch` to
  ABANDON an inconvenient tail: a signer at `seq 20` under `key_epoch N` rotates to `N+1`, hands a
  verifier a head at `max_seq 2` under the new `key_id`, and the verifier records a clean first-sight
  pin — no transition fires, the `N` tail is silently abandoned, and rotation is indistinguishable
  from honest key-compromise rotation at the public-key-only surface. Same root cause as
  audience-splitting: TOFU is per-verifier, per-`(signer, key_id)`, and cannot witness state it never
  received. The only structural closure is a cross-epoch continuity link (the `key_epoch N+1` genesis
  sentinel optionally committing to `(max_seq, head_hash)` of epoch N), which requires the key
  directory (§8.4, SHOULD/dead-dependency) to publish per-epoch heads a verifier can chain-walk across
  epochs — new shared infrastructure the bounded-trust model must justify. Until then, honest
  disclosure is the only correct disposition.
- **Single-rendezvous tail-truncation is NOT closed.** A verifier that rendezvouses exactly once (the
  common single-receipt marketplace default) gets NO truncation detection — T2 requires a second
  sighting. The §8.9.7 first-sight disclosure (`bounded` = baselined-pending-second-sighting) is the
  honest surfacing of this irreducible TOFU limit.

#### 8.9.10 Audience scoping, metadata privacy, and cross-artifact non-correlation (MUST)

- **`max_seq` is competitively-sensitive metadata in cleartext.** A single signed head reveals the
  signer's cumulative receipt count; two heads over time reveal rate/growth — the exact class the
  residency-internal witness anchor's salted digest (§4) salts away. The head MUST be scoped to a
  counterparty/auditor AUDIENCE and MUST NOT be broadcast.
- **Scope-to-audience is a PRODUCER discipline with NO cryptographic enforcement and NO
  leak-attribution, and does NOT survive cross-audience collusion.** The head object is bit-identical
  across audiences (no per-audience nonce/tag/recipient binding); a head leaked to a non-audience
  party is cryptographically indistinguishable from a legitimately-received one and cannot be
  attributed to the leaker. Two audiences who each receive a head MAY collude and union their
  `max_seq` sightings to reconstruct the full count/rate timeline. Implementations MUST disclose that
  scope-to-audience bounds metadata exposure to the UNION of a signer's head-audiences, NOT
  per-audience. A per-recipient binding (which would enable leak-attribution) is NOT adopted, because a
  per-recipient tag is itself a correlation/fingerprinting surface AND would change `head_hash` per
  recipient, breaking the single-recomputable-tip property (§8.9.2); leaked-head non-attribution is
  accepted as an irreducible residual of a bearer head.
- **Cross-artifact non-correlation (MUST).** Where an implementation also maintains a
  residency-internal witness anchor (§4), the external head's signed pre-image and the residency
  anchor's pre-image MUST be **domain-separated** such that knowing the external `(max_seq, head_hash)`
  confers **ZERO confirmation advantage** against the residency digest. The residency anchor MUST NOT
  be a digest over any tuple a field of which is externally observable in cleartext, and the external
  head MUST NOT be derivable as a substring/projection of the residency pre-image. An implementation
  MUST NOT claim the external head preserves the residency anchor's non-invertibility until that
  non-correlation property is independently established for that implementation; until then it MUST
  disclose the cross-artifact confirmation surface as an OPEN residual.
- **Verifier obligation carries NO leak amplification — except on the proof path.** The §8.9
  verifier-side obligation operates only on heads the audience ALREADY received (no re-publication, no
  broadcast) → zero new leak on the honest-signer path. BUT when a fork/truncation fires, the emitted
  `proof_artifact` (§8.9.8) embeds head bytes (hence `max_seq`) and its named consumer (key-directory
  revocation + marketplace de-listing) is a broadcast surface beyond the original scoped audience.
  This is acceptable — a proven equivocator forfeits metadata privacy — but MUST be stated, not glossed
  by a blanket "leaks no metadata" claim: the "never broadcast" invariant is suspended exactly when
  misconduct is proven.
- **MUST NOT (future-substrate fence).** Any future rendezvous/gossip substrate proposed to close
  audience-splitting (§8.9.9) MUST NOT broadcast `max_seq` in cleartext beyond the original scoped
  audience; it MUST preserve the audience-scoping invariant and, if it crosses into residency, the
  residency anchor's salt-non-invertibility invariant. A gossip substrate that broadcasts heads to
  close audience-splitting trades the §4 metadata invariant for suppression-detection — that trade
  requires explicit bounded-trust-model justification, never a default.

#### 8.9.11 Head conformance vectors (WHAT each pins; bytes generated by the reference encoder per §8.8)

A DISJOINT addition to the V2-1..V2-16 receipt set, subject to the §8.8 emit-and-diff gate BEFORE any
byte freeze:

- **HV-1** genesis-head — head at `max_seq == 0` (pins the head shape against a genesis receipt;
  `head_hash` == SHA-256 of the V2-1 genesis-write pre-image).
- **HV-2** head-at-`max_seq == N` — head over a chain-of-N tip (pins `head_hash` == SHA-256 of the tip
  receipt's pre-image at N).
- **HV-3** `head_hash`-recompute-matches-receipt — the C2/T5 mechanic: a held receipt at `max_seq` and
  the head mutually verify (`recompute(receipt.pre_image) == head.head_hash`); a one-byte tip mutation
  flips the match.
- **HV-4** head key-ordering — pins the exact code-point byte positions of `{head_hash, key_id,
max_seq, signer_delegate_id}` (the silent-transposition guard, the §8.8 emit-and-diff target;
  replaces any hand-derived ordering).
- **HV-5** two-head equivocation proof (T3) — two heads sharing one `(signer, key_id, max_seq)` with
  different `head_hash` → the portable proof artifact; pins the proof's canonical shape.
- **HV-6** truncation-proof pair (T2) — two validly-signed heads under one `(signer, key_id)` with
  `H_new.max_seq < pinned_max_seq` → the truncation-proof pair shape.

Plus the head's canonicality REJECT re-run (float / NaN / non-string key / lone surrogate / duplicate
key / out-of-range `max_seq` at `2^53`) against the head canonicalizer. NO concrete head
byte/sig/digest string lands in any spec until the `canonical-signing-bytes.md` v2 re-freeze +
reference-encoder generation complete and the fixtures are vendored with the generating commit-SHA +
release-tag provenance.

### 8.10 Transport-envelope binding + SHOULD→MUST graduation (dependency boundary — graduation is path-scoped)

The head MAY be published two ways: (i) **embedded** as an OPTIONAL SIGNED field riding the transport
envelope (`provenance: embedded`); or (ii) **standalone**, as a self-contained signed artifact
(`provenance: standalone`). The standalone form's SHAPE depends ONLY on the frozen canonical core and
the §8.9 state machine; it is NOT hostage to the transport envelope, whose shape is owned externally
and is DRAFT.

**Graduation rule (MUST — only the fully-specified path graduates).** A SHOULD→MUST graduation is
earned ONLY for the path whose mechanism is FULLY specified. Split cleanly:

- The **§8.9 verifier-side pin/compare obligation** graduates to MUST NOW. It consumes only heads its
  audience already received — no channel dependency, no metadata-leak amplification.
- The **PRODUCER publish obligation stays SHOULD for BOTH paths.** A standalone-artifact SHAPE is NOT
  a publishing MECHANISM: §8.9 specifies the standalone artifact's signed shape but NOT its wire form /
  delivery channel / audience-scoping transport. Graduating the producer publish to MUST against an
  unspecified channel re-opens the dead-dependency anti-pattern §4/§8.1 forbid — identically for the
  standalone path AND the envelope path. The standalone producer-publish stays SHOULD until a concrete
  audience-scoped delivery channel is specified; the envelope-embedded producer-publish stays SHOULD
  until the transport envelope is frozen.

Until the producer publish graduates, head-withholding remains a deniable producer move (a signer can
withhold the head from one counterparty and claim none was published); a future
producer-MUST-publish-to-scoped-audience is what removes withholding as a deniable option — and is
gated on BOTH a specified channel AND accepting that a MUST-publish compels the §8.9.10
cleartext-`max_seq` leak, which the metadata-leak-honesty constraint forbids compelling for
count-sensitive connectors. The producer end-state is therefore **SHOULD-with-strong-default, scoped
narrowly**, NOT a blanket MUST-publish.

## 9. Change control

This spec is DRAFT until maintainer approval, then frozen. Any change to the two-layer model, the
v2-core field set, the head shape, the §8 safety clauses, or the conformance discipline requires a
documented revision. The v2-core `protocol_version` 1→2 increment is coordinated with the
`canonical-signing-bytes.md` v2 re-freeze (§6 upstream sequencing); v1 and v2 coexist per §6.
