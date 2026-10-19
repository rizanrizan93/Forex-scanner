# XAUUSD manual reversal: confirmed-entry PF audit (2026-10-20)

**Research only, not a cBot backtest or authorization to trade.** Source: Dukascopy original tick-derived BID M1, 2019-01-01 through 2026-03-31. Aggregate source M1 bars: 2,557,244; candidate H1/H2/H4 first-contact zones: 10,183; M15/M5 confirmed model entries: 5,191. It is not a true raw bid/ask tick replay and is not FP Markets execution parity.

A causal candidate uses a completed M15 reclaim after a zone contact and a later completed M5 close breaking the prior three M5 candles. Model fills on the next M1 open; stop is beyond distal by 0.05 ATR; target is 1.5 times entry-to-stop risk; time exit after ~24h, waiting until market reopens if the market was shut at cutoff; gap stops fill at the opening price. STOP_FIRST if stop and target hit on same M1. Commission model $0.07 per ounce roundtrip ($7/100 oz), slippage $0.05 per ounce each side, historical average M1 spread with approximated ask. This is a **synthetic execution model using actual historical BID M1**. There is no platform-side position sizing, fill rejection, fee parity, macro vintage data, or historical order book. Three outcomes have no qualifying reopening within 72h and are excluded.

## Net modeled PF, 1.5R (independent event ledger)

| Instrument | 2019-2023 | 2024-2025 | Jan-Mar 2026 |
|---|---:|---:|---:|
| All H1/H2/H4 | 0.842 (3,515) | 0.937 (1,509) | 1.489 (164) |
| H2 | 0.831 (1,119) | 0.941 (463) | 1.720 (49) |
| Confirm <=30 minutes | 0.924 (860) | 1.328 (343) | 1.905 (40) |

A 'one-position-at-a-time' model reduces the All H1/H2/H4 Jan-Mar 2026 PF from 1.489 to ~1.029. Thus the 2026 independent-event PF must **not** be presented as portfolio trading profitability.

## Selected challengers (6,242 filter combinations screened)

- A: confirmation within 30 minutes, zone age no more than 12h, entry opposite closed D1 EMA20/EMA50 regime. PF 1.112 train (295), 1.338 validation (119), 2.438 Q1 2026 (21). PF risk-normalized train 0.957; 2024-25 monthly block-bootstrap 95% interval for per-ounce PF includes 1: [0.897, 1.853]. One-position PF validation ~1.140.
- B: H2/H4 with departure BOS and <=60-minute confirmation; PF validation ~1.161 (157), Q1 2026 ~0.661 (13).
- C: H2/H4, <=45m confirmation, closed D1 aligned trend; PF validation ~1.589 (139), Q1 2026 0.754 (11), showing regime/overfit sensitivity.

**Multiple-testing warning:** 2024-25 validation was inspected while selecting filters, so it is not an untouched holdout for the final selected rule. Q1 2026 is too small. No tested rule is certified PF >=1.5 after risk normalization, overlapping-event removal and adverse transaction-cost sensitivity. D1 research candle alignment is UTC, while broker-native cTrader D1 sessions may differ.

## Release policy

Existing H1/H2/H4 structural references, H12/D1/W1 context, M15/M5 confirmation and manual dashboard remain **read-only**. Do not use any historical PF value as a probability of reversal or entry entitlement. Do not alter frozen cBots, risk, bridge, sizing, SL/TP or trading permissions. Future testing: broker-native bid/ask tick replay, exact fee/slippage and point-in-time macro, one-position ledger, correction for multiple model search, new multi-year true holdout or forward paper-trading before any promotion.

Full reproducibility package: supplied in the ChatGPT research artifact `RIZAN_XAU_CONFIRMED_REVERSAL_RESEARCH_2019_2026.zip`; massive tick archive excluded.
