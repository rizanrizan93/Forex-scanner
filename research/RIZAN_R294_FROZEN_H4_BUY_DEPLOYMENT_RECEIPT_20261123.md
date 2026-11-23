# RIZAN R29.4 — Frozen R29.2 H4 BUY, ForexScanner SHADOW deployment receipt

Date: 23 November 2026 (WIB). Research-only, cTrader market data READ ONLY.

## 1. Frozen and verified

- Original benchmark: R29.2 `precision`, H4 BUY `79/126 = 62.6984%` pooled across 2024–2026 annual policies, **not** a single model's forward win rate.
- Frozen **2026** policy: `ridge` (StandardScaler + LogisticRegression C=0.025, random_state=292), `broad_context` (78 causal OHLC/context features), BUY threshold `0.54`, confirmation `trend_impulse`.
- Training uses 2019–2024 candles, **not** 2025/2026 target labels; selected by completed 2025 validation.
- Original 2025 parity replay **41 correct / 63** and exact feature list: PASS.
- Original 2026 evaluation: **14 correct / 23** (60.87%; insufficient to establish stable forward alpha).
- Historical portfolio side set H4 SELL: NOT APPROVED, **127/226 = 56.19%**, assumed avg net `-$0.9996/oz`.
- Lock: `research/RIZAN_R292_H4_BUY_PRECISION_RESEARCH_LOCK_20261123.json`; exact historical artifact content SHA256 `f5fb876d38b5e8e8599037d1474aa6c2c62ffc3a8ba3a66c845916a8bc2aaa2c`. Frozen MODEL_ID `R29_2_H4_BUY_PRECISION_2026_FOLD_FROZEN_20261123`.

## 2. Successful live, broker-read-only acceptance

- [Research tests & broker closed H4 inference GitHub Actions run 45174744359](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45174744359): **19 focused tests PASSED**, 2025 selection parity proved, cTrader public broker M1 source and full closed H4 recognized, source age and final publisher checked.
- [Production research-only publisher GitHub Actions run 45175563668](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45175563668): **SUCCESS** after merge to main.
- Published payload: `runtime/r294-h4-buy-shadow.json` on THIS branch, generated 2026-11-23 **12:34:48 UTC / 19:34:48 WIB**, broker snapshot 12:34:33 UTC, H4 target expires **16:00 UTC / 23:00 WIB**.
- **Latest at that receipt: WAIT MODEL**; BUY probability `0.325865076201034`, threshold `0.54`, `trend_impulse=True`. No BUY trigger.
- Publisher: fixed contract + SHA + frozen selection parity, 4h target, fresh broker feed; any mismatch/expiry -> no new BUY published. Research-only account/order contract false. Scheduled at `:03,:18,:33,:48` UTC Mon–Fri, GitHub scheduling is best effort (not a guaranteed heartbeat).

## 3. ForexScanner deployment

- [PR #921 merged into `main`](https://github.com/rizanrizan93/Forex-scanner/pull/921): `src/fx_scanner/r294_frozen_h4_buy_feed.py`, `r294_frozen_h4_buy_dashboard.py`, integrated `Frozen Direction` panel and `.github/workflows/r294_frozen_h4_buy_shadow.yml`.
- Display: **H4 BUY · R29.2 Precision (FROZEN SHADOW)**, 30-second Streamlit refresh, exact candle expiry guard after cache. Displays historical pooled 62.70% separately from 2026 model 60.87%.
- No replacement of R28.1 H4, no R25/R11 changes, no cBot or orders; separately visible research signal for discretionary manual review only.

## 4. Forward-validation requirement and next research

- This isn't an approved profitable entry strategy. Prospective forward BUY precision/expectancy must be tracked after the model freeze without retuning, with FP Markets executable spread/slippage and MFE/MAE measured.
- False positives, missed opportunities, new candle expiry, and the 2027 year cutoff must be audited. Stop and explicitly relabel WAIT DATA rather than using expired model.
- Continue [R29.5 tail-risk and macro-lag exploration](https://github.com/rizanrizan93/Forex-scanner/tree/research/r295-tailrisk-macro-direction-20261123) for H1 BUY/SELL, H4 SELL, D1 BUY/SELL; protect frozen H4 model and LIVE strategies from experimental code.
