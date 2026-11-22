# RIZAN Bootstrap125 — Controlled Snowball Trial R2

Research only. No edits to frozen strategy, cBots, BUY050, broker, VPS, state, or live orders.

## Matched benchmark and no regressions

Original immutable comparison: RIZAN_BOOTSTRAP125_V1_FROZEN_20261114, 14 Nov 2026, 2019–13 Nov 2026, $100 start, 1:200 simulated leverage, 20.75% growth budget, EUR M5 BUY seed risk <=8%, one position, two seed entries/day, growth handoff only when balance AND equity >=$125 and flat. Frozen report's *earlier frozen research packet* lists SHA256 `6a92026bff80b81b41e7a2f76343fc31cc7aa0dcccde00b327dc663080904648`; the separately distributed Library `RIZAN_BOOTSTRAP125_V1_FROZEN_20261114.zip` bytes verified SHA256 `0bd93f3f8ad3d64c3171a3fdd49d536b65fd9cfbf69d71e7740d685ac826488c`. Do not equate the two archive hashes.

Historical re-audit in `research/bootstrap125_growth_r2_existing_replay_evidence.json`: **114 existing source-replay records**; only a derived matched archive audit, NOT a new candidate backtest. 8 annual resets; growth-only M5-G19.5 increases baskets in all 8 and balance in only 5; fails 2020/2023/2024. All 9 archived growth challengers fail no-worse-all-years. Since all share Frozen EUR seed, none accelerates $100→$125. The 2024 original seed handoff is 8 April, 98.63 days since Jan 1, so prioritize seed.

## Next genuinely NEW parameter trials (not executed by archive audit)

All seeds tested using the SAME source data, costs, C# replay accounting, period cutoff and broker volume/margin normalisation, not independent directional proxies.

| Candidate | Seed-only delta vs B0 original | Risk exposure |
| --- | --- | --- |
| B0 | EUR M5 BUY breakout 64 candles +0.05 ATR14, bullish M5, H4 EMA20>80, SL at least 1.25 ATR14, TP4R, 120m, max 2/day | Frozen control |
| S1 | EUR M5 BUY retest following qualifying 64/32-candle breakout, M5 close reclaim, same H4 bullish filter | <=8% trade risk |
| S2 | EUR M5 SELL breakout 64/32 in strict bearish completed H4 EMA20<80; symmetric stop/TP, no overlap | <=8% trade risk |
| S3 | EUR BUY breakout 32/48 with separate displacement/ATR filters; repeat 64 baseline | <=8% trade risk |
| S4 | EUR M15 liquidity sweep and M5 reclaim in trend, with 5m-confirmed entry | <=8% trade risk |
| S5 | B0 plus additional eligible seed entry/day only while flat, with same cooldown and total daily risk budget, max 3/day | <=8% each and unchanged total shared budget |

Grid attempts must use broker-same minimum EUR lot (skip unaffordable), actual margin bounds, no clipping to make trades appear profitable. Never select an entry after seeing the outcome, never pick calendar-specific winning policies.

## Tier and gate

Measure $100→$125, $125→$250, $250→$1k as separate phases; core Frozen V1 Growth must otherwise remain unchanged and receive execution precedence after handoff. Single shared account/queue. Addon seeds cannot run concurrently with core and cannot place any LIVE order.

Require all of: (1) baseline parity and input SHA256, (2) same starting cash/timestamps and price-event tape, (3) year reset 2019–2026 plus a continuous 2019–2026 $100 account, (4) both A/B deterministic intrabar paths and 1×/2× costs with funded BTC rollover/EUR swap tracked, (5) annual cash, DD, total and seed baskets, time-to-tier, fill rejects, risk/margin, and net P&L (6) forward 2026 if not development-tuned; otherwise explicitly label exploratory.

Do NOT award extra points for merely more signal opportunities. Count extra **filled** basket entries, within risk and free margin, and whether the added setups displace profitable frozen entries. Reject if a candidate wins in only the final year while 2020/2024 deteriorate, or if 2024 2× fee case cannot survive seed, or if max floating DD crosses the preset risk threshold. Predeclare scoring before scanning.

## Required data/capability blocker

The user's original detailed `annual_seed_search/data` (M1 timestamp and OHLC for EUR, XAU, BTC, exact news/macro history and C# native harness artifacts) and full `november_research/data/corrected` are not included in the small research ZIP. 114 archive summaries are insufficient to regenerate fills under NEW seed candidates. Restore and verify immutable raw-source checksum from the source archive before executing new native trials; never imply the evidence-only audit equals a fresh matched replay.

## Profit headline constraint

Frozen continuous *model* balance $1,662,133,293.08, 56.67% max DD, no capacity proof. $10 billion would require 6.0164x that model result. It is an aspirational mathematical scenario, NOT proven achievable; portfolio sizing, market impact, variable broker leverage and live liquidity likely break linear scaling. Prioritize survivability and opportunity efficiency.
