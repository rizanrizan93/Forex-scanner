# Five Core Tournament V1

Research-only contract. execution_influence=false.

Core instruments: XAUUSD, EURUSD, GBPUSD, USDJPY, AUDUSD.

Goal: learn pair-specific strategy fit using a small fixed universe, not a universal-strategy assumption.

Frozen strategy families before OOS review:
1. H4 time-series momentum.
2. H4 trend-pullback continuation.
3. H4 volatility compression -> breakout expansion.
4. M15 Asia-range sweep -> reversal.

Primary historical split:
- Development: 2018-01-01 through 2022-12-31 for H4 families; 2022-01-01 through 2023-12-31 for M15 session family.
- Validation: 2023-01-01 through 2024-12-31 for H4; 2024 for M15.
- OOS: 2025-01-01 through 2026-08-31.

Costs:
- Major FX: 1.2 pip round-trip base, stress 1.5 and 2.0 pips.
- XAUUSD: $0.17 round-trip base, stress $0.25 and $0.35. This reflects September 2026 FP Markets Raw pricing approximately: average XAUUSD spread $0.11 plus $3/lot each-way cTrader metal commission (about $0.06 round trip per standard 100 oz lot). Historical backtest remains approximate and will later need cTrader broker replay.

Conservative mechanics:
- Entry next bar after signal.
- STOP_FIRST when SL and TP are both touched inside the same OHLC bar.
- At most one active trade per instrument per strategy.
- No execution or promotion side effects.

Selection rule:
- Do not tune on OOS.
- Rank pair x strategy only after development + validation diagnostics are frozen.
- OOS must be reported for every frozen candidate, including failures.
- A candidate is not promotion-eligible unless OOS expectancy > 0, PF > 1, cost stress is acceptable, and performance is not concentrated in a single year.
