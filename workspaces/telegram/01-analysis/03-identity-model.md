# 03 — Telegram identity model + principal resolution

Resolves open question #2 (the directory's primary resolution key) against the
shipped `DelegateIdentity` constraint and the inherited dual-key resolver pattern.

## The shipped DelegateIdentity constraint (re-verified for Telegram shapes)

The email connector discovered (`workspaces/email/journal/0006-DISCOVERY-*`) that
`DelegateIdentity`'s ref fields (`sovereign_ref` / `role_binding_ref` /
`genesis_ref`) are validated against `^[a-zA-Z0-9_-]+$` — an email address
(containing `@` and `.`) is REJECTED at construction. I re-introspected the wheel
with Telegram-shaped values:

```
$ .venv/bin/python  # kailash 2.26.2
>>> DelegateIdentity(delegate_id=uuid4(), sovereign_ref="123456789",
...     role_binding_ref="tg-chat-987654321", genesis_ref="tg-genesis",
...     principal_kind="delegate")
ACCEPTED   sovereign_ref="123456789"  role_binding_ref="tg-chat-987654321"

>>> DelegateIdentity(..., sovereign_ref="@alice", ...)
REJECTED   ValueError: contains unsafe characters (must match ^[a-zA-Z0-9_-]+$)
```

Findings:

- Telegram's **integer `user_id` / `chat_id`, stringified** (`"123456789"`,
  `"987654321"`), PASS the ref regex — digits and `-` are in the allowed set.
  This is BETTER than email: the channel's native identifiers are already
  ref-safe, no transformation needed.
- Telegram **`@username` handles are REJECTED** (the `@` is unsafe) — the exact
  same failure mode as an email address. So a Telegram `@handle` CANNOT ride on a
  `DelegateIdentity` ref field; only the numeric id can.

## Identity facts about Telegram (Bot API semantics)

- A bot sees the sender's integer **`user_id`** on direct (private-chat) messages.
- A bot sees the **`chat_id`** for the conversation: for a private chat `chat_id`
  == the user's `user_id`; for a group/supergroup `chat_id` is the negative group
  id and is distinct from any member's `user_id`.
- `@username` is an optional, mutable display handle — NOT a stable key (a user
  can change or remove it). The integer `user_id` is the stable identity.

## Resolution decision (mirrors email's dual-key resolver)

The email resolver (`directory.py::EmailPrincipalResolver`) is dual-keyed: by
normalized email AND by `delegate_id` string, because `authenticate` resolves by
`delegate_id` (the ref-safe key) while the literal email lives on the payload.
Telegram lifts this pattern with the integer ids as the native keys:

- **Primary resolution key for `authenticate`: the dispatch identity's
  `delegate_id`** (a UUID) — identical to email. `authenticate(identity, ...)`
  resolves `str(identity.delegate_id)` against the resolver's delegate_id view.
  This is the inherited contract; the channel does not change it.
- The resolver is **dual-keyed by `user_id` AND `chat_id`** (both stringified
  integers), in addition to the `delegate_id` view. Rationale: a direct sender is
  resolved by `user_id`; a group message is resolved by `chat_id` (since the
  sender's `user_id` may not be the addressable principal for a group bot). Both
  keys are ref-safe and can ALSO ride on the `DelegateIdentity` ref fields
  (`sovereign_ref` = `user_id`, `role_binding_ref` = `chat_id`) — unlike email,
  where the address could not.
- `@username` is NEVER a resolution key (mutable + ref-unsafe). If a caller
  supplies a `@handle`, it is treated as un-resolvable → `Reject` (fail-closed),
  exactly the unknown-sender disposition.

So the directory's primary key is `delegate_id` (for the ABC `authenticate`
contract), with a dual `user_id`/`chat_id` view for transport-side resolution —
the same shape as email's `delegate_id` + email dual-keying, with the channel's
two native integer ids replacing email's single address.

## Unknown-identity disposition

Unchanged from the inherited contract: an unresolved `user_id`/`chat_id`/handle →
`ConnectorAuthenticationError` (the closed-enum `Reject`, fail-closed), raised
BEFORE any Bot API call on the `invoke` hot path. `Accept` is reserved for resolved
principals; `EscalateToHuman` for a later policy shard.

## For Discussion

1. For a group message, the addressable principal is the `chat_id`, not the
   sender's `user_id`. If the resolver keys BOTH, which one wins when a message
   carries both a known `user_id` and a known-but-different `chat_id` — and does
   the conformance `BehaviouralOutcome` (outcome-keyed, not key-keyed) even see
   the difference?
2. `@username` is rejected as ref-unsafe AND as mutable. If the SDK had permitted
   `@`-shaped refs, would binding to the mutable handle have re-created the
   address-change-re-roots-identity fragility that email's journal/0006 §2 flagged
   for email addresses?
3. Telegram's integer ids are ref-safe where email's address was not — so for
   Telegram the `user_id`/`chat_id` CAN ride on `DelegateIdentity` ref fields.
   Does using the ref fields (vs the delegate_id-only keying email was forced
   into) add resolution robustness, or does it just create two resolution paths
   that can drift?
