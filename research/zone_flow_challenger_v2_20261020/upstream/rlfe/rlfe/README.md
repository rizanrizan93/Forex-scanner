# RIZAN RLFE V2 — Reversal Liquidity Fusion (research only)

Independent read-only Python modules designed to add venue-specific order-flow observations to manual reversal zone analysis. Existing structural zone and Candidate A WATCH/WAIT semantics are untouched.

## Contents
- `src/fx_scanner/reversal_liquidity_fusion.py`: ordinal support evaluator; never a probability.
- `src/fx_scanner/manual_reversal_orderflow.py`: strict per-zone sidecar matching, fails closed to `NO_DATA`.
- `tests/`: unit tests across XAU, EUR, BTC, with stale, future, broker-depth-only and duplicate safeguards.
- `docs/research/reversal_liquidity_fusion_20261020.md`: research architecture and next stage.

## Checked locally
`PYTHONPATH=src pytest -q tests` -> 10 passed (synthetic evidence / functional contract, **not** market-data replay).

## GitHub changes
Draft PR #799: https://github.com/rizanrizan93/Forex-scanner/pull/799
Research branch: `research/rlfe-manual-orderflow-20261020`.
The GitHub pull request is the authoritative source for the optional Streamlit dashboard wiring; this ZIP packages the portable core and tests only.

## Known limitations
No licensed Bookmap/CME depth feed, no running order-flow collector or sidecar producer, and no historical L2 order book replay are connected. Missing or untrustworthy market depth yields `NO_DATA` or `STALE`. The index is uncalibrated; it must not be labeled as win rate. No cBot, execution, bridge, risk or portfolio mutations.
