# RIZAN XAU — Rejection Engine V2 (RESEARCH ONLY)

## Objective

Track **BUY and SELL simultaneously**, show actionable watch locations *before* price
touch, detect a candidate M1 rejection without requiring an M5 close, and offer
an optional retest/reclaim path. Never send or authorize trades.

## Data and time contract

- Existing `manual_r3_feed.fetch_market()` provides validated cTrader **read-only** M1 OHLC,
  timestamped by **UTC candle OPEN**, with separate bid/ask quote timestamps.
- M5/H1/H4 are reconstructed only from **complete contiguous minutes within each bar**
  and labeled with **UTC candle CLOSE**. No incomplete current bar, no interpolation.
- All watch geometry excludes any M5/H1 bar that includes the latest M1 event.
- M1 close older than 90 seconds, M5 data too old, missing source, invalid OHLC,
  or invalid timestamps mean **WAIT DATA**. Old/absent bid/ask means **NO entry candidate**.
- H1 and H4 bias must agree; otherwise primary bias is **WAIT**, not an invented
  directional forecast. If M1 history is too short, HTF bias is **UNAVAILABLE**.
- This provider has limited M1 history (2,000–12,000 bars), so H4 may be
  unavailable. The panel must say so rather than substitute a fictitious value.

## Watch zones

At least **one structural** (M5/H1 support or resistance) and **one EMA** (M5
EMA20/50 or H1 EMA20) are retained per side, plus the next nearest third.
Both sides remain visible regardless of trend; countertrend levels are not
silently omitted. A zone has a level and width derived from historical M5 ATR
and current spread when a fresh quote is available.

`APPROACHING` → `TOUCHED` → `EARLY REJECTION` or `WAIT RETEST` →
`RETEST RECLAIM` / `MISSED`. All are **unvalidated research classifications**.

## Entry timing and anti-chase

- Earliest candidate: first **closed M1** that touches a watched zone, reclaims
  its level and has a rejection wick ≥30% of that M1 candle.
- Quote fresh ≤30 seconds; aligned H1/H4 bias; spread ≤0.2 M5 ATR;
  directional chase distance 0–0.6 M5 ATR. If any gate fails → WAIT.
- Retest is **optional**, never compulsory. A fresh closed M1 reclaim of a
  recently rejected zone can become `RETEST RECLAIM CANDIDATE`.
- These thresholds are *hypotheses*, not calibrated probability, and may change
  after genuine out-of-sample replay.
- Displayed invalidation is a **structural reference**, NOT a broker SL.
  Manual trader must account for actual spread/slippage/risk.

## Test status

Synthetically constructed BUY/SELL trend scenarios cover H1/H4 bias, both
sides and both zone types, M1 early candidate before M5 close, optional
BUY/SELL retest, partial/missing M5 bars, forming bar, stale and naïve
timestamps, unavailable H4 bias, and stale/missing quotes.

**Not completed:** real Dukascopy/FP Markets event replay, 2019–2026 BUY and SELL
accuracy with n, transaction costs and first-touch evidence, yearly ablations,
holdout, prospective forward test, latency and slippage assessment.

## Release gate

Do not merge this draft into `main` or enable in ForexScanner production
until the synthetic CI is green **and** independent real-market replay,
data freshness, UI smoke testing, and performance thresholds are accepted.

Acceptance metrics must include BUY/SELL n separately, Wilson 95% intervals,
signal-to-touch delay, 2025–26 as already-observed rather than pristine holdout,
year-level stability, and additional $10 MFE only **after** directional validity.
Do not change Frozen V1, Manual R3, cBots, bridge, order routing or risk settings.
