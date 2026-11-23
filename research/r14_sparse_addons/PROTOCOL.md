# R14 — fixed sparse-add-on research basket

Registered 24 November 2026 WIB. The user explicitly chooses R13's first diagnostic (M5 breakout SELL, configuration27615) and asks to accumulate additional sparse candidates. This changes the research objective: low individual frequency is allowed if several distinct policies can contribute useful combined fills. This does not change R13's recorded failure or qualify a policy for LIVE.

Parent evidence commit02a2736247488f0e46ad29c67d8bf6694b4ed87c. No changes to main, Frozen V1, broker or bridge. All results remain independent fixed-one-ounce research, not native V1 shared-wallet performance.

## Fixed candidate registry

Anchor slot0 is exactly R13 configuration27615: XAUUSD M5 BREAKOUT, look32, SELL, hold240min, stop>=3ATR and beyond signal-bar extreme, target2.5R, H4 WITH, LONDON06–10UTC (13–17WIB), spread<=.35ATR, volatilityALL. Its parameters are frozen for research; its 40-fill development sample is not validated alpha.

Additional slots are selected only from existing R13 development2012–2018 score arrays, never later-period PnL. Fixed exploratory gates: N>=30, net expectancy>.05R, PF_R>1.20, >=5 positive years. Rank by development netR, then N, then configuration ID. Keep at most one policy per(family,timeframe,side), explicitly including the anchor's bucket first. Also suppress exact aggregate-metric aliases (n,wins,netR,gainR,lossR,netUSD,sumR2,positive-year-count); this is a conservative diagnostic duplicate suppression, not a proof of independent return streams. Maximum16 slots total. Do not force all slots to fill, retune parameters, or claim independent hypotheses. R13's millions of correlated trials remain the selection history.

This lower N threshold is a disclosed user-directed change after R13 results, not a retrospective R13 pass or a significance claim. Register every selected policy before later-period replay. The anchor remains in the registry even if subsequent replay rejects it; rejection changes deployment eligibility, not historical identity.

## Replay and fixed combination

Replay every registered policy annually2019–2025 plus2026 Jan–Aug partial. Data, execution, hypothetical costs, quote validation, completed-bar features, A/B paths, stops and next-M1 entry are inherited from the tested R13 engine. Use all four scenarios A1,B1,A2,B2; no parameter optimization after these outcomes. Save both raw gated counterfactual opportunities and individually admitted fills, never label raw opportunities as funded baskets.

Individual validation2019–2022: both stress paths N>=20, meanR>0, gainR>1.05*lossR, >=3 positive years. Evaluation2023–2025: both stress paths N>=15, meanR>0, >=2 positive years. Partial2026 is separate. Passing is only INCONCLUSIVE_FORWARD_NATIVE_REQUIRED. Never keep only profitable historical years or remove future losing fills.

Fixed basket uses all registered slots, not only those that later look profitable. Compare ANCHOR_ONLY against ALL_SLOTS on identical source quotes, four scenarios and years. Build combined execution from **all raw gated opportunities**, not the already-pruned individual ledgers. Sort solely by entry minute, then fixed registry priority. At an entry timestamp retain the first policy for the same symbol/side; record alternative-policy duplicates. Admit at most one open independent one-ounce position across the basket, with a five-minute post-settlement embargo. Opposite signals and later anchor signals receive no hindsight exemption. Count anchor trades displaced by prior add-on occupancy instead of pretending priority at simultaneous timestamps prevents all displacement. Keep discarded signals and reasons.

Acceptance screen for the fixed basket on2019–2025: both stress paths N>=80, meanR>0, gainR>1.05*lossR, >=5 positive years, positive flat1oz netUSD, and more fills AND greater netUSD than ANCHOR_ONLY. Report failures unchanged. No selection of a better subset based on these periods. This portfolio is a capacity-constrained research experiment, not Frozen V1's core account: no native equity, funded margin or terminal balance claim.

## Evidence and limitations

Retain registry, source commit, input archive SHA, all candidate parameters/development scores, monthly source hashes, actual dates, raw counterfactual and individually admitted ledgers, both basket ledgers, duplicate/occupancy/embargo rejects, and per-slot attribution. Include losing candidates and years. Artifacts90days; permanent results/evidence committed to branch.

Historical periods were previously researched; no pristine out-of-sample claim. Small sample and cross-policy dependence remain even if the basket has more fills. Exact native replay still requires seed tapes, macro vintage, original control-ledger parity and broker specifications. V1 incremental funded baskets, wallet balance change and floating equity drawdown remain unknown. Production eligibility remains false pending that native comparison and new forward evidence.
