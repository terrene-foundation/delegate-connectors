# Specs Index — delegate-connectors

Domain specifications for the OSS Python connector monorepo. Authority on each
topic; downstream code + red team verify against these. Grounded in shipped
`kailash.delegate` (kailash 2.26.2), NOT the README/issue prose (both stale — see
`connector-contract.md` § Divergence).

| Spec                                             | Domain             | One-line                                                                                                   |
| ------------------------------------------------ | ------------------ | ---------------------------------------------------------------------------------------------------------- |
| [connector-contract.md](connector-contract.md)   | Connector ABC      | The shipped `Connector` interface every connector implements                                               |
| [runtime-composition.md](runtime-composition.md) | Delegate runtime   | How a connector wires into `DelegateRuntime` + `DispatchSurface`                                           |
| [email-connector.md](email-connector.md)         | Email connector    | The email connector's v0 behavior (SMTP write / IMAP read / authenticate)                                  |
| [slack-connector.md](slack-connector.md)         | Slack connector    | The slack connector's v0 behavior (`chat.postMessage` write / `conversations.history` read / authenticate) |
| [telegram-connector.md](telegram-connector.md)   | Telegram connector | The telegram connector's v0 behavior (Bot API `sendMessage` write / `getUpdates` read / authenticate)      |
| [test-infrastructure.md](test-infrastructure.md) | Test infra         | 3-tier test topology; Mailpit real-infra; in-memory audit                                                  |
| [conformance.md](conformance.md)                 | Conformance        | Vector contract + the sourcing/runner gap (BLOCKED — see file)                                             |
| [monorepo-layout.md](monorepo-layout.md)         | Packaging          | `connectors/email/` package shape, namespace, licensing                                                    |

## Status

- **Determined (buildable now)**: connector-contract, runtime-composition,
  email-connector, test-infrastructure, monorepo-layout.
- **Gated**: conformance — depends on sourcing the canonical vectors from kailash-py
  (cross-repo read; needs user authorization per `repo-scope-discipline.md`).
