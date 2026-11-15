# RIZAN XAU Alpha R2 — Research Pilot (2026-11-15)

Status: RESEARCH_ONLY, no deployment authority, no signal-to-order wiring.

## Scope
- Research USD 100, compounding, leverage 1:200, broker-discrete lot sizing.
- Public H1 source: https://github.com/getdata-finance/xauusd-1h-ohlcv-metals-historical-data
- 3,006 historical H1 bars between 2026-03-26 and 2026-09-25 UTC.
- Public candles are NOT FP Markets native bid/ask and cannot establish broker-executable backtest performance.

## Candidate indicator
BUY: last closed H1 above previous 20-bar Donchian high, above EMA200, RSI14 >=60.
SELL: last closed H1 below previous 20-bar Donchian low, below EMA200, RSI14 <=40.
ATR14 defines stop-width references; compare 0.25/0.5/1/2 ATR, 2R exits, H1 signal and next H1 open. No future candle information in signal generation.

## Key result: small-account executable size
Across 211 qualifying raw signal bars before overlapping-trade restrictions:
- Median stop width at 2 ATR: USD 37.98 per ounce.
- Median nominal margin at minimum lot 0.01, contract 100 oz/lot, leverage 1:200: USD 21.88.
- Median gross stop-loss plus assumed USD 0.80 round-trip friction: USD 38.78.
- 1% risk cap on USD100 cannot submit even one trade at 2 ATR stop if minimum 0.01 lot.
- The assumed volume min/contract from FP Markets MetaTrader literature MUST be verified on the actual cTrader XAU symbol.

## Experimental min-lot replay (NOT native broker parity)
- Risk 1%, stop 2ATR: 0 executable trades.
- Risk 5%, stop 2ATR: 0 executable trades.
- Risk 5%, stop 0.25ATR: 14 executed trades, approximately USD85.44 final equity (loss).
- Risk 10%, stop 0.25ATR: 20 executed trades, approximately USD39.98 final equity (loss).
These are exploratory calculations with assumed costs and simple OHLC gap/stop fills, NOT tick bid/ask validation.

## Continuous-sizing warning
Prior +17.83% net return / 1.46 PF assumes fractional exact risk sizing on USD10,000: it is NOT achievable with the same position sizing from USD100 and 0.01-lot minimum.

## Dashboard component
- New read-only Streamlit page: pages/4_XAU_Alpha_Indicator_R2.py
- New calculation module: src/fx_scanner/xau_alpha_r2.py
- Standalone tests: tests/test_xau_alpha_r2.py
- Historical sample default, or user CSV of CLOSED UTC H1 bars.
- Status flags: WAIT_SIGNAL, BLOCKED_BY_RISK, READY_RESEARCH_ONLY and STALE on stale data.
- No cBot order actions, existing bridge or runtime files touched.
- Macro yield and DXY are NOT connected; no invented probabilities.

## Next validation steps
1. Check actual cTrader LIVE XAU contract size, VolumeInUnitsMin/Step and estimated margin via safe read-only API.
2. Replay M5/M15 setups, where tighter structural stops may accommodate USD100 without risking 25%-50% on a single trade.
3. Walk-forward 2019–2026 using bid/ask ticks and actual execution costs, including floating drawdown, spread, commission and swap.
4. Validate indicator + real-time macro as-of timestamps before displaying any actionable live decision.

Decision: NO-GO for LIVE execution. Dashboard remains a research candidate until code review and tests pass.
