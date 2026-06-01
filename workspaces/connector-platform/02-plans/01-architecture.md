# Architecture — Trust-Native Connector Marketplace ("the n8n killer")

**Status:** PROPOSED — for owner review before any code (Phase 0 gated on approval).
**Date:** 2026-06-01
**Supersedes:** `specs/monorepo-layout.md` (the four-separate-packages "v0 decision"), once Phase 0 lands.
**Decision record:** `workspaces/connector-platform/journal/0001-DECISION-pivot-to-connector-platform.md`
**Research:** `workspaces/connector-platform/01-analysis/00-market-research-dossier.md` (~60 cited sources, 11-agent adversarial study)

---

## 1. The pivot

We are moving from **four separately-maintained PyPI packages** (`delegate-connector-{email,slack,telegram,whatsapp}`) to a **trust-native connector marketplace**: contributors author and own thousands of connectors; the core team maintains a discovery mechanism, a trust contract, and a registry — **never a package per connector.**

Maintaining a package per connector is structurally identical to n8n's `n8n-nodes-base` monorepo, which is the documented bottleneck on n8n's own official-integration throughput. It cannot scale to thousands of contributor connectors.

### Owner decisions (2026-06-01, verbatim choices)

1. **Commit to the pivot; write the architecture up first** (this document), for review before any code.
2. **Ship only the true (subset) trust claim** during the phased rollout — never market a guarantee before its mechanism exists.
3. **Yank the four published 0.1.0 packages from PyPI and restart clean** under the plugin model.

---

## 2. The wedge — and the honest current-state reality

The differentiator versus n8n / Zapier / Make / Airbyte is **trust**. n8n's fatal flaw: a community node calls `getCredentials()` and receives your **decrypted** API keys, then runs **in-process at full host privilege** — the exact vector exploited in the January 2026 n8n supply-chain campaign. The Delegate substrate signs, identity-binds, and audits every connector action; n8n structurally cannot.

**But the wedge is currently half-built.** The substrate **attests** (signs + audits — real and verified) but does **not yet contain** (credential-blindness, capability enforcement, sandboxing). Verified in current source by the adversarial study:

| Property                         | Status today              | Evidence                                                                                                                                                  |
| -------------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Signed, identity-bound receipts  | ✅ real                   | `dispatch.py` signing-bytes cover identity fields                                                                                                         |
| Tamper-evident audit chain       | ✅ real                   | audit-visible event allowlist                                                                                                                             |
| Fail-closed authenticate         | ✅ real                   | unknown sender → `ConnectorAuthenticationError`                                                                                                           |
| Connector cannot see credentials | ❌ **false**              | all 4 connectors read `os.environ` directly (`smtp.py:164`, `imap.py:76`, `slack/web_api.py:74`, `telegram/transport.py:97`, `whatsapp/cloud_api.py:128`) |
| Connector cannot forge receipts  | ❌ **false**              | connector holds the raw Ed25519 signing key (`connector.py:269`, signs at `:293`)                                                                         |
| Capability set is enforced       | ❌ **false**              | `requires_capabilities` is a bind-time string-subset check (`dispatch.py:1428`/`:1606`), never enforced against syscalls/egress                           |
| Revocation works                 | ⚠️ documented placeholder | `NeverRevokedChannel.is_revoked` returns `False` always (`connector.py:112`) — fine for first-party v0, structurally unsafe for untrusted contributors    |

These are reasonable choices for **first-party** connectors. They do **not** generalize to **untrusted contributors** — which is exactly why the new model requires Phase 0 (containment) before any community code runs.

