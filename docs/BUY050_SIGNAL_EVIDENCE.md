# BUY050 LIVE cBots Signal → Broker Evidence (read-only)

**Scope:** LIVE cTrader account suffix 7903, frozen BUY050 profile SHA
`13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6`.

This instrumentation does not build/restart/redeploy a cTrader instance, write
VPS checkpoint/bridge DBs, acquire leases, modify positions, or request orders.
It uses a separate GitHub Actions worker and ephemeral read-only SQL / Open API.

## Active components

- `scripts/watch_buy050_native_events.py`: samples the BUY050 bridge's
  durable checkpoints with 1s cadence during a job; guards native identities
  and emits sanitized transitions `SIGNAL_RECORDED`, `INTENT_PREPARED`,
  `BASKET_STATE_ACTIVE`, quarantine/fault, and exit-pending.
- `scripts/collect_buy050_execution_evidence.py`: read-only cTrader
  `ProtoOAReconcileReq`, `ProtoOAOrderListReq`, `ProtoOADealListReq`
  with strict allowed-message filtering, 48h bounded history, and account,
  symbol, and native BUY050 label checks.
- `scripts/merge_buy050_event_audit.py`: normalizes observations, preserves
  48h of redacted evidence on the isolated
  `buy050-event-audit` branch, and detects unsampled gaps between jobs.
- `src/fx_scanner/cbot_buy050_event_dashboard.py`: read-only chronology in
  the cBots tab.
- `.github/workflows/buy050-event-audit-readonly.yml`: runs every ~5m;
  scheduled observation windows are 250 seconds. GitHub Actions schedules
  are best effort and may be delayed. Push tests deliberately sample only
  15 seconds to reduce account/API load.

## Evidence hierarchy

1. **Technical signal:** independent BUY050 frozen-source calculation; not
   proof of a native decision.
2. **SIGNAL_RECORDED:** native checkpoint's `LastSignalUtc`/BTC `LastSignal`
   advanced during observed polling (or inferred between poll windows).
   This is not proof that an order was sent.
3. **INTENT_PREPARED:** native pending intent became active; not proof of
   broker acceptance.
4. **BASKET_STATE_ACTIVE:** a basket exists in checkpoint; not proof of fill.
5. **BROKER_ORDER_ACCEPTED/FILLED/REJECTED:** broker order-history record
   with matching BUY050 native label; closing orders excluded.
6. **BROKER_DEAL_FILLED/PARTIAL/REJECTED/ERROR/NO_RESPONSE:** broker
   execution-history record with a matching BUY050 native label; closing
   deals excluded.
7. **BROKER_OPEN_POSITION_OBSERVED:** broker reconciled an open position with
   the native BUY050 label. Does not establish whether historical positions
   were closed before this poll.

Never infer rejection or missing entries from an absent open position, absent
deal, stale data or missed sampling. A record in `BROKER_DEAL_NO_RESPONSE`
is cTrader's deal-status `MISSED` (LP did not respond); it does **not** mean
the strategy skipped an eligible setup.

## Coverage and limitations

- Read frequency is 1s **within** the sampling job, not nonstop all-day
  capture, and dashboard delivery is periodic, not one-second streaming.
- The UI shows `unobserved_gap_s`. Any gap >2s invalidates a claim of
  continuous capture. Delayed GitHub runners can create larger gaps.
- The native checkpoint stores the latest signal, not the full pre-gate
  decisions. A BUY050 signal blocked before the checkpoint update cannot be
  reconstructed from this monitor alone.
- cTrader Cloud cBot terminal journal is not accessible through this VPS
  bridge. Exact internal reason for a non-submitted order requires a future
  **native cBot telemetry event** emitted by the deployed binary, and a
  controlled, separately approved binary rollout. This observer does not
  silently change the deployed strategy.
- Brokerage order/deal history is bounded to 48h; historical request
  `hasMore` or a failed request is surfaced as incomplete. Only positive
  records with matching labels can produce status evidence.
- Never publish full accounts, tokens, raw labels, broker order IDs, order
  volume, private checkpoint JSON, or raw broker responses.

## Acceptance / regression

`PYTHONPATH=src:. python -m unittest discover -s tests -p test_buy050_event_audit.py -v`

The workflow must pass read-only VPS capture, broker historical read, schema
allowlisting and public publication. CI pass is **not** proof of a live order;
broker records are authoritative for observed execution status.
