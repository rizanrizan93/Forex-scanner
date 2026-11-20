# R7.1 XAU: 2023 source repair, original Treasury observation archive, broker USD quote timestamps and nested regimes
Date: **2026-11-21 WIB**. This is a source-audited DEVELOPMENT research result, NOT a finished predictive engine.

## I. Original 2023 XAU source repair — empirical evidence
- Original HistData 2023: **164** UTC days accepted (March 1, April 7, May 6, June 6, July 4).
- Independent Dukascopy 2023 source: **436,420 real BID M1 rows**, all 12 monthly source downloads succeeded and were SHA256-hashed, **259** UTC daily bars admitted (at least 1,000 observed M1/day, max internal gap 7,200 seconds).
- **+95** separately sourced daily bars vs original 2023 accepted days.
- Overlapping verified dates had **0.0899% p95 absolute close difference** relative to HistData; calendar/session time basis UTC.
- Correct label: Dukascopy source replacement for 2023 is an **explicit provider switch**. It is not interchangeable with FP Markets native execution prices. Both source variants were retained and tested; original was NOT overwritten.
- GH independent year retrieval: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44831088385
- Source verification and replacement: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44831450440

## II. Historical official rates and dollar index — obtained with provenance caveats
Official U.S. Treasury:
- Source-hashed, unmodified official Treasury CSV archives (nominal 1990–2023, real 2003–2023) and original Treasury Atom XML for both 2024 rate series.
- Official observations from 2018–2024: nominal **2-year**, nominal **10-year**, and TIPS real **10-year**, with original *observation dates*.
- These are NOT independently archived historical release timestamps. The Treasury states rate-curve inputs are observed around **3:30 p.m. New York**. Observation time is **not** publication time.
- The Atom XML element **updated** for 2024 currently shows a feed refresh timestamp in **2026**, not a 2024 original data release. It was deliberately rejected as a PIT stamp.
- Daily research used a predeclared **two-calendar-day conservative lag** from observation date, visibly labeled as a *lag assumption*; NOT certified as the true original release time.
- GH official Treasury retrieval: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44831912361
- Treasury documentation: https://home.treasury.gov/treasury-daily-interest-rate-xml-feed

Dollar index:
- Pinned Dukascopy source instrument **DOLLAR.IDX/USD**, complete independent annual **H1 BID quote history** downloaded for **2018–2024**, with Unix-millisecond bar timestamps and raw SHA256 archives.
- It is a broker-traded **Dollar Index CFD quotation/proxy**, NOT ICE licensed cash DXY, not broad USD FRED and not the official ICE publication time archive.
- A conservative publication/usage lag was applied. The archival retrieval in 2026 cannot by itself prove a quote was already in a model's original 2018–24 realtime feed.
- GH broker Dollar Index acquisition: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44831876236
- Vendor instrument list: https://www.dukascopy-node.app/instruments?class=indices
- Official ICE DXY license: https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-currency-indices

ALFRED:
- ALFRED has historical **vintage dates**. These are day-granular and are NOT original intraday publication time and original data-capture receipts.
- Historical ALFRED exact vintage rows for the 2018-2024 Treasury/DXY combination were **not acquired here**, nor was full licensed ICE DXY history. These remain blockers to promotion and genuine PIT certification.
- Source verification code refuses to turn self-reported SHA256 strings and timestamp fields into proof of an independently captured original historical publication record. Only internal temporal order can be checked.
- Documentation: https://fred.stlouisfed.org/docs/api/fred/series/vintagedates.html

