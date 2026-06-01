# Spec — Canonical Signing Bytes & Receipt Wire Form (NORMATIVE, FROZEN v1)

**Status:** **FROZEN v1** — the receipt-signing core is hardened and ready for a second
implementation (the Rust `dc-enterprise` tier) to build against. Adversarially probed for
Python↔Rust silent-break edge cases (2026-06-01).
**Audience:** any implementation that must produce or verify Delegate connector receipts
**byte-for-byte interoperably**.
**Conformance language:** MUST / SHOULD / MAY per RFC 2119.

This is the single load-bearing cross-implementation contract. One field-order, encoding,
timestamp, key-order, integer, or escaping difference breaks **100%** of cross-impl
verifications, **silently** (the receipt still "looks signed"). Every clause below was probed
against the actual Python encoder AND a Rust `serde_json` cross-check; where they diverge from a
"standard" (notably RFC 8785/JCS), that is called out explicitly.

> **Distinct from the audit layer.** This pins the _connector-receipt_ signing layer
> (`SignedActionEnvelope`, `AttestedReadReceipt`). The SDK _dispatch audit-event_ layer
> (`kailash.delegate.audit.content_signing_bytes`, pre-image `{event_type, event_payload,
signer_delegate_id}`, signature 128-char hex) is a **different pre-image and wire form** — §4.

---

## 1. Canonical JSON encoding (the shared primitive)

Every signed byte string here is the **strict UTF-8** encoding of a **canonical JSON** document.
The Python reference encoder is:

```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
```

`allow_nan=False` is **REQUIRED** (§1.4). The rules below are normative; the call is one
conforming encoder.

### 1.1 Key ordering — Unicode code point, **NOT** RFC 8785/JCS

Object keys MUST be sorted ascending by **Unicode scalar value (code point)** at every nesting
level — equivalently, by the **raw UTF-8 byte sequence** of each key (UTF-8 byte order ==
code-point order). This is **NOT** RFC 8785 / JCS, which sorts by **UTF-16 code unit** and
produces a _different_ order for any key containing a character above U+FFFF.

- Implementations **MUST NOT** use a JCS / RFC-8785 library for key ordering.
- Python `json.dumps(sort_keys=True)` is correct as-is. Rust `BTreeMap<String, _>` or
  `Vec<String>::sort()` is correct as-is (both are UTF-8 byte order == code-point order).
- Probed: `{"😀", "�"}` → `�` (replacement char) sorts **before** `😀` (U+1F600) —
  the _opposite_ of UTF-16 order. Locked by Vector D (§6).

### 1.2 Object keys MUST be strings

All object keys MUST already be strings before canonicalization. Non-string keys
(int/float/bool/null) are **FORBIDDEN**; the canonicalizer MUST reject any mapping with a
non-`str` key at every level. _(Rationale: Python sorts typed keys numerically then stringifies,
so int keys `1,2,10` emit as `"1","2","10"` — an order no string-keyed verifier reproduces.)_

### 1.3 Integers — domain `[-(2^53-1), 2^53-1]` (JS-safe; owner decision, frozen 2026-06-01)

Signed-pre-image integers MUST lie in the closed range `[-(2^53-1), 2^53-1]` — i.e. JavaScript's
safe-integer range, `±9007199254740991` (`Number.MAX_SAFE_INTEGER`). Any integer with absolute
value `≥ 2^53` (`9007199254740992`) MUST be **rejected by the producer before signing** OR carried
as a **decimal string**, never as a bare JSON number. Integers render as bare decimal digits — no
leading `+`, no leading zeros (except `0`), no exponent.

