# V342 Afiq Behavioral Replay — 2026 Preliminary

Source workflow run: `37119966147`, job `replay-year (2026)`.

Status: completed successfully. Research-only; no execution authority.

Historical shard:
- normalized XAUUSD M1 rows: 348,070
- fetched periods: 10
- failed periods: 1
- checksum prefix: `09477130e4f8926c`

Behavioral replay:
- episodes: 590
- neutral 0.50 ATR reaction rate: 0.8135593220
- V342 exact touched-zone selection rate: 0.2016949153
- V342 same-direction selection rate: 0.6694915254
- V342 early-confirmation rate: 0.1508474576
- V342 full-confirmation rate: 0.0779661017
- V342 sweep-detection rate: 0.0508474576
- M30 direction-alignment rate (research-only diagnostic): 0.4915254237
- confirmed episode count: 89
- precision of early-confirmed episodes for neutral 0.50 ATR reaction: 0.7640449438
- median early-confirmation delay: 15 minutes
- reaction exact-zone selection rate: 0.1895833333
- break exact-zone selection rate: 0.2547169811

Outcome counts:
- `HOLD_050_DIRECT`: 468
- `HOLD_050_AFTER_SWEEP`: 12
- `BREAK`: 96
- `BREAK_TOUCH`: 10
- `STALL`: 4

Interpretation constraints:
- This is a behavioral/zone replay, not a trade-P&L backtest.
- `reaction_050_rate` is a neutral zone-reaction label, not win rate.
- M30 is diagnostic-only in this replay and does not influence production V342.
- Historical news/macro surprise context is not reconstructed in this run.
- Public M1 OHLC is used; it is not bid/ask tick execution replay.

Initial research implication:
The current V342 detects many zones that later produce a 0.50 ATR reaction, but its exact selection of the particular touched zone as the decision zone is low (~20%), and explicit sweep recognition is low (~5%). This supports prioritizing zone-role selection, acceptance/rejection, liquidity classification, M30 structure, and response-timer experiments before expanding execution authority.
