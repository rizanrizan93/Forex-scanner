# RIZAN USD Lead V2 — BUY / SELL XAU with Yield Pressure Confirmation

Date: 16 November 2026 WIB. Status: decision-support research only. Execution authority FALSE; Frozen V1 cBot and bridge untouched.

## Symmetric direction logic

- **USD potentially UP + Treasury yield pressure UP**: evaluate **SELL XAU** if bearish H1/M15/M5 + V404 and REAL yield DAILY corroborate.
- **USD potentially DOWN + Treasury yield pressure DOWN**: evaluate **BUY XAU** if bullish H1/M15/M5 + V404 and REAL yield DAILY corroborate.
- DXY/USDX is a contemporaneous confirmation, not the sole cause of a trade.
- USD direction watch is permitted without yield projection alignment but does **not** escalate to an XAU SELL/BUY shadow watch; the yield row stays UNKNOWN or FAIL.
- Full dashboard requires three distinct families: policy repricing ZQ, yield/differential US2Y/DE2Y, DXY confirmation, plus separate XAU technical and yield context. US2Y and US-DE differential share the US2Y leg and MUST NOT be double-counted as independent predictors.
- Regardless of output, no automatic order or position instruction. Capital risk and actual broker margin are still separate mandatory checks.

## New yield pressure nowcast (hypothesis, not proven model)

- Read the *original* timestamp and price change for US 10Y Treasury futures proxy ZN in existing ForexScanner macro evaluation.
- **ZN futures price DOWN** generally supports **YIELD UP** pressure; ZN price UP supports YIELD DOWN pressure, subject to futures duration/basis and quote quality.
- Require a recognized independent original ZN futures source, valid session, and <=15 minute quote age. Small/flat changes are WAIT.
- Confirm with Fed Funds futures ZQ **implied-rate repricing**, with the same strict original quote timestamp checks. If ZN and ZQ disagree, state WAIT_CONFLICT; if only ZN available, state ZN_PROXY_ONLY and do not mark yield complete.
- Only CONCORDANT_PROXY may pass the yield checklist. Because ZQ is already the USD Lead policy-repricing check, its corroboration does NOT provide another independent leading vote.
- Horizon label: **next 15–60 minutes, exploratory pressure scenario**. **No numeric 10Y yield forecast, calibrated probability, or verified lead-lag accuracy.**
- **US2Y, US10Y, and 10Y REAL yield Treasury official releases remain DAILY historical context, never a prediction of the next intraday tick.**
- Missing, stale, weekend/holiday, inconsistent sources: WAIT / UNKNOWN. No green PASS from a guessed yield.
- This qualitative projection needs forward/paper monitoring and out-of-sample replay before it can be treated as predictive.

## UI

- Same ForexScanner route: **XAUUSD → USD Lead**.
- Side-by-side counts for **USD Menguat** and **USD Melemah**, and a separate yield pressure state.
- Tabs: **USD NAIK + Yield NAIK → Periksa SELL XAU**, **USD TURUN + Yield TURUN → Periksa BUY XAU**.
- Eight independent DISPLAY checks per direction: Fed ZQ, daily US2Y, daily US-DE2Y, DXY confirmation, official daily 10Y real yield, verified post-news actual (optional), qualitative yield nowcast, XAU structure H1/M15/M5/V404.
- The optional news and spread rows may remain UNKNOWN and need not force a discretionary trader to infer a missing value.
- All checks expose PASS, FAIL, UNKNOWN and reason, never an invented success probability.

## Source/validation limitations

Existing macro feed and original quote source timestamps govern all calculations. A 15–60 minute forecast cannot be verified by in-sample fitting to current values. Actual US10Y yield is NOT mathematically identical to inversely scaled ZN futures price; ZN duration/basis and risk/liquidity regimes matter.

No change to the live Frozen V1 strategy or cTrader order dispatcher. Production integration affects only the read-only research dashboard once tests pass.
