# RIZAN Forex R6 — Liquidity Regime Research (R6.4 draft, 2026-11-20)

**Status:** RESEARCH BRANCH ONLY / READ-ONLY / NO ORDER AUTHORITY.
Existing Frozen V1, cBots LIVE, cTrader, bridge, and execution sizing unchanged.

## Research hypothesis
XAU often reacts to nominal/real yield and USD changes but can diverge
when leveraged holders raise cash, cover margin or rebalance. WGC and BIS
discussed leverage and liquidation as contributors to the 2026 gold sell-off.
This is not proof any particular R6 signal is caused by forced liquidation.
20 Nov 2026 Reuters commentary reports *apparent* forced selling,
not verified intraday exchange-level margin calls.

Sources:
- World Gold Council, March 2026 market commentary:
  https://www.gold.org/goldhub/research/gold-market-commentary-march-2026
- BIS, Quarterly Review March 2026:
  https://www.bis.org/publications/qr-202603/markets-recalibrate-amid-shifting-currents
- Reuters 20 Nov 2026:
  https://www.reuters.com/world/india/gold-set-worst-week-eight-months-firm-dollar-fed-hike-bets-weigh-2026-11-20/
- CME open interest reference (end-of-day, not M5):
  https://www.cmegroup.com/education/lessons/open-interest
- CFTC COT (Tuesday positions generally released Friday):
  https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm

## As-of XAU liquidity map
`fed_r64_liquidity_pools.py` projects *only already completed*:
1. Prior complete New York 17:00 FX daily session high/low (250+
   M5 samples, no >30min gaps); and
2. Latest complete 08:00–13:00 WIB Asia session high/low
   (EXACT 60 contiguous M5 bars, known only after 13:00 WIB).

These are *reference levels* where clustered stops may exist, not
actual observed orders or assured reversal points. Partial sessions
are never used to infer future highs/lows.

## Price-stress read-only veto
`fed_r63_liquidity_stress.py` distinguishes downside/upside
displacement, sweep/reclaim, volatility spike and spread widening.
The report does not assert forced liquidation or actual dealer flow.
When macro and closed M15/H1 agree, an M5 stress flag vetoes any
direction upgrade from WATCH to WAIT. Existing Fed R4 remains WAIT
without verified live point-in-time OIS/TIPS data. Thus even a normal
liquidity panel is never an order permission.

## Forensic data inventory: connected ForexRizan (read-only SQL)
As of this inspection:
- xau_dom_pressure_samples: **2,250** entries, 2026-09-27
  through 2026-10-01 (**5 observed calendar days**). All 2,250
  states tagged `BALANCED_OR_CONTESTED`; this does NOT establish
  an exchange-level margin liquidation history.
- xau_outcome_ledger: **481** episodes, 2026-09-22 through
  2026-10-01 (**5 observed calendar days**).
- signals: **17,991** entries, 2026-09-02 through 2026-10-01
  (**25 observed calendar days**).
- liquidity_levels: **0** persisted records.

On the historical, **different** strategy
`LIQUIDITY_SWEEP_REVERSAL`, **47** episodes were present, **40**
with populated `outcome_at`, **29** with `stop_hit` true and
**18** with `tp1_hit` true. Counts can overlap when a TP1 is
followed by stop, and several entries were not live-executed.
DO NOT calculate a R6 win rate from them or compare these episodes
as randomized samples against the 61 `TREND_CONTINUATION` episodes.

The direct 2019–2026 event-complete M5 + aligned point-in-time
R6 macro signal ledger is NOT in those Supabase tables, so the
new overlay accuracy remains **NOT MEASURED**. The previously
audited 69 FOMC events are ex-post and lack paired M5 signal data.

## Reproducible A/B study, when historical aligned data is available
`fed_r64_liquidity_replay.py` requires:
- Complete M5 OHLC, timezone-aware, CLOSE-stamped;
- A point-in-time ledger of the **same** baseline R6 signals
  containing `signal_at,side,macro_received_at,price_received_at`;
- Source availability <= decision timestamp (abort on future arrival);
- No more than one signal per nonoverlapping trade horizon;
- Fill at *next* M5 open; assumed round-trip spread as a cost;
- Completed future bars for after-event outcomes; no peeking
  at them in the stress-classifier input.

Measures directional correctness *after spread*, mean price-point
expectancy, MAE, blocked losers, blocked winners, coverage and
Wilson 95% lower bound separately for BUY/SELL. A positive hit-rate
shift with 95% suppression of signals may be economically worse.
Do not assert greater accuracy without both-sides and holdout-year
coverage. This replay is research instrumentation only, not a
validated fill/slippage simulation or executable trader.

## Next research sequence
1. Historical data admission: retrieve 2019–2026 XAU M5 from the
   user's archived VPS; pair with time-of-availability Treasury
   official daily, intraday DXY and real-yield/OIS when legally
   accessible. Flag missing data rather than synthetic replacements.
2. Label true broad funding stress **only if** cross-asset indicators
   and delayed COMEX OI/CFTC positioning actually support it.
   Avoid timestamp leakage: daily OI must not explain the M5
   candle before it is published.
3. Separate price regimes: breakout and hold, sweep then reclaim,
   failed reclaim, and post-impulse stabilization.
4. Freeze thresholds; replay 2019–2024 development and
   2025–2026 out-of-sample, including March 2020/2026.
5. Validate accuracy **and** signal coverage, per-side sample
   counts, false vetoes, after-cost expectancy, MAE, max DD,
   and sensitivity to 1–3 M5 bar execution delay.
6. Only then assess whether a research signal merits dashboard
   upgrade. No cBot/Frozen V1 changes without separate approval.

## CI nuance
The targeted R6.1/R6.2/R6.3 workflow should be used to validate
these functions. The general monorepo CI contains legacy tests
asserting *retired DEMO workflows* are still active; those are
unrelated to whether the R6 guard is a validated strategy.
