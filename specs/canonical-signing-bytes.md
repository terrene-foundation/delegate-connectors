# Spec — Canonical Signing Bytes & Receipt Wire Form (NORMATIVE)

**Status:** ACTIVE — describes the **shipped** receipt-signing behavior of every connector in
this repo (verifiable against `connectors/*/src/.../connector.py` on `main`).
**Audience:** any implementation that must produce or verify Delegate connector receipts
**byte-for-byte interoperably** — including the Rust `dc-enterprise` tier.
**Conformance language:** MUST / SHOULD / MAY per RFC 2119.

This is the single load-bearing cross-implementation contract. A `SignedActionEnvelope` or
`AttestedReadReceipt` produced by one implementation **MUST** verify under another's verifier.
One field-order, encoding, or timestamp-format difference breaks **100%** of cross-impl
verifications, silently (the receipt still "looks signed"). There is **zero** tolerance for
ambiguity here.

> **Scope note.** This file pins the _connector-receipt_ signing layer (`SignedActionEnvelope`,
> `AttestedReadReceipt`). It is **distinct** from the SDK _dispatch audit-event_ signing layer
> (`kailash.delegate.audit.content_signing_bytes`, pre-image `{event_type, event_payload,
signer_delegate_id}`, signature rendered as 128-char hex). The two are **different pre-images
> and different wire forms** — see §4. Do not conflate them.

---

## 1. Canonical JSON encoding (the shared primitive)

Every signed byte string in this spec is the UTF-8 encoding of a **canonical JSON** document.
Canonical JSON is defined **language-neutrally** as:

1. **Object keys MUST be sorted** ascending by Unicode code point, **at every nesting level**.
2. **No insignificant whitespace.** The item separator is `,` (U+002C) and the key/value
   separator is `:` (U+003A), with **no** spaces or newlines anywhere.
3. **Non-ASCII characters MUST be emitted literally** as UTF-8 (NOT `\uXXXX`-escaped). E.g.
   `é` is the two bytes `0xC3 0xA9`, not `é`.
4. **Booleans** are lowercase `true` / `false`; **null** is `null`.
5. **Integers** are rendered as bare decimal digits with no decimal point, no leading `+`, no
   leading zeros (except `0` itself), no exponent.
