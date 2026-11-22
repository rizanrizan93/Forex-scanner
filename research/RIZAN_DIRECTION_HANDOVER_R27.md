# RIZAN Direction Research — Handover R27
Date: 2026-11-22 WIB. Research only. This file is the continuation point for a new ChatGPT conversation or ChatGPT Work.
Repository: rizanrizan93/Forex-scanner
Research branch: research/r91-early-warning-m1-20261121
Dashboard: https://forexrizan.streamlit.app

## User mandate
Build EIGHT independent XAUUSD close-to-next-close direction engines: H1 BUY/SELL, H4 BUY/SELL, D1 BUY/SELL, W1 BUY/SELL. Minimum target 60% per side, aspiration >=80% with adequate samples and stability; not a promised achievable outcome. Each side may select different data, model, horizon-appropriate features, session, gates and calibration. Conflicts = WAIT, missing data = WAIT. Lock historical high-water marks without overwriting originals. Improve weak sides and coverage, do not sacrifice validated precision. Treat prediction coverage as fraction of eligible decision times, distinguish total-market coverage and per-side support. Direction prediction is NOT trade win rate or profitability.

Strict phase boundary: only after reliable direction demonstrated, develop a separate predicted liquidity waiting-zone engine (>=5 minute advance preparation notice, M1/M5 confirmation, directional alignment, invalidation, $10/oz minimum desirable excursion, $20–50 aspiration, measured MFE/MAE and execution costs). No entry zones yet. No edits to main, Frozen V1, BUY050, LIVE cBots, production dashboard, orders, broker or credentials. No paid services without permission.

## Frozen exploratory references (NOT frozen live strategies)
Original manifest: research/direction_benchmark_lock_20261122.json
Commit 5af98f8291b663facb6be0510158324586b2717a.
Successor manifest: research/direction_benchmark_lock_r27_20261122.json
Commit f6dcfcb01bc4f705d49f0b9f189d627010aa6efc.
These are historical reported high-water marks, not exhaustive search maxima, and source folds/coverage differ. Some are conflict-resolved predictions dependent on opposite head. Preserve original entire policy and selected annual configuration in artifacts, not just headline percentages. Never pool best BUY and SELL percentages into a purported combined realized outcome.

| Engine | Reference | Correct/n | Accuracy |
|---|---|---:|---:|
| H1 BUY | R25 regime specialist |407/767|53.06%|
| H1 SELL | R11 selected sell |164/296|55.41%|
| H4 BUY | R25 regime specialist |164/277|59.21%|
| H4 SELL | R11 selected sell |79/142|55.63%|
| D1 BUY | R16 complex |n=1217|54.89%|
| D1 SELL | R18 independent |184/355|51.83%|
| W1 BUY | R27 70% validation floor, extended resolved |33/48|68.75%|
| W1 SELL | R24 news-buy/COT-hybrid-sell crossover resolved |25/40|62.50%|

R11 references had negative estimated net P&L. R25 H4 BUY unstable, annual 2023 79/123=64.23%, 2024 36/62=58.06%, 2025 37/64=57.81%, 2026 12/28=42.86%. R27 W1 BUY lower Wilson95 54.67%; opposing SELL14/35=40%, combined coverage 83/350=23.71%. R24 SELL lower Wilson95 47.03%, paired BUY74/125=59.20%. NONE approved for live execution. R20 W1 full hybrid BUY96/159=60.38% SELL57/105=54.29%, combined coverage61.25%, remains balanced exploratory benchmark, preserve alongside side-focused marks. R24 reverse crossover BUY54/82=65.85%, SELL60/127=47.24% preserved.

## Latest completed R27
Run 44965849048 (success all three jobs), https://github.com/rizanrizan93/Forex-scanner/actions/runs/44965849048
Script scripts/r27_coverage_extension.py commit bb432a5bad47320148a7334cb16e64d21381a810
Workflow .github/workflows/r27_coverage_extension.yml commit 9d1e48a9df6b910401e5220b594d8f410e864616
Artifacts H1 14730994468, H4 14731707042, macro D1/W1 14731403073.
221184 side-specific evaluations across folds, 1920 fits.
Train, candidate selection year, separate extension selection year, evaluation year; purge unfinished labels. Dedup top40 candidate masks on prior selection, add <=3 additional rules per side if marginal and union precision reach fixed validation floor (60/70/80), conflicts WAIT. Floors are NOT achieved historical evaluation guarantees.
| Horizon | Common eligible n | 60-floor single coverage | extended coverage | extended BUY | extended SELL |
| H1 |20559|1.4106%|2.3493%|135/272=49.63%|112/211=53.08%|
| H4 |5127|4.2715%|5.3248%|18/43=41.86%|112/230=48.70%|
| D1 |1724|16.0673%|25.5800%|127/271=46.86%|81/170=47.65%|
| W1 |350|36.5714%|53.4286%|85/135=62.96%|20/52=38.46%|
70-floor W1 single BUY16/27=59.26%, SELL14/35=40%, coverage62/350; extended BUY33/48=68.75%, SELL14/35=40%, coverage83/350. 70-floor H1 no signals; H4 BUY18/45=40%, no SELL; D1 BUY13/35=37.14%, no SELL. 80-floor H1/H4 no signals; D1 BUY0/1, no SELL; W1 extended BUY18/29=62.07%, no SELL. Undefined accuracy when n=0, not 0% or 100%. No robust >=80% candidate. Complementary rules increased coverage but commonly degraded accuracy; do not adopt R27 broadly.

