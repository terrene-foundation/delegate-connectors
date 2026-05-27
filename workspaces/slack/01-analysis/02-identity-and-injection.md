# 02 — Identity Model + Outbound Injection Boundary

> Claim cluster for brief open questions #2 (identity/directory resolution key)
> and #3 (Block Kit / mrkdwn injection surface). Grounded in shipped kailash 2.26.2
> introspection + the inherited email ADR-1 (subclass `Connector` directly) and the
> email `DelegateIdentity` ref-field discovery (`workspaces/email/journal/0006`).

## 1. Identity model — Slack ids vs email addresses (open question #2)

### The shared SDK constraint, and where Slack DIVERGES from email

The shipped `DelegateIdentity` validates its `sovereign_ref` / `role_binding_ref` /
`genesis_ref` fields against `^[a-zA-Z0-9_-]+$` (`kailash.delegate.types`, via
`validate_id`). The email connector hit this: an email address contains `@` and `.`
and is REJECTED at `DelegateIdentity` construction, so email resolves identity by
`delegate_id` (UUID) only, and the literal email lives on the payload + `Principal`
claims (`workspaces/email/journal/0006`).

**Verified delta for Slack (introspected against the wheel):** Slack ids are
alphanumeric-safe and PASS the same regex —

| literal               | matches `^[a-zA-Z0-9_-]+$` | `DelegateIdentity` ref accepts |
| --------------------- | -------------------------- | ------------------------------ |
| `U07ABCDE123` (user)  | yes                        | ACCEPTED                       |
| `C0123456789` (chan)  | yes                        | ACCEPTED                       |
| `W0XYZ…` (Enterprise) | yes                        | ACCEPTED                       |
| `alice@example.com`   | no (`@`, `.`)              | REJECTED (email's problem)     |

So Slack has a cleaner identity story than email: the Slack user id CAN ride on a
`DelegateIdentity` ref field if desired. But for v0 the dispatch resolution key
MUST stay the **`delegate_id`** — for two reasons that survive the difference:

1. **Cross-connector uniformity.** The dispatch surface resolves a connector by
   `authenticate(identity, envelope)`; the runtime hands the connector a
   `DelegateIdentity` whose stable dispatch key is `delegate_id`. Resolving by
   `delegate_id` keeps `SlackConnector.authenticate` byte-identical in shape to
   `EmailConnector.authenticate` (same fail-closed contract, same resolver call) —
   the brief's whole point is "same ABC, different transport".
2. **Stability across handle changes.** A Slack user id is stable; a `delegate_id`
   UUID is stabler still and decoupled from Slack's namespace. Keying on
   `delegate_id` means a workspace migration or id remap does not re-root the
   dispatch identity (the same argument email's journal 0006 made for the UUID key).

### RECOMMENDATION (resolves open question #2): dual-keyed resolver, `delegate_id` primary

Mirror email's `EmailPrincipalResolver` exactly. `SlackPrincipalResolver` is
constructed from a mapping of **Slack id → `Principal`** and builds TWO indices:

- **`by_delegate_id`** (PRIMARY) — `authenticate` resolves the dispatch identity's
  `delegate_id` against this index. Unknown → fail-closed
  `ConnectorAuthenticationError` (closed-enum `Reject`).
- **`by_slack_id`** (SECONDARY, literal) — keyed on the normalized Slack id, for
  payload-side resolution (which user/channel a `chat.postMessage` is attributed
  to / a `conversations.history` read is scoped to). The literal Slack id lives on
  the message payload + `Principal.claims`, exactly as email puts the literal email
  on the payload.

This is email's dual-key pattern (`delegate_id` + literal) with `literal = Slack id`
instead of `literal = email address`. Resolution key precedence is identical:
`delegate_id` is the authority axis; the Slack id is the presentation/payload axis.

#### Normalization for Slack ids (the analogue of `normalize_address`)

Slack ids are case-sensitive opaque tokens (`U07ABCDE123`, NOT lowercased like an
email). `normalize_slack_id` therefore:

- strips surrounding whitespace,
- validates the shape (`^[UWCGD][A-Z0-9]+$` — `U`/`W` users, `C` public channels,
  `G` private/group, `D` DMs) and REJECTS anything else with a typed error,
- does NOT lowercase (Slack ids are case-significant; lowercasing would break the
  index).

Note the divergence from email's `normalize_address` (which lowercases and strips
display names). Slack ids carry no display name and are case-significant — the
normalizer is shape-validation + trim only.

### Channel ids vs user ids — both are `Principal`-keyable

Brief open question #2 asks whether the primary key is "user id, or user id +
workspace id". For v0 (single pre-installed bot token, single workspace — brief
§ open question #5), the workspace is implicit in the bot token, so a bare Slack id
(`U…` or `C…`) is unambiguous. The resolver keys on the bare Slack id; the workspace
(team) id is recorded in `Principal.claims` for forward-compat with multi-workspace
OAuth (a later shard) WITHOUT becoming part of the v0 lookup key. This does not
block the multi-workspace path: when OAuth lands, the key becomes
`(team_id, slack_id)` and `Principal.claims["team_id"]` is already populated.

## 2. Outbound injection boundary (open question #3)

### The Slack injection surface vs email's CR/LF header injection

Email's injection vector is **CRLF header injection** (`smtp.py::validate_header_field`
rejects `\r`/`\n`/`\x00`/control chars in `sender`/`to`/`subject`). Slack's
`chat.postMessage` is a **JSON Web API call**, not a line-delimited protocol, so
CRLF header injection does NOT apply. Slack's injection surfaces are different:

