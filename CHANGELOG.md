# Changelog

All notable changes to the Terrene Delegate connectors are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the connectors follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file covers all four connectors, which release together at a shared version:
`delegate-connector-email`, `delegate-connector-slack`,
`delegate-connector-telegram`, and `delegate-connector-whatsapp`.

## [0.1.1] - 2026-06-01

### Fixed

- **Documentation accuracy.** Removed the stale "Known limitation — runtime
  `execute()` audit gate" sections from all four connector READMEs (the
  long-description shown on each PyPI page). Those sections described an SDK
  audit-emit bug (kailash-py#1182) that fails `runtime.execute()` — but that bug
  was fixed at `kailash >= 2.28.0`, which is the connectors' dependency floor.
  `runtime.execute()` now runs the full signed dispatch end-to-end. Replaced with
  an accurate "Runtime execution — end-to-end" section plus a historical note.
- Corrected the matching stale `compose.py` docstring cross-references
  ("see the module-level KNOWN SDK BLOCKER") in all four connectors.

No code behavior changed — documentation-only patch.

## [0.1.0] - 2026-06-01

Initial public release. Four OSS connectors for the Terrene Delegate substrate
(`kailash.delegate`), each composing a real signed `runtime.execute()` end-to-end
on the Kailash Python SDK (`kailash >= 2.28.0`).

### Added

- **email** — SMTP send / IMAP read connector with async transports
  (`aiosmtplib`, `aioimaplib`).
- **slack** — Slack Web API connector.
- **telegram** — Telegram Bot API connector.
- **whatsapp** — WhatsApp Cloud API connector (freeform sends require an open
  24-hour customer-service window).
- Canonical conformance vector suites with a per-vector driver running real
  signed-envelope outcomes for every connector.
- Ed25519-signed action envelopes verified end-to-end through the Kailash
  runtime audit chain.

[0.1.1]: https://github.com/terrene-foundation/delegate-connectors/releases/tag/v0.1.1
[0.1.0]: https://github.com/terrene-foundation/delegate-connectors/releases/tag/v0.1.0
