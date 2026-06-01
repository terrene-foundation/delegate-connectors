# Market Research Dossier — How thousands-of-contributor plugin ecosystems scale

**Date:** 2026-06-01
**Method:** 11-agent adversarial workflow (`wf_d3f9341a-899`): 6 parallel research deep-dives
(web + primary sources) → synthesis → 3 adversarial stress-tests → final reconciliation.
**Scope:** n8n, Airbyte/Singer/Meltano/Pipedream, WordPress/HACS/VS Code/Terraform/Obsidian,
Python plugin mechanics + sandboxing, supply-chain provenance.

This file records the evidence the architecture (`02-plans/01-architecture.md`) is grounded in.

---

## n8n (the target)

**Authoring:** two node styles — programmatic TypeScript node classes, and a "declarative"
node JSON (`description` object) for simple REST. `@n8n/node-cli` (new/dev/lint/build/release)

- `n8n-nodes-starter`.
  **Distribution/discovery:** community nodes are `n8n-nodes-*` npm packages; **no first-party
  marketplace** — users npm-spelunk. Verified vs community tiers; verified mandates provenance
  (only since May 2026).
  **Security — the fatal flaw:** a community node calls `getCredentials()` → receives **decrypted**
  credentials, runs **in-process at full host privilege.** Manual human review is a documented
  **3-week-to-3-month** bottleneck. `n8n-nodes-base` monorepo is the structural bottleneck on
  official-integration throughput.
  **Incidents to beat:** Jan-2026 supply-chain campaign (malicious community nodes siphoning
  creds); CVE-2025-68613 (expression-injection RCE); CVE-2025-68668 (in-process sandbox escape).
  **Lessons:** decentralized package + naming convention + auto-discovery (good); credential
  brokering + capability manifests + sandbox + static-lint-on-ingest + provenance-for-all +
  automated tiered admission + a real registry (the gaps to close).
  **Cites:** docs.n8n.io/integrations/{creating-nodes,community-nodes}; `@n8n/eslint-plugin-community-nodes`;
  thehackernews.com/2026/01/n8n-supply-chain...; resecurity.com CVE-2025-68613; community.n8n.io
  threads on review backlog + "Unrecognized node type" upgrade breakage.

## Airbyte / Singer / Meltano / Pipedream (connector platforms)

- **Airbyte low-code CDK** — declarative YAML connector format (auth + pagination + rate-limit +
  error-handling + endpoint mapping as configured primitives). **The single biggest scaling
  lever:** most connectors are HTTP APIs and need **no code**. Connector Builder UI ⇄ YAML is
  **round-trippable (one artifact, two surfaces).** 100+ marketplace connectors in one 6-month
  window. Registry generated from per-connector **metadata files** (never hand-curated). Formal
  breaking-change protocol: SemVer + machine-readable `breakingChanges` + `upgradeDeadline` +
  CI-enforced migration note + `scopedImpact`. **Protocol versioned independently** of connectors.
- **Pipedream** — **managed auth for 2,500+ apps** (`this.$auth`): the platform owns credentials,
  contributor code never sees raw long-lived secrets. **Per-invocation micro-VM isolation** +
  KMS-encrypted creds. Capability annotations (`readOnlyHint`/`destructiveHint`). In-product
  "Contribute to Marketplace" opens a GitHub PR from the builder.
- **Singer/Meltano** — taps/targets spec + Hub. **Variant fragmentation** is the documented pain
  (N implementations of the same connector, opaque quality) → Meltano's explicit
  variant+recommended-default + per-plugin `.lock` for reproducibility.
- **Lessons:** declarative-by-default for the REST long tail; one round-trippable artifact;
  generated registry from metadata; **solve auth once at the platform** (broker, never per-connector);
  formal breaking-change protocol; decouple wire-contract version from connector versions; 2–3
  clear trust tiers; isolate untrusted code at runtime; prevent variant proliferation; lockfile pinning.
- **Cites:** docs.airbyte.com/platform/connector-development/{config-based,connector-builder-ui,
  connector-metadata-file}; airbyte.com/blog/maintaining-hundreds-of-api-connectors...; hub.meltano.com;
  Pipedream component docs.

## WordPress / HACS / VS Code / Terraform / Obsidian (mass ecosystems)

