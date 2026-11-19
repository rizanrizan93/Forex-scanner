# Rejection Engine V3 — lifecycle & breakout kill-switch (research only)

**Date:** 19 Nov 2026. **Branch:** `research/rejection-engine-v1-20261119`.
**PR:** #887, draft. Nothing is merged into `main`; no cBot, account or
bridge interaction. No performance improvement is claimed.

## Motivation: intraday SELL scenario

Observed screenshot sequence: XAUUSD rejected around 3727–3728, dropped
toward 3723, then spiked toward 3735. The early price decline establishes
a *short-lived rejection*, NOT a durable H1/H4 reversal. Once the market
crosses the frozen failure boundary, an old SELL event must never continue
to show `VALID` or suggest additions just because an EMA has shifted.
Screenshot prices are illustrative; **not** an archived executable fill feed.

## Causal event lifecycle

1. `EARLY_REJECTION`: closed M1 wick/reclaim, watch-only. M1 candle CLOSE
   determines event identity; actual panel observation is separately logged.
   It does not mean trend reversal is verified.
2. `REJECTION_CONFIRMED`: a later CLOSED M1 candle breaks the opposite
   three-bar pre-event structure. Does not assert H1/H4 success.
3. `BREAKOUT_RISK`: current valid quote goes beyond the FROZEN failure
   price, even before the M1 bar closes. This is a reversible *display*
   warning; it does not fabricate an OHLC close.
4. `REJECTION_INVALIDATED`: subsequent CLOSED M1 closes beyond frozen
   extreme + 0.10 historical ATR(M5) buffer. Never replace old boundaries
   with current moving EMA prices.
5. `BREAKOUT_CONFIRMED`: completed M5 closes beyond same frozen failure
   price. Takes precedence over an earlier M1 confirmed rejection.
6. `EXPIRED` / `DATA_GAP`: time window exceeded or missing M1 observed.
   Both suppress entry suggestions. No interpolation.

Early alert is issued at first M1 close, without waiting for M5. A retest
is optional, and a confirmed breakout **never automatically flips into BUY**:
BUY remains an independently validated watch setup.

## Fail-closed rules

- A same-side rejection that is invalidated, confirmed broken out, or
  data-gap compromised blocks ALL same-side entry suggestions for a
  minimum 15 minutes after failure detection. It cannot be rebranded by a
  moving EMA, nearby support or a differently named watch zone.
- Each event stores immutable `signal_at` (UTC M1 close), `observed_at`
  (UI review), `level`, `zone_low`, `zone_high`,
  `structure_trigger`, and `invalidation`.
- UI persists recent events in Streamlit session state, but does **not**
  claim continuity across cleared sessions or source switches. No position
  or broker order state is accessed.
- No bid/ask quote, quote older than 30 seconds, partial M1, missing
  complete M5/H1/H4 bars, or forward timestamps: no executable entry
  authority. Manual dashboard is only a decision aid.
- Numeric 0.10 ATR boundary, 15-minute veto, 30/120-minute expiry are
  **research hypotheses** and not tuned/win-rate validated.

## Regression gate

`tests/test_rejection_lifecycle_research.py`: symmetrical SELL/BUY paths
from rejection → M1 MSS → adverse breakout → M5 breakout, frozen invalidation,
quote risk before close, M1 missing minute, deduplication and dual-side
tracking.

`tests/test_rejection_v2_research.py`: regression asserting failed
same-side event cannot be revived by another dynamic watch zone.

These tests prove **state correctness only**, not ≥60% BUY and SELL accuracy.

## Promotion

Draft PR must remain unmerged until regression CI is green, UI smoke checks
pass, and genuine historical bid/ask-aware, day-clustered and prospective
replay demonstrates BOTH BUY and SELL with adequate n. Existing V2 replay
statistics do **not** transfer to V3 after lifecycle filters change.
