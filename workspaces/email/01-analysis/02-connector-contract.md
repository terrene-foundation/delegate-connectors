# 02 — Connector Contract + Base-Class Choice (Email Connector)

> Claim cluster: connector contract + base-class choice. Open questions #1 (base class)
> and the README-divergence claim. Read-only `/analyze` research; introspected against
> **kailash 2.26.2** in `.venv/` (`.venv/bin/python`). All findings independently verified.

## TL;DR

- **README-divergence verdict: TRUE.** `connect()`, `identify()`, `normalize()` do NOT
  exist on the shipped `Connector` ABC. Only `authenticate` survives (with a different
  signature). The README's connector-contract bullets (lines 20–23) are stale.
- **Base-class RECOMMENDATION: subclass `Connector` directly** (the 4-primitive shape),
  NOT `LegacyInvokeConnector`. The legacy path's `read`/`write` emit **empty
  attestations/signatures** and its three trust properties **raise on access** — it
  cannot deliver email's audited read/write, which the brief's acceptance criteria require.

---

## 1. Verified ABC surface (`kailash.delegate.Connector`)

Source: `kailash/delegate/dispatch.py` (re-exported at `kailash.delegate.Connector`).
MRO: `Connector → abc.ABC → object`.

`Connector.__abstractmethods__` (7 members):
`{auth_verifier, authenticate, invoke, ledger, read, revocation, write}` — 4 methods + 3 properties.

| Member                  | Kind                     | Full signature                                                                                                                            |
| ----------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `authenticate`          | abstract method          | `(self, identity: DelegateIdentity, envelope: DelegateConstraintEnvelope) -> Principal`                                                   |
| `invoke`                | abstract method          | `(self, input_payload: dict[str, Any], *, identity: DelegateIdentity, envelope: DelegateConstraintEnvelope) -> ConnectorInvocationResult` |
| `read`                  | abstract method          | `(self, query: Callable[[], Awaitable[T_Read]], *, identity, envelope) -> tuple[T_Read, AttestedReadReceipt]`                             |
| `write`                 | abstract method          | `(self, action: Callable[[], Awaitable[Any]], *, identity, envelope) -> SignedActionEnvelope`                                             |
| `auth_verifier`         | abstract property        | `(self) -> AuthVerifier`                                                                                                                  |
| `ledger`                | abstract property        | `(self) -> KnowledgeLedger`                                                                                                               |
| `revocation`            | abstract property        | `(self) -> RevocationChannel`                                                                                                             |
| `connector_id`          | class attr (`str`)       | non-empty required; bind check raises if empty (`__init_subclass__`)                                                                      |
| `connector_kind`        | class attr (`str`)       | non-empty required                                                                                                                        |
| `requires_capabilities` | class attr (`frozenset`) | must be a frozenset                                                                                                                       |

Docstrings (verbatim, key points):

- `authenticate`: "Authenticate the dispatch identity; return a `Principal`. Raises a
  connector-defined exception if authentication fails."
- `invoke`: "Invoke the external endpoint (**legacy single-method shape**). Pre-F-17 entry
  point... New connectors SHOULD implement the 4-primitive shape (`authenticate`/`write`/`read`)."
- `read`: "Execute a read query under audit; return (payload, attested-receipt)."
- `write`: "Execute a write action under audit; return a signed action envelope. The
  signature on the envelope MUST be verifiable via the runtime's `Verifier`."
- `auth_verifier`: "The connector's authentication verifier (OIDC/SAML/etc.)."
- `ledger`: "The connector's knowledge ledger (where dispatch reads/writes record)."
- `revocation`: "The connector's revocation channel. Reachable for every dispatch."

**`read`/`write` take a thunk, not raw data.** `read(query=…)` and `write(action=…)` each
take a zero-arg async callable; the connector executes it _under audit_ and wraps the
result. This is the audited-execution seam — the connector is the place that turns a raw
IMAP fetch / SMTP send into an attested receipt / signed envelope.

---

## 2. Type catalog (resolved + cited)