- **WordPress** — the canonical thousands-of-contributors directory + review process.
- **HACS (Home Assistant)** — community integrations are **git repos installed at runtime**, not
  packages; huge ecosystem; by-URL escape hatch marked higher-risk.
- **VS Code Marketplace** — manifest/permissions, publisher verification; capability declaration as
  a ranking/trust signal.
- **Terraform Registry** — providers published to a **registry** with **signing** and namespaced
  `owner/provider`; `protocol_versions` (5.0/6.0) negotiation.
- **Obsidian** — git-repo-based community plugins + review.
- **Lessons:** a generated thin-index registry; explicit review/verification tiers; capability/permission
  declaration visible at install; signing/provenance; by-URL escape hatch for the unlisted (marked
  risky); plan for long-tail decay (adopt-to-revive + acceptance tests).

## Python plugin mechanics + sandboxing

- **Entry points** (`importlib.metadata`, `[project.entry-points]`) — the modern standard; the
  `pytest11` model: install == registration, `O(1)` host discovery. **`stevedore`** (OpenStack)
  for namespaced driver loading; **`pluggy`** for hook-based extension. **PEP 420** namespace
  packages let siblings coexist (already used: `delegate_connectors.*`).
- **Critical:** `entry_points(...).load()` **imports the module** → discovery of a code plugin
  **is** code execution. Discovery must be separated from a gated load path.
- **Sandboxing untrusted Python:** in-process sandboxes (RestrictedPython, etc.) are **disqualified**
  — live escape CVEs. Viable: **out-of-process** subprocess under **gVisor/seccomp** (3–20% overhead),
  **microVM/Firecracker** (startup latency), **WASI-component** (strong isolation but loses native
  transports — an SMTP/IMAP connector can't run without host-provided socket capabilities).
- **Cites:** packaging.python.org entry-points; pytest plugin docs; stevedore docs; gVisor/seccomp docs.

## Supply-chain provenance + trust (the differentiator)

- **Attacks:** npm/PyPI typosquatting, dependency confusion, compromised-publisher silent re-publish
  (Shai-Hulud, event-stream class, the n8n 2026 campaign).
- **Defenses:** **Sigstore/cosign**, **npm provenance attestations**, **PyPI Trusted Publishers +
  PEP 740 attestations**, **SLSA** levels; content-hash pinning; signed monotonic revocation denylists.
- **Capability/permission models:** browser-extension Manifest V3 permissions, VS Code capabilities,
  OpenBSD pledge/unveil, object-capability security.
- **Lesson for Delegate:** the signed-envelope + capability + audit substrate is a **second, stronger
  provenance story** (the connector's own runtime claims are cryptographically verifiable post-hoc) —
  _but only once credential-brokering + capability-enforcement + sandbox make it real._

## Internal grounding (the `Connector` ABC)

`kailash.delegate.dispatch.Connector`: abstract method `invoke`; also `authenticate`/`write`/`read`;
class attrs `connector_id`, `connector_kind`, `requires_capabilities` (frozenset of capability
strings); trust properties `auth_verifier`/`ledger`/`revocation`. A connector is constructed and
wired into a `DelegateRuntime`/`DispatchSurface` via a ~250-LOC `compose.py` ceremony, hand-copied
across all four connectors. The shipped substrate enforces signed receipts + capability-subset
gating (bind + per-dispatch) + fail-closed authenticate + audit chain — but **today** connectors
self-acquire credentials (`os.environ`), hold the raw signing key, and ship `NeverRevokedChannel→False`.
See the architecture doc §2 table for the file:line evidence.

---

## Adversarial stress-test verdicts

| Lens                          | Verdict                  | Load-bearing fix                                                                                                                                                                                                                                           |
| ----------------------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Supply-chain / untrusted-code | **needs major revision** | Re-sequence by threat: lead with the declarative tier (safe by construction); gate code-connector `.load()` behind a provenance allowlist; stop claiming credential-blindness until the broker exists; package-level revocation + content-pinning day one. |
| Scale / maintenance           | sound with fixes         | Versioned factory + `delegate_host_protocol`; production trust concretes; capped `kailash` range; fault-isolating discovery sweep; versioned `delegate-conformance` package; registry is a security-response authority, not a static index.                |
| Contributor DX                | sound with fixes         | Declarative tier first; factory must absorb resolver + default transports (target <50 LOC for a code connector, ~40 lines YAML for declarative); record-and-replay acceptance gate; present-tense honesty banner.                                          |
