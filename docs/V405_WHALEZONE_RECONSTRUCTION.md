# V405 RIZAN Whalezone Reconstruction

## Scope

V405 reconstructs the observable behaviour of the user-supplied `WHALEZONE MAPPING TODAY` example without claiming access to the original proprietary formula or private order-flow feed.

The supplied reference image shows one grey BUY reaction box below/around current price and three tiered pink SELL boxes above price. The accompanying text describes Gold as sideways but structured. V405 therefore treats the behaviour as a tiered structural reaction map rather than assuming the labels are direct evidence of institutional/whale orders.

## Causal inputs

V405 uses only fields already available in the scanner snapshot:

- H4/H1 supply and demand (`active_zones`);
- support/resistance map for local refinement;
- liquidity candidates near each box;
- lifecycle/condition fields;
- M15 acceptance/solid-close evidence only when the upstream snapshot actually contains it.

No screenshot price is hard-coded into runtime logic.

## Mapping model

1. Build candidate BUY and SELL bands from active supply/demand and support/resistance.
2. Reject broken, invalid, retired or quarantined zones.
3. Keep BUY geometry below/around current price and SELL geometry above/around current price, with a small ATR tolerance for current-zone interaction.
4. Merge strongly overlapping duplicate bands.
5. Order zones by distance from current price so the nearest reaction becomes tier 1, followed by tier 2 and tier 3.
6. Preserve H4/H1 structural strength, liquidity proximity and lifecycle evidence as metadata rather than using distance alone.
7. Report M15 solid-close acceptance as `UNKNOWN_NO_M15_CLOSE_INPUT` when it is not present upstream. The engine must never fabricate confirmation.

The expected behavioural output is therefore analogous to:

- `WHALEZONE BUY 1` — nearest demand/support reaction box;
- `WHALEZONE SELL 1` — nearest overhead supply/resistance box;
- `WHALEZONE SELL 2` — next higher structural supply;
- `WHALEZONE SELL 3` — deeper/higher structural supply.

V405 can also produce up to three BUY tiers when the market structure contains them.

## Sideways interpretation

When a valid BUY box exists below current price and a valid SELL box exists above current price, the engine reports `SIDEWAYS_STRUCTURED_RANGE`. Being inside a BUY or SELL box is reported separately as `IN_BUY_REACTION_ZONE` or `IN_SELL_REACTION_ZONE`.

This deliberately separates *location* from *entry authority*. A zone is a place to expect reaction, not proof that a reversal has already occurred.

## Confirmation and invalidation

The reconstruction hypothesis is that wick penetration alone should not automatically invalidate a reaction box. A durable/solid close beyond the distal edge is a stronger invalidation signal. V405 exposes upstream M15 acceptance evidence when available, but does not invent it when absent.

Historical replay should separately measure:

- first touch vs retest;
- wick sweep vs accepted break;
- reversal MFE after zone entry;
- MAE/overshoot before reversal;
- time to first opposing tier;
- M15 solid-close confirmation delay;
- false reversal rate after the box is entered.

## Comparison matrix

V405 research should compare:

| Variant | Purpose |
| --- | --- |
| V390 | nearest local reversal baseline |
| V404-A | strict V390+V403 confirmed consensus |
| V404-A+B | confirmed plus early/liquidity-qualified consensus |
| V405 | tiered Whalezone-style structural mapping |
| Hybrid | V405 location + V404 direction/quality confirmation |

The image/reference mapping is a behavioural benchmark only and must not leak its specific historical prices into runtime or backtest decisions.

## Promotion contract

V405 itself is mapping/research only:

- `execution_authority = false`
- `demo_auto_execution = false`
- `live_execution_enabled = false`

For DEMO calibration, an independent sampler may consume a V405 box only after it has its own explicit DEMO-only risk contract, idempotency, structural SL/TP, account-environment verification, and outcome ledger. LIVE execution remains outside V405 authority.
