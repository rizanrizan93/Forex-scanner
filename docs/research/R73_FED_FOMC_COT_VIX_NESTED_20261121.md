# R7.3 Fed/FOMC/Expectation-Proxy/Liquidity Challenger — empirical nested audit (21 Nov 2026)

**RESEARCH STATUS: NO PRODUCTION PROMOTION.** No R7.3 cBot orders, no ForexScanner production merge, no change to Frozen V1 or R7.2 frozen model.

## Contract & provenance
Actual price data: validated daily XAUUSD M1 archive 2018–2024, with two independent alternative 2023 cohorts.
- OLD 2023 HistData source 164 accepted UTC session days (missing many).
- REPAIRED 2023 Dukascopy BID source 259 days, +95 additional accepted, p95 cross-provider close difference 0.0899%.
- 2025–2026 prior inspected price and returns **never read into this experiment**; cannot call 2022–2024 novel untouched holdout either because R7 and R7.1 previously inspected that period.
- Fixed trade evaluation: signal after completed daily UTC source, next session open to close of horizon D1=1, W1=5, M1=21 sessions; hypothetical $0.40/oz cost. No FP Markets bid/ask, spreads, slippage or execution parity.

R7.3 macro sources independently downloaded / source hashed:
- FRED latest-vintage DFEDTARU and DFEDTARL, official Fed target upper and lower. Encoded actual mid-target and change over 14 calendar days **with assumed +3 calendar day availability lag**. **This is an effective policy rate change, NOT the unexpected component of the meeting decision.**
- Official U.S. Treasury nominal 2Y, 10Y and TIPS real 10Y historical observations. **Observation date != verified original release timestamp**, with assumed +2 calendar day lag.
- Fed-path **proxy**: observed Treasury nominal 2Y minus actual Fed target midpoint; change over 5 gold sessions. Not CME rate-cut probabilities or licensed Fed Funds futures / OIS implied curve.
- Dukascopy DOLLAR.IDX/USD H1 BID CFD, not the ICE official DXY feed, +2 calendar day assumed usage lag.
- FRED latest-vintage VIXCLS (level and 5-observation percentage change), +2 calendar day assumed lag.
- **Official CFTC COMEX GOLD futures-only report**, contract 088691. 2018–2024 annual source archives, actual managed-money net positions/open-interest and weekly net/OI change, **+14 calendar days lag from Tuesday observation date**. This is a conservative *research assumption*, NOT verified original Friday publication time, particularly during atypical reporting delays.
- OHLC price-based BULLISH / BEARISH / LIQUIDITY_STRESS / NEUTRAL regime. Volatility/displacement `LIQUIDITY_STRESS` != observed forced liquidation, level-2 order-book or margin calls.
- Historical Federal Reserve FOMC public statements, dot plots, Powell news tone, CME FedWatch probabilities and pre-meeting rates **were NOT incorporated into numerical historical scoring**. True surprise = actual announced target midpoint (bps) minus ex-ante probability-weighted midpoint (bps). Adapter refuses to certify PIT or emit a trading direction without independently archived CME premeeting receipts. Official CME API supports paid historical FedWatch from 2015, but access was not supplied in this study.

## Reproducible evaluation method
6 feature families, **all compared on exactly the same historical outcome decision dates**; no model-specific cherry-picked dates:
1. R72_METHOD_PRICE_ONLY (price-only model method *refit within each historical outer fold*, NOT using the frozen 2024 R7.2 coefficients to score 2022!)
2. R73_PRICE_FED_POLICY_AND_PATH_PROXY
3. R73_PRICE_FED_TREASURY_BROKER_USD
4. R73_PRICE_FED_COT_VIX
5. R73_FULL_GLOBAL
6. R73_FULL_REGIME_BLEND_HALF

Inner sequential walk-forward year selection chooses ridge lambda from fixed (100,500,1500) using only **prior** inner years; outer evaluation only 2022, 2023 and 2024. Train/outer purged by at least 2x the outcome horizon, each horizon's outer outcomes nonoverlapping. Y1 is explicitly WAIT insufficient cycles. Total 27 tests passing at commit near final run. Normalization train-only.

### Empirical results — PRIMARY repaired 2023 source cohort
Absolute accuracy after assumed fixed cost, **not independently verified P&L**:

