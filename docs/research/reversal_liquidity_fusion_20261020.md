# RIZAN RLFE V2 — Manual Reversal × Order-Flow Research (2026-10-20)

**Status: research branch / not merged / no live Bookmap feed / no demonstrated P&L uplift.**

## What changed
- `src/fx_scanner/reversal_liquidity_fusion.py`: evaluates independently observed, timestamped depth/trade evidence using a bounded *ordinal* index. No probabilities.
- `src/fx_scanner/manual_reversal_orderflow.py`: accepts only one correctly tagged observation per exact `zone_id`; invalid, duplicate, stale and absent evidence fail closed.
- `src/fx_scanner/manual_reversal_dashboard.py`: retains original Candidate A WATCH/WAIT and zone map; displays supplementary RLFE state under the H1/H2/H4 anchor with venue label, as-of time and provisional index. It reads an optional dedicated sidecar from `scanner-reversal-snapshots/runtime/manual_reversal_orderflow_snapshot.json`.
- New regression tests cover missing feed, order permission isolation, SELL/BUY direction, invalid basis, broker-only DOM, wrong symbols/times, and duplicate zone evidence.

**No producer currently publishes the optional sidecar. The dashboard therefore defaults to NO_DATA, not false Bookmap signals. The main branch, cBots, bridge, settlement engine, trading risk and account state are not changed.**

## Sidecar contract

The optional JSON object must contain:
```json
{
  "contract": "RIZAN_REVERSAL_ORDERFLOW_SIDECAR_V1",
  "symbol": "XAUUSD",
  "execution_authority": false,
  "execution_influence": false,
  "observations": []
}
```
Each observation must be calculated from an actual licensed historical/live market-depth/prints feed and must contain the exact manual-map zone id, `symbol`, `source`, `window_start`, `window_end`, `depth_updates`, `depth_imbalance` (-1..1), `near_wall_retention` (0..1), `near_wall_pull_ratio` (0..1), and `mapped_zone_overlap: true` only when verified against the exact price zone. The retention/pull attributes must refer to the depth supporting the **zone's side** (bid for BUY, ask for SELL). CME/crypto observations additionally require `mapping_error_atr` from *past-only* simultaneous exchange-vs-CFD prices. For valid venue trade prints, optionally attach `trade_count`, `signed_cvd_change`, and `signed_absorption`, with `signed_absorption>0` defined as buyer absorption. A `CTRADER_LEVEL_II` feed may never claim these trade-derived features.

Depth updates and trade prints must have actual exchange/native timestamps plus collector receipt timestamps in upstream permanent evidence, source venue, market type, symbol mapping and contract roll id. Never generate order flow with M1 OHLC, DOM score only, or LLM inference. Prefer keyed, immutable evidence storage and explicit gaps; benchmark record age independently of stream freshness.

XAU = CME GC or broker-specific cTrader DOM; EUR = CME 6E or broker-specific DOM; BTC = identified crypto spot or perp venue/aggregation. These are **not** identical to FP Markets CFD order books and need observed, causal price alignment. Orderbook charts/heatmaps are not enough to prove executed absorption. No BTC CFD weekend permission is inferred from 24/7 crypto exchange data.

## Decision semantics

- `SUPPORTIVE`: observed flow/depth tentatively supports the planned zone direction (not an order).
- `MIXED`: conflicting or indecisive evidence.
- `OPPOSING`: opposing order-book pressure; no automatic veto.
- `STALE`: observation too old.
- `NO_DATA`: missing, invalid, duplicate, unmatched or unavailable.
- `support_index`: fixed **research heuristic only**, never win probability, never order permission.

The manual page's ~60-second refresh cannot support sub-second Bookmap execution. The snapshot's 90s limit is only for display. No collector, credentials, API subscription or historical L2 archive was provisioned in this change.

## Measurement protocol

Freeze the current baseline (H1/H2/H4 zone, H12/D1/W1 context, first touch ≤12 h, M15 reclaim, M5 BOS, 1R Candidate A) and compare four **pre-registered challenger** families: absorption, sweep/control-flip, liquidity withdrawal/continuation risk, and macro+HTF+orderflow fusion. Replay must use identical entry-opportunity timestamps, next executable bid/ask quote, broker cost, one-position exposure, and exact stop-first / gaps. Preserve shadow zones that were not selected to measure opportunity loss. Separate exchange depth availability by venue; never backfill with candle proxies.

Train using chronological data, purge overlapping event windows, keep a genuine untouched multiyear holdout or forward paper-trading period, and report win rate, PF, expectancy (R), drawdown, trade count, opportunity coverage, MFE/MAE, and threshold sensitivity. Correct for multiple testing. Previous Candidate A validation PF ≈1.338 in independent overlapping event ledger but ≈1.140 in one-position validation; results are insufficient to claim a proven edge. Historical replay did not include real order book.

## Bookmap implementation caveat

Bookmap supports order/depth and trade listeners; the platform also offers Python add-on examples, subject to environment and access. The availability of a documented API **does not confer a working connection or access to CME historical L2**. Confirm licensing, machine uptime and retention before attempting a collector. Relevant primary documentation:
- https://bookmap.com/knowledgebase/es/docs/API-Tutorial
- https://github.com/BookmapAPI/python-api
- https://bookmap.com/knowledgebase/de/docs/Addons-Market-Pulse-Web

## Release guard

Merge/deploy only after independent regression and review. Even after UI promotion, keep `execution_authority=false`, `execution_influence=false`, `probability=null`, and prohibit imports of the bridge or execution code into the manual map. Neither RLFE output nor any Bookmap feed may alter frozen XAU–EUR–BTC cBots.