## III. Pre-2025 nested regime-weight research
Reproducible methodology:
- Complete daily OHLC only, completed historical price moments; four states **BULLISH, BEARISH, LIQUIDITY_STRESS, NEUTRAL** (UNKNOWN is excluded).
- LIQUIDITY_STRESS is an **OHLC volatility/displacement proxy**. Historical liquidation/DOM/actual market depth were NOT independently acquired.
- Nested development folds evaluate outer years **2021, 2022, 2023, 2024**, with inner train/selection dates strictly earlier than each outer year; each training label is embargoed by at least one forecast horizon.
- 27 predeclared regularised regime-blend/edge combinations per inner fold, not another unbounded million-grid.
- D1=next 1 valid session; W1=5, M1=21, Y1=252. Labels use **NEXT session open to future closing price** with hypothetical roundtrip cost $0.40 per oz.
- **2025 and 2026 are excluded** from every feature, normalization, hyperparameter optimization, decision and performance evaluation of this revision: those outcomes were inspected by R7 and must never be reused as an untouched holdout.
- No available fresh post-freeze forward evaluation dates; fresh truly unseen forward shadow starts no earlier than 21 Nov 2026 and must wait for new completed sessions.
- Historical outer periods 2021-24 were previously examined in R7's development process; nested folds are a **causal-style development diagnostic only**, not a genuinely never-inspected future holdout.

#### Historical development diagnostic: recovered 2023 alternative
| Feature family | D1 | W1 | M1 | Y1 |
|---|---:|---:|---:|---|
| XAU price-only | 51.992% (502) | 51.656% (151) | 61.765% (34) | WAIT |
| XAU + latest-vintage FRED broad USD/nominal/real rates | 51.292% (503) | 47.020% (151) | 58.823% (34) | WAIT |
| XAU + official Treasury observation + Dukascopy Dollar Index CFD | **50.847% (767)** | **50.993% (151)** | **61.764% (34)** | WAIT |

Important: **sample selections/coverages differ between variants** (e.g. D1 502 versus 767) due to tuned abstention thresholds and input availability; these rows are NOT a same-date matched-signal causal superiority test. Need paired all-date forecast loss/precision and new unseen holdout before deciding one source is more predictive.

Original deficient 2023 side-by-side sensitivity:
- Official Treasury + broker USD, old incomplete original 2023: D1 51.828% (629), W1 50.407% (123), M1 65.384% (26).
- Same source family, replaced 2023: D1 50.847% (767), W1 50.993% (151), M1 61.764% (34).
- The 65.384% in the incomplete cohort is a small-sample selection artifact candidate; DO NOT use as a reliable performance assertion.

**Regime result:** in most tested outer folds, the nested inner-selection process selected **regime-blend 0.0** (global weights) over separate regime coefficients. Stress observations were infrequent (e.g., in 2021 only 4 stress events in D1 evaluation), far below sufficient confirmation for a standalone liquidation engine. Therefore **adaptive regime weights are NOT proven superior**, and LIQUIDITY_STRESS is not authorised as a BUY/SELL signal.

The 2022 D1 official-source model emits only **7/250** directional signals, emphasizing why coverage and both-side sample counts must accompany accuracy. Several conditions might be stable in regimes while the selection is not; no trial is yet promoted.

## IV. Research decision and next independent evidence
**REJECT production promotion for now.** Preserve Frozen V1/cBots, existing broker bridges and order permissions unchanged. No R7.1 alpha or 80% claim.

Mandatory before any new release:
1. Exact ALFRED initial/vintage values *and* vendor-acquisition logs with immutable original reception timestamps, plus licensed ICE DXY original data if claiming ICE DXY. Never confuse recorded date, observed market quote clock, vendor archive modification time, and actual release time.
2. Refit the complete source-aligned model in nested walk-forward with **paired same-decision-date** RMSE and after-cost accuracy, sufficient BUY and SELL samples, and stress-state sample size/coverage gates.
3. Pre-register/freeze candidate weights before a **new future forward-shadow interval**. Evaluation after that freeze should use genuinely new sessions and remain separately labeled, not the previously reviewed 2025–26 market.
4. Final profitability requires native FP Markets BID/ASK, costs, slippage, trade overlap, drawdown and risk limits, not sampled historical spot BID alone.

Exact Actions for the four-state model regression: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44831514395
Nested development with data repair: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44831679034
Official Treasury plus broker dollar index nested trial: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44832275052