`Connector` and its key types live in `kailash.delegate.dispatch`; the envelope/identity
types live in `kailash.delegate.envelope` / `.types`. **Note for imports:** `Principal`,
`ConnectorInvocationResult`, `AttestedReadReceipt`, `SignedActionEnvelope`, `AuthVerifier`,
`KnowledgeLedger`, `RevocationChannel`, `LegacyInvokeConnector` are NOT in
`kailash.delegate.__all__` — import them from `kailash.delegate.dispatch`.
`ConstraintEnvelope`, `DelegateConstraintEnvelope`, `DelegateIdentity`, `PrincipalDirectory`,
`Verifier`, `NullVerifier`, `Ed25519Verifier`, `ConformanceVector`, `ConformanceVectorLoader`
ARE in `kailash.delegate.__all__`.

| Type                         | Module                      | Fields / constructor                                                                                                                                                                            |
| ---------------------------- | --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ----- |
| `DelegateIdentity`           | `kailash.delegate.types`    | `(delegate_id: UUID, sovereign_ref: str, role_binding_ref: str, genesis_ref: str, principal_kind: PrincipalKind='delegate')` — all `*_ref` eager-required                                       |
| `Principal`                  | `kailash.delegate.dispatch` | `(delegate_id: str, tenant_id: str                                                                                                                                                              | None, claims: dict[str,Any]=<factory>)`—`delegate_id`MUST match bound identity's stringified`delegate_id` |
| `ConnectorInvocationResult`  | `kailash.delegate.dispatch` | `(payload: dict[str,Any], audit_events: tuple[DelegateEventType,...], tenant_id_observed: str                                                                                                   | None, external_side_effect: bool)`; `to_dict/from_dict` is the cross-SDK wire contract                    |
| `DelegateConstraintEnvelope` | `kailash.delegate.envelope` | `(inner: ConstraintEnvelope, genesis_id: str)` — type-state wrapper; tightening-only; fresh envelope only via `from_genesis(GenesisRecord)`                                                     |
| `ConstraintEnvelope`         | `kailash.delegate.envelope` | `(financial, operational, temporal, data_access, communication, gradient_thresholds, posture_ceiling, metadata)` — all `…Constraint                                                             | None`+`metadata: dict` (the 5 CARE constraint dimensions)                                                 |
| `AttestedReadReceipt`        | `kailash.delegate.dispatch` | `(read_id: UUID, canonical_bytes: bytes, attestation: bytes, attester_delegate_id: str, observed_at: datetime)` — read-side forensic primitive                                                  |
| `SignedActionEnvelope`       | `kailash.delegate.dispatch` | `(action_id: UUID, canonical_bytes: bytes, signature: bytes, signer_delegate_id: str, payload: dict=<factory>)` — write-side audit artifact; dispatch verifies `signature` via bound `Verifier` |
| `AuthVerifier`               | `kailash.delegate.dispatch` | **Protocol** (`_ProtocolMeta`) — structural; OIDC/SAML/mTLS/JWT/no-auth all bind. Authenticates the dispatch IDENTITY (distinct from `Verifier`)                                                |
| `KnowledgeLedger`            | `kailash.delegate.dispatch` | **Protocol** — narrow audit-append surface; in-mem/SQLite/Postgres bind structurally                                                                                                            |
| `RevocationChannel`          | `kailash.delegate.dispatch` | **Protocol** — `is_revoked(delegate_id)` reachability gate per dispatch                                                                                                                         |
| `PrincipalDirectory`         | `kailash.delegate.types`    | `(identities: tuple[DelegateIdentity,...], verification_keys: dict[UUID,bytes])`; methods `.resolve(delegate_id)->DelegateIdentity                                                              | None`, `.public_key_for(delegate_id)->bytes                                                               | None` |

Trust verifiers (`kailash.delegate.verifier`):

- `Verifier` — **Protocol**: `verify(message, signature, signer_delegate_id) -> bool`,
  fail-closed, NEVER raises (caller inspects bool). This is the signature verifier the
  dispatch surface uses against `SignedActionEnvelope`/`AttestedReadReceipt`.
