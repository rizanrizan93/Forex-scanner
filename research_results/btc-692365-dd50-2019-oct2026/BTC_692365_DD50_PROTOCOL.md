# Candidate 692365 DD<50 focused protocol
Frozen research reference: POSITION_HIGH 692365, $1,005,025.5238208736, floating DD67.92092400829017%,63baskets.
Standalone USD100,2019-01-01 to2026-10-15, canonical Bitstamp M1 unchanged. No topups, target stop, DD clamp or live changes.
Signal locked: H4 displacement_follow, threshold2, trend1, session1 UTC00-08, BUYonly. All execution/accounting rules inherited unchanged.
First reproduce original equity/DD/trades after expanding numerical risk/margin arrays; original nine engine fixtures must pass.
Coarse geometry grid: stops1/1.5/2/3ATR, TP6/8/12/16/24R, holds8/16/32 H4bars, layers0/1/2, BE0/1/2R.
Sizing grid risk4/5/6/8/10/12/15/20/25/30/40%, margin30/50/60/75/95%.29700coarse configurations plus original if not duplicate.
Deterministic refinement: top12 distinct geometries DD<50, next12 distinct geometries DD<=55, next8 unrestricted; each risk1–40% in1%steps and same5margins. Unique canonical tuples only. Selection full-period exploratory, not OOS.
Promote baseline, unconstrained leader,top5 DD<50,top3 DD50–55, minimum20baskets for constrained groups. Raw replay every case with ledgers: BASE,COST1_5,COST2,NEXT_M1_DELAY,LEVERAGE2/5,NO_ADDS,three restart100segments.
All selected scenario ledgers independently reconcile PnL/fees/carry/cash; monthly/yearly BASE and equity/DD plots. Preserve all configurations, source diff and provenance SHA.
DD is conservative modeled M1 OHLC floating DD, not broker/tick DD. Leverage10,spread5bp,slip1bp/side,fee5bp/side,carry3bpnotional/day assumptions. Coststress excludes spread. Delay minimum1minute, not2seconds. Original stopout priority/capital-floor and layer-risk rules retained.
No future information added. Signal/volume optimized on same historical period => overfit risk. Portfolio BTC+XAU/EUR NOT_TESTED. No guarantee $1m survives DD constraint.

Stage2 declared after initial run39245458518: retain coarse29700 tuples and same top32 geometry selection; refine each selected geometry across risk1–40% and margin30–95% in1% steps (66margins). Original margin array order kept first5 for exact baseline. Add highest nominal DD<45 andDD<48 candidates to all stress/ledger checks. First observed familybest$48,153.12/DD49.93009%; initial top5 exceedDD50 atcost1.5. Stage2 is sequential full-period exploratory optimization, not untouched validation.
