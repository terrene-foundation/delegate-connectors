# Conformance Contract — what the canonical vectors actually assert

> Claim cluster for `/analyze` open question #3: "What do the canonical conformance
> vectors actually assert about a connector?" Verified against kailash 2.26.2 via
> `.venv/bin/python` introspection. Every claim below cites a module path + line.

## TL;DR contract surface

A conformance vector is a **spec-§-anchored behavioural assertion** — `(given, behaviour,
expected)` where `expected` is a CLOSED 3-value enum (`Accept` / `Reject` /
`EscalateToHuman`), NOT a payload or engine value. The vectors describe what the
**Delegate runtime** must do given a scenario; they are deliberately fenced away from
any connector/engine internals. There is **no shipped runner** that takes a `Connector`
and runs it against the vectors, and **the canonical fixture file is not shipped in the
wheel** (load-bearing, contradicts the brief — see § "Contradictions with the brief").

## 1. Vector shape and count

- `ConformanceVector` is a frozen dataclass with exactly five fields:
  `id, spec_anchor, given, behaviour, expected`
  (`kailash/delegate/conformance/schema.py:272-290`).
- Field semantics (from the validating constructor + docstrings,
  `schema.py:295-359`):
  - `id: str` — non-empty; addresses the vector for a cross-impl receipt
    (e.g. `"DV-7.3-001"`), `schema.py:305-311`.
  - `spec_anchor: SpecAnchor` — MANDATORY Delegate-spec § number, dotted-decimal,
    no `§` glyph stored (e.g. `"7.3"`, `"11"`), `schema.py:146-223`. This is
    "F1 structural fence #1": every vector MUST anchor to a published spec section.
  - `given: str` — non-empty; the scenario in plain spec language, `schema.py:312-318`.
  - `behaviour: str` — non-empty; the spec-§-numbered behaviour the runtime MUST
    exhibit, in plain spec language, `schema.py:319-326`.
  - `expected: BehaviouralOutcome` — a CLOSED enum, `schema.py:232-263`:
    `ACCEPT="Accept"`, `REJECT="Reject"`, `ESCALATE_TO_HUMAN="EscalateToHuman"`.
    Because the enum is closed, "a vector CANNOT assert an engine internal — a literal
    error-variant name, a tightening order, an audit-row cardinality are all
    unrepresentable" (`schema.py:236-240`).

### Vector COUNT — not determinable from the installed wheel

`ConformanceVectorLoader.load_canonical()` raises `FileNotFoundError`:

```
canonical conformance fixture not found at
  .venv/lib/python3.12/site-packages/tests/fixtures/delegate-conformance/canonical.json
```

The loader walks up from `__file__` looking for the relative path
`tests/fixtures/delegate-conformance/canonical.json`
(`schema.py:479` `_CANONICAL_REL_PATH`; `schema.py:591-606` `_locate_canonical`).
That fixture is **not in the wheel** — `kailash-*.dist-info/RECORD` ships
`kailash/delegate/conformance/schema.py` but no `canonical.json`, and a filesystem
search of the venv finds none. So the **canonical vector count cannot be read from the
installed package**; it lives in the SDK's own `tests/fixtures/` tree (a repo artifact,
not a distributed data file).

### `to_dict()` wire shape (verified by construction, in-memory)

A representative vector serializes (`schema.py:342-359`) as:

```json
{
  "id": "DV-7.3-001",
  "spec_anchor": "7.3",
  "given": "an identity with valid clearance and a within-envelope action",
  "behaviour": "the runtime admits the action and emits a signed receipt",
  "expected": "Accept"
}
```

(Constructed + validated + digested in-memory to confirm the shape; the three example
vectors above are illustrative, not the canonical set.)

## 2. The test mechanism — and what the conformance module does / does NOT do

### What the conformance module provides

- `validate_vector_set(vectors)` (`schema.py:396-431`): every vector individually valid
  AND all ids unique. Raises `SchemaError(kind="duplicate_id"|"empty_field"|...)`.
  This is the **in-session feedback loop on the VECTOR SET itself** — it does NOT run a
  connector. It validates that the vectors are well-formed.
- `canonical_vector_set_digest(vectors)` (`schema.py:453-467`): SHA-256 over canonical
  JSON of `[v.to_dict() ...]`, order-sensitive. Stored in the fixture's `digest` field;
  the loader re-computes and compares on load → tamper-evident
  (`ConformanceVectorIntegrityError`, `schema.py:117-125`, `schema.py:550-558`).
