# RIZAN XAU H1/H4 Direction R1 — research only

Status 18 November 2026: causal engine and tests prepared, but the full 2019–2026 real-price replay is not yet verified. LIVE execution remains unchanged.

## Objective
Predict the directional move to the end of the next H1 (60 minutes) or H4 (240 minutes) starting from the next M1 open after the completed candle. Three outputs: BUY, SELL and WAIT. A score is a technical setup score, never a calibrated win probability.

## Frozen hypotheses and data
Candidates are: 20-bar prior-high/low liquidity sweep and reclaim; EMA20 trend pullback with EMA20/EMA50 alignment; and structural breakout with candle body greater than 0.3 ATR. Add or subtract score only from the last COMPLETED H4 regime. Ties and unsupported setups return WAIT.

Use eight precommitted policies: thresholds 3/4/5/6, each with or without H4 confirmation. Price source is HistData public XAUUSD M1 normalized by the existing V193 importer from fixed EST to UTC. This is not FP Markets bid/ask and must never be represented as executable broker prices. The full data source or a current-year gap may fail; do not infer success when download is incomplete. A $0.50/oz roundtrip cost is a SCENARIO only, not measured commission/spread.

## Evaluation
Every H1 and H4 forecast uses completed bars only. An incomplete constituent H1/H4 or future forward path is not labeled successful. Main outcome: at-horizon net directional accuracy, calculated independently for BUY and SELL. Secondary outcome: net favorable $10 before adverse $10 inside the horizon, same-minute ambiguous hits counted adverse-first. Also report signals, coverage, gaps, net movement and MAE. Distinguish correct direction from actual $10 target success.

Train model selection on 2019–2023, validate on 2024, lock 2025–2026 as test. Among policies with at least 50 evaluated BUY and 50 SELL signals, select by worst-side 95% Wilson lower bound from training. No claim that Wilson alone corrects for multiple testing or clustered trades. Report per year and per direction. 2026 is partial through latest available provider minute.

ICE DXY and true timestamped intraday UST yields are NOT included in this price-only version. A later macro improvement needs source provenance and same-event ablations, not a substituted EURUSD series or daily Treasury yield.

## How to run
1. Run the focused tests: PYTHONPATH=src:. python -m pytest -q tests/test_xau_h1h4_direction_r1.py
2. Open the GitHub Actions workflow xau-h1h4-direction-r1.yml on this branch / PR. It fetches all eight yearly public M1 shards with the existing pinned project HistData downloader; requires checksum parity and no failed periods; evaluates years in separate jobs; uploads yearly JSONs.
3. The aggregator refuses any missing or duplicate year, mismatched cost assumptions, or invalid shard contract. It emits one full 2019–2026 report only after eight successful shards.

## Promotion gate
Do not present these unverified signals as actionable entries in ForexScanner yet. After replay is actually complete, compare BUY and SELL OOS metrics and confidence intervals, then add a standalone H1/H4 research/shadow dashboard as a separate reviewed change. Preserve Manual R3, Frozen V1, cBot LIVE, bridge, sizing and all execution policies.

No historical accuracy is asserted before real data results are inspected.
