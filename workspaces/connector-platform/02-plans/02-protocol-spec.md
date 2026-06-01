# Delegate Connector Plugin Protocol — Normative Specification (DRAFT)

**Status:** DRAFT — the normative contract a SECOND implementation (e.g. the Rust
`dc-enterprise` tier) conforms to. Intended to be published **CC BY 4.0** as a Foundation
standard once stabilized.
**Conformance language:** MUST / SHOULD / MAY per RFC 2119.
**Protocol version:** `1` (the single monotonic integer §8 negotiates on).
**Companion:** the architecture + rationale live in `01-architecture.md`; this is the wire
contract. The crypto core (§1–§3) is **already shipped** and pinned in
`specs/canonical-signing-bytes.md` — those sections reference it, they do not restate it.

Each section is tagged **[IMPLEMENTED]** (pins behavior verifiable on `main` today) or
**[DRAFT]** (defines a contract not yet built — tracked in this workspace; migrates to `specs/`
when implemented). **Conformance is tri-part:** behavioral outcomes AND byte-level receipt
interop AND schema validation. A green behavioral run is **NOT** sufficient for interop.

---

## 0. Front matter, conformance, versioning [IMPLEMENTED for §1–3, DRAFT elsewhere]

- License: CC BY 4.0, language-neutral. No section may say "whatever the Python code does" — the
  rule is normative, the Python call is one conforming encoder.
- `protocol_version` is a single monotonic integer. The current value is `1`. §8 governs
  host↔connector negotiation on it. Any breaking change to §1–§3 (signing) or §5–§6 (manifest/
  registry schemas) requires a `protocol_version` bump + coordinated migration.
- A conforming implementation MUST pass all three gates of §10.

## 1. Canonical JSON encoding [IMPLEMENTED]

Normatively defined in **`specs/canonical-signing-bytes.md` §1** (UTF-8; code-point key sort at
every level; separators `,`/`:` no whitespace; non-ASCII literal; integers bare; floats
constrained-out as a cross-language hazard). All signed artifacts in this spec derive their
bytes from that rule. Implementers MUST read that file first.

## 2. Canonical signing bytes — receipts [IMPLEMENTED]

Normatively defined in **`specs/canonical-signing-bytes.md` §2–§3**:

- `SignedActionEnvelope` pre-image = `{action_id, observed_at, payload, signer_delegate_id}`.
- `AttestedReadReceipt` pre-image = `{attester_delegate_id, manifest, observed_at, read_id}`.
- `observed_at` = RFC 3339, `+00:00` offset (not `Z`), microseconds-or-omitted-when-zero.
- This connector-receipt layer is **distinct** from the SDK dispatch audit-event pre-image
  `{event_type, event_payload, signer_delegate_id}` — do not conflate.
  Three reproducible (input → bytes → signature under a fixed key) vectors are pinned there.

## 3. Signature wire form + key/fingerprint [IMPLEMENTED]

Normatively defined in **`specs/canonical-signing-bytes.md` §4**: receipt signatures are RAW
64-byte Ed25519 (hex-rendered 128 chars in text transports); the audit-event signature is
128-char hex over its different pre-image. Public key = raw 32-byte (hex). Signing-key
fingerprint = lowercase-hex SHA-256 of the raw 32-byte public key.

## 4. Capability grammar + enforcement semantics [IMPLEMENTED semantics / DRAFT lattice]

- **Token syntax:** `^[a-z0-9]+(\.[a-z0-9]+)+$` — a `<resource>.<action>` dotted form
  (e.g. `email.send`, `slack.post`, `http.read`, `http.write`). Case-sensitive (lowercase).
  Wildcards are **NOT** permitted in v1.
- **Vocabulary:** v1 ships a CLOSED registry of tokens (the four reference connectors' tokens +
  the `http.{read,write}` set for declarative connectors). New tokens are added by spec
  revision, not by contributors inventing strings.
- **Enforcement semantics TODAY [IMPLEMENTED]:** `requires_capabilities` is a frozenset checked
  (a) at bind time as a subset of the role scope (`dispatch.py:1434`) AND (b) re-checked at
  dispatch time (`dispatch.py:1606`, the monotonicity runtime re-check). It is **string-equality
  membership only** — it is **NOT** enforced against network egress, filesystem, or syscalls.
