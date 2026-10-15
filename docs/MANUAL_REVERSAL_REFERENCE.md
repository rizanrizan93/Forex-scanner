# Manual XAU reversal reference

The XAU "Zona reversal" tab shows a separate manual reference map. It does not
change the frozen strategy, cBot configuration, bridge state, selected raw
reference, execution gateway, account binding, or order workflow.

## Observable rules

- A base of 1–3 completed candles precedes a displacement with range >= 0.9 ATR,
  body >= 50% of range and base width <= 1.3 ATR. A zone only becomes available
  after the displacement closes. A source-timeframe close through its distal
  boundary plus 0.05 ATR retires it.
- Eligible H1 zones anchor each direction, with H4 as larger context or fallback.
  M15/M5 zones can refine the anchor; they never become a major reversal anchor.
  Correct-side zones are selected before the per-timeframe display cap.
- The latest completed M15 contact must reclaim the proximal boundary with a
  directional body. A later completed M5 candle must break the preceding three
  contiguous M5 bars and reclaim the parent zone. A simultaneous M15/M5 close
  cannot confirm. A new M15 contact resets earlier confirmation.
- Confirmation must occur within 60 minutes of the M15 reclaim and expires after
  30 minutes. A subsequent M5 close beyond invalidation cancels that event.
  Movement more than one confirmation-candle range displays that the move has
  already started. Overlapping opposing H1/H4 zones block confirmation.
- Targets are opposing H1/H4 boundaries ahead of the actual snapshot price.
  An already-passed level or a micro-timeframe zone is not promoted to a target.
  The displayed dollar distance is price movement per ounce, not position P&L.

These are explicit structural definitions, not calibrated reversal probabilities
or a demonstrated profitable strategy. The new confirmation rules have logic
and UI tests, not a new profitability replay. A $10–$100 move is not promised.

## Data and isolation

The existing read-only collector reuses its authenticated cTrader connection and
adds four throttled native-timeframe history requests. Its unchanged protocol
allowlist permits authentication, symbol catalogues and trend bars only. There
are no position reads, orders, OAuth refreshes, cBot bridge calls, or execution
imports. Manual collection failures publish an unavailable state without
discarding the existing legacy reversal snapshot.

The additional output is `runtime/manual_reversal_snapshot.json` on the existing
`scanner-reversal-snapshots` branch, with contract
`RIZAN_XAU_MANUAL_REVERSAL_MAP_V2`. Both `execution_authority` and
`execution_influence` must be false. The legacy snapshot contract is preserved.

Collection remains every five minutes; dashboard checks refresh every 60 seconds.
Both publication age and the actual M1 close timestamp must be within seven
minutes. Republishing an old candle cannot renew it. Stale/unavailable data hides
price levels. The displayed price is a completed candle close, not live bid/ask.
Each timeframe also has its own freshness check for anchors and confirmations.

## Verification

Run `PYTHONPATH=src:tests python -m pytest -q tests/test_manual_reversal_*.py`.
Tests cover causal availability, source-close invalidation, stale price handling,
price-side selection, target selection, timeframe roles, ordered confirmations,
new-contact reset, conflicts, confirmation expiry, execution contract rejection,
protocol/import isolation, and Streamlit rendering. Existing cBot, execution and
bridge source/configuration files are outside this change.
