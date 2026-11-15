# RIZAN Yield–Asia R1 — protocol and limits

Created 15 November 2026 WIB. Isolated offline experiment, no real orders.

## Baseline identity and preservation

Attachment: RizanBootstrap125V1.algo, release 1.0.1, SHA256 7f58f6839c21785cdcce2c629acd5a2b009593f47dabb6effd8a1b0225a22619.
The source ZIP matches the attached binary; all 29 source checksums match. The baseline is not reimplemented or changed in this research. Its SEED→GROWTH transition requires both balance/equity ≥125, a flat account, recorded seed completion and a durable phase ACK. Current baseline documentation says the historical billion-dollar result was a synthetic M1 archive, not a certified tick-broker replay. No archived performance figure is reused as this research's result.

## Dataset and clocks

XAUUSD: 87 monthly Parquet files, January 2019–March 2026. Downloaded bytes match the read-only VPS manifest. The actual observations end 31 March 2026 UTC. April–15 November 2026 are absent. Full 2026 YTD conclusions are unavailable.

UTC millisecond tick clock; WIB is UTC+7 without DST. Integer XAU quote point=1000, from file schema metadata. Preserve tick order, including multiple ticks with identical timestamps. Same-time same-price records are counted as duplicate *quotes*, because volume is not part of the audit comparison; they are retained. Tick spread summaries are quote-weighted and cannot be interpreted as time-weighted spreads.

Audit exact bytes, monotonicity, bid≤ask, positive prices, file boundaries and quote gaps. Byte equality with an existing manifest is not an independent guarantee of source accuracy. Four attempted first-party hourly crosschecks were rate-limited (HTTP429); no independent primary-row parity claim is made.

Quarantine, uniformly before scoring: a session-day must have ≥95% expected nonempty M5 bars, no observed interquote gap over 5 minutes within it, a quote within60seconds of its opening boundary, within60seconds before its closing boundary, and within60seconds after its closing boundary. The boundary rule was added after the audit found exits delayed beyond13:00 during a source outage; every affected experiment was rerun. This uses future *data completeness* only to define the retrospective audit sample; it is not a trading filter or future price input. All excluded dates are exported. Closed-bar signal prefix invariance is tested independently of this audit sample definition. Occasional sub-five-minute quote gaps and genuine no-change periods cannot be distinguished perfectly from feed loss.

## Costs, sizing and execution

BASE: observed Dukascopy bid/ask; $0.10/oz adverse slippage each market execution; $6/lot round-turn commission; 1 lot=100 oz. Current FP Markets cTrader Raw metals commission is $3/lot/side, but the historic account fee schedule and symbol-specific rules have not been obtained. These are explicitly model assumptions, not FP Markets historical fill parity.

STRESS15: spread×1.5, $0.25/oz slippage, $6/lot. STRESS20: spread×2, $0.50/oz slippage, $8/lot.

Market buy at ask+slippage; sell at bid−slippage. Buy limit needs ask≤limit, sell limit bid≥limit; filled at limit with no favourable price improvement. Stop triggered on executable opposite side and filled at current quote plus adverse slippage, including price gaps. TP filled at target less adverse slippage. Limit expires 15 minutes after the completed signal bar. Entry requires the first quote within 60 seconds of signal time. Max hold 120 minutes or session end, whichever comes first; exits at the first available quote. No new entry in final 15 minutes. One position per candidate, three entries/day maximum, cooldown15 minutes after exit. No overnight holding/swap in tested entry sessions.

Equal starting equity $10,000, reference leverage1:200, assumed minimum/step0.01 lot=1oz, initial risk budget0.5%=$50 including planned friction, rounded down. Entry margin≤20% equity. Continuous fixed-dollar baseline retains the $50 budget as balance changes; it is not a recommended live sizing rule. Margin/minimum-lot rejection is included. Separate compounding uses0.5% current balance. A $100 compounding scenario is separate and respects the same minimum lot. It does not simulate EUR bootstrap or the125 handoff. No risk increase is used as alpha evidence.

