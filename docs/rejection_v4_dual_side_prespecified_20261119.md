# RIZAN Rejection Engine V4 — symmetric BUY/SELL hypotheses (RESEARCH)

**Frozen design declaration before first V4 real-price replay, 19 Nov 2026.**
Draft PR #887; must **not** merge or deploy into production. V3 lifecycle
remains separate and retains frozen invalidation and breakout kill-switch.

## Why V4

V3 required H1 and H4 to agree with entry side. This systematically
suppressed countertrend reversal BUY during bearish H1/H4 regimes, and
countertrend SELL during bullish H1/H4 regimes. That is a model-coverage
failure, not proof missed BUY trades were profitable.

V4 emits both side watch records independently, routing to:

1. **TREND_REJECTION**: both H1 and H4 agree with entry side.
   If last closed M1 touches EMA20 from last completed M5, reclaims it,
   has >=25% rejection wick and directional close, it is an early
   candidate subject to quote / spread / chase / opposing-room gates.
2. **COUNTERTREND_REVERSAL**: H1 and H4 are both available and at
   least one is opposite entry direction. Look for a liquidity sweep of
   12 prior closed M1 high/low by >=0.015 ATR(M5), reclaim inside that
   reference and >=25% rejection wick. Within three closed M1 candles,
   require directional close beyond pre-event 3-bar opposing structure
   (MSS) with >=30% body/range. Same-bar displacement is allowed if it
   clears the existing structure *after a completed M1 close*.
3. **HTF_CONTEXT_UNAVAILABLE**: missing/mixed/neutral H1/H4 produces
   watch-only, not an executable BUY/SELL candidate. Bias must never be
   invented to increase sample counts.

## Timing / risk guards

- Only completed candle timestamps UTC. M5/H1/H4 are reconstructed from
  full sets of M1 minutes; forming candles forbidden. No forward-looking
  pivot-high confirmation.
- Quote age <30 seconds from existing reader and spread <=0.20 ATR(M5).
  Research replay simulates constant $0.50/oz spread; not a genuine fill.
- Anti-chase: quote-to-watch directional distance 0–0.65 ATR(M5).
- Opposing-room: closest historical completed M5 opposite swing >=0.80
  ATR(M5) away; absence is fail-closed. No automatic order routing.
- Only first event per side/setup within fixed 60-minute cooldown for
  evaluation. Both BUY and SELL n required, not only signal count.
- V4 results are independent of V3 signal states; V3 invalidation and
  failed-rejection veto can block a V4 candidate for 15 minutes.
- All thresholds above are **unvalidated prespecified research
  hypotheses**; not tuned on the 2026 screenshot or November samples.

## Required falsification

- Report **BUY and SELL separately**: event n, H1/H4 signed direction
  after hypothetical cost, first touch +$3 before adverse -$3 and
  +$10 before -$5, first +$3 before frozen invalidation, Wilson 95%.
- Compare trend and countertrend by year and session and against the
  V3/zone-touch baseline **on exactly matched time windows**.
- The 2023 and 2026 samples were used in earlier research; treat them
  as **exploratory / not pristine**. Validate prospectively on later
  timestamped signals with real spread and quote-age before deployment.
- Do not claim success from a single side, small n or synthetic tests.

## Reproducibility

- Classifier: `src/fx_scanner/rejection_v4_research.py`
- Tests: `tests/test_rejection_v4_research.py` and
  `tests/test_rejection_v4_replay.py`
- Replay: `scripts/replay_rejection_v4_outcomes.py`
- CI: `.github/workflows/rejection_v4_replay.yml`

Nothing changes Frozen V1, Manual R3, cBot LIVE, bridge, order routing or
account risk. `execution_authority = False`.
