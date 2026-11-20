# RIZAN Fed R5 — Macro Direction → Rejection/Continuation Entry Research

**Status:** RESEARCH ONLY, NOT a LIVE cTrader/cBot policy.
Branch `research/fed-direction-entry-r5-20261120`; draft PR #893
depends on R4 draft #892, R3 #891, R2 #890, R1 #889 and V4 #887.
No production deployment, no change to Frozen V1, Manual R3,
bridge, orders, position sizes or leverage.

## Required directional invariant

- Fed Macro R4 **BUY** → only a technically valid V4 BUY candidate
  may pass R5 *research alignment*. Any SELL candidate is blocked.
- Fed Macro R4 **SELL** → only a technically valid V4 SELL candidate
  may pass R5 *research alignment*. Any BUY candidate is blocked.
- Fed Macro R4 **WAIT**, opposite stock/yield/USD signals, no
  intraday OIS/TIPS feed, stale quote, stale Fed event, stale R4
  timestamp or mismatched source event → **both sides blocked**.
- Macro WATCH permission cannot create a technical V4 setup.
- Prior V4 failed-rejection cooldown, real bid/ask, chase, structural
  room, sweep/MSS and invalidation gates remain intact.
- **No signal, no fill and no expected win-rate claim.** This
  read-only gate deliberately returns no broker order authority.

R4's initial event-window watch expires after 150 minutes from
the official release; R5 macro snapshot also expires after 10 minutes.
Therefore a valid FOMC view **cannot** be reused as a BUY/SELL signal
for D1/D5/D10 without independently captured *fresh* daily/intraday
revalidation of yields, OIS/TIPS, DXY, other Fed speeches and news.

## Verified implementation

- `research/fed_expectation_r1/macro_entry_alignment_r5.py`:
  read-only BUY and SELL permission filter.
- `research/fed_expectation_r1/policy_information_watch_r4.py`:
  public market-provenance status after validating completed
  captured pre/post intraday quote timestamps. **No actual feed
  has been connected**; data with missing status block.
- `src/fx_scanner/rejection_dashboard_research.py`:
  research-only panel shows **MACRO WAIT** and blocks V4 technical
  candidates instead of displaying research-technical as actual entry.
- `research/fed_expectation_r1/fomc_continuation_observation_r5.py`:
  a separate M1 EMA9 + three-bar closed-candle structure break
  observation to test missed Fed impulse continuation. Entirely
  **NOT TRADABLE**; never bypasses V4 to send orders.
- Tests:
  `tests/test_fed_macro_entry_alignment_r5.py`,
  `tests/test_fed_r4_v4_entry_integration_r5.py`,
  `tests/test_fed_r5_continuation_observation.py`,
  `tests/test_fed_r5_paired_pilot.py`,
  `tests/test_fed_r5_2019_2026_paired.py`.

## First real historical XAU paired pilot: 20 Sept 2023 FOMC

- Price: September 2023 HistData XAUUSD real M1,
  **28,330 candles**, SHA
  `0127bae35fc66a5ba44eccf1f407fe03c7772a9d3eff2effd4e12cb98714668c`.
- Official San Francisco Fed USMPD original XLSX SHA
  `2b91297c42cf692dd74f65eabf7ee97f81d452676e23fa02edb222bfa60f0d0a`.
- Full FOMC communication window ended exactly
  **2023-09-20 19:30Z**; initial R4 context expired
  **20:30Z** (=150 minutes after the 18:00Z statement release).
  Therefore only **60 closed M1 minutes** were scored.
  The earlier 90-minute exploratory run was superseded because
  it included 30 minutes beyond the initial event-context limit.
- Ex-post macro filters:
  `MP2_TIPS10_DXY` = WAIT,
  `POLICY_OIS1Y_TIPS10_SP500_VETO` = SELL,
  `OIS1Y_TIPS10_DXY` = SELL.
- V4 technically qualified entry candidate count = **0**;
  BUY watch-only M1 = 39, SELL watch-only M1 = 43,
  existing invalidated/cooldown blocked BUY 21 and SELL 17
  (counts represent M1 statuses, NOT independent trades).
- A separate EXPLORATORY continuation observation found
  **3 raw SELL M1 structural break observations**, all technically
  after the completed communication window. Two repeated patterns
  were excluded; the FIRST unique event-window observation was
  **1/1 H1 direction correct** after synthetic $0.50/oz cost.
  The whole sample is ONE FOMC meeting, NOT three independent
  winners or a validated 100% strategy. The 2023 source was previously
  researched, NOT untouched OOS.

## Full-year scale-out

- `scripts/replay_fed_r5_2019_2026_paired.py`:
  69 FOMC meetings, per-year real XAU M1 (20 days before to 7 following
  calendar days), original event type and exact Eastern release
  time, closed M1/M5 and synthetic spread.
- `scripts/aggregate_fed_r5_paired_2019_2026.py`:
  independent FOMC meeting as unit, separate BUY/SELL,
  event count, first observation, H1 directional outcomes,
  Wilson 95% confidence interval and year decomposition.
- CI `.github/workflows/fed_r5_2019_2026_paired.yml`;
  no source failures may be silently counted as missed entries.
- Historical SF Fed USMPD market-response values are **ex-post
  market-study inputs** and NOT verified released PIT streams.
  Therefore genuinely tradable historical R5 macro signal
  BUY n=0, SELL n=0 even if ex-post pairings appear impressive.

## Statistical and risk research required before deployment

1. Preserve one event unit, compare *matched* entry conditions with
   and without macro direction on the same price data; account for
   80% target on **BOTH** BUY and SELL with enough independent
   samples and Wilson bounds.
2. Gather actual intraday OIS1Y, TIPS10Y, UST2Y/US10Y, dollar
   and stocks, timestamp of real capture, actual broker bid/ask
   spread, execution slippage, and overnight financing.
3. Prospectively collect NEW events after code/threshold freeze
   because 2019–26 has already been searched many times.
4. Extend event universe to verifiable FOMC minutes, Fed speeches,
   CPI, PCE and NFP; no artificial time-stamping or copying
   final post-release market reactions into pre-release inputs.
5. Develop separate **rolling policy-expectation regime** for
   H4/D1/D5/D10. An initial 150-minute event shock cannot
   justify holding one direction for 10 days without revalidation.

**Production release gate remains LOCKED.**