1. **Channel/identity field injection.** The `channel` argument and any id-bound
   field MUST be a validated Slack id (`^[UWCGD][A-Z0-9]+$`), NOT arbitrary text —
   an unvalidated `channel` could redirect a post to an unintended conversation.
   This is the Slack analogue of email's header-field validation: validate the
   id-bound fields at the message-construction boundary.
2. **Block Kit JSON structural injection.** If v0 accepted caller-supplied raw
   `blocks` / `attachments` JSON, a crafted payload could inject unintended
   interactive elements, or (via string concatenation into a JSON template) break
   out of the intended structure. The defense is: **never string-build JSON.**
3. **mrkdwn vs plain-text rendering.** Slack `text` is rendered as mrkdwn by
   default (so `<!channel>`, `<@U…>`, `<http://…|click>` link/mention syntax in
   user-controlled text becomes a live mention/link). For v0 the safe default is to
   send with `mrkdwn` semantics controlled by the connector, not by injected text.

### RECOMMENDATION (resolves open question #3): two-layer validation at the OutboundSlackMessage boundary

Mirror email's single-boundary defense (`OutboundMessage.__post_init__` validates
every header field so EVERY send route is covered). For Slack:

- **`OutboundSlackMessage`** dataclass (frozen) validates at construction
  (`__post_init__`):
  - `channel` MUST pass `normalize_slack_id` shape-validation → typed
    `SlackFieldError` on a malformed id (the Slack analogue of
    `HeaderInjectionError`). This is the id-injection boundary.
  - `text` is **plain text** in v0. The connector escapes the three Slack
    mrkdwn-control sequences (`&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`) per
    Slack's documented text-escaping contract, so user-controlled text CANNOT
    inject a live `<@U…>` mention, `<!channel>` broadcast, or `<url|label>` link.
    This is the mrkdwn-injection boundary.
- **Block Kit JSON is OUT of v0 scope** (brief § out-of-scope: "rich Block Kit
  composition beyond a baseline text message"). v0 ships a **baseline text message
  only** — no caller-supplied `blocks`/`attachments`. This removes the structural-
  JSON-injection surface entirely for v0 (you cannot inject into a structure that
  is not exposed). When Block Kit lands (later shard), blocks MUST be constructed
  from typed builders (never string-concatenated JSON) and serialized via the SDK's
  own JSON encoder — the framework-first defense against structural injection.

The validation boundary is therefore the **`OutboundSlackMessage` construction
seam**, identical in placement to email's `OutboundMessage.__post_init__`: every
send route (the `invoke` hot path and any direct `write`) builds an
`OutboundSlackMessage` first, so no route can bypass id-validation + text-escaping.

### Cons (honest)

- **Text-escaping changes what the user sees.** A user who legitimately wanted to
  send the literal characters `<`/`>`/`&` sees them rendered as typed (escaped),
  not as Slack formatting. For v0 (a connector that sends a plain notification),
  this is the correct safe default — formatting is a v1 Block Kit concern. Document
  it so it is not a surprise.
- **No rich formatting in v0.** Plain text only. Acceptable per brief scope; the
  cost is a less pretty message, not a capability gap for the reference connector.

## Citations

- `DelegateIdentity` ref regex + Slack-id pass/fail: introspected `kailash.delegate.types`
  against the wheel (this session); email precedent `workspaces/email/journal/0006`.
- Dual-keyed resolver pattern: `connectors/email/src/delegate_connectors/email/directory.py::EmailPrincipalResolver`.
- Single-boundary injection defense: `connectors/email/src/delegate_connectors/email/smtp.py::validate_header_field` + `OutboundMessage.__post_init__`.
- v0 out-of-scope (Block Kit beyond baseline text): `workspaces/slack/briefs/01-brief.md`.