- **[DRAFT] Phase-3 lattice (owner-gated — §11):** a capability MUST bind to a
  `(method-set, host-class)` enforced by the runtime — `http.read ⇒ {GET, HEAD}` only (**not**
  OPTIONS — CORS-preflight recon/SSRF surface) **AND `http.read` MUST forbid request bodies**
  (method-set alone is not side-effect-free); `http.write ⇒ {POST, PUT, PATCH, DELETE}`.
  Until that lands, implementations MUST NOT claim capability-as-egress-boundary. A Rust impl
  MUST implement the same string-membership semantics as today and MUST NOT invent a phantom
  enforcement the Python side lacks.

## 5. Declarative manifest schema (the EASY-tier interop artifact) [DRAFT]

A versioned normative JSON Schema with a `manifest_schema_version` field (§5.7). The interpreter
(`GenericHTTPConnector`) is the only code; the manifest is data. Required pins:

1. **Auth schemes** — CLOSED enum: `bearer`, `basic`, `api-key-header`,
   `oauth2-client-credentials` (extensible by revision). Credential **placement is owned by the
   host/broker**, NOT the manifest: the manifest names the scheme + (for `api-key-header`) a
   header name from a host allowlist; it MUST NOT specify query-string credential placement or
   attacker-suggestible field names. The probe-emitted scheme is a _suggestion_ the host validates.
2. **Pagination** — CLOSED enum: `cursor`, `offset`, `link-header`, `none`, each with its field
   bindings AND **hard bounds** (max pages, max total bytes, max wall-clock) the interpreter enforces.
3. **Response extraction** — JSONPath restricted to **RFC 9535** with NO script/filter/custom
   functions.
4. **`allowed_hosts`** — the egress ceiling. Matching semantics: HTTPS-only; resolve the
   hostname host-side and validate the **resolved IP** (reject RFC1918/link-local/loopback/CGNAT/
   metadata-IP `169.254.169.254`); pin that IP for the connection (defeat DNS-rebinding TOCTOU);
   `follow_redirects=false` and strip `Authorization` on any cross-origin redirect; reject
   IP-literal and non-DNS hosts; `trust_env=false`.
5. **Expression/template DSL** — a CLOSED, non-Turing, side-effect-free grammar: literal
   interpolation of host-provided values only; NO attribute access, NO callable invocation, NO
   `eval`/`format`/jinja2. Hard CPU/recursion/output-size bounds. ("No executable code" is only
   true if the evaluator is provably sandboxed — see the CVE-2025-68613 expression-injection class.)
6. **`requires_capabilities`** — per §4.
7. **`manifest_schema_version`** + interpreter-side version negotiation/refusal mirroring §8;
   SemVer + `upgrade_deadline` deprecation (the Airbyte `breakingChanges`/`upgradeDeadline` pattern).
8. The manifest's own signature derives from §1; a complete worked example + its exact signing
   bytes MUST accompany the schema.

## 6. Registry schema (`registry.json` — the cross-impl trust authority) [DRAFT]

Versioned normative JSON Schema with `schema_version`. Per-entry keyed on `connector_kind`:

- **`content_hash`** — algorithm SHA-256; the EXACT covered byte range pinned per artifact type:
  for declarative = SHA-256 over the canonicalized manifest; for code = SHA-256 over the wheel
  RECORD-hash PLUS a full transitive-dependency lockfile hash.
- **`signing_key_fingerprint`** — per §3 (`specs/canonical-signing-bytes.md §4.1`).
- **`provenance_tier`** — CLOSED literal set: `declarative-community`, `verified-code`,
  `official`. (These are _protocol_ tiers; commercial "edition" tiers are a separate axis — §11.)
- **`connector_kind` namespacing + collision rule** — v1 decision REQUIRED (see §11 open
  items): globally-unique vs publisher-namespaced (`owner/kind`, Terraform model). Collision
  (same `kind` + different `content_hash`/`fingerprint`) MUST **fail closed** with both
  distributions surfaced; two implementations MUST reach the **identical** verdict. The four
  official kinds (`email`/`slack`/`telegram`/`whatsapp`) are reserved.
- The registry's OWN signature derives from §1 (threshold N-of-M signing + append-only
  transparency log RECOMMENDED). A worked `registry.json` example MUST accompany the schema.
- **Revocation:** a signed, monotonically-versioned denylist (`connector_id` + version +
  fingerprint) with a hard fetch ceiling and **fail-closed on stale** (refuse code-connector
  load on a stale denylist; do NOT serve-from-cache). Revocation is a **load-time** check.

## 7. Discovery + instantiation contract (language-neutral) [DRAFT]

Python uses `importlib.metadata` entry-points (group `delegate.connectors`); **Rust has no
importlib**, so the protocol pins a language-neutral descriptor BOTH loaders read:

