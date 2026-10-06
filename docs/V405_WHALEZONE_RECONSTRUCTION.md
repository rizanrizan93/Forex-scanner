# V405 RIZAN Tiered Reaction Map — Behavioral Reconstruction

## Scope

V405 reconstructs the *observable behavior* of the tiered BUY/SELL zone map shown in the user-provided WHALEZONE example. It does **not** claim access to the original indicator source code, hidden order flow, or proprietary formula.

The source image visibly contains three pink SELL boxes, one grey BUY box, current price near the BUY area, and descending step-like pink overlays. The accompanying text states that pink boxes are SELL areas, grey boxes are BUY areas, and the market is sideways but structured.

Everything beyond those visible facts is an engineering hypothesis that must be validated independently.

## Reconstruction hypothesis

V405 maps current causal XAUUSD structure into outward tiers:

- `BUY_1..BUY_3`: demand/support reaction areas at or below current price;
- `SELL_1..SELL_3`: supply/resistance reaction areas at or above current price;
- tier 1 is the nearest relevant reaction edge;
- later tiers are progressively deeper structural areas, with H1/H4 persistence used as a quality tiebreaker;
- overlapping S/R and S/D geometry is clustered to avoid duplicate boxes;
- liquidity metadata is attached to each tier when available.

The engine reuses V390 causal S/D + S/R + liquidity candidate construction so V405 does not introduce benchmark prices from the example image into live runtime logic.

## Timeframe contract

The working behavioral model is:

1. **H4** — primary structural anchors and deeper destination/reversal areas.
2. **H1** — local structural refinement and intermediate reaction zones.
3. **M15** — validation/acceptance layer.
4. **M5** — entry refinement/timing layer.

The specific hypothesis under test is that a wick/sweep outside a mapped box is not enough to invalidate it, while a solid M15 close/acceptance outside the structural edge can invalidate the current tier and shift focus to the next tier. V405 currently exposes this as metadata only; it does not fabricate M15 candle evidence when that evidence is absent from the input snapshot.

## Ranking and lifecycle

V405 starts with V390 candidates, excludes broken/invalid/retired zones, clusters overlapping candidates, then ranks outward from current price. When two candidates are similarly located, structural quality is favored using H4/H1 timeframe, S/D source, lifecycle state, score, liquidity, and excessive-touch penalties.

This is intentionally different from selecting the single highest-scoring distant H4 area. The objective is to retain a map such as `BUY_1 -> SELL_1 -> SELL_2 -> SELL_3` while still preserving the higher-timeframe structure.

## Sideways interpretation

When both a nearest BUY and nearest SELL tier are valid and non-overlapping, V405 publishes a local range with floor, midpoint, ceiling, and current-price location. This directly supports the user-facing question: *which edge should be watched next, and what is the next structural tier if that edge fails?*

## Safety and execution boundary

V405 is analysis/reconstruction only:

- `execution_authority = false`
- `demo_auto_execution = false`
- `live_execution_enabled = false`

The engine can supply geometry to a separately audited DEMO calibration path, but broker execution must remain outside V405 and retain DEMO-account verification, idempotency, server-side SL/TP, spread checks, position limits, and event/shock blocks.

## Validation plan

Independent validation should compare V405 against V390/V404 using causal historical and forward data. Record at minimum:

- zone-touch frequency;
- reaction probability by tier;
- overshoot/sweep depth;
- M15 close-through invalidation rate;
- MFE/MAE after first touch;
- probability of reaching the opposing tier;
- entry frequency and delay;
- win rate, profit factor, expectancy, drawdown, and cost stress for any separately defined DEMO execution rule.

The user-provided example levels are reference evidence only. They are never hard-coded into runtime zone selection.
