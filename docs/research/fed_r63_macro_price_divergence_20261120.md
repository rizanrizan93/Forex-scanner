# RIZAN XAUUSD R6.3 — Macro vs Price Divergence Protection

Status: **READ-ONLY DISPLAY + VETO**, NOT a new 2019–2026-tested strategy.
No cTrader, broker order, Frozen V1, bridge, risk or position changes.

## Incident, 20 November 2026

The user observed XAU falling while they believed DXY and Treasury
yields were falling. Inspecting actual source timestamps shows
different horizons:

- Snapshot of the public macro worker published 2026-11-20T05:53:07Z.
- Official US2Y yield: 4.76%, -4 bp on observation DATE **Nov 19**.
- Official US10Y yield: 5.04%, -3 bp on observation DATE **Nov 19**.
- DXY *vendor proxy*, 2026-11-20 05:42:58Z: 103.8160,
  from 103.7730 at 05:00:00Z; **+0.0414%**, NOT a -0.0414%
  drop on that minute-range. It is FLAT under the R6.2 ±0.05%
  context threshold and was >5min old when source published.
- ZN futures price 106.1875 at 05:42:46Z,
  `YIELD_FLAT_PROXY`, not the Treasury cash 10Y yield.
- Real yield 10Y was unchanged in the prior DAILY macro record.
- The macro quality worker itself reported `WAIT_DAILY_DATA`,
  `intraday_bias=UNAVAILABLE`, `entry_permission=false`.
- Reuters (20 Nov 2026 03:24Z) reported gold -2.7% around
  05:04Z, near $3,525.25/oz, on December Fed hike bets,
  USD still near a 19-month high and apparent broad forced
  liquidation. This confirms that *week-long Fed repricing and
  liquidation conditions* can persist despite a short-lived
  retreat in nominal yields, not that any one macro move
  mechanically causes every gold M1 bar.
  https://www.reuters.com/world/india/gold-set-worst-week-eight-months-firm-dollar-fed-hike-bets-weigh-2026-11-20/

## R6.3 decision presentation

Original R6.2 conditional market bias requires corroboration from
official DAILY US2Y/US10Y and a fresh intraday DXY quote, and
does not claim 80% live win rate. Fed R4 remains locked without
intraday OIS1Y, TIPS and independently timestamped surprise.

New *price confirmation* uses ONLY completed M15 and H1 candles
built from the public cTrader M1 source (read-only). Each side is
classified using price vs EMA20 and its slope; H4 must not
contradict if enough fully closed candles exist. This **is a
trend heuristic, not an independently validated SMC BOS/CHoCH
or predictive win probability**.

- **Macro BUY / XAU H1+M15 SELL** → `MACRO_PRICE_DIVERGENCE`.
  Display final direction **WAIT**, do not show BUY as confirmed.
- **Official DAILY yield lean BUY, DXY macro WAIT / XAU SELL**
  → `DAILY_MACRO_LEAN_VS_XAU_DIVERGENCE`, final **WAIT**.
- Mirror rule for macro SELL versus XAU BUY.
- If DXY+yield macro is BUY (SELL) AND completed XAU M15/H1
  is BUY (SELL), and available H4 does not contradict:
  `MACRO_AND_PRICE_ALIGNED_WATCH`, NOT a trade.
- No matching macro/price combination, missing or stale cTrader
  quote/M1, mixed M15/H1, H4 opposite, bad source contract:
  final **WAIT**; price data cannot be invented.
- No direct commission, spread, TP/SL outcome or stop execution
  evidence is produced by this display heuristic.
- Dynamic WATCH zones are still generated, including both
  sides as reference; all R4 broker/trading gates remain unchanged.
  The panel explicitly displays macro context, separate
  daily-yield lean, M15/H1/H4 trend and final PRICE-filtered WAIT.

## Research limitations

R4/R5/R6 replay 2019–2026 covered 69 FOMC events. It was based
on USMPD ex-post event-window factors and did NOT test the
new R6.3 live-mixed-frequency price veto as a strategy.
It found no >=80% success rate for BUY and SELL entries
after adverse excursion. R6.3 makes NO new backtest claim.
Before strategy promotion, gather paired point-in-time M1,
US2Y/US10Y, real TIPS, DXY, OIS, news and broker actual
bid/ask; test out-of-sample across ALL trading days and
FOMC events without lookahead.

No changes to cTrader account, cBots LIVE, Frozen V1, bridge,
orders, risk, leverage, stop-loss or limit-order placement.