- **`delegate-connector.toml`** (in the distribution) declares: `kind`, `artifact_type`
  (`declarative` | `code`), `entry_symbol`, `host_protocol` range (§8), `requires_capabilities`,
  `requires_credentials`.
- For **code** connectors the `entry_symbol` MUST resolve to a **zero-arg factory `() ->
Connector`** (or a class with a pinned constructor-injection protocol). The host passes the
  broker transport handle(s) and the host-side sign handle into the connector via a pinned
  **constructor-injection signature** (§ broker, below) so credentials + signer reach the
  connector identically on both implementations.
- **Load-path gate:** `.load()` == arbitrary-code-execution (it imports the module). Loading a
  code connector MUST be **atomic hash-and-load** (verify the content hash on the in-memory
  artifact bytes, then load — never stat-then-load, a TOCTOU window), MUST refuse if >1
  distribution claims a `kind` (shadowing) unless exactly one is allowlisted, and MUST enforce
  the transitive-dep lockfile hash. Discovery (enumeration) is unrestricted; **loading** is gated.

## 8. Host-protocol negotiation [DRAFT]

- `host_protocol` is an integer (or a declared inclusive range `[min,max]`) the connector
  declares; the host advertises its supported set `H`. **Load iff `S ∩ H ≠ ∅`; bind at
  `max(S ∩ H)`; else REFUSE with a loud load-time error** of a pinned error kind (§9). The error
  message MUST name the connector kind, the connector's declared range, and the host's range.
- Relationship to the SDK `kailash>=2.28,<3` pin: these are **two different axes** — the SDK
  version range constrains the _Python implementation's_ dependency, while `host_protocol`
  constrains the _cross-impl wire contract_. A Rust host has no `kailash` dep but MUST honor the
  same `host_protocol` integer. State both; never collapse them.

## 9. Error taxonomy (cross-boundary, portable) [IMPLEMENTED kinds / DRAFT mapping]

Every cross-boundary failure MUST surface a **stable language-neutral `kind` string**, not a
language-native class name, so the conformance driver asserts on `kind`. v1 mapping (from the
shipped SDK exception classes):

| portable `kind`               | shipped class                                         |
| ----------------------------- | ----------------------------------------------------- |
| `auth.rejected`               | `ConnectorAuthenticationError` (fail-closed `Reject`) |
| `envelope.widening`           | `EnvelopeWideningError`                               |
| `cascade.scope_expansion`     | `CascadeScopeExpansionError`                          |
| `cascade.tenant_violation`    | `CascadeTenantViolationError`                         |
| `dispatch.cascade_violation`  | `DispatchCascadeViolationError`                       |
| `dispatch.envelope_violation` | `DispatchEnvelopeViolationError`                      |
| `composition.r2`              | `R2CompositionError`                                  |
| `runtime.phase`               | `RuntimePhaseError`                                   |
| `runtime.composition`         | `RuntimeCompositionError`                             |
| `runtime.posture_blocked`     | `RuntimePostureBlockedError`                          |
| `protocol.unsupported`        | host-protocol negotiation refusal (§8)                |

`BehavioralOutcome.Reject` and `EscalateToHuman` MUST map to pinned portable kinds. Both
implementations surface the portable `kind`; the conformance driver asserts on it.

## 10. Conformance — behavioral AND byte-interop AND schema [IMPLEMENTED + DRAFT]

Three distinct, all-required gates:

1. **Behavioral** [IMPLEMENTED]: the canonical given→expected outcome vectors (DV-3/5/7/9/10,
   from the vendored `canonical.json` — see the conformance-vector provenance note in
   `specs/conformance.md`) driven through the spine; observed outcome == expected.
2. **Byte-level receipt interop** [IMPLEMENTED contract, fixtures to commit]: the §6 vectors of
   `specs/canonical-signing-bytes.md` reproduced byte-for-byte, PLUS a cross-verification matrix
   (Python verifies Rust-signed receipts and vice versa). Fixtures live at
   `tests/fixtures/receipt-interop/`, version-pinned, consumed by every implementation.
3. **Security/abuse vectors** [DRAFT]: receipt-forge-without-egress refusal; credential-handle
   non-introspectability; capability→verb refusal; SSRF (rebinding/metadata-IP/redirect/
   IP-literal); expression-injection (CVE-2025-68613 class); load-gate (TOCTOU/kind-shadow/
   dep-confusion); host-side revocation enforced at dispatch.

---

## 11. Freeze status (resolved 2026-06-01 via adversarial hardening — `wf_faa33b0e-65b`)

