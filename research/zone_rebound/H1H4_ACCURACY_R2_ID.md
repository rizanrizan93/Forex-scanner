# RIZAN XAU H1/H4 Directional Accuracy R2 — 60% gate

**Prepared:** 18 November 2026 (WIB). **Research status:** model tournament and historical validation pipeline; *no accuracy claims until GitHub replay completes*. No LIVE execution.

## Research objective
Achieve at least **60% correct at the end of the next H1 or H4** for both BUY and SELL separately, **after a cost sensitivity scenario**. This is not the same as touching USD 10 and not a demonstrated profitable trade system. WAIT (abstention) is allowed, but report coverage, n and confidence bounds so selective tiny samples do not masquerade as an edge.

## Baseline, why R2 exists
Frozen R1 report PR #881, in 2025–2026 test (sampled signals only):
- H1 BUY 50.00% (n=824), H1 SELL 45.81% (n=465)
- H4 BUY 53.30% (n=182), H4 SELL 57.39% (n=115)
- 2024 H4 SELL 39.22%; no 60% result was validated.

The R1 fixed-$10 rebound research was even weaker, so **do not optimize USD10 until H1/H4 directional edge is reasonably proven**. R1 and R4 documentation remain unmodified.

## R2 hypothesis
A statistical classifier may discern conditional trend persistence, reversal and regime changes better than a single hand-tuned candle rule. But XAU bar-to-bar direction may be nearly unpredictable; **not achieving 60% is a valid research outcome**.

Every feature comes from completed H1/H4 candles available at the entry timestamp:
- ATR-normalized body, wick asymmetry, close position, EMA20/EMA50 deviation and slope, 1/2/3/6/12-bar momentum
- RSI14, ADX/DI, normalized prior 20-bar swing high/low distance, volatility regime
- latest completed H1 and H4 context (never unfinished H4)
- fixed cyclical session/day encodings in WIB

H1/H4 entry proxy: first M1 **open after the completed H1/H4 bar**; label at final M1 close in the next 60/240-minute interval. Only continuous M1 paths count as evaluated. Future data never enters feature creation.

## Precommitted models and selection
- Train: calendar 2019–2023. Binary direction target: future XAU price delta positive or negative.
- Candidate classifiers: regularized logistic regression (C=0.16) and small-depth HistGradientBoosting (max_leaf_nodes=7, depth=3, 110 iterations, conservative leaf regularization).
- Confidence filters: model P(up) >= 0.52/0.55/0.58/0.60/0.62/0.65/0.68/0.70 -> BUY; P(up) <= 1-threshold -> SELL. Otherwise WAIT. These numbers are **model decision thresholds, not true calibrated probabilities**.
- Gates: ALL / H4 aligned / current-timeframe momentum aligned. A total of 2 x 8 x 3 = 48 predeclared candidates per horizon. **Multiple testing remains a concern**.
- Select on **2024 only** using the *minimum of BUY and SELL Wilson lower 95% bound*, with 25 observed signals per side for H1, 12 for H4. This is development selection, not holdout proof.
- Evaluate the *one selected policy per horizon* on 2025–2026; publish yearly BUY/SELL outcomes and ALL signal coverage. The baseline project previously inspected 2025/26 and thus they are **not completely pristine across the research program**.
- Test diagnostics: H1 minimum 100 observations **per side**; H4 40 per side before referring to 'both sides 60%'. The report distinguishes observed >=60% vs lower Wilson bound >=60%, which is stronger evidence.
- Metric: signed future H1/H4 **close move minus assumed $0.50/oz cost** > 0. This cost is a sensitivity scenario (not verified FP Markets executable quote spread, commission, or slippage). A model predicting rising gold does not automatically have positive expectancy.

## Source and limitations
- Reuses pinned public HistData XAUUSD M1 downloader; requires source provenance, SHA256 and no missing downloaded periods in **every year 2019–2026**, 2026 partial by provider availability.
- Real ICE DXY/US10Y/US2Y yields 2019–26 intraday are not currently available with validated as-of timestamps. **R2 is strictly PRICE/STRUCTURE only**; never silently substitute EURUSD or lagged daily yield for intraday DXY/yield.
- R2 makes no claim of order-book access, institutional identities or smart-money order confirmation: SMC features are OHLC-derived proxies.
- **A second genuinely unseen forward interval is required before calling a research finding deploy-ready**, especially after exploring multiple candidate grids in past XAU research.
- PR #880 is the DXY/yield data-contract handoff, separate from this R2 pilot. PR #881 is the frozen R1 baseline.

## Validation and promotion
- Strict 2019–2026 cross-year annual source manifests, 2024 selection and sealed 2025–2026 reporting.
- Do not selectively exclude bad years, rare sessions, winners with gaps or bad confidence calibration. Never represent accuracy on 2024 selection data as independent out-of-sample.
- Even if >=60% observed for both directions, only propose a **shadow read-only** ForexScanner panel after validating stable per-year performance, sample size, reference/control direction, inference on non-overlapping events, and freshness. Any live implementation requires separate review and broker-fill replay.
- Research-only. Preserve Frozen V1, Manual R3, cBot LIVE, bridges and all execution controls.

## Reproduction
- Unit: `PYTHONPATH=src:. pytest -q tests/test_xau_h1h4_accuracy_r2.py`
- Historic: `.github/workflows/xau-h1h4-accuracy-r2.yml` downloads one M1 shard per year, writes `r2-year-YYYY.json` + `r2-year-YYYY.csv.gz` containing SHA256 and source dates.
- Aggregated: `scripts/research_xau_h1h4_accuracy_r2.py --aggregate artifacts/shards/r2-year-{2019,2020,2021,2022,2023,2024,2025,2026}.json --out artifacts/xau-h1h4-r2-accuracy-2019-2026.json`
- No output is an instruction to send orders.