- `ConformanceVectorLoader.SCHEMA_VERSION = 1` (`schema.py:504`); fixture top-level shape
  is `{schema_version, digest, vectors:[...]}` (`schema.py:485-502`).

### What it does NOT provide — there is NO connector-vs-vector runner

The conformance module is **behavioural-only and engine-free by design** ("Fence B",
`schema.py:6-9, 32-33`). It imports ZERO symbols from
`kailash.delegate.{runtime,dispatch,trust,audit,posture}`. Confirmed: a grep for any
runner/harness (`run_conformance`, `run_vector`, `*Runner`, `*Harness`) across
`dispatch.py` + `runtime.py` returns nothing. **The package ships no function that
accepts a `Connector` and executes it against the vector set.**

The actual execution path that PRODUCES a behavioural outcome is the **Delegate runtime**,
not the conformance module: `DelegateRuntime.execute(input_payload) ->
RuntimeExecutionResult` (`kailash/delegate/runtime.py:1264-1287`), which drives a
connector through `DispatchSurface.dispatch` (`dispatch.py:494` —
`await connector.invoke(...)` directly in the hot path). The runtime result is what gets
compared cross-impl (see §3). The conformance vectors are the **spec's behavioural
checklist**; the SDK's OWN test tree (in `tests/`, not shipped) is where a vector's
`given` scenario is set up against a runtime+connector and the observed outcome is
asserted equal to `expected`. **For this repo, the harness that maps a vector to an
executed scenario does not exist in the wheel and must be authored (or the fixture +
runner obtained from the SDK source).**

## 3. What receipt-agreement checks (#1035 "py chain verifies under rs verifier")

Two distinct comparators — the brief conflates them:

### `receipts_agree(a, b)` — counts-based, takes two `ConformanceReceipt`

`schema.py:734-758`. A `ConformanceReceipt` is `{implementation, vector_crate_version,
commit_sha, vectors_total, vectors_passed}` (`schema.py:615-633`). Two receipts agree iff:

1. **distinct implementations** (`a.implementation != b.implementation`),
2. **same vector-set** (identical `vector_crate_version` AND `commit_sha`),
3. **both conformed** — `conforms()` = ran ≥1 vector AND `vectors_passed == vectors_total`
   (`schema.py:682-685`).

"This is a verifiable cross-reference, NEVER a field-by-field engine diff" (`schema.py:747-750`).
Verified: `receipts_agree(py, rs)` over matching version+SHA+full-pass → `True`;
same-implementation pair → `False`.

### `assert_receipts_agree(a, b, *, exclude_fields=None)` — takes two DICTS

`schema.py:908-926`. **Important: it does NOT take `ConformanceReceipt` objects** (the
brief implies it does). It takes two **already-serialized
`RuntimeExecutionResult.to_dict()` dicts** and does a deep byte-shape comparison via
`receipts_agree_dict` (`schema.py:798-850`):

- observation-local timestamp fields excluded at ANY depth (default
  `{terminated_at, executed_at, started_at, signed_at}`, `schema.py:769-776`);
  caller `exclude_fields` UNIONs with defaults (cannot re-enable timestamps);
- lists/tuples compared **as ordered sequences** (`audit_chain_entries`, `transitions`
  are ordered chains — set comparison would mask reorder bugs, `schema.py:817-819`);
- nested dicts recurse; scalars by type+equality (`schema.py:853-905`);
- raises `ReceiptsAgreementError` with a `ReceiptsAgreeReport` attached on disagreement.

This dict comparator IS the #1035 "py-emitted chain verifies under rs verifier" check:
the py runtime serializes its `RuntimeExecutionResult` (including the audit chain) to a
dict, the rs runtime serializes its own, and the two dicts must agree field-for-field
(minus timestamps). The engine class never crosses the fence — only its `.to_dict()`
output (`schema.py:18-24, 806-810`).

## 4. Reference connectors / fixtures shipped — NONE usable

- No example/reference connector ships in `kailash.delegate`.
- The only `tests/`-pathed files in the wheel (`RECORD`) are unrelated:
  `kailash/api/tests/...` and `kailash/migration/tests/...`. No
  `delegate-conformance` fixture, no passing reference connector.
- The base options for an EmailConnector are confirmed present:
  `Connector` ABC (`dispatch.py:449`) — 3 `@property @abstractmethod` accessors
  (`revocation`/`ledger`/`auth_verifier`, `dispatch.py:688-705`) + 3 `@abstractmethod
async` primitives (`authenticate`/`write`/`read`, `dispatch.py:707-757`) + legacy
  `invoke` hot-path entry; class-level metadata `connector_id` / `connector_kind` /
  `requires_capabilities` for bind-time gating (`dispatch.py:472-473, 500-502`).
  `LegacyInvokeConnector` (`dispatch.py:871`) wraps a bare `async invoke` callable.
  `__init_subclass__` (`dispatch.py:573-599`) auto-installs the 6 new abstracts as
  proxies routing through `invoke` for legacy subclasses.

