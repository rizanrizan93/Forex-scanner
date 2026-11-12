# XAU Macro Attribution V400 — evidence quality and validation

## Status

V400 is a read-only diagnostic overlay for the existing V399 worker.
It does not change the legacy macro score, broker execution, cBot orders,
frozen strategy parameters, or the intraday M15 forecasting model.

It displays a separately named quality-screened score, and returns WAIT
when FRED original timestamps are invalid, simultaneous economic releases
are unverified or mixed, independent currency/rate families are missing,
or fresh DXY/rates contradict the daily macro direction.

## Reliability gates

1. Daily FRED inputs are checked using the original observation timestamp,
   not the time the dashboard was refreshed. H.10 USD broad index max age
   7 days, H.15 Treasury yields max 5 days. Quotes older than 48 hours are
   explicitly labelled delayed daily context even if still valid.
2. Independent breadth requires both dollar and interest-rate families.
   The three Treasury series are correlated, not three independent markets.
3. Post-news actuals only receive a vote if official or two independent
   actual sources agree. Forecast versus previous never counts as an actual
   surprise; opposing verified simultaneous actuals produce WAIT.
4. Intraday confirmation requires DXY and a rates component whose original
   quote timestamps are within 15 minutes. A daily-intraday disagreement
   always produces WAIT.
5. Execution authority, order influence, and entry permission remain false.

## Accuracy validation required before any performance claim

Use point-in-time XAUUSD broker M1/ticks with as-of official calendar,
forecast and FRED release timestamps; do not leak revised future data.

- Pre-register chronological training, validation and untouched holdout
  partitions (e.g. training through 2023, validation 2024, holdout 2025–26).
- Compare V399, V400, the M15-only baseline and a no-signal/majority baseline
  on identical eligibility windows.
- Test 1-, 2-, 15-, and 60-minute direction separately and segregate news
  releases from ordinary sessions.
- Report signal coverage, abstention rate, directional accuracy,
  balanced accuracy and block-bootstrap uncertainty intervals.
- Include latency, spread, whipsaw, slippage, missing-data exclusions,
  maximum adverse excursion, and simulated net expectancy if trades are tested.
- Never translate a signed heuristic macro score to a probability of winning.
- Move from read-only to paper validation only after holdout success; never
  enable automatic cBot execution from this layer.

Unit-test pass confirms code contracts, not predictive win-rate.
