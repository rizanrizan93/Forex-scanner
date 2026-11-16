# RIZAN USD Lead Engine V1 — Research and deployment contract

Date: 16 November 2026 (WIB). Status: RESEARCH ONLY, no execution permission. Frozen V1, live cTrader cBot, bridge, and VPS remain untouched.

## Hypothesis and order of evidence
Fed policy repricing and relative short-end US yield moves are potential leading inputs to USD; DXY is a contemporaneous confirmation; real yield and XAU H1/M15/M5 structure are separate filters before considering XAU SELL. No single DXY rise guarantees gold will fall, especially during geopolitics or systemic risk-off.

## Seven directional checks
1. Fed Funds futures ZQ intraday change (+/-1bp or more), requiring original quote and comparison timestamps within 15m freshness and <=4h window. Yahoo ZQ is a proxy for the average effective Fed funds rate, NOT CME FedWatch meeting probabilities. Never substitute US2Y-derived daily proxy.
2. US2Y official Treasury daily change (+/-2bp), requires CURRENT_PUBLISHED and correct original observation date, not intraday ticks.
3. US2Y - German2Y daily differential change (+/-2bp), pairing two dates exactly between official US Treasury and Bundesbank Schatz (series BBSSY.D.REN.EUR.A610.000000WT0202.A). Missing weekend dates are NOT filled.
4. DXY secondary Yahoo or broker proxy with original quote <=15m and +/-0.05% move over <=4h. Treated as confirmation, NOT an independent causal leading vote.
5. Official real Treasury 10Y yield daily change >=+/-2bp, release/current age checked.
6. Verified post-news US surprise (optional), only independently confirmed actual and within 60m; missing news stays UNKNOWN.
7. XAU H1 EMA / M15 ADX-DI / M5 BOS-MSS and V404 fresh structure: watch only if all pass.

## Decision
- USD DIRECTION WATCH ONLY = Fed ZQ PASS + at least US2Y or US-DE spread PASS + no contrary leading input + DXY PASS.
- XAU SELL/BUY SHADOW WATCH = USD watch + real yield PASS + XAU technical PASS; never grants an order.
- USD DAILY RATES WATCH ONLY = Fed UNKNOWN but daily US2Y, US-DE spread and DXY PASS; explicitly NOT independent leading votes because spread reuses US2Y leg.
- WAIT for stale sources, conflicting directions, unclear macro releases, invalid as-of observations or unverified structure.
- Check count is NOT a probability and has NO risk authority; unknown min broker lot/equity/margin remain separate blockers.

## Sources
- US Treasury official daily: https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics
- Deutsche Bundesbank daily 2Y: https://www.bundesbank.de/en/statistics/money-and-capital-markets/interest-rates-and-yields/daily-yields-of-current-federal-securities-772220
- Exact Bundesbank REST CSV: https://api.statistiken.bundesbank.de/rest/data/BBSSY/D.REN.EUR.A610.000000WT0202.A?format=csv&lang=en
- CME FedWatch methodology: https://www.cmegroup.com/articles/2023/understanding-the-cme-group-fedwatch-tool-methodology.html
- Existing ForexScanner V400, read-only H1/M15/M5 cTrader candle and V404 structure.

Bundesbank public CSV actual wide format has series ID as column header, metadata rows, and '.' for unavailable weekend dates. Live CI verified this provider format; do not treat provider retrieval time as price observation time.

## Files / isolation
- src/fx_scanner/usd_lead_decision_v1.py: pure fail-closed policy
- src/fx_scanner/usd_lead_bund_2y_v1.py: official Bundesbank adapter + exact date join to Treasury
- pages/5_USD_Lead_Engine.py: 60s UI refresh, seven directional checklist
- main.py: XAUUSD → USD Lead route
- tests/test_usd_lead_decision_v1.py and tests/test_usd_lead_bund_2y_v1.py
- .github/workflows/usd-lead-v1-tests.yml
- No broker order, token mutation, trade dispatch, bridge, or Frozen V1 modification.

## Research limitations
No 2019-2026 point-in-time cross-market or bid/ask tick OOS proof that this checklist predicts USD/XAU. Daily official rates are not instantaneous. Yahoo proxies are not direct licensed ICE/CME quotes. Multi-source rate signals share some inputs; independence is limited. The next valid study must log original as-of timestamps for fixed 15m, 1h and 3-6h windows, analyze conditional XAU returns and costs on untouched data, and report calibrated precision without retrofitting thresholds.
