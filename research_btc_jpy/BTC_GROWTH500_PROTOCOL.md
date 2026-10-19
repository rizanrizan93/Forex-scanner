# BTC standalone growth repair — minimum500k, maximum floating DD56

Initial100USD,no topups,2019-01-01–2026-10-15. BUY/SELL share balance,margin,
compounding,state,one basketactive,busy signals ignored. No live changes,orders,
bridge/env changes,dataset deletion or mainmerge.

Model/data unchanged: BitstampM1OHLC SHA256
c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504.
Leverage10 hypothesis,min/step0.01BTC,max100BTC,spread5bp,fee5bp/side,
slippage1bp/side,financing debit3bp/day bothdirections. Not broker ticks or FULL_PARITY.
Stop-first,gapworseopen,capitalfloor,expiry/SL/TP before stopout inherited.

Preserve7776 V2 profiles and IDs as frozen sources for SELL. Add2592 growthBUY
geometries: H4displacement_follow/D1structure_break x3entry x3closedHTFregimes
x4SL(1.5/2/2.5/3ATR) x3TP(6/8/12R) x2hold(16/32signalbars)
x3exit(fixed/BE1R/trailing1.5R) x2sessions(all/00–08UTC).
Thresholdindex2. Entry0 nextopen,entry1 nextcandleconfirmation,entry2 midpointretest.
Regime0 closedH4aligned;regime1 H4aligned+D1aligned;regime2 H4aligned+D1notopposing.
GrowthBUY restores legacy noRSI/noATRratio/bodycap: these caps suppressed the
strong legs that produced prior growth. Retain maximum0.5ATR chase from closed
signal/confirmation close. This is explicit modelselection,not proof bull dependence
has disappeared. Sells retain V2 filters and their own SL/TP/hold/exit.

8 SELL profiles frozen from prior2019–2024 quality selection plus mirrorBUY control.
Stage1 exactly23328 combinations,BUYrisk23%,SELLrisk7.5%,BUYmargin95%,SELLmargin75%.
Select up to80 geometries by documented terminal/DD/directional screen;include
legacy geometry7844 with all9 SELLchoices as controls if absent,max89 seeds.
Stage2 perseed180sizings:BUYrisk15/18/21/23/26/30%;SELLrisk2/4/7.5/10/15%;
BUYmargin75/85/95%;SELLmargin30/75%. Risk/margin are budgets,not guaranteed loss.

Target qualification:balance>=500000,floatDD<=56,BUYnet>0,SELLnet>0,>=10actual
baskets each direction,>=30total and >=1basket each calendaryear2019–2026.
Mirror controls do not qualify unless these same conditions pass.
Report best nominal and six locked stress scenarios(normal,cost1.5,cost2,
delaynextM1,absoluteleverage2/5),bothdirections and eachyear,including2025/2026loss.
Coststress scalesfee/slip/financing only,never spread.

This is fullperiod in-sample optimization after examining2026. The SELL seed
selection was before2025 but this new BUY/sizing selection is NOT untouchedOOS.
No future data inside signals,no calendar trading rules,no reset/topup,no
syntheticticks,no retroactive loss deletion. Do not promise minimum500k exists.
