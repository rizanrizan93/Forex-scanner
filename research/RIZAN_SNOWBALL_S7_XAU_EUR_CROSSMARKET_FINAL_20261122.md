# RIZAN Snowball S7 — XAU entries using EURUSD M5 as a USD-proxy filter

**22 November 2026 WIB. Completed 14/14 annual year jobs plus aggregate — ZERO validated candidate. Research only.**

## What was actually tested

- Primary traded instrument: XAUUSD bid/ask M1, third-party public Dukascopy-derived archive pinned at commit `1d8e4c008fe177be455f6de05f5057ebdde901ae`.
- Context only: FXCM public EURUSD bid/ask M1. EURUSD 15- or 60-minute returns from fully CLOSED M5 candles. This is merely a EURUSD dollar *proxy*, not DXY and not actual Treasury yields or macro point-in-time evidence. No EUR orders or simultaneous XAU/EUR positions were simulated.
- Regime gates: H4 same-direction or opposed; M5 XAU volatility above/below past ATR median; liquidity sweep/reclaim, sweep→MSS, failed break, squeeze expansion, EMA50 dip, BUY/SELL; sessions 14–19/19–01 WIB; hold 60/120 minutes and stop-first M1; TP1.5/2.5R; past lookback12/36; EUR return aligned, counter, or not used.
- **3,840 model configurations × 14 years 2012–2025 = 53,760 model-year evaluations**, four nominal cash feasibility stages $100/$125/$250/$1000. Data from two providers; no matched portfolio or native Frozen V1 cash curve.
- Historical fold gates predeclared in S7 script: train 2012–18 needs >=80 entries, mean net stress >0.03R, PF_base>1.12 and >=5 positive stress years; validate 2019–22 >=50, stress>0.02R, PF_base>1.08, >=3 positive years; retrospective 2023–25 only if selected in prior folds. EUR public source 2023–25 contains gaps and does not produce pristine future holdout.

## Outcomes

| Tier / nominal cash | XAU + EUR context policies qualified train | Valid qualified | Retrospective qualified |
| --- | ---: | ---: | ---: |
| $100 | 0/3,840 | 0 | 0 |
| $125 | 0/3,840 | 0 | 0 |
| $250 | 0/3,840 | 0 | 0 |
| $1,000 | 0/3,840 | 0 | 0 |

Full 14-year crossmarket replay and aggregate GitHub Actions run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45026823361 . Pilot earlier 2019/2024: https://github.com/rizanrizan93/Forex-scanner/actions/runs/45026732777 . Pilot per-year selected winners differed and were not predeclared or robust; do not promote.

Earlier S6 XAU-only run also failed every cash tier (0/3,456), https://github.com/rizanrizan93/Forex-scanner/actions/runs/45026252308 . Earlier S5 EUR-alone run had 0/3,456 qualified; https://github.com/rizanrizan93/Forex-scanner/actions/runs/45024843870 .

**S6 + S7 are independent signal-only simulations, NOT a test of shared XAU+EUR trade execution or $100→$125→$250→$1,000→$10B compounding.** Their separate input feeds and normalized R returns cannot be arithmetically combined to claim a new terminal balance or max floating drawdown.

## Execution assumptions and failures to certify

- M5 signal closes, hypothetical entry at following M1 open; 1oz XAU nominal minlot, 1:200 leverage, 8% per-entry risk, 50% margin cap. FP Markets may set account-specific leverage, minimum gold volume and cTrader symbol lot contract. These must be checked using actual cTrader symbol metadata.
- XAU bid/ask costs: vendor spreads plus 0.05 USD/oz slippage per side, 0.10 USD/oz round-trip assumed commission. Approximate 2x-cost stress is applied to *same* stop/TP event path; not a native cTrader double-fee + latency scenario. Funding/roll, market impact and fill queue unknown.
- 2012–2018 is historically inspected development data and not pristine holdout. Multiple configurations (many redundant signals) mean positive in-sample single years are not enough.
- Frozen V1 annual reset/base model: eight positive years but 2024A/2x fee seed failed; continuous model 2019–Nov13 2026 $1.662B and DD56.67% remain model-only, no market-capacity proof.

## Decision

Keep Frozen V1 unchanged, including EUR bootstrap and XAU/EUR/BTC core. XAU only remains an independent research candidate; EUR+XAU simultaneously has NOT passed a shared-account, fill-risk-constrained backtest. EURUSD context filter does not deliver robust extra XAU alpha in this screening.

Next materially different hypotheses before searching another large grid: exact native C# replay parity on checksum-matched three symbol M1 tapes; point-in-time DXY/US2Y/US10Y regime stratification where source coverage can be verified; post-announcement volatility regime and order execution capacity; time-to-tier under fixed risk and actual minlot. Do not refit S5–S7 losers using 2023–25 retrospective data. Never change cBots LIVE or broker bridge on these results.
