# V3 — staged 302,330,880 configuration search (research only)
24 Nov 2026. Based on V2 exact-input screens and Work's recovered EUR/BTC tapes.
The objective is $10B continuous terminal model cash, not a forecast. No change to Frozen V1, main, cTrader or production.

## Design
36 base setups: 3 timeframes (M5,M15,H1), 3 structural families (breakout, liquidity sweep, trend pullback/recovery), 4 lookbacks (8,16,32,64). Stops 4, TP 5, hold 6, trend 3, sessions 6, universes 3 (EUR, BTC, EUR+BTC), direction 3. This yields 699,840 signal groups. Each group has 432 money-management policies: 9 distinct seed/growth risk pairs, 4 daily admission limits, 4 loss cooldowns, 3 win cooldowns. Nominal design space 302,330,880, not a claim that every combination was simulated or economically distinct.
 
Stage 1 checks nonoverlapping event expectancy in development 2019–22 at 1x and 2x costs, >=40 trades, >=3 positive years, mean R >0.02 and PF >1.08. Only survivors enter stage 2. Stage 2 simulates one-position wallet from $100, sticky transition at settled $125, tracks $250/$1000 and ending cash (not full Frozen core). Dev gates are predeclared: at least 6/8 $125 hits, 4/8 $250 hits and one $1000 hit, worst cash >=60, conservative approximate DD <60%, positive log growth. Evaluation 2023–25 only after dev passes (minimum 4/6 $125, 2/6 $250, worst cash >=60, DD <60%, positive log growth); 2026 partial separately only after evaluation. Historical sample repeatedly explored; not pristine OOS. No automatic selection by 2026.
 
The simulator inherits the isolated M1 outcome source, stop-first ambiguity convention, estimated spreads/fees/funding, nominal minimum lots and margin cap. Approximate DD can overstate intrabar excursions; no broker-certified execution or capacity. Reject candidates if native wallet cannot reproduce effects; a screened candidate is not a full cBot upgrade. Gaps are counted; all gap-sensitive candidates require native repricing. Keep production and bridge untouched. Stage 1 is a heuristic filter and can discard potentially viable policies: report pruned groups, not pretend full exhaustive backtests.
 
## Run on restored Work inputs
```
python research/v3_stage_search/run.py --inputs /path/to/exact/restored/csvs --work /path/to/isolated/v3 --bases 3
python research/v3_stage_search/run.py --inputs /path/to/exact/restored/csvs --work /path/to/isolated/v3 --bases all
```
The driver checks exact original EUR/BTC SHA-256, regenerates tapes using pinned completed-bar generator, checks tape hashes and archives per-shard receipts. First command is pilot; all bases = 36 separate shards, resumable. Raw result files distinguish actual group evaluations, wallet policy evaluations, cost/year trials, survivors and development-trace aliases. Native replays remain zero until run separately on actual matched three-asset source and ledgers. XAU remains part of original core only; standalone EUR/BTC screen is not a portfolio replay. No 2012–18 BTC or pre-2019 activity is fabricated. Next native tests should compare A/B and 1x/2x costs, annual resets and continuous 2019–2026, exact stage timestamps, DD, core fill displacement, risk, capacity and final balance. Do not count CI smoke tests as historical financial tests.