**Consequence for marketing (decision #2):** until containment ships, the only defensible claim is the true subset:

> _"Every action any connector takes is cryptographically signed, identity-bound, and auditable — and code connectors run only from publishers you have allowlisted."_

We do **not** claim "credential-blind" or "run any community connector safely" until Phase 0 (credential broker) and Phase 3 (sandbox) land. Claiming the full wedge before the mechanism exists is the single most dangerous artifact the study found — it is how you become the _next_ supply-chain headline.

---

## 3. Target architecture (Architecture C — Hybrid, threat-sequenced)

> **The wire contract lives in the normative protocol spec, not here.** This section is the
> design narrative. The contracts a second implementation (the Rust `dc-enterprise` tier) MUST
> conform to are pinned in **[`02-protocol-spec.md`](02-protocol-spec.md)** (capability grammar,
> manifest schema, registry schema, discovery descriptor, host-protocol, error taxonomy) and the
> already-shipped crypto core in **[`specs/canonical-signing-bytes.md`](../../../specs/canonical-signing-bytes.md)**
> (canonical bytes, signature wire form, reproducible cross-language test vectors). Read those for
> conformance; read this for rationale.

Two artifact shapes, one discovery group, one signed registry, **sequenced by threat, not by ease.**

```
                    ┌──────────────────────── delegate.connectors (entry-point group) ────────────────────────┐
                    │                                                                                          │
   EASY TIER  ──►   │  Declarative YAML manifest  ──►  GenericHTTPConnector (core-maintained interpreter)      │
   (default,        │  (auth + endpoints + pagination + allowed_hosts + requires_capabilities)                 │
   REST 80%)        │  ▸ no arbitrary code  ▸ credential-blind by construction  ▸ egress capped to manifest    │
                    │                                                                                          │
   CODE TIER  ──►   │  Wheel subclassing Connector ABC  ──►  delegate.connector_builder() factory              │
   (escape hatch,   │  (SMTP/IMAP, triggers, exotic auth)                                                      │
   exotic 20%)      │  ▸ gated behind provenance allowlist until the sandbox exists                            │
                    └──────────────────────────────────────────────────────────────────────────────────────────┘
                                                         │
                                     ┌───────────────────┴───────────────────┐
                                     ▼                                       ▼
                          signed registry.json                     host LOAD-PATH GATE
                          (kind → capability footprint +            (.load() == arbitrary code;
                           content-hash + key fingerprint +          refused for non-allowlisted
                           provenance tier)                          code connectors)
```

### 3.1 Discovery — one entry-point group

`[project.entry-points."delegate.connectors"]` in each connector's `pyproject.toml`; **install == registration**; the host enumerates via `importlib.metadata.entry_points(group="delegate.connectors")` keyed on `connector_kind`. This is the proven pytest-`pytest11` / Terraform-registry model: **O(1) core maintenance regardless of connector count.** `connector_kind` is already a class attribute on every connector, so discovery is additive.

> **Security invariant:** `entry_points(...).load()` _imports the module_ — discovery of a code connector **is** arbitrary-code-execution. Therefore enumeration is safe but **loading** a code connector is gated (§3.5).

### 3.2 Easy tier — declarative manifests (the safe default)

Most connectors are HTTP/REST APIs. A connector becomes a **signed YAML manifest** (auth scheme, base URL, per-operation endpoint + pagination + JSONPath response extraction, `allowed_hosts`, `requires_capabilities`) interpreted by **one** core-maintained, hardened `GenericHTTPConnector`. This is Airbyte's low-code CDK applied to Delegate — its single biggest scaling lever (100+ marketplace connectors in one 6-month window).

**Why it is the safe default:** a manifest contains no executable code. The interpreter is the only code; credentials are injected by the interpreter and never enter the manifest, so **"credential-blind" is true by construction** for this tier (a manifest has no code that could read a secret). **"Capability-bounded" is NOT yet true** _(redteam correction)_: capability strings are declarations, not enforced; egress is bounded only by `allowed_hosts`, which itself MUST be SSRF-hardened (resolve + pin the IP, reject RFC1918/loopback/metadata-IP `169.254.169.254`, no redirects, HTTPS-only — protocol spec §5.4). Capability→verb/host enforcement is Phase 3. The visual/no-code builder (later) emits the _same_ YAML artifact (Airbyte's "one artifact, two surfaces" lesson — never let easy and real connectors diverge into incompatible formats).

### 3.3 Code tier — the ABC + a versioned factory (the escape hatch)

For the exotic ~20% (SMTP/IMAP, triggers, stateful, non-REST), a connector is a wheel subclassing the `Connector` ABC (the 7 members) via a single versioned factory:

```python
delegate.connector_builder(connector, *, signer_callback=...) -> ComposedRuntime
```

The factory absorbs the ~250-LOC compose ceremony every connector hand-copies today (246 LOC email / 286 LOC whatsapp), and reads a `delegate_host_protocol` integer the connector declares — refusing unsupported ranges with a **loud load-time error** (Terraform's `protocol_versions` 5.0/6.0 model). This converts ~20 unversioned spine couplings into **one** versioned contract, so a spine change is a coordinated migration, not a silent thousands-wide break.

### 3.4 Registry — one signed catalog, generated not curated

One generated, signed `registry.json` keyed on `connector_kind`, carrying **capability footprint + content-hash + signing-key fingerprint + provenance tier** for both artifact shapes. Generated deterministically from a per-connector metadata block on publish (Airbyte's metadata-service pattern) — **never hand-curated.** Capability footprint is a discovery/ranking signal (low-authority connectors preferred). The registry is a **trust authority**, not a static index (see §8).

### 3.5 Containment — the load-path gate + credential broker + sandbox

Three layers no incumbent ships together:

1. **Load-path gate (Phase 2):** discovery enumerates the whole catalog, but **loading** a _code_ connector is refused unless its `(distribution, version, hash, key-fingerprint)` is on the provenance allowlist. Community code wheels are **catalog-discoverable but not auto-loadable** until allowlisted (or until the sandbox lands). Kind collisions and hash mismatches fail closed.
2. **Credential broker (Phase 0) — a signing-surface refactor, not a flag-flip** _(corrected per redteam; the original claim here was verified FALSE in source)_: connectors declare `requires_credentials={'smtp'}`; the **host** owns `from_env()` and injects an **opaque `BoundTransport`** exposing only `send(...)`/`fetch(...)`. Two things make today's design insufficient, and Phase 0 MUST close both: (a) every existing transport leaks the secret via a public `.config` property (`SmtpConfig.password`, etc.), so injecting the current transports would recreate the n8n `getCredentials()` leak — a **new** non-introspectable handle type is required (no config accessor, credential-redacting repr, no pickling). (b) Handing the connector a `signer(bytes)` thunk is a **forge oracle** — the connector can sign a delivery that never happened, or sign arbitrary bytes under the host key. Receipt signing MUST move **host-side**: the DispatchSurface derives the canonical bytes (`specs/canonical-signing-bytes.md`) from the **host-observed brokered side effect** and signs them — a refactor of the connector's action-signing path (`connector.py:293`), NOT dropping a constructor arg. Until both land, "credential-blind" and "unforgeable" are false and MUST NOT be marketed (§2).
3. **Out-of-process sandbox (Phase 3):** code connectors run in a **per-connector subprocess** under gVisor/seccomp with an egress allowlist **mechanically derived** from the declared capability frozenset — **not** in-process Python (every in-process Python sandbox is disqualified by live escape CVEs, including n8n's own CVE-2025-68668). Only then does `requires_capabilities` become a syscall-level boundary, and only then can the allowlist gate relax to admit sandboxed community code.

---

## 4. Trust tiers + admission

Automated, tiered admission (n8n's manual 3-week-to-3-month human review is the bottleneck to beat):

| Tier                        | Who          | Admission                                                                                        | Runtime                                                                                                 |
| --------------------------- | ------------ | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| **Declarative / community** | anyone       | mechanical: schema-valid manifest + provenance + capability lint + acceptance test → **instant** | interpreter egress-allowlist (credential-blind by construction; egress = SSRF-hardened `allowed_hosts`) |
| **Official**                | core team    | the 4 references + first-party                                                                   | allowlisted; runs in-process (audited)                                                                  |
| **Verified code**           | contributors | mechanical gates + human review **only for elevated-capability requests**                        | provenance-allowlist → sandbox (Phase 3)                                                                |

Publish gate (all tiers, automated): substrate-conformance vectors **+** byte-level receipt-interop vectors (`specs/canonical-signing-bytes.md` §6 — a **separate** gate from behavioral conformance) **+** PyPI Trusted-Publishing OIDC / PEP 740 provenance **+** static capability-manifest lint **+** a **record-and-replay acceptance test** (against a recorded cassette, so it stays mechanical/"instant" — not a live-API call). The acceptance test is **required, and is also a RUNTIME dispatch invariant**, not just a publish-time check: the host refuses to sign a receipt for a side effect it did not observe (so a connector cannot sign a send that never happened, in production, not only at publish). The badge splits: **"substrate-conformant"** ≠ **"receipt-interoperable"** ≠ **"functionally-verified"** ≠ **"safety-tier"** — never collapsed into one "conformance-passing" label users misread as "safe."

> **Conformance-vector dependency** _(redteam — was omitted)_: the canonical behavioral vectors were **not** shipped in the distributed `kailash` wheel (`ConformanceVectorLoader.load_canonical()` raised `FileNotFoundError`; flagged in `workspaces/email/journal/0002-GAP`) and required a cross-repo vendoring action (resolved 2026-05-27, `journal/0012`). The `delegate-conformance` package vendors them; the publish gate depends on it. This is real Phase-1 scope, not a free primitive.

---

## 5. Contributor experience (the pitch)

**Easy path** (declarative, REST 80%): `delegate-connector new acme --declarative` → the CLI probes the API and emits `acme.connector.yaml` pre-filled with the detected auth scheme → contributor fills ~40 lines (3 operations + `allowed_hosts: [api.acme.com]` + `requires_capabilities: [http.write]`) → `dev` (live API, token injected by host, never embedded) → `conformance` + `acceptance` → `publish` (OIDC provenance, opens hub PR). **Zero Python, zero crypto, credential-blind by construction.** Co-installs with 50 others conflict-free (a manifest drags zero dependencies). n8n makes her write a TypeScript node and pipes her users' decrypted keys into it.

**Code path** (exotic 20%): `delegate-connector new email` → skeleton with the entry-point + factory call pre-wired; declares `requires_credentials={'smtp','imap'}`; host injects opaque `send()`/`fetch()` handles; gets the signer thunk, never the raw key. Target **<50 LOC** of glue (the factory absorbs the rest).

**Present-tense honesty banner** (CLI + README, until the easy path ships): _"Today, adding a connector requires full delegate-substrate fluency (~1500 LOC, the 7-member ABC, hand-written resolver and transports). The fill-in-YAML easy path lands in the manifest-tier wave."_

---

## 6. Migration — yank and restart clean (decision #3)

1. **Yank** (not delete) the four `0.1.0` packages on PyPI — yank hides them from new installs while **keeping the names reserved** (deleting would free them for typosquatters, which the study explicitly warns against). Reserve `delegate-connector-*` and the four kinds; ship a guarding distribution owning the `delegate_connectors` PEP 420 namespace root. _(Yank/delete is a PyPI web-UI operation requiring your logged-in session — an upload token cannot do it; see the handoff note.)_
2. The repo's connector source becomes the **starting material** for the Phase-0 rewrite — re-introduced under the factory + broker as **official-tier reference plugins**, not shipped as-is. The four are deliberately heterogeneous (3 REST-ish + SMTP/IMAP + stateful WhatsApp) so they exercise the code tier fully and prove the declarative tier is genuinely additive.
3. Re-release the rewritten references under the new model (new version line, e.g. `0.2.0`/`1.0.0` — owner's call at Phase 0).

---

## 7. Phased rollout

- **Phase 0 — decoupling foundation** _(MUST precede any contributor; mostly additive, tractable):_ ship production trust-primitive concretes (`KnowledgeLedger`/`RevocationChannel`/`AuthVerifier`); delete the `NeverRevokedChannel→False` placeholder; ship the versioned `connector_builder()` factory + `delegate_host_protocol`; ship the credential broker + host-side signer; refactor the 4 references onto all of it; correct README drift.
- **Phase 1 — declarative tier ships first** _(the safe community on-ramp):_ `GenericHTTPConnector` interpreter + signed manifest schema + `delegate-connector new --declarative` CLI + record-and-replay acceptance gate + versioned `delegate-conformance` package.
- **Phase 2 — gated code discovery:** entry-point group + generated signed `registry.json` + fault-isolating hash-pinned discovery sweep + kind-collision fail-closed + capped `kailash>=2.28,<3` range + package-level revocation denylist + content-hash pinning. **Code connectors discoverable but not auto-loadable** (allowlist-only).
- **Phase 3 — the sandbox** _(greenfield, ~2–3× first-session cost):_ per-connector gVisor/seccomp subprocess + egress allowlist derived from the capability set + a conformance vector that attempts undeclared egress and asserts refusal. Opens the full "run any community connector safely" claim.
- **Phase 4 — operational hardening:** standing supply-chain security-response function, `eject` (manifest → pre-populated code connector), CLI tier auto-detection.

The platform delivers real, safe value at **every** phase without waiting for Phase 3.

---

## 8. Honest trade-offs

- **The full trust wedge is phased, not present.** Two of five headline clauses are verified false today; the marketable claim shrinks to the true subset until Phase 0+3 land (decision #2).
- **Re-sequencing by threat costs calendar time** before the first easy-path contributor ships — we trade an early-but-unsafe win for a later-but-safe one. Correct for a platform whose entire pitch is trust.
- **Two authoring surfaces** (YAML manifest + the 7-member ABC) plus a capability contract version independently — more parity surface than single-surface n8n. The host-protocol integer + versioned factory + versioned conformance package contain it; the `eject` command softens the low-code wall.
- **The sandbox (Phase 3) is genuine greenfield** with real cost (gVisor 3–20% overhead, microVM startup latency; WASI disqualified for native SMTP/IMAP). Until it ships, code connectors are allowlist-gated and the manifest tier carries contributor-count growth.
- **The registry is a trust authority, not a static index.** "O(1) core cost" is true for per-connector _code_, false for the _ecosystem_: running it is a standing 24/7 security-response obligation (compromise monitoring, de-list triage, revocation propagation) that must be staffed and named honestly.
- **The 4 references would fail a baseline-community safety lint** (they self-acquire credentials) — the correct signal that they belong at official tier, but it means the canonical examples are not examples of the safe community pattern until Phase 0 refactors them. CLI templates must teach the broker pattern regardless.

---

## 9. Open decisions (parked — not blocking the write-up)

1. **Sandbox technology (Phase 3):** per-connector gVisor/seccomp subprocess (preserves native SMTP/IMAP transports; 3–20% overhead; Linux-centric) vs WASI-component (stronger isolation; loses native transports). No reversible default; gates when the full claim can be made.
2. **Registry hosting + revocation authority:** who operates the signed denylist + compromise-monitoring, and the revocation-fetch TTL (minutes of exposure on a compromised-publisher incident). A standing role, not a static index.
3. **Re-release version line for the rewritten references** (`0.2.0` vs `1.0.0`).
4. **`connector_kind` namespacing:** globally-unique vs publisher-namespaced (`owner/kind`, Terraform model). Blocks the registry collision rule (protocol spec §6/§11).

> _(Resolved, moved out of "open": the acceptance-test gate is **required** — run against a recorded cassette to stay mechanical — AND enforced as a runtime dispatch invariant, see §4. The earlier "parked/undecided" framing was a contradiction the redteam caught.)_

---

## 10. References (key sources; full set in the research dossier)

- n8n node architecture + community-node risk model; the Jan-2026 supply-chain campaign; CVE-2025-68613 / CVE-2025-68668 — `docs.n8n.io`, `thehackernews.com/2026/01/...`, `resecurity.com`.
- Airbyte low-code CDK + Connector Builder + connector-support-levels + protocol versioning — `docs.airbyte.com`.
- Pipedream managed auth (`this.$auth`, 2,500+ apps) + per-invocation micro-VM isolation.
- Python entry-points (`importlib.metadata`, the `pytest11` model), `stevedore`, `pluggy`; PEP 420 namespaces.
- Supply-chain provenance: PyPI Trusted Publishers + PEP 740 attestations, Sigstore, SLSA.
- HACS / Terraform Registry / VS Code Marketplace / WordPress — registry + verification-tier models.

---

## 11. OSS ↔ enterprise boundary (governance + Rust `dc-enterprise` alignment)

The connector protocol is an **open Foundation standard (CC BY 4.0)** — `02-protocol-spec.md`.
The Foundation publishes a **full-featured Apache-2.0 Python implementation** + reference hub;
it is **not** a teaser or community-edition funnel to a paid tier.

**`dc-enterprise` is an INDEPENDENT Rust implementation of the same protocol.** Both conform to
the same normative spec and the same cross-language test vectors (`specs/canonical-signing-bytes.md`
§6). **Shared protocol, divergent implementations** — this is the alignment mechanism: the Rust
tier aligns to the _spec + vectors_, never to the Python source.

Per `rules/terrene-naming.md` + `rules/independence.md`: `dc-enterprise` is **not** a Foundation
artifact, MUST NOT be cited as "the reference," and the relationship MUST NOT be described as
donated / licensed-from / derived-from. **Commercial offerings any entity (including the operator
of `dc-enterprise`) may build on the open protocol** — private/internal registries, premium
connector catalogs, SLA hosting, sandbox-as-a-managed-service, usage metering/billing — are **not**
Foundation tiers. Drawing this line now is cheap; retrofitting private-registry support, license
headers, and per-tier capability gating after the open architecture calcifies is expensive.

## 12. Tracked completeness gaps (redteam — address in the protocol spec before freeze)

These are real omissions the redteam surfaced; captured here + in `02-protocol-spec.md` so they
are not lost. **Must-address-in-spec:** inbound/trigger/**read-connector** modeling (the design is
send-centric, but `read` is 1 of 4 ABC methods, WhatsApp is webhook-driven, and "beat n8n" is a
_trigger_ product — who owns the public webhook socket at scale, and how is `AttestedReadReceipt`
produced for platform-ingested data?); **multi-tenancy** isolation invariant (a correctly-signed
receipt for the _wrong tenant's_ data is NOT caught by the signed-receipt substrate); platform
**rate-limiting/quota** (allowed-host at 10k req/s is still DoS); `connector_kind` **namespacing**
(§9.4). **Defer-with-tracking-note:** observability/metering for any billed tier (SHOULD derive
from the signed audit chain, not a parallel counter); discovery/search/ranking UX; broker
credential-rotation lifecycle.

---

## Redteam revision log

- **2026-06-01** — 4-lens adversarial redteam (workflow `wf_405bd2d6-850`). Verdict: design
  `approve-with-edits`, cross-impl-alignment `needs-revision`. Applied: narrowed the §2/§3.2/§3.5/§4
  trust over-claims verified false in source (credential-blindness, unforgeability, capability-bounded);
  reframed the broker as a signing-surface refactor; added the conformance-vector dependency; resolved
  the acceptance-test contradiction (required + runtime invariant via cassette); added this enterprise
  boundary (§11) and the tracked completeness gaps (§12). Authored the normative protocol spec
  (`02-protocol-spec.md`) + the byte-pinned crypto core (`specs/canonical-signing-bytes.md`) — the
  cross-impl contract the Rust tier aligns to. Full disposition: redteam workflow output + this log.
