# Fed Expectation Macro R1 — directional bias up to two trading weeks

**Purpose:** correct the prior measurement mismatch. A Fed expectation shock
is a possible *macro regime / directional context*, not an automatic XAU
M1 +$3 scalp. Rejection Engine V4 selects precise M1/M5 entry only after
the independent macro context is evaluated.

## Predeclared horizons (post-event, at-time eligibility separate)

- H4: price at exactly 240 contiguous M1 after the known event-window end;
  if M1 gap, **censor**.
- D1/D3/D5/D10: close of the 1st, 3rd, 5th and 10th **subsequent
  complete weekday UTC trading sessions**. A session must have >=1000
  observed M1, begin no later than 02:59Z, end after 19:00Z, and have
  no within-day gap >120 minutes. Whole missing or partial weekdays
  result in **censor**, not imputation. Weekend short sessions ignored.
- D5 ~ one trading week; D10 ~ two trading weeks. These are NOT elapsed
  calendar days nor user-defined brokerage session cutoffs; results
  must be compared to a broker-calendar-aware implementation later.
- Primary metric: **terminal signed return % after a declared spread
  assumption**, scored separately for BUY and SELL. Supplementary:
  net USD/oz, MFE, MAE, censor reasons and exposure length.
- Fixed $3 barrier, if retained, is strictly a **separate M1/M5 entry
  execution metric**, not how macro directional accuracy is defined.
- No assumption that macro direction lasts automatically for 5/10
  sessions; future Fed expectations, other data, real yield, DXY,
  position flows and geopolitical regime may change. Prospectively,
  the macro state must be re-evaluated with only available data.

## Real 2023-09-20 XAU pilot (single prior-researched event)

Source: verified official San Francisco Fed full USMPD, time-stamped
Eastern event windows, spreadsheet SHA:
`2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a`.
Price source: verified HistData Sep 2023 28,330 XAU M1 rows, UTC
normalization fixed source EST-5,
`0127bae35fc66a5ba44eccf1f407fe03c7772a9d3effd4e12cb98714668c`.

Statement window ended 2023-09-20 18:20Z. Its **ex-post** shock tags
SELL (MP2 +2.06897 bps, UST2Y +6.525 bps, DXY +0.29972%).
Hypothetical entry at next M1 open $1947.025; assumed fixed $0.50/oz
round-trip cost. XAU price outcome (not actual entry/fill):

| Subsequent sessions | Observed close | Gold price change USD/oz | Direction of SELL after assumed cost |
|---|---:|---:|---|
| D1 | $1919.955 | -$27.070 | correct |
| D3 | $1916.435 | -$30.590 | correct |
| D5 | $1876.815 | -$70.210 | correct |
| D10 | no complete data | CENSORED | UNKNOWN |

**This does NOT validate a 1-week Fed trading strategy.** The official
factors are retrospectively compiled event-window observations, not
verified historical live delivery. Gold also responds to macro factors
other than Fed policy. No genuine PIT-eligible BUY/SELL signal was
emitted; H1/H4 had data gaps in the early session. This is one
illustrative event, not a 60% forecast, and does not establish execution
edge after real spread and slippage.

## Causal separation

1. **Macro direction** (Fed Funds/SOFR repricing + US2Y + dollar, plus
   real yields/US10Y and later macro changes): label BUY/SELL/WAIT and
   finite validity; update as new data actually become available.
2. **Technical entry**: V4 liquidity sweep/MSS/rejection, return-to-zone,
   room to opposing swing, spread and anti-chase.
3. **Exit/risk**: structure- and volatility-based invalidation; do not
   naively set a $3 TP for a multiday macro thesis.
4. **Research score**: directional H4,D1,D3,D5,D10, confidence
   intervals, median signed net return, by-side n, by-year n,
   overlapping exposure control, paired no-macro baseline.

Research implementation:
- `research/fed_expectation_r1/macro_horizons.py`
- `tests/test_fed_macro_horizons_r1.py`
- `scripts/replay_fed_macro_event_pilot_r1.py`
- `scripts/replay_fed_macro_multiday_2023_r1.py`
- `.github/workflows/fed_macro_multiday_r1.yml`

**Production status: LOCKED.** No merge or LIVE changes. PR #889 remains
draft; PR #887 remains draft. The 2019–2026 macro sample has already
been researched; neither the single event nor the 8-meeting year is a
pristine holdout. A genuine timestamped forward test is required.
