# Fed Expectation R1 — 2023 real-XAU FOMC event batch (8 meetings)

**Status:** Replay executed and recorded, **NO PRODUCTION**.
GitHub CI: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44617232607
Raw event ledger in artifact:
`fed-macro-r1-real-xau-2023-eight-events-ORACLE`.

## Source authentication

- Full official San Francisco Fed USMPD XLSX raw SHA-256
  `2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a`.
  Official worksheet supplies completed FOMC event-window *changes* for
  MP2, cash UST2Y yields and DXY from LSEG Tick History. Source
  `date_time` is Eastern Time, converted with DST.
- XAUUSD real public HistData M1 via pinned
  `histdata-fetcher` commit `4a3c11b67f97758f6e3f77a3e5905b6aa87367b8`,
  each meeting window normalized fixed EST-5 source -> UTC; raw
  month/day provenance and normalized hash recorded per event.
- **All 8 scheduled 2023 FOMC dates fetched**, no source acquisition
  failure; 24 overlapping analysis windows (statement, press, full).
- Entry modeled only after corresponding window ends, at next M1 open.
  Fixed assumed $0.50/oz round-trip spread, not broker quotes. H1
  and H4 scores require full contiguous future candles; otherwise
  censored, not imputed.
- **USMPD factors are retrospectively released published research
  observations, NOT historically archived realtime macro snapshots**
  or a working predictor available to traders at the past entry time.
  This run is an EX-POST oracle falsification, not a usable historical
  R1 production backtest. The strict PIT release gate still has
  BUY eligible n=0 and SELL eligible n=0.

## Results by event-window type (don't pool overlapping windows)

| Window type (8 meetings each) | EX-POST BUY tags | EX-POST SELL tags | WAIT tags | BUY H1 evaluable & correct | SELL H1 evaluable & correct |
|---|---:|---:|---:|---|---|
| Statement | 0 | 1 | 7 | none | 0 eligible evaluable |
| Press conference | 2 | 0 | 6 | 0/1 | none |
| Full monetary event | 2 | 0 | 6 | 1/2 (50%) | none |

For full-event BUY, 95% Wilson interval on directional H1 correct
is **9.45–90.55%**; meaningless for ≥60% dual-side deployment.
For unfiltered counterfactuals, H1 full at only **4/8** meeting
windows; missing intervals and trading-session gap censor the others.
The same meeting's statement/press/full rows are correlated and
MUST NOT be counted as 24 independent trades.

## What this falsifies

- The idea *all* hawkish headlines imply instant XAU SELL or dovish
  headlines imply immediate BUY. Surprise measurement and market
  repricing can change sign between statement and later press.
- A full-event **BUY success 50% (n=2)** is not evidence >=60%.
- A successful program/CI pipeline and official data source do not
  demonstrate a LIVE-capable signal or fill.
- Data availability over all three simultaneously known market series
  has NOT been established historically at every decision timestamp.

## Next non-negotiable gates

- Obtain historical **raw timestamped Fed Funds/SOFR same-contract**
  expected-policy-rate snapshots, nominal **cash UST2Y intraday**,
  and price-level **USD index** (either licensed official ICE or
  transparently labeled proxy) with release/quote/ingestion time and
  source rights. The USMPD *ex-post changes* cannot be passed to
  `research/fed_expectation_r1/engine.py` as invented before/after quotes.
- Compare identical frozen XAU event IDs with and without each macro
  feature, by year and BUY/SELL, using realistic spread/commission/
  slippage, no filling through missing minute bars, and future
  prospective untouched evaluation.
- Require at least meaningful independent sample sizes on BOTH
  sides, 95% CI, positive net expectancy and full source provenance.
  `release_gate.py` requires 100+ independent n each and Wilson
  95% lower bound >=60%; this is a conservative **research gate**.
- Keep draft PR #889 and #887 unmerged; do not alter production
  ForexScanner, Frozen V1, Manual R3, cBot LIVE, bridge, order routing
  or risk until evidence and explicit production review.
