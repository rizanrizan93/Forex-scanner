# V404 Runtime Integration & Research Protocol

## Objective

V404 tests whether requiring agreement between the V390 local reversal engine and the V403 generalized AFIQ challenger can improve XAUUSD decision quality without recreating the historical problem of an empty or excessively late scanner.

V404 is deliberately a **shadow consensus layer**. It can emit `READY_CONFIRMED` or `READY_EARLY` for research/logging, but it has no LIVE or DEMO execution authority until historical and forward evidence passes the promotion protocol below.

## Runtime hypothesis

The working hypothesis is:

1. V390 supplies nearby, causal local supply/demand geometry so the scanner does not wait only for distant H4/H1 zones.
2. V403 adds challenger logic around liquidity, structural invalidation, validation levels, event risk, and the generalized AFIQ-pattern state machine.
3. V404 rejects direction conflicts and unavailable/event-blocked states rather than averaging conflicting engines.
4. Agreement should reduce false positives; the cost is lower trade frequency. That trade-off must be measured, not assumed.

## States under test

- `READY_CONFIRMED` — V390 is ready and V403 is confirmed in the same direction. Research Grade A.
- `READY_EARLY` — V390 is ready and V403 has a causal early/liquidity-qualified state in the same direction. Research Grade B.
- `WATCH_*` — geometry or directional evidence exists but consensus is incomplete.
- `WAIT_CONFLICT` — V390 and V403 disagree. Fail closed.
- `BLOCKED_EVENT`, `INVALIDATED`, `WAIT_V403_UNAVAILABLE` — hard fail-closed states.

No state in V404 currently grants execution authority.

## Historical comparison matrix

The research should compare, on identical causal data windows:

| Variant | Description |
| --- | --- |
| V390-only | Local reversal geometry/trigger baseline |
| V403-only | Generalized challenger bridge baseline |
| V404-A | Consensus, `READY_CONFIRMED` only |
| V404-A+B | Consensus, `READY_CONFIRMED` + `READY_EARLY` |

Results must be separated by LONG/SHORT and by calendar year rather than reporting only one aggregate number.

## Walk-forward period

Target period: 2012–2026, using the existing V402 calendar-year walk-forward architecture with fixed pre-year warmup. Every decision must be causal: no future zone information, future event result, or benchmark/reference forecast price may leak into the runtime context.

## Primary metrics

For each variant record at minimum:

- number of trades and trades/year;
- win rate;
- fixed-price profit factor;
- expectancy;
- net price-unit PnL;
- maximum drawdown in the same fixed-price units;
- LONG/SHORT balance;
- cost-stress profit factor and expectancy;
- per-year stability, not only full-sample performance.

Also log scanner-specific classification metrics where labels are available: signal precision, false-positive rate, missed-reversal rate, and median entry delay from first valid zone interaction.

## Promotion gates

V404 should inherit the existing V402 numeric discipline rather than inventing a softer threshold:

- all expected walk-forward years present;
- at least 100 total trades;
- aggregate fixed-price PF >= 1.50;
- positive aggregate expectancy;
- PF >= 1.20 after 0.50 XAU price-unit cost stress;
- every robust year (>=5 trades) has PF >= 1.00.

Even if numeric gates pass, promotion remains blocked until the existing V402 data-quality blockers are addressed:

- historical spread and commission are not directly observed;
- causal event-blackout archive has not yet been applied;
- parameter selection requires held-out validation.

## Additional robustness slices

Before DEMO promotion, inspect:

- high-impact event window vs normal market;
- Asia, London, New York and overlap sessions;
- high/low volatility buckets;
- US10Y daily regime and intraday pressure alignment;
- first-touch vs retested zones;
- liquidity sweep present vs absent;
- LONG vs SHORT asymmetry;
- entry latency and missed trades caused by confirmation.

A strategy that reaches PF >=1.50 only in one narrow regime should not be promoted globally. Prefer explicit regime gating instead.

## Forward validation

After historical/held-out gates pass, run V404 in shadow forward mode before enabling DEMO auto-order. Compare timestamped V404 decisions with realized XAU path and broker-observed spread/costs. Only DEMO execution may be promoted after this stage; LIVE auto-execution remains outside V404 authority.

## Current implementation status

V404 runtime consensus is implemented for decision support and dashboard display. The Streamlit src-layout bootstrap regression is also addressed in the V404 integration branch. Historical V404 performance is **not yet claimed**; the purpose of the next replay work is to measure it without look-ahead or benchmark leakage.
