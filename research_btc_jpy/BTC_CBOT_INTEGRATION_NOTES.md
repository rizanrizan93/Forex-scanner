# BTC candidate integration notes (design only)
This note does not modify or deploy any cBot. Pin the actual XAU–EUR portfolio source and deployed binary checksums before integration; the older Oct11 standalone parity document is not proof of the Oct17 settlement portfolio identity.

The research model sizes one standalone BTC basket using its own equity and leverage10 hypothesis. That result is not retained automatically when XAU/EUR use the same equity, margin and pending risk. Preserve the selected signal parameters as a separate baseline; any portfolio allocation is a separately labelled experiment.

A shared coordinator needs an atomic account snapshot, margin and worst-stop-loss reservations for outstanding requests before ACK, deterministic processing of simultaneous intents, position ownership/conflict rules, unique intent IDs, durable checkpoint revisions and idempotent ACK/reject/recovery settlement. BTC trades24/7; broker maintenance and actual symbol calendar must be represented.

Read the real BTC symbol units, min/step/max volume, lot/contract size, tick size, commission type/currency, swaps/financing schedule, leverage tiers, account currency conversion, min stop distance and stop-out threshold. The symbol name may be broker-specific. Do not equate one cTrader volume unit with one BTC without evidence.

Official cTrader documentation:
- Minimum and increment: https://help.ctrader.com/ctrader-algo/references/MarketData/Symbols/Symbol/VolumeInUnitsMin/ and https://help.ctrader.com/ctrader-algo/references/MarketData/Symbols/Symbol/VolumeInUnitsStep/
- Leverage tiers: https://help.ctrader.com/ctrader-algo/references/MarketData/Symbols/Symbol/DynamicLeverage/
- Estimated margin: https://help.ctrader.com/ctrader-algo/guides/estimated-margin/
The last guide states estimated margin during backtesting/optimisation does not consider account exposure. Therefore an isolated GetEstimatedMargin result cannot replace portfolio exposure/risk reservation.

Signal parity requirements: reproduce UTC bar boundaries, closed-only signal availability,100-bar cold-start eligibility, ATR Wilder/EMA initialisation from the exact input history, H4 closed trend, next-bar decision/fill distinction, first-fill stop/target anchor, expiry, BE effective on next bar, and precise stage rejection/consumption behaviour. cTrader default indicators/history may initialise differently from this engine.

Execution remains model-only: M1 STOP_FIRST does not prove intraminute order. Margin stop-out precedence versus SL/TP, partial fills, latency, spread jumps, reject/ACK/recovery and liquidity must be tested with broker quote/spec evidence. In particular the existing research engine assigns SL/TP before its intrabar stop-out fallback; it is not evidence of broker priority equivalence. High-risk candidate selection must not be presented as broker-safe.

Required next validation before a combined-performance claim: replay BTC+XAU+EUR on one chronological timeline and one account, preserve all positions/cooldowns/checkpoints across years, compare each signal/intention separately from allocated quantity, reconcile fees/equity/margin and settlement, and stress ordering/delays/specifications. Do not sum standalone ending balances or infer floating-equity diversification from daily realised-cash correlation.
