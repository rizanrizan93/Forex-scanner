# R8-Z: event-time is not vendor availability

Date: 2026-11-20. Research-only; no LIVE changes.

## Reproducible adversarial observation
Using the local R8-Y `features()` function with 64 synthetic consecutive UTC M1 candles and event at 13:03 UTC, the gate returns `OK`. Simulating all 64 rows being first delivered at 13:08 UTC (five minutes after the event) does not alter the gate's outcome, because `features()` accepts `(bar_open, price, quote_timestamp)` and has no `first_seen_at` / vendor `available_at` field. This is a **synthetic counterexample**, not evidence of delayed Dukascopy delivery. SHA256 of local test: `e98635babf9947f4824f70cc8b15c0443848a999bb328c259e3d11b2efb2874e`.

## Interpretation
A conservative candle-close + 60-second assumed lag prevents mechanical future-bar access but does not prove the data was actually available to a trader at the historical decision time. Source tick/quote event timestamp is distinct from ingestion/first-seen timestamp. The replay must disclose this as an assumption or use independently verified historical availability provenance. No real USD archive was downloaded; vendor DNS lookup failed in the research runtime.

## Required next checks
1. Obtain authentic `DOLLARIDXUSD` source bytes, hash SHA-256, document UTC conversion and source coverage.
2. Record data lineage, quote timestamp, and (if available) publication/first-seen timestamp. Reject rows with `available_at > decision_at`.
3. Compare baseline R6 with USD 5/15/60-minute conditional direction, per-side/per-year and overlap-embargoed CIs, net of costs. Do not treat 2025–2026 as pristine holdout.
4. Do not claim >=60% BUY/SELL until genuine market replay demonstrates it.