## Experiment ledger — don't repeat unchanged
All run links use https://github.com/rizanrizan93/Forex-scanner/actions/runs/<run_id>. Successful job != validated strategy. Historical evaluation periods repeatedly inspected; NONE pristine holdout.
- R9.8 daily source/replay 44886465487: D1 2012–26; 336 candidates; highest selected using viewed evaluation is not independently valid. Daily artifact pattern r98-daily-*.
- R10 44901264975: immutable H1/H4 shards from HistData M1 normalized UTC 2019–2026, pattern r10-shard-*. Earlier R10.2 anomalous 67–82% INVALID due to higher timeframe pandas index leakage. Correction run44906983770; R10.3 independent prefix 44907102788. Never use old r10_million.align_context; use r102_calibrated.context.
- R11 44907879558 artifact14709146843: 100663296 parameter tuples, not unique strategy signals. H1 BUY49.54% n109 SELL55.41% n296; H4 BUY51.14% n350 SELL55.63% n142. All failed target and estimated net profit.
- R12/R12.1 manual profit engine 44916167164/44916307381: negative SELL expectancy, weak BUY not robust and negative 2026. No zone development until direction.
- R14/R14.1 44919966084/44920158146: 4 TF direction; R14.1 H1 53.00/53.93 H4 53.67/47.32 D1 51.62/48.73 W1 51.92/47.27. Selective H1 low coverage.
- R15 44920728465: 18432 indicator-rule vectors; all fail both directions.
- R16 44921819655 artifact14712979950: 17280 evaluations /2156 fits. Simple vs complex vs ensembles. Best D1 complex BUY54.89/SELL47.89, H1 ensemble52.52/49.50, H4 simple51.52/49.06, W1 complex57.14/44.25. More complexity alone did not solve.
- R17 first failed 44956365901 FRED timeouts, repaired 44956908725 artifact14728286227. Treasury annual XML fallback nominal2Y/10Y real10Y 4224 each 2010–2026; FOMC timezone failed in this run. W1 hybrid BUY101/166=60.84%, SELL96/208=46.15%; H1/H4/D1 fail.
- R18 44957921767 artifact14727659960: FOMC UTC fixed, 280 event observations (UST2Y response proxy), 16128 evaluations /1008 fits. Separate side logistic models. H1 52.25/50.11; H4 52.13/46.33; D1 54.57/51.83; W1 55.70/43.41. Treasury/FOMC 2-business-day lag proxy, not strict point-in-time.
- R19 44958127493 artifact14728328180: macro pressure and FOMC signed decay/confirmation, 2548 vectors/TF and142688 side/fold evaluations. H1 50.69/48.84 H4 50.38/46.46 D1 49.08/45.10 W1 55.41/52.08. Failed.
- R20 44958824668 artifact14728158324: CFTC legacy gold futures-only COMEX code088691, 881 observations 2010–2026, net noncommercial positioning, OI, changes and crowding. 17640 evaluations/1260 fits. W1 full hybrid 60.38/54.29 coverage61.25%; H1 51.51/49.77 H4 48.94/46.08 D1 51.33/46.79. COT report date+14d proxy, latest vintage, not true release time.
- R21 44961643293 artifacts H1 14729289705, H4 14729747025, D1 14729419489; 7182 eval/513 fits. Horizon specialist H1 sessions, H4 objective SMC structure, D1 macro. H1 52.09/52.54 H4 49.82/50.23 D1 53.69/47.07. Failed.
- R22 44962326125 FAILED data acquisition, manifest artifact14730263228. EURUSD 49/94 monthly files, USDJPY 28/94 monthly files. Dukascopy monthly H1 BI5 timeout/503; never claim FX data integrated. Do not loosen 90% completeness retrospectively to claim original success. Try new prespecified smaller scope/source, cache and verify hashes/UTC, no silent fill.
- R23 44962495112 artifact14730555692: 2444 filtered/normalized actual-minus-consensus events via superpilot69/fred-us-macro-open-data; 11340 eval/810 fits. Retrospective calendar archive ends Apr2026, first-print/forecast snapshots not independently verified. Exclude approximate release dates, missing consensus, ambiguous duplicates; calendar date+3d buffer; use actual/forecast from matched Investing consensus, not revised FRED actual. W1 news only BUY84/133=63.16% SELL74/163=45.40%; matched n402 baseline BUY56.97%; D1 no improvement. Not pre-release prediction.
- R24 44962650523 artifact14730481343: matched D1/W1 seven policies; W1 n386. News BUY/COT hybrid SELL 59.20/62.50, reverse 65.85/47.24, pure COT hybrid61.83/52.27. Separate policies; don't mix headline best values. D1 failed.
- R25 44964431677 artifacts H1 14731141368 H4 14730673399 macro14729919911. 298080 eval/2592 fits. Eight heads independent feature/model/threshold/regime, previous two-year validation. Regime H1 53.06/53.90 coverage7.66%; H4 59.21/47.44 coverage13.79%; D1 ungated50.49/49.76 W1 ungated58.82/51.92. No freeze as final, H4 instability noted.
- R26 44964862206 artifact14731496029: intra-H4 completed H1 path, reconstructed H4 OHLC and >=50min each subbar,16 causal prefix audits. 216 fits/28512 eval. Matched n4379: H4 structure BUY55.20/SELL48.43; H1 path56.28/52.66; hybrid58.52/45.74; independent best56.99/47.21. No new high-water mark.
- R27 completed details above. No rerun identical rule search merely to raise trial count.

