# XAUUSD Expansion Challenger — Shadow V1

Status: **OBSERVATION_ONLY**. This research hypothesis has no execution, sizing, entry, SL, TP, RR, correlation, stacking, or LIVE authority.

Rule version: `XAU_IMPULSE_RETEST_EXPANSION_SHADOW_V1`.

The challenger is intentionally a strict subset of the active `IMPULSE_RETEST_V2` concept. A snapshot is active only when XAUUSD has directional impulse, directional structure, a controlled first retest in the 0.10–1.25 ATR band, displacement quality of at least 1.20 ATR range and 0.80 ATR body, and expansion confirmation from either an aligned expanding M5/M15 EMA state or directional displacement on both M5 and M15.

Session and regime are recorded as context, not hard filters. This is deliberate: the public temporal holdout did not support making those filters universal.

Evaluation uses durable `DEMO_SIGNAL_FEATURE_SNAPSHOT_V2` evidence and joins only to reliable, non-manual, non-partial `DEMO_TRADE_CLOSED` outcomes. Shadow events use the distinct event type `DEMO_XAU_EXPANSION_CHALLENGER_SHADOW`; they must never be counted as completed DEMO trades.

Promotion is forbidden by this module. Any future execution experiment requires separate forward evidence, a separate policy decision, tests, and a new reviewed change.