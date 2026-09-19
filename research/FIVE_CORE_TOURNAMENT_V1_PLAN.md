# Five Core Tournament V1

Research-only contract. `execution_influence=false`.

## Fixed universe

1. XAUUSD
2. EURUSD
3. GBPUSD
4. USDJPY
5. AUDUSD

The purpose is to learn instrument-specific behavior instead of assuming that one strategy must work on every pair.

## Frozen strategy families

The following rules are frozen before reading this tournament's OOS results:

1. `D1_TSMOM_60_200`
   - Daily timeframe.
   - Trend direction: close vs EMA200.
   - Momentum confirmation: 60-day return has the same sign as the trend.
   - Entry: next daily open.
   - Stop: 2 ATR14.
   - Target: 4 ATR14 (2R).
   - Max hold: 30 daily bars.

2. `H4_TREND_PULLBACK`
   - H4 timeframe.
   - Trend: EMA50 vs EMA200.
   - Pullback/reclaim: prior close on the wrong side of EMA20, current close reclaims EMA20 in the trend direction.
   - Entry: next H4 open.
   - Stop: 1.5 ATR14.
   - Target: 3 ATR14 (2R).
   - Max hold: 24 H4 bars.

3. `H4_COMPRESSION_BREAKOUT`
   - H4 timeframe.
   - Compression: ATR/close below the lagged rolling 100-bar 35th percentile.
   - Breakout: close beyond the prior 20-bar high/low in the EMA50/EMA200 trend direction.
   - Entry: next H4 open.
   - Stop: 1.5 ATR14.
   - Target: 3 ATR14 (2R).
   - Max hold: 24 H4 bars.

4. `M15_ASIA_SWEEP_REVERSAL`
   - M15 timeframe, Europe/London DST-aware session clock.
   - Asia range: 00:00-06:45 London local.
   - London observation window: 07:00-11:45 London local.
   - Reversal signal: price sweeps an Asia extreme by at least 0.10 ATR14 and closes back inside the range.
   - Entry: next M15 open.
   - Stop: signal extreme plus 0.25 ATR14 buffer.
   - Target: 1.5R.
   - Max hold: 16 M15 bars (4 hours).
   - Max one trade per London-local date.

## Historical splits

Slow families (`D1_*`, `H4_*`):
- Development: 2018-01-01 through 2022-12-31.
- Validation: 2023-01-01 through 2024-12-31.
- OOS: 2025-01-01 through 2026-08-31.

M15 session family:
- Development: 2022-01-01 through 2023-12-31.
- Validation: 2024-01-01 through 2024-12-31.
- OOS: 2025-01-01 through 2026-08-31.

## Cost contract

- Major FX base: 1.2 pip round trip; stress: 1.5 and 2.0 pips.
- XAUUSD base: USD 0.17 round trip; stress: USD 0.25 and USD 0.35.

The XAUUSD base is an approximation aligned to current FP Markets Raw pricing: September 2026 average XAUUSD spread about USD 0.11 plus USD 3/lot each-way cTrader metal commission; a standard 100 oz gold lot makes USD 6 round-trip commission approximately USD 0.06 in price terms. Broker replay will still be required before any promotion.

## Conservative mechanics

- Dukascopy BID historical bars.
- Entry is always next bar, never signal-bar close.
- `STOP_FIRST` when stop and target are both touched in one OHLC bar.
- One active position per instrument per strategy.
- No execution, order, calibration-promotion, or Supabase side effects.

## Interpretation gate

OOS is not used to tune rules. Every failure remains reported. A strategy is only a research candidate if OOS expectancy is positive after cost, PF is above 1, annual results are not obviously concentrated in one year, and cost stress does not destroy the edge. Forward DEMO and broker-specific cTrader replay are still mandatory before execution influence.