Floating equity is marked every tick, deducting entry commission when open and remaining commission on close. Intratrade peaks and drawdowns are recorded in original tick order. Gapped TP fills do not create impossible equity peaks. Maximum floating DD is not inferred from closed trades alone. Every experiment has its own independent account; overlapping early/late/full sessions are not a proposed combined portfolio.

## Five reproducible price hypotheses

M5 midpoint candles, available at candle open+5min. ATR14 RMA, at least50 observations; EMA20/80 M5 with80-bar warmup. Twenty-four valid preceding bars, no signal-bar quote gap over60sec. Swing confirmation: pivot i−2 is a five-bar extreme on bars i−4…i; it becomes known only at bar i close.

1. MOMENTUM: EMA20>EMA80 and close>prior12-bar high+0.05ATR, bullish body>0.3ATR; symmetric sell. SL1.5ATR.
2. SWEEP_MSS_FVG: in preceding/current six completed bars, wick through prior24-bar extreme by0.05ATR and close back inside; subsequent close crosses prior6-bar opposite structure, body>0.5ATR, plus three-candle FVG gap>0.05ATR. Limit at midpoint of FVG; SL=max(1.5ATR,distance to swept six-bar extreme+0.1ATR). Symmetric sell. This is a sparse hypothesis and is not claimed to exhaust ICT definitions.
3. OPENING_BREAKOUT: first six completed M5 bars define session opening range. Later close breaks range+0.05ATR with directional body>0.5ATR. SL1.5ATR.
4. NY_CONTINUATION: most recent completed19:00–00:00WIB session has ≥54 bars and absolute return≥30% of its range. Its direction must match EMA20/80 and a prior6-bar breakout with body>0.3ATR. SL1.5ATR. This prior-session direction is price based, not a macro substitute.
5. TREND_FVG: EMA20/80 trend, directional body>0.8ATR, candle range>1.2ATR and three-candle FVG>0.05ATR. Limit midpoint; SL1.5ATR.

TP grid1.5R,2R,3R. Five sessions:08:00–10:30,10:30–13:00,08:00–13:00,14:00–19:00,19:00–00:00WIB. The final one is a generic session comparator, never labelled Frozen V1. Total75 base combinations. Macro Continuation and Macro Divergence setup versions remain blocked pending verified intraday macro data.

## Validation and selection

Training2019–2021, validation2022–2023, final historical test2024–March2026. Per setup/session, choose TP by training expectancy, then PF, requiring50 training trades. Insufficient sample defaults to predeclared2R and is flagged, not declared an optimized winner. Costs and signal rules are fixed before looking at results; no post-result search for a profitable pattern.

Three account tracks: CONTINUOUS starts once in2019; PERIODS resets to$10,000 at Jan2022 and Jan2024 for independently funded training/validation/test; ANNUAL resets each January for year-by-year comparison. Never splice annual-reset balances into a continuous equity curve. Retrospective train/test labels are not pristine prospective OOS: these years were already available when the hypotheses were written. No live forward evidence is claimed.

Walk-forward: choose TP from preceding three complete years, test next year2022…2026; keep setup rules unchanged. Bootstrap:3000 circular moving block samples of five trading days, including zero-trade weekdays, on2024–March2026 test. Holm adjustment across five full-Asia setup tests. This limited adjustment does not fully remove family-selection/75-test researcher degrees of freedom.

## Macro gates

Official daily Treasury nominal2/5/10Y and real5/10Y are acquired2019–15Nov2026 for descriptive analysis. Date markers are not publication timestamps. No historical first-seen archive, verified intraday Treasury quote panel, licensed ICE DXY panel or vintage economic surprise panel was available. These variables are never silently forward-filled or used as retroactive trading inputs. Latest revised FRED values are not supplied as historical predictors. No model probability, MAE, directional accuracy or incremental macro profit is reported without a genuine PIT training/test run.

Model APIs require aware decision_at, feature_available_at, target_available_at plus vintage/intraday verification. Regression baseline: ridge; nonlinear comparison: histogram gradient boosting. Probability API uses chronological fit and a distinct multinomial calibration segment. Model APIs are research scaffolding, not fitted production models. All optional sources and hypotheses remain explicitly untested when required histories are missing.
