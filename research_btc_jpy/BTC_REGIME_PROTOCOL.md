# BTC entry/exit/regime repair — bounded research

Objective: improve entry/SL/TP and achieve useful SELL contribution, not merely
maximize full-period compounded equity. Previous target600k/DD56 remains a
reported comparator, not a guarantee or a reason to alter the data/model.

Data fixed: Bitstamp M1 2019-01-01 through2026-10-15, decompressed SHA256
c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504.
Leverage10,minimum/step0.01BTC,max100BTC,spread5bp,fees5bp/side,slip1bp/side,
financing debit3bp/day both sides. Normal/cost1.5/cost2/delay1min/lev2/lev5.
Cost stress never scales spread. No tick or broker FULL_PARITY claim.

7776 profile geometries,each evaluated BUY and SELL: 2TF(H1/H4) x12 prior base families x3entry modes x3regimes x2stops x3targets x2holds x3exits.
15552 directional configurations,31104 TRAIN/VALID rows. Same prior raw family
definitions,threshold1. Entry0 next open;entry1 next closed candle breaks signal
extreme;entry2 next closed candle retests signal midpoint and rejects in direction.
No entry more than0.5ATR beyond last closed signal/confirmation close. No candle
body>2.5ATR;RSI cappedBUY75/floorSELL25;ATR ratio to20bars ago0.6–1.8.
Regime0 closedH4 aligned;regime1 closedD1 aligned and H4notopposing;
regime2 reversal families require flatH4 and ER12<0.35,trend families H4aligned
and ER12>=0.35. Regime is computed from closed data available at entry.
SL0=1.5ATR;SL1 signal/confirmation extreme plus0.15ATR,entry-to-stop must be
0.5–3ATR. TP2/3/6R;hold8/16 signal-TFbars;exit0 fixed,exit1 BE1R nextminute,
exit2 trailing1.5R from completedM1close after1.5R close profit,nextminute effective.
No layers. No year-dependent trading rule or hindsight regime label.

TRAIN2019–2022 and VALID2023–2024 are used for selection. Profile diagnostic segments start at10000 separately to reduce minimumlot distortion;
pair TRAIN uses100 and VALID10000, normalized returns and annual trade coverage; those balances are NEVER added or chained to create
full-period performance. Final2019–2026 replay uses one uninterrupted100USD
account,sharedmargin/state,one activebasket,busy signals ignored. Simultaneous
opposing entry signals are both discarded. BUY and SELL may use different
profile geometry and directional risk. Pair sizing riskBUY5/8/10/15/20%,SELLweight
0.5/1/1.5;sharedmargin50/75%,up to12profilesperdirection,at most4320pairs.

Individual selection initially requires profitable TRAIN and VALID,PF>1.05,
TRAIN>=20 and VALID>=10 baskets,DD<=56 bothsegments. Profiles are diversified
by family/TF/entry/regime before selecting top12 per direction. If no strict
candidate exists,the fallback and its weaker conditions must be clearly logged.
Pairs ranked using only TRAIN/VALID,with actual BUY/SELL counts and profit,
then finalists are evaluated on continuous2019–2026 and six stress cases.
2025–2026 are diagnostic only,not untouchedOOS: these dates were seen in prior
research and motivated this repair. Changing a strategy after inspecting2026
does not make2026 independent validation. No promised profit everyyear/regime.
Report eachyear and direction,fees/carry,cashreconciliation,robustness failures,
baseline comparison and whether600k/DD56 survives. No live changes or mainmerge.
Inherited capitalfloor,OHLCbounds,expiry/SL/TP/stopout model limitations retained.

V2: minimum3 actual baskets per TRAINyear2019–2022 and VALIDyear2023–2024 for selection coverage. Full2019–2026 ALWAYS100USD,minimum0.01BTC unchanged. Inactive2025/2026 is rejection evidence,not successful risk control. First attempt retained.
