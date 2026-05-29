# Todo 14 — Bound the `ServiceWindowTracker._last_inbound` map

**Implements:** workspaces/whatsapp/02-plans/02-connector-spec.md § Outbound gating (template + service window)
**Type:** Build (security hardening) · **Capacity:** single shard (~80 LOC, 3 invariants)
**Depends:** 06 (template-window-gate, already complete)
**Origin:** Wave-1 security review (L1, 2026-05-28). Defense-in-depth before the Cloud API transport (todo 03) ships and the buffer becomes reachable in real deployments.

## Do

- `connectors/whatsapp/src/delegate_connectors/whatsapp/templates.py` — convert
  `ServiceWindowTracker._last_inbound` from an unbounded `dict` to a bounded LRU
  cache (`collections.OrderedDict` with `move_to_end` on record, `popitem(last=False)`
  on overflow) parameterized by a `max_entries` constructor kwarg (default tuned
  per the spec — propose 100_000 in the PR for review).
- On every `record_inbound`: move the key to the MRU position; if size exceeds the
  cap, evict the oldest entries until the cap holds.
- On every `is_window_open`: pure read; do NOT move the key (a window-state check
  is not "activity" — keys are added/refreshed only on actual inbound).
- Add `ServiceWindowTracker.size` property for observability + testing.

## Invariants (3)

1. `record_inbound` never grows `_last_inbound` beyond `max_entries` (evicts on overflow).
2. `is_window_open` is a pure read; it does NOT mutate ordering (only `record_inbound` does).
3. Eviction is FIFO-by-record-time (the oldest recorded entry evicts first when full).

## Acceptance

- [ ] Unit test: 200 distinct inbounds against a `max_entries=100` tracker → `size == 100`, the oldest 100 keys evicted, the newest 100 retained.
- [ ] Unit test: `is_window_open` calls do NOT alter the eviction order.
- [ ] Unit test: a key recorded at t=0, then recorded again at t=10, stays open at t=10+SERVICE_WINDOW_SECONDS-1 (the refresh works through the cap).
- [ ] No existing template/window test regresses (run `PYTHONPATH=connectors/whatsapp/src .venv/bin/python -m pytest connectors/whatsapp/tests/unit/test_templates.py -q`).
