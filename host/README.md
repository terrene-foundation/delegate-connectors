# delegate-connectors-host

The **host-side trust surface** for the Terrene Delegate connector platform.

This package is the _trusted host_. Connectors are untrusted consumers; the host owns what a
connector must never hold:

- **Credential broker + `BoundTransport`** — the host owns `from_env()` and injects an opaque,
  non-introspectable handle. The connector declares `requires_credentials` and receives a handle
  exposing only `send()`/`fetch()` — never a raw secret.
- **Host-side signing** — the host holds the Ed25519 key and signs only over the side effect it
  itself brokered and observed (a connector cannot forge a receipt for a delivery that never happened).
- **Production trust primitives** — `KnowledgeLedger` / `RevocationChannel` concretes replacing the
  in-connector placeholders (`NeverRevokedChannel→False` is deleted).

The host↔connector package boundary **is** the trust boundary established in Phase 0 of the
connector-platform pivot. See `workspaces/connector-platform/02-plans/01-architecture.md` §3.5 and
the Phase-0 todo set (`workspaces/connector-platform/todos/active/`).

Conform to the frozen crypto core at `specs/canonical-signing-bytes.md` (v1) — never edit §1–§6.

**Status:** Alpha — Phase 0 in progress. Not yet published.

License: Apache-2.0 — Terrene Foundation.