- `Ed25519Verifier(directory: PrincipalDirectory)` — concrete; looks up `signer_delegate_id`
  in the directory, verifies a detached Ed25519 signature against canonical bytes. Per #1035
  C1 this is the "real encryption" defense.
- `NullVerifier()` — concrete, fail-closed default: rejects EVERY signature. Constructed when
  a runtime is built without an explicit verifier, so a missing-wire surfaces as a typed
  audit error rather than silent accept.

---

## 3. Base-class choice — `LegacyInvokeConnector` vs direct `Connector` (open question #1)

`LegacyInvokeConnector(Connector)` (`kailash/delegate/dispatch.py`):
`__init__(invoke_callable, *, connector_id=None, connector_kind=None, requires_capabilities=None)`.
It implements ONLY `invoke` (forwards to the wrapped callable). The other 6 abstracts are
"auto-satisfied" — but reading the source shows what those auto-installs actually are:

- `Connector.__init_subclass__` detects a subclass that defines `invoke()` but not the 6 new
  primitives, and installs **default proxies**: `_legacy_write`, `_legacy_read`,
  `_legacy_authenticate`, and `_LegacyAccessor` descriptors for `revocation`/`ledger`/`auth_verifier`.
- `_legacy_write` (docstring, verbatim): "Executes the action and returns a synthesized
  SignedActionEnvelope with an **EMPTY signature** — legacy connectors did not produce
  cryptographic action signatures. New-shape callers receiving an empty-signature envelope
  from a legacy connector **MUST treat it as unverifiable**."
- `_legacy_read`: "returns the value plus a synthesized `AttestedReadReceipt` with an
  **EMPTY attestation**."
- `_legacy_authenticate`: returns a "trivial `Principal`" (`tenant_id=None, claims={}`).
- `_LegacyAccessor.__get__` → `_legacy_unsupported(name)` — i.e. the three trust properties
  (`revocation`/`ledger`/`auth_verifier`) **raise on access** for a legacy connector.