The 5 open items split into **frozen now** (the receipt-signing core — what the Rust team needs
first) and **owner-gated** (wire contracts for subsystems that don't exist yet).

**✅ FROZEN v1 — `specs/canonical-signing-bytes.md`** (the crypto core; the deliverable to send the
Rust team now):

- **Item 2 (floats):** FORBIDDEN in signed pre-images; `NaN`/`Infinity` rejected (`allow_nan=False`).
  Verified: no connector receipt payload uses floats.
- **Item 3 (timestamp):** fixed-width 6-digit microseconds always (`+00:00`, not `Z`) — kills the
  omit-when-zero branch. Vectors regenerated (A/C changed, B identical) + verified.
- **9 NEW canonical-JSON edge-case pins** the hardening surfaced (each empirically probed): key
  ordering = code-point/UTF-8 byte order (**NOT** RFC 8785/JCS — diverges on astral keys);
  integer domain `[-(2^63-1), 2^64-1]` (serde_json silently floats `≥2^64`); object keys
  MUST be strings; exact string-escape table; lone-surrogate reject; duplicate-key reject
  (verifier); no Unicode normalization; container/literal byte forms. Locked by vectors A–E + a
  reject suite.

**⏳ OWNER-GATED — cannot freeze (no implementable anchor in this repo; need decisions + the
registry/protocol-subsystem design first):**

- **Item 1 (`connector_kind` → `owner/kind`):** direction is right (always `owner/kind` on the
  wire; bare names forbidden in any signed/trust surface), but `owner` derivation has no canonical
  definition. **Owner must decide:** is `owner` the signing-key fingerprint or an OIDC/PEP-740
  trusted-publisher anchor? (Recommended: a stable publisher anchor + reserved literal `delegate`
  for Foundation connectors, with the per-version fingerprint as a _separate_ field — the draft's
  "fingerprint-OR-OIDC" forks identity on key rotation.) **Prerequisite:** the registry/protocol
  spec that owns `owner` + the registry keyed on `owner/kind` does not exist yet.
- **Item 4 (capability→egress lattice):** owner-gated whether it lands in this repo at all (only
  bare `channel.action` frozensets exist — no interpreter/sandbox/`host_class`). Two corrections
  locked regardless of where it lands: `http.read` ⇒ `{GET, HEAD}` only (**drop OPTIONS** — CORS
  preflight recon/SSRF surface) AND `http.read` MUST forbid request **bodies** (method-set alone
  isn't side-effect-free). MUST NOT be written as Phase-1/Phase-3 split-state prose in `specs/`
  (`spec-accuracy.md`).
- **Item 5 (registry signing):** the signature-list/threshold-T design is sound and
  forward-compatible, but two clauses are unimplementable-as-written: (a) **self-referential
  signing** — sign over the canonical bytes **with the `signatures` field REMOVED entirely** (not
  emptied), so the pre-image is identical for 0 or N signatures; (b) **transparency log** —
  "MUST-publish/SHOULD-verify against an unprovisioned log" is the dead-dependency anti-pattern.
  **Owner must decide:** downgrade publish to SHOULD until a log is provisioned, OR commit to a
  concrete log (Sigstore Rekor / a Foundation RFC-6962 Merkle log) + pinned inclusion-proof format
  - client-verify-MUST-when-present. **Prerequisite:** same missing registry/protocol spec as Item 1.

**Owner decisions still open** (none block sending the frozen crypto core): the Item-1 `owner`-axis
form; whether Item 4 lands here; the Item-5 transparency-log option (A vs B); JS-interop integer
scope (`2^64-1` vs `2^53-1`); and authorizing the registry/protocol-subsystem spec (gates Items 1
& 5).

## 12. OSS ↔ enterprise alignment (governance)

This protocol is an **open Foundation standard (CC BY 4.0)**. The Foundation publishes a
**full-featured Apache-2.0 Python implementation** + reference hub — **not** a teaser or
community-edition funnel. **`dc-enterprise` is an INDEPENDENT Rust implementation of this same
protocol**; it conforms to this spec and the §10 cross-language vectors. Shared protocol,
divergent implementations. Per `rules/terrene-naming.md` + `independence.md`: `dc-enterprise` is
NOT a Foundation artifact, MUST NOT be cited as "the reference," and the relationship MUST NOT be
described as donated/licensed-from/derived-from. Private registries, premium connector catalogs,
SLA hosting, the sandbox-as-a-service, and metering are **commercial offerings any entity
(including dc-enterprise) may build on the open protocol** — they are not Foundation tiers.
