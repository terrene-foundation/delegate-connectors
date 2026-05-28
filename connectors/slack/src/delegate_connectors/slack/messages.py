# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Slack message types + the single injection-validation boundary.

The construction boundary IS the validation boundary (ADR-S3): every outbound
send route builds an :class:`OutboundSlackMessage` FIRST, and that class's
``__post_init__``:

1. shape-validates every id-bound field (``channel``) via
   :func:`normalize_slack_id`, and
2. mrkdwn-escapes the user-controlled ``text`` (``&`` -> ``&amp;``,
   ``<`` -> ``&lt;``, ``>`` -> ``&gt;``) per Slack's documented escaping
   contract,

so an injected ``<@U…>`` mention / ``<!channel>`` broadcast / ``<url|label>``
link cannot render live. Block Kit / ``attachments`` / ``blocks`` are OUT of v0
scope — there is deliberately NO structural-JSON surface here, which removes the
structural-injection vector entirely (ADR-S3).

``normalize_slack_id`` is shape-validate + trim only and is CASE-SIGNIFICANT (it
does NOT lowercase) — a deliberate divergence from email's ``normalize_address``,
because Slack ids are case-significant (see
``workspaces/slack/journal/0002-DISCOVERY-*``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "SlackFieldError",
    "normalize_slack_id",
    "escape_mrkdwn",
    "OutboundSlackMessage",
    "InboundSlackMessage",
]


class SlackFieldError(ValueError):
    """Raised when an id-bound field is malformed or a field is invalid.

    Raised at the :class:`OutboundSlackMessage` construction boundary — BEFORE
    any Slack Web API call — so every send route is covered. Also raised by
    :func:`normalize_slack_id` directly for standalone id validation (e.g. the
    principal resolver's stored + incoming Slack ids).
    """


# A Slack object id is an uppercase letter type-prefix (U user, C public channel,
# G private channel/group, D direct-message, W enterprise user, B bot, T team/
# workspace, etc.) followed by uppercase-alphanumeric base-34 characters. Slack
# ids are case-significant. We validate SHAPE only (a leading uppercase letter +
# >=8 uppercase-alphanumeric chars), NOT a closed prefix allowlist, so a new
# object type does not require a code change. Verified shapes (journal 0002):
#   U07ABCDE123  (user)      -> pass
#   C0123456789  (channel)   -> pass
_SLACK_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{7,}$")


def normalize_slack_id(value: str) -> str:
    """Shape-validate + trim a Slack id; return it UNCHANGED otherwise.

    Trims surrounding whitespace and validates the trimmed value against the
    Slack-id shape regex. Does NOT lowercase — Slack ids are case-significant
    (the divergence from email's ``normalize_address``). A malformed id raises
    :class:`SlackFieldError`.

    Applied IDENTICALLY to stored directory keys and incoming ids so resolution
    is symmetric (invariant 3 of the principal resolver).
    """
    if not isinstance(value, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise SlackFieldError(
            f"Slack id MUST be a str; got {type(value).__name__}"
        )  # pyright: ignore[reportUnreachable]
    trimmed = value.strip()
    if not _SLACK_ID_RE.match(trimmed):
        raise SlackFieldError(
            f"malformed Slack id {value!r}: expected an uppercase letter prefix "
            "followed by >=7 uppercase-alphanumeric characters (e.g. 'U07ABCDE123', "
            "'C0123456789'); ids are case-significant"
        )
    return trimmed


def escape_mrkdwn(text: str) -> str:
    """Escape the three mrkdwn metacharacters per Slack's escaping contract.

    Replaces ``&`` -> ``&amp;``, ``<`` -> ``&lt;``, ``>`` -> ``&gt;`` (``&``
    MUST be first so the ``&`` introduced by the ``<``/``>`` replacements is not
    double-escaped). After escaping, a user-supplied ``<@U123>`` /
    ``<!channel>`` / ``<https://evil|click>`` is inert text — Slack will NOT
    render it as a live mention, broadcast, or link.

    Reference: Slack "Formatting message text" — escape ``&``, ``<``, ``>`` and
    only those three.
    """
    if not isinstance(text, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise SlackFieldError(
            f"message text MUST be a str; got {type(text).__name__}"
        )  # pyright: ignore[reportUnreachable]
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass(frozen=True)
class OutboundSlackMessage:
    """A message to post via ``chat.postMessage``. Pure data — no transport.

    ``__post_init__`` is the single injection-validation boundary (ADR-S3):

    - ``channel`` is shape-validated via :func:`normalize_slack_id` (raises
      :class:`SlackFieldError` on a malformed id), and
    - ``text`` is mrkdwn-escaped via :func:`escape_mrkdwn`, so any injected
      ``<@U…>`` / ``<!channel>`` / ``<url|label>`` becomes inert.

    The dataclass is frozen (immutable). Because ``text`` is escaped IN
    ``__post_init__``, the stored ``text`` is the already-escaped, send-safe
    value — every read of ``msg.text`` after construction is the escaped form.
    """

    channel: str
    text: str

    def __post_init__(self) -> None:
        # Validate + normalize the id-bound field. Raises SlackFieldError before
        # any Web API call if the channel id is malformed.
        normalized_channel = normalize_slack_id(self.channel)
        # Escape the user-controlled text at the boundary so a live mention /
        # broadcast / link cannot render. & MUST be escaped first.
        escaped_text = escape_mrkdwn(self.text)
        # frozen=True forbids normal attribute assignment; use object.__setattr__
        # to write the validated/escaped values back (the documented pattern for
        # post-init normalization on frozen dataclasses).
        object.__setattr__(self, "channel", normalized_channel)
        object.__setattr__(self, "text", escaped_text)


@dataclass(frozen=True)
class InboundSlackMessage:
    """A normalized inbound message returned by the ``conversations.history`` pull.

    Pure data. ``channel`` is the channel id the history was pulled from, ``ts``
    is the Slack message timestamp id (the per-message canonical id), ``user`` is
    the author's Slack user id (may be empty for non-user events such as bot
    posts), and ``text`` is the raw message text as Slack returned it.

    Inbound text is NOT mrkdwn-escaped — escaping is an OUTBOUND render-safety
    concern. Inbound text is carried verbatim so a downstream consumer sees what
    Slack stored.
    """

    channel: str
    ts: str
    user: str
    text: str