## Data/tools and reproducibility
Source functions: scripts/r14_multitimeframe_direction.py load_tf(tf) returns d,z,x,y,valid,signal_times; labels next completed candle close vs current close; gaps filtered; D1/W1 aggregation boundaries UTC rather than exact broker session. Use actual timestamps and label maturation. scripts/r16_direction_complexity.py features(z). scripts/r17_macro_pilot.py treasury_fallback(), align(). scripts/r18_asymmetric_direction.py fomc_fixed(), side_metrics(). scripts/r20_cot_direction.py cot(). scripts/r23_news_surprise.py news(). scripts/r25_eight_specialists.py setup(), macro_sources(). R27 references those.
GitHub Actions download immutable R10 run44901264975 pattern r10-shard-* path /tmp/r10 merge-multiple:true; R9.8 run44886465487 pattern r98-daily-* path /tmp/r98. Use github.token with actions:read. Fetch original per-year selected rules and manifests via artifact IDs. Artifacts expire; preserve important configs and provenance in versioned research files as needed, avoid exposing credentials or redistributing restricted source material.
Source URLs: official Treasury XML annual endpoints, SF Fed USMPD.xlsx, CFTC annual legacy futures zip. News archive https://github.com/superpilot69/fred-us-macro-open-data; attribution original FRED/Investing sources; verify rights and data vintage. No independently verified DXY intraday or yield intraday yet.
Always verify fresh run/job evidence before claiming outcomes. Do not invent IDs or infer success from workflow creation.

## Next research priorities (R28+)
1. H1/H4 weakest lanes: new original information, reliable cross-asset FX hourly/minute acquisition with predeclared coverage windows, source verification; actual DXY or a clearly identified proxy, intraday yields/futures where lawful/available. More OHLC combinations alone have repeatedly failed. Compare matched ablation, avoid false simultaneity. 
2. D1: actual/consensus release-aware first-print data and FOMC repricing, post-news continuation versus pre-release prediction separate; audit true publication timestamps and missing events. Test robust macro interactions and change-of-regime rather than assume hawkish always bearish.
3. W1: preserve R27 BUY, R24 SELL and R20 balanced baseline without mixing incompatible conflict-resolved records; compare locked full decision policies on same sample, source availability audit, independent forward shadow receipt. Increase support and stability before claiming >60/80.
4. Use two-stage or nested chronological selection and purged labels, negative controls, prefix checks, Wilson/blocked bootstrap, exact n, coverage, baseline, annual and recent performance. Do not select by looking at test results and rebrand as holdout. Report precision conditional on declared signal versus overall classification accuracy, separate actual trading expectancy and costs. 
5. User decides real strategy freeze following verified evidence. Keep archive append-only/versioned; do not overwrite prior high-water marks. If any challenger passes minimum with credible support, ask user before production deployment. No zone engine until direction is demonstrably robust.

## Automation
Existing hourly task ID 6afd29ec872081919c4acd36cb61842b. Keep one task, not duplicates. Report completed meaningful experiments with actual workflow receipts and artifacts, no repetitive status-only updates or claims of unscheduled background execution. User requested immediate report when completed and new-chat continuity. Verify latest task and run status on resumption.