6. **Strings** use standard JSON escaping for the mandatory escapes only (`"`, `\`, and
   control chars U+0000–U+001F); all other characters (including non-ASCII) are literal.
7. **Arrays** preserve element order; each element is canonicalized recursively by this rule.
8. **NaN / Infinity / -0.0 MUST be rejected** (not valid JSON per RFC 8259).

> **Reference implementation (informative):** Python `json.dumps(obj, sort_keys=True,
separators=(",",":"), ensure_ascii=False)` (`kailash.trust._json.canonical_json_dumps`).
> The rule above is normative; the Python call is one conforming encoder.

### 1.1 Floating-point numbers — HAZARD (constrained)

Floating-point number canonicalization diverges across languages (Python `repr`-based vs Rust
`ryu` vs Go `strconv`) and is **NOT** pinned by this version of the spec. Therefore: signed
payloads/manifests **SHOULD NOT** contain JSON floating-point numbers. Decimal quantities
**MUST** be carried as strings (e.g. `"amount": "10.50"`) or integers (minor units). An
implementation that emits a float into a signed pre-image is **non-conforming** until a future
revision pins float rendering. (Connector receipt payloads are connector-controlled, so this is
enforceable at the connector boundary.)

---

## 2. Pre-images (the exact covered fields)

### 2.1 `SignedActionEnvelope` (a `write`)

The signed bytes are the UTF-8 canonical-JSON encoding of **exactly** this object:

```
{
  "action_id":          <string>,   // UUID string form, lowercase, hyphenated
  "observed_at":        <string>,   // §3 timestamp
  "payload":            <object>,   // the action result, canonicalized recursively (§1)
  "signer_delegate_id": <string>    // UUID string form
}
```

Covered field set = `{action_id, observed_at, payload, signer_delegate_id}` — **no more, no
less.** (Key order in the _encoded_ bytes is the §1 sorted order, shown above.) Source:
`build_action_signing_bytes` (`connectors/email/src/.../connector.py:115`).

### 2.2 `AttestedReadReceipt` (a `read`)

```
{
  "attester_delegate_id": <string>,  // UUID string form
  "manifest":             <object>,  // the read manifest, canonicalized recursively (§1)
  "observed_at":          <string>,  // §3 timestamp
  "read_id":              <string>   // UUID string form
}
```

Covered field set = `{attester_delegate_id, manifest, observed_at, read_id}`. Source:
`build_read_signing_bytes` (`connector.py:140`).

### 2.3 Verification contract

A verifier MUST (a) **re-derive** the canonical bytes from the receipt's own identity fields
and assert they equal the stored `canonical_bytes`, **then** (b) Ed25519-verify the signature
over those bytes under the signer's public key. Both checks MUST pass. (Source:
`verify_action_envelope` / `verify_read_receipt`, `connector.py:163,193`.)

---

## 3. The `observed_at` timestamp (the #1 cross-language trap)

`observed_at` is **inside** the signed pre-image and is **re-derived at verify time**, so its
string form MUST be byte-identical across implementations. The shipped form is Python
`datetime.isoformat()` on a UTC-aware datetime:

- **RFC 3339 / ISO 8601**, e.g. `2026-06-01T12:00:00.789012+00:00`.
- The UTC offset is the literal `+00:00` — **NOT** `Z`.
- The fractional-seconds component is **microseconds (6 digits)** when non-zero, and is
  **OMITTED ENTIRELY when the microsecond component is zero** (Python `isoformat()` behavior):
  `2026-06-01T12:00:00+00:00` (no `.000000`).

> **Rust/Go/JS implementers:** your default formatters are wrong here. Rust `chrono`
> `to_rfc3339()` emits `Z` and a fixed fractional precision; you MUST format to match: `+00:00`
> offset, and emit the fractional part **only** when microseconds ≠ 0, with exactly 6 digits
> when present. The two §6 vectors (zero- and non-zero-microsecond) pin both cases. A future
> revision MAY mandate fixed-width 6-digit fractional to remove the omit-when-zero branch;
> until then, **match the shipped behavior exactly.**

---

## 4. Signature wire form (raw vs hex — inconsistent within the codebase; pinned here)

- **`SignedActionEnvelope.signature`** and **`AttestedReadReceipt.attestation`** are **RAW
  64-byte** Ed25519 detached signatures (`Ed25519PrivateKey.sign()` output, `connector.py:293`).
  When rendered in a text/JSON transport, they MUST be lowercase hex of the 64 raw bytes
  (128 hex chars), and decoded back to 64 raw bytes before `Ed25519.verify`.
- **By contrast**, the SDK dispatch **audit-event** signature (`compose.py` signer thunk) is a
  **128-char lowercase-hex** string at its own boundary, over the §-different pre-image. Do not
  reuse one path's wire form for the other.

This raw-vs-hex split is a real inconsistency in the current code. This spec pins both forms as
they ship; a future revision SHOULD unify on hex-at-the-boundary, raw-into-`verify`.

### 4.1 Keys & fingerprints

- **Public key** wire form: raw 32-byte Ed25519 public key (`public_bytes_raw()`), hex-rendered
  (64 hex chars) in text transports.
- **Signing-key fingerprint** (used by the registry, §6 of the protocol spec): lowercase-hex
  **SHA-256 of the raw 32-byte public key** (64 hex chars). Implementations MUST compute it this
  way so registry entries agree across impls.

---

## 5. Conformance — TWO distinct gates

An implementation claiming Delegate-receipt interoperability MUST pass **both**:

1. **Byte reproduction:** given each §6 vector's input + the fixed test key, the implementation
   reproduces the `canonical_bytes` **byte-for-byte** AND the signature **byte-for-byte**.
2. **Cross-verification matrix:** implementation A's verifier accepts implementation B's signed
   receipts and vice versa, over a shared key, for action and read receipts.

Behavioral/outcome conformance (`specs/conformance.md`) is **NOT** sufficient for interop — it
verifies outcomes, not receipt bytes. These are separate gates; the publish gate requires both.

---

## 6. Normative test vectors (reproducible)

**Fixed test key** (publishable; for conformance only — never a production key):

|                              | value                                                              |
| ---------------------------- | ------------------------------------------------------------------ |
| Ed25519 seed (32 bytes)      | `0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20` |
| public key (raw 32 bytes)    | `79b5562e8fe654f94078b112e8a98ba7901f853ae695bed7e0e3910bad049664` |
| pubkey fingerprint (SHA-256) | `65b60673d6ed884bf01c2c222d82ada0740f29ac3355d6a925c81f17f47a27b8` |

### Vector A — action, **zero-microsecond** timestamp

- Input: `payload={"accepted": true, "to": "ops@x.com"}`,
  `signer_delegate_id="11111111-1111-1111-1111-111111111111"`,
  `action_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"`,
  `observed_at="2026-06-01T12:00:00+00:00"`
- Canonical bytes (UTF-8):
  `{"action_id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","observed_at":"2026-06-01T12:00:00+00:00","payload":{"accepted":true,"to":"ops@x.com"},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}`
- Signature (raw 64-byte, hex):
  `fe7608809ab48aa4ff2151b821a5932b5c59743ea4cf09028d7704f419e2a8084f403eca76bf2412122c92f1e1e8ee96e6ca6e3e56c3be72b760c5b9a4ad5c0f`

### Vector B — action, **non-zero microsecond + non-ASCII** (`café`)

- Input: `payload={"n": 7, "unicode": "café"}`,
  `signer_delegate_id="11111111-1111-1111-1111-111111111111"`,
  `action_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"`,
  `observed_at="2026-06-01T12:00:00.789012+00:00"`
- Canonical bytes (UTF-8, note `café` → `…636166c3a9…`, `ensure_ascii=false`):
  `{"action_id":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","observed_at":"2026-06-01T12:00:00.789012+00:00","payload":{"n":7,"unicode":"café"},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}`
- Signature (raw 64-byte, hex):
  `c61c8dbb0f7699b463ee6840b7643a7abf323128d6c1868d0575bce9ce8c9599896bb0f80cd0f0249ad987e9fe0fe50512d2eef96c4ba9786178535e7b6d3302`

### Vector C — read receipt

- Input: `manifest={"count": 2, "message_ids": ["m1","m2"]}`,
  `attester_delegate_id="22222222-2222-2222-2222-222222222222"`,
  `read_id="cccccccc-cccc-cccc-cccc-cccccccccccc"`,
  `observed_at="2026-06-01T12:00:00+00:00"`
- Canonical bytes (UTF-8):
  `{"attester_delegate_id":"22222222-2222-2222-2222-222222222222","manifest":{"count":2,"message_ids":["m1","m2"]},"observed_at":"2026-06-01T12:00:00+00:00","read_id":"cccccccc-cccc-cccc-cccc-cccccccccccc"}`
- Signature (raw 64-byte, hex):
  `38905840b0e8143829ecde931419171f0ed02a148dc6692dd7850a6d39bae20f0c742319ecc95ed7127f39403ce2f8f524b71015a887b4d238a1a4d288e78a0d`

> These vectors were generated from the shipped `build_action_signing_bytes` /
> `build_read_signing_bytes` under the fixed seed above. A conforming implementation reproduces
> every `canonical bytes` and `signature` value exactly. They MUST be committed as a
> cross-language fixture (`tests/fixtures/receipt-interop/`) consumed by both the Python and
> `dc-enterprise` test suites.

---

## 7. Change control

This contract is **frozen** once a second implementation depends on it. Any change to the
covered field set, key-ordering rule, timestamp form, or signature wire form is a
**breaking protocol change** requiring a `protocol_version` bump (see the protocol spec §0/§8)
and a coordinated migration across all implementations. Append a dated entry below for any
revision.

- 2026-06-01: initial extraction from shipped connector source; vectors pinned.