> **Why this cap (not the wider `2^64-1`):** JavaScript / browser consumers are in scope (owner
> decision 2026-06-01). A JS `JSON.parse` collides at `2^53+1` (`Number` is `f64`), so a receipt
> carrying a larger bare integer verifies in Python/Rust but is silently corrupted the moment any
> JS client reads it. Capping at `2^53-1` makes the pre-image safe across Python, Rust (`i64`/`u64`
> both hold it), AND JavaScript. The canonicalizer MUST raise on out-of-range ints, never emit
> them. (Separately, a bare `≥2^64` literal would make a `serde_json` verifier silently coerce to
> `f64` — the cap forecloses that too.)

### 1.4 No floats; reject NaN/Infinity

JSON floating-point numbers are **FORBIDDEN** in any signed pre-image (cross-language float
formatting — Python `repr` vs Rust `ryu` vs Go `strconv` — is not pinned by v1). Decimal
quantities MUST be carried as strings (`"10.50"`) or integer minor-units. The canonicalizer MUST
enforce this at the connector boundary (not rely on result-shape coincidence). `NaN`, `Infinity`,
`-Infinity` MUST be **rejected** (`allow_nan=False`) — Python's default `allow_nan=True`
_silently_ emits the non-JSON tokens `NaN`/`Infinity`/`-Infinity`, which `serde_json` rejects on
parse, making the pre-image permanently unverifiable with no producer-side error.

### 1.5 Strings — exact escape table, strict UTF-8, no normalization