| Model | D1 n=759 | W1 n=151 | M1 n=34 |
|---|---:|---:|---:|
| Price-only method (refit as-of fold) | 50.198% (381/759) | 48.344% (73/151) | 61.765% (21/34) |
| Price+Fed actual target & 2Y-path proxy | 50.856% (386/759) | 46.358% (70/151) | 67.647% (23/34) |
| Price+Fed+Treasury+broker Dollar Index | 51.515% (391/759) | 50.993% (77/151) | 67.647% (23/34) |
| Price+Fed+COT gold+VIX | 51.910% (394/759) | 48.344% (73/151) | 64.706% (22/34) |
| **R7.3 Full Global** | **51.383% (390/759)** | **50.993% (77/151)** | **64.706% (22/34)** |
| R7.3 Full Regime Blend 50% | 51.647% (392/759) | 49.669% (75/151) | 64.706% (22/34) |

Note: First row is the same-method refitted price-only baseline; the *frozen* R7.2 candidate exists separately and remains unchanged.

### Statistical paired evidence — FULL GLOBAL vs price-only
| Horizon | Correct from base -> full | FULL right/BASE wrong | FULL wrong/BASE right | Exact unadjusted paired McNemar p | Relative RMSE |
|---|---:|---:|---:|---:|---:|
| D1 | 381 -> 390, +9 | 61 | 52 | 0.451853 | **0.21% worse** |
| W1 | 73 -> 77, +4 | 10 | 6 | 0.454498 | **0.33% worse** |
| M1 | 21 -> 22, +1 | 3 | 2 | 1.000000 | **5.96% better** |

All exact p-values are **uncorrected** for 5 challenger-family comparisons, 3 horizons, repeated historical research, and choice of data vendor; none are remotely significant even before correction. Do NOT interpret development gains as validated alpha.
- D1 Full Global accuracy Wilson 95% interval 47.83–54.92%; W1 43.09–58.84%; M1 47.91–78.51%.
- D1 Fed+COT+VIX 51.91%, 57 paired gains vs 44 losses, exact p=0.2323 uncorrected; still not demonstrated benefit.
- M1 Fed+path-proxy 67.647% on only 34 outcomes, 31 BUY and **3 SELL**; not credible bidirectional model. Difference from baseline only 2 additional correct outcomes, paired p=.5.
- Stress regime study counts: D1 51 distinct outcomes; W1 only 8 and M1 2. No robust separate stress-regime alpha.
- Y1: 0 model evaluations because 7 research years do not provide enough independent 252-session cycles.

### Deficient original 2023 cohort sensitivity
Full Global: D1 52.174% (621 outcomes), W1 52.033% (123), M1 69.231% (26).
Original deficient cohort is highly sensitive to missing 2023 days. Favor repaired source as complete sensitivity cohort, but provider switch and non-PIT macro remain scientific confounders. Comparisons across source cohorts are **not** pairwise on identical dates.

### Decision
- **NO PROMOTION**. The numerical R7.3 feature panel is a RETROSPECTIVE latest-vintage, assumed-publication-lag study. The full FOMC expectation/surprise is absent, and realized profitability is not established.
- R7.2 frozen D1 and its post-freeze read-only audit remain independently frozen; R7.3 did NOT amend either.
- Next: license/ingest CME FedWatch historical event probabilities or independently archived Fed Funds futures/OIS settlement+receipts, fetch original FOMC statement, dot plot and Powell timestamped published text, calculate true pre-release surprise without label lookahead. Obtain verified historical release receipts or use strictly new prospective receipts. Allow macro engine confidence only when validated.
- Require paired same-date nested improvement in both loss and after-cost expectancy with credible BUY/SELL n, regime robustness, and NEW prospective events after a separate R7.3 pre-registration, avoiding any reuse of already examined 2025-2026 as novel holdout.
- Add native FP Markets spread/slippage/DD simulations before any possible execution authority. Until then output WAIT for unverified true-FOMC-expectation predictions.

## GitHub reproducibility
- Probe official Fed target/VIX & CFTC: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44843731861
- Acquire 2018–24 gold CFTC annual primary sources: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44843868893
- 27 tests: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44844538805
- Source-hashed matched-date nested empirical artifact: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44844538933
- Relevant official docs: https://www.cmegroup.com/market-data/market-data-api/fedwatch-api.html ; https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm ; https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm
