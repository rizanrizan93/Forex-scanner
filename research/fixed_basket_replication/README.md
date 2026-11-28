# RIZAN Fixed Basket original recovery — 2026-11-28

**Status: BLOCKED_ORIGINAL_INPUTS. 15 archived parameter vectors recovered; zero new financial replays executed.** No LIVE deployment, main edits, broker changes or VPS changes. This is a research branch based on research/r9-r10-100b-local-20261125.

## For Work

1. Open RECOVERED_PROFILES.json. Source manifests are inherited on this branch under research/r9_r10_local. Check every blob SHA and preserve exact vectors. The first 25 parameter names are from R12; the remaining 7 are descriptions from R17/R18, not recovered implementation.
2. Recover the original ZIPs from the original Work sessions, including RIZAN_INCREMENTAL_CONTROLLED_RESEARCH_20261128.zip, RIZAN_ALGO_R28_Bootstrap_Hybrid_20261126.zip and RIZAN_ALGO_R21_Balance_Robustness_20261126.zip; additionally R37/R38 for 104 tapes and seed cache. Use the original workspace path, not a new guessed path. Do not upload private raw market data to a public repo.
3. Run `python3 research/fixed_basket_replication/verify_original.py inventory /path/to/recovered/archives`. Compare pinned SHA256 and ZIP integrity. A valid ZIP alone does not establish parity.
4. Execute the ORIGINAL fixed-basket kernel with original normal and cost2 inputs. Reproduce R21_MAX_GROWTH (2019–2026; $187805402649277.8 normal, $15859144896364.94 cost2) and R28_BALANCED (2012–2018 bootstrap + core; $468751669458472.4 normal, $138595134457147.42 cost2). R28_MAXIMUM_GROWTH and R28_LOWER_DD have no exact vectors in GitHub manifests; recover archive first. Uncapped Maximum and Robust require the 28 November archive; do not infer vectors from terminal balances.
5. Export the original runner's chronological settled ledger with basket_id,symbol,entry_utc,exit_utc,settlement_seq,net_pnl_usd,balance_after_usd. One row per unique basket; net costs included; no topups, no resets. Run `python3 research/fixed_basket_replication/verify_original.py audit ledger.csv --profile R21_MAX_GROWTH --cost 1` and repeat cost2. Ledger parity is only an independent check; original kernel and inputs must be executed and hashed. Compare trade-by-trade, annual balances, entry sizing and ordering. Report discrepancies and original tape cutoffs.
6. Only then port the exact strategy into causal C#; rerun original and continuous 2012–2026 with one shared wallet, $100, leverage model 1:200. Recompute signals, fills, lot steps, fees, margin, floating equity and rejection; no fixed realized-PnL injection. Preserve uncapped parity as diagnostic and report executable broker-capacity constraints separately. Stress costs 1x/1.5x/2x, delay, spreads, volume tiers, rolling regimes and Monte Carlo block-bootstrap with documented seeds. Target floating DD <60%; it is not assumed.
7. Produce original and native result manifests, code/data hashes, logs, trade and equity paths, annual results, and explicit pass/fail. Do not merge or deploy to LIVE.

## Important distinctions

- R21/R18 use 2019–2026 core fixed tapes; addon data ends March 2026, core October 2026. R28 hybrid stops bootstrap entries on 2018-12-01 for a flat handoff. It is a calendar switch, not a causal adaptive strategy.
- Archived high-balance R21 finalists fail cap2; R28 hybrid all-cap passes = 0. Closed DD is not floating DD. Astronomical uncapped simulated balances do not demonstrate realistic execution.
- This branch contains original archived vectors and provenance, not a newly reproduced trading algorithm. The verifier only audits artifacts and settlement outputs.