**Conclusion (resolves open question #1):** Extending `LegacyInvokeConnector` gives you
`invoke` only. It does NOT give real audited read/write — the proxies fabricate
empty-signature / empty-attestation receipts the spine itself marks "unverifiable", and the
trust properties raise. Email's brief requires the audited read (IMAP) / write (SMTP) split
with verifiable receipts (acceptance criteria: "Audit receipts emitted on read/write and
verify under the spine verifier"). The legacy shape structurally cannot meet that.

### RECOMMENDATION: subclass `Connector` directly (4-primitive shape)

Implement `authenticate`, `read`, `write` (skip a meaningful `invoke` — or route it through
`write` — since email is not a single-call RPC), plus the three properties returning real
backing objects.

- **Why:** Only the direct shape produces real `SignedActionEnvelope` (SMTP send, signature
  verifiable via the bound `Verifier`) and real `AttestedReadReceipt` (IMAP fetch). It is
  the path the ABC docstring itself prescribes: "New connectors SHOULD subclass `Connector`
  directly and implement all 6 new abstracts."
- **Tradeoff (honest cons):** more surface to implement up front — you must supply concrete
  `ledger` / `revocation` and an `auth_verifier`, and wire `read`/`write` to run their thunk
  under audit and emit signed/attested receipts. `LegacyInvokeConnector` is ~10 lines by
  comparison. But that brevity is exactly the capability gap: the cheaper path delivers
  unverifiable receipts and raising trust-properties, so for email it is a dead end, not a
  shortcut. (`invoke`-only via auto-adapt is fine for a stub passing back-compat tests — the
  brief explicitly wants a real implementation, not a stub.)

---

## 4. Wiring the 3 trust properties (open question #4 within cluster)

Concrete `AuthVerifier` implementations that ship: **none named `*AuthVerifier`** —
`AuthVerifier` is a `Protocol`, so any object with the structural surface binds. The shipped
_signature_ verifiers are `Ed25519Verifier(directory)`, `NullVerifier()`, and the `Verifier`
protocol — these are `Verifier` (audit-signature) implementations, distinct from
`AuthVerifier` (identity authn). `KnowledgeLedger` and `RevocationChannel` are also Protocols
with no shipped concrete class surfaced in `kailash.delegate.__all__`.

**Simplest correct wiring for v0:**

- `auth_verifier` → a minimal object satisfying the `AuthVerifier` Protocol (env-credential
  SMTP/IMAP authn per brief scope — no OAuth2 in v0).
- `ledger` → a minimal `KnowledgeLedger`-conforming object (in-memory for Tier 1; real
  Postgres-backed for Tier 2/3 per the brief's real-infra requirement).
- `revocation` → a minimal `RevocationChannel` whose `is_revoked(delegate_id)` returns
  `False` for the always-reachable default.
- Signature/attestation verification → `Ed25519Verifier(PrincipalDirectory(...))` so `write`
  produces a `SignedActionEnvelope` whose `signature` verifies (NOT `NullVerifier`, which
  rejects everything by design).

These are Protocols, so the brief's "no custom trust primitives" is satisfied by supplying
thin spine-conforming objects; the only concrete shipped class to reuse directly is
`Ed25519Verifier` + `PrincipalDirectory`. (Whether a richer default ledger/revocation ships
elsewhere in the package is open question #3/#4 follow-up — out of this cluster.)

---

## 5. README-divergence verdict: TRUE

The README (`README.md` lines 20–23) states the connector responsibility as:

> - `connect()` — wire setup
> - `identify()` — `Principal` resolution against `PrincipalDirectory`
> - `authenticate()` — `Posture` + `Genesis` write
> - `normalize()` — channel envelope → `InboundIntentEnvelope`

Verified against the shipped ABC:

- `connect` — **ABSENT** (wiring is constructor/property-based; no such method).
- `identify` — **ABSENT** (folded into `authenticate`, which returns a `Principal`).
- `normalize` — **ABSENT** (payload shaping happens inside `invoke`/`read`/`write`).
- `authenticate` — **EXISTS but mis-described**: shipped signature is
  `authenticate(identity: DelegateIdentity, envelope: DelegateConstraintEnvelope) -> Principal`;
  the README's "`Posture` + `Genesis` write" is not what the method does.

3 of 4 named methods do not exist; the 4th has a different contract. The README connector
section needs a correction PR (the brief flags this as separate from connector code —
acceptance criterion "README connector-contract section corrected (separate doc PR)").

---

## Citations

- `kailash/delegate/dispatch.py` — `Connector` ABC, `__init_subclass__` legacy auto-adapt,
  `_legacy_write` / `_legacy_read` / `_legacy_authenticate` / `_LegacyAccessor`,
  `LegacyInvokeConnector`, `Principal`, `ConnectorInvocationResult`, `AttestedReadReceipt`,
  `SignedActionEnvelope`, `AuthVerifier` / `KnowledgeLedger` / `RevocationChannel` Protocols.
- `kailash/delegate/envelope.py` — `ConstraintEnvelope`, `DelegateConstraintEnvelope`.
- `kailash/delegate/types.py` — `DelegateIdentity`, `PrincipalDirectory`.
- `kailash/delegate/verifier.py` — `Verifier`, `NullVerifier`, `Ed25519Verifier`.
- `kailash/delegate/conformance/schema.py` — `ConformanceVector`, `ConformanceVectorLoader`.
- `README.md:18-23` — stale connector-contract bullets.
- Introspected against kailash 2.26.2 at
  `.venv/lib/python3.12/site-packages/kailash/` via `.venv/bin/python`.

## Note for sibling clusters (out of my cluster)

`ConformanceVectorLoader.load_canonical()` raises `FileNotFoundError` in this venv — it
expects a vendored fixture at `tests/fixtures/delegate-conformance/canonical.json`. This
matches README step "vendor the conformance vector set from kailash-py". The conformance
cluster (open question #3) must vendor that fixture before vectors can load.