- **Escape ONLY:** `"` (U+0022 → `\"`), `\` (U+005C → `\\`), U+0008 `\b`, U+0009 `\t`,
  U+000A `\n`, U+000C `\f`, U+000D `\r`. **All other** characters in U+0000–U+001F escape as
  `\u00XX` with **lowercase** hex. `/` (U+002F) is **NOT** escaped. U+007F (DEL) and all U+0080+
  (C1 controls + non-ASCII) are emitted as **raw UTF-8 bytes**, never escaped. No other character
  is ever escaped. _(Probed byte-identical Python `ensure_ascii=False` ↔ `serde_json` default on
  all cases — pin it so neither side swaps in a library that escapes `/` or non-ASCII.)_
- **Lone surrogates** (U+D800–U+DFFF) MUST be **rejected**. Sign over the **strict UTF-8 byte
  encoding** of the canonical string (`errors='strict'`), never over the Python `str` object —
  Python `json.dumps` does _not_ raise on a lone surrogate; the failure surfaces only at
  `.encode("utf-8")`. `serde_json` rejects `\uD83D` on parse, so such a pre-image is unverifiable.
- **No Unicode normalization** at any stage. NFC (`é` = U+00E9) and NFD (`e` + U+0301) are
  **distinct** keys/values producing distinct signatures. Callers requiring normalization MUST
  normalize (recommend NFC) **before** the canonicalizer; the canonicalizer MUST NOT normalize.

### 1.6 Containers & literals

Empty object = `{}`; empty array = `[]`; `null`; booleans `true`/`false` (lowercase, unquoted).
**No whitespace anywhere** — separators are exactly `,` and `:`. Arrays preserve order; every
value is canonicalized recursively by these rules at every nesting level.

### 1.7 Duplicate keys — verifier MUST reject

A conforming **verifier/parser** MUST **reject** any received receipt/registry JSON object
containing duplicate keys (raise — do **not** last-wins). `serde_json`'s default `Value` parser
silently accepts duplicates and keeps the last, letting an attacker craft a receipt whose
displayed bytes differ from the canonicalized bytes. Use a duplicate-key-rejecting deserializer
(a custom visitor erroring on repeat insert). _(A producer Python `dict` cannot hold duplicates;
this is a verifier-side clause.)_

---

## 2. Pre-images (the exact covered fields)

### 2.1 `SignedActionEnvelope` (a `write`)

Pre-image object = `{action_id, observed_at, payload, signer_delegate_id}` — **no more, no less**.
`payload` is canonicalized recursively (§1). `action_id`/`signer_delegate_id` are UUID string
form (lowercase, hyphenated). Source: `build_action_signing_bytes` (`connector.py:115`).

### 2.2 `AttestedReadReceipt` (a `read`)

Pre-image object = `{attester_delegate_id, manifest, observed_at, read_id}`. `manifest`
canonicalized recursively (§1). Source: `build_read_signing_bytes` (`connector.py:140`).

### 2.3 Verification

A verifier MUST (a) re-derive the canonical bytes from the receipt's own identity fields and
assert equality with the stored `canonical_bytes`, then (b) Ed25519-verify the signature over
those bytes under the signer's public key. Both MUST pass.

---

## 3. The `observed_at` timestamp — **fixed-width** (frozen)

`observed_at` is **inside** the signed pre-image and re-derived at verify time, so its string form
MUST be byte-identical across implementations. **v1 mandates fixed-width**:

- **RFC 3339 / ISO 8601, UTC**, with the literal offset `+00:00` (**NOT** `Z`).
- **Always exactly 6 fractional digits** (microseconds), even when zero:
  `2026-06-01T12:00:00.000000+00:00`. (Python: `datetime.isoformat(timespec="microseconds")`.)

This deletes the Python-default omit-when-zero branch (a cross-language footgun). **The Phase-0
connector rewrite MUST emit `timespec="microseconds")` at all 12 sign/verify call sites
atomically.** _(History: the yanked 0.1.0 connectors used bare `isoformat()` = omit-when-zero;
that form is retired with those packages and is NOT a conforming v1 producer.)_

> **Rust/Go/JS:** your default formatters are wrong. Rust `chrono` `to_rfc3339()` emits `Z` and
> variable precision; format to match `+00:00` + fixed 6-digit. Vectors A/C (zero-µs) and B
> (non-zero-µs) lock both renderings.

---

## 4. Signature wire form + key/fingerprint

- **`SignedActionEnvelope.signature`** and **`AttestedReadReceipt.attestation`** are **RAW 64-byte**
  Ed25519 detached signatures (`signing_key.sign()`, `connector.py:293`); rendered as lowercase
  hex (128 chars) in text transports, decoded to 64 raw bytes before `Ed25519.verify`.
- The SDK **audit-event** signature is **128-char lowercase hex** over its own (§-different)
  pre-image. Do not reuse one path's wire form for the other.
- **Public key:** raw 32-byte (`public_bytes_raw()`), hex (64 chars). **Fingerprint:** lowercase-hex
  **SHA-256 of the raw 32-byte public key** (64 chars).

---

## 5. Conformance — TWO gates + the reject suite

An implementation claiming interoperability MUST pass **both**:

1. **Byte reproduction:** given each §6 _accept_ vector's input + the fixed test key, reproduce the
   `canonical_bytes` **and** signature byte-for-byte.
2. **Cross-verification matrix:** each implementation's verifier accepts the other's signed
   receipts, for action and read, over a shared key.

Plus the **reject suite** — the canonicalizer/verifier MUST reject (raise, never sign/accept):
a float; a NaN/Infinity; an integer outside `[-(2^53-1), 2^53-1]`; a non-string object key; a
string with a lone surrogate; a JSON object with duplicate keys (verifier side).

Behavioral/outcome conformance (`specs/conformance.md`) is **NOT** sufficient for interop — it
verifies outcomes, not receipt bytes.

---

## 6. Normative test vectors (reproducible; all verified to round-trip)

**Fixed test key** (publishable; conformance only):

|                       | value                                                              |
| --------------------- | ------------------------------------------------------------------ |
| Ed25519 seed          | `0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20` |
| public key (raw 32B)  | `79b5562e8fe654f94078b112e8a98ba7901f853ae695bed7e0e3910bad049664` |
| fingerprint (SHA-256) | `65b60673d6ed884bf01c2c222d82ada0740f29ac3355d6a925c81f17f47a27b8` |

**A — action, zero-µs (fixed-width `.000000`)**

- bytes: `{"action_id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","observed_at":"2026-06-01T12:00:00.000000+00:00","payload":{"accepted":true,"to":"ops@x.com"},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}`
- sig: `af74eb243b0c2baaf3bb40f629363f0870aecfd8692c817c80b5980e77dd37856dc2b377917ca0c8363f4bb3dbed2560c6debfee412461cecdfe201708a2690b`

**B — action, non-zero-µs + non-ASCII (`café` → `…636166c3a9…`)**

- bytes: `{"action_id":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","observed_at":"2026-06-01T12:00:00.789012+00:00","payload":{"n":7,"unicode":"café"},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}`
- sig: `c61c8dbb0f7699b463ee6840b7643a7abf323128d6c1868d0575bce9ce8c9599896bb0f80cd0f0249ad987e9fe0fe50512d2eef96c4ba9786178535e7b6d3302`

**C — read receipt, zero-µs**

- bytes: `{"attester_delegate_id":"22222222-2222-2222-2222-222222222222","manifest":{"count":2,"message_ids":["m1","m2"]},"observed_at":"2026-06-01T12:00:00.000000+00:00","read_id":"cccccccc-cccc-cccc-cccc-cccccccccccc"}`
- sig: `b34e4f2a199357ad968f33daecd7b3e138a0f56680f9566a7a490542cde15be63b5bf540444a1ce609b4bf7323df486aa40fff66d1439769cc81f098c9a6260b`

**D — astral key ordering (locks code-point, NOT UTF-16/JCS): `U+FFFD` sorts before `😀`**

- bytes: `{"action_id":"dddddddd-dddd-dddd-dddd-dddddddddddd","observed_at":"2026-06-01T12:00:00.000000+00:00","payload":{"�":"replacement","😀":"emoji"},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}`
- sig: `8b55028b7723becec430c453a135102eec1e4a749061ca3603bd31f37ebe6164626fd5066e281488dbdafbbb6bc88b91a9ce690fd034abf8ba816d3157f0420c`

**E — integer JS-safe boundary (`±(2^53-1)` = `±9007199254740991`, both valid bare)**

- bytes: `{"action_id":"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee","observed_at":"2026-06-01T12:00:00.000000+00:00","payload":{"max_safe":9007199254740991,"min_safe":-9007199254740991},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}`
- sig: `e11846a488e5155de6c9483409ac7401bac0e6dc9ad99727849b3afd196245e3c15f0e293ce1536b83d2492e5628a1c5fa274e5dddc93d43e581a37af851820d`

**Reject cases** (no bytes — assert rejection): `9007199254740992` (`2^53`, first JS-unsafe int);
`float 1.5`; `NaN`; object key `1` (int); string `"a\uD83Db"` (lone surrogate); object
`{"k":1,"k":2}` (duplicate, verifier side).

> All accept vectors generated from the shipped `build_action/read_signing_bytes` under the fixed
> seed (timestamps via `timespec="microseconds"`) and verified to round-trip under the published
> public key. Commit as `tests/fixtures/receipt-interop/`, consumed by both implementations.

---

## 7. Change control & open prerequisites

This contract is **frozen v1**. Any change to the covered field set, key-ordering rule, timestamp
form, integer domain, escaping, or signature wire form is a **breaking** change requiring a
`protocol_version` bump + coordinated migration across all implementations.

Owner decisions affecting this core are **resolved** (2026-06-01): (a) **JS-interop scope** —
JavaScript consumers ARE in scope, so the integer domain is `[-(2^53-1), 2^53-1]` (§1.3), final;
(b) **`protocol_version` = `1`** — defined here with fixed-width timestamps from the start (no
prior frozen version shipped; the yanked 0.1.0 connectors predate any numbered protocol), so no
bump is required to reach this v1. §1–§6 are **final and ready to hand to a second implementation.**

- 2026-06-01: initial extraction + adversarial hardening (9 canonical-JSON edge-case pins, float
  ban, fixed-width timestamp); vectors regenerated + verified. **Frozen v1.**