## To be conformant, an EmailConnector MUST:

1. **Be a `Connector`** — subclass `kailash.delegate.Connector` (`dispatch.py:449`)
   directly implementing the 3 accessors (`revocation`, `ledger`, `auth_verifier`) + 3
   async primitives (`authenticate`, `write`, `read`), OR subclass
   `LegacyInvokeConnector` (`dispatch.py:871`) supplying one `async invoke`. `isinstance`
   /ABC instantiation check is the acceptance gate (the ABC refuses direct instantiation,
   `dispatch.py:491-495`).
2. **Carry bind-time metadata** — set `connector_id`, `connector_kind`,
   `requires_capabilities` (`dispatch.py:500-502`); `requires_capabilities` MUST be a
   subset of the bound role's grants (`dispatch.py:29, 210`).
3. **Produce the right BehaviouralOutcome per scenario** — when driven by
   `DelegateRuntime.execute` (`runtime.py:1264`), the runtime+connector composition MUST
   exhibit, for each canonical vector's `given`, the vector's `expected` outcome from
   `{Accept, Reject, EscalateToHuman}` (`schema.py:247-249`). Email-relevant mapping
   (to confirm against the actual canonical set once obtained): within-envelope authorized
   send → `Accept`; out-of-envelope / unknown sender / revoked → `Reject`; action
   requiring human sign-off → `EscalateToHuman`.
4. **Emit a cross-impl-agreeing audit chain** — `read` returns an `AttestedReadReceipt`,
   `write` returns a `SignedActionEnvelope` (`dispatch.py:719-757`); the runtime's
   `RuntimeExecutionResult.to_dict()` (incl. ordered `audit_chain_entries` /
   `transitions`) MUST satisfy `assert_receipts_agree` against the reference
   implementation's dict, timestamps excluded (`schema.py:798-850, 908-926`).
5. **NOT assert engine internals in any vector it adds** — vectors are behavioural-only;
   anything beyond the closed `BehaviouralOutcome` enum is structurally unrepresentable
   (`schema.py:236-240`).

## Contradictions / corrections vs the brief

1. **`load_canonical()` does NOT work out-of-the-box.** The canonical fixture
   (`tests/fixtures/delegate-conformance/canonical.json`) is **not shipped in the kailash
   2.26.2 wheel**. The brief's acceptance criterion
   "`validate_vector_set(ConformanceVectorLoader.load_canonical())` green against the
   connector" cannot run against the installed package as-is — the fixture must be
   vendored from the SDK source, regenerated (via `canonical_vector_set_digest`), or the
   path supplied via `load_canonical(root=...)`. **`/analyze` MUST resolve where the
   canonical fixture comes from before the acceptance criterion is achievable.**
   (Also: vector COUNT is therefore unknown from the wheel.)

2. **There is NO connector-vs-vector runner/harness in the package.**
   `validate_vector_set` validates the VECTOR SET's well-formedness — it does not execute
   a connector. The brief's phrasing "connector must satisfy each vector's
   `(given, behaviour, expected)`" is correct as INTENT, but the SDK ships no function
   that performs that satisfaction check. The execution + assertion harness lives in the
   SDK's own (un-shipped) `tests/` tree and **must be authored in this repo**.

3. **`assert_receipts_agree` takes DICTS, not `ConformanceReceipt` objects.** It compares
   two `RuntimeExecutionResult.to_dict()` outputs (`schema.py:908`). The counts-based
   receipt comparator is the separate `receipts_agree(a, b)` (`schema.py:734`). The brief
   should distinguish the two: `receipts_agree` = pass-count cross-reference;
   `assert_receipts_agree` = deep audit-chain dict parity (the actual
   "py chain verifies under rs verifier" check).

4. **The `expected` field is a closed 3-value enum, not a payload.** A connector's
   conformance is judged on which of `{Accept, Reject, EscalateToHuman}` the
   runtime+connector exhibits — not on returned data. This sharpens open question #2
   (unknown-sender disposition): the disposition MUST be expressible as one of those three
   outcomes (most likely `Reject`, possibly `EscalateToHuman`), and the choice should be
   driven by which canonical vector(s) anchor the authenticate path.
