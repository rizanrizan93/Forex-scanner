# Strategy and liquidity contract v0.8

## Selection

The configured universe remains 15 FX pairs.

1. Pair ranking is produced by the upstream macro/technical/cross-asset engine.
2. Direction must agree with signed relative macro edge.
3. The best eight macro-compatible pairs form the research shortlist.
4. The best five receive deep MTF analysis.
5. Any selected pair missing required data is recorded in `DeepScanReport`
   rather than silently disappearing.

## Closed-bar invariant

Bar timestamps represent bucket starts. A bar is eligible only when:

```text
bar.timestamp + timeframe_seconds <= as_of
```

The partial current candle is excluded.

Maximum age of the most recent closed bar:

- D1: 72 hours (weekend-safe)
- H4: 8 hours
- H1: 2 hours
- M15: 30 minutes
- M5: 10 minutes

Any stale required timeframe sets `STALE_SIGNAL`.

## MTF hierarchy

### D1

Regime context. Opposing established trend can hard-block the candidate.

### H4

Primary directional bias.

### H1

Structure and dealing-range anchor. H1 swing points also provide structural
stop/liquidity context.

### M15

Setup layer. v0.8 supports:

- Liquidity Sweep Reversal
- Trend Continuation

A setup may exist without an M5 trigger. Such a candidate remains
`SETUP_FORMING`; it cannot jump directly to execution readiness.

### M5

Trigger confirmation requires:

- aligned valid displacement, and
- aligned BOS or MSS.

Only after the M5 trigger and valid trade geometry can the candidate progress
toward `ARMED` or `EXECUTION_READY`.

## Liquidity map

### External references

- PDH / PDL
- PWH / PWL
- completed Asia high / low
- completed London high / low
- completed New York high / low

### Internal references

- equal highs/lows using ATR tolerance
- latest H1 swing high/low
- FVG state
- validated order blocks
- dealing-range premium/discount/equilibrium

Equal-level tolerance is 0.15 ATR and requires at least two touches.

## FVG state

A three-candle imbalance is tracked as:

- OPEN
- PARTIAL
- FILLED

Filled FVGs are not eligible entry zones.

## Order-block validation

An order block is accepted only when:

1. an opposite candle exists before a valid displacement,
2. the displacement closes beyond recent structure,
3. origin and displacement chronology are valid.

Mitigation and invalidation are recorded separately.

## Trade plan

For LONG:

- entry: aligned FVG zone
- SL: below bullish sweep level or H1 swing low, with 0.15 ATR buffer
- TP1/TP2: next distinct active liquidity above entry

For SHORT, geometry is mirrored.

The data contract rejects:

- SL inside/wrong side of entry
- TP on wrong side
- TP2 not beyond TP1
- RR2 not above RR1
- incomplete TP/RR pairs

## Do-not-chase

- <= 0.25 ATR: normal
- 0.25 to 0.50 ATR: execution-quality degradation
- > 0.50 ATR: `CHASE_BLOCK`

## RR

- TP2 minimum: 1.50R
- preferred: >= 2.00R

Low or missing TP2 on an otherwise formed trade plan activates `RR_BLOCK`.

## Signal phases

High upstream scores cannot bypass pattern maturity.

- no M15 setup -> at most WATCH
- M15 setup but no confirmed M5 trigger -> at most SETUP_FORMING
- trigger but incomplete plan -> at most SETUP_FORMING
- valid trigger + plan + sufficient score -> ARMED/EXECUTION_READY according to score
- any active hard guard -> NO_TRADE

## Provider coverage

v0.8 adds keyless official/public provider adapters for:

- Federal Reserve policy-tool series through FRED CSV
- RBA Cash Rate Target

Together with v0.7:

- ECB Data Portal
- Bank of Canada Valet

This is not yet complete eight-currency macro coverage. GBP, JPY, CHF and NZD
remain pending official-source adapters.

## Execution

v0.8 does not enable live or demo automated order submission.

```text
risk.mode       RESEARCH_ONLY
execution.mode  DISABLED
auto fallback   false
```

Real-money readiness is not claimed.
