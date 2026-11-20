# ForexScanner: XAUUSD Fed R6 · Area Entry (manual / read-only)

This production-dashboard **display panel** is intentionally isolated
from Frozen V1, cTrader cBots LIVE, order routing, trading risk, and
the multi-PR research implementation #887–#894.

Access: XAUUSD → **Fed R6 · Area Entry** (or deep link
`/XAU_Fed_R6_Area_Entry`).

## Basis and live data

- Reads the SAME strictly timestamp-validated, public market-only
  cTrader M1 + bid/ask feed as the existing Manual R3 panel, via
  `manual_r3_feed.fetch_market()`.
- Price is shown only with a fully closed M1 within 90 seconds;
  bid/ask must be within 30 seconds, spread geometry valid.
  A missing/stale source yields WAIT, not fabricated numeric levels.
- M5 resamples must contain all 5 M1 constituents; H1 and H4
  likewise require fully closed 60 and 240 M1 bars.
- Swing high/low confirmation is strict **2 complete M5 bars LEFT
  and 2 complete M5 bars RIGHT**, with no M5 gaps. The swing cannot
  be used until the second right bar closes. Lookback 96 M5.
- BUY watch is below market: confirmed **SWING LOW** to
  `low + 0.25 * ATR14(M5)`. SELL watch is above market:
  `high - 0.25 * ATR14(M5)` to confirmed **SWING HIGH**.
  Only unbroken pivot structures are shown, with first-touch
  freshness disclosed; maximum two displayed per direction.
- This is a **new manual-watch geometry hypothesis inspired by R6**.
  It is NOT the original 69-FOMC V4/continuation backtest strategy
  and **does not inherit its historical success rate**.

## What the user can see per side

- dynamic price band, when confirmed, distance in M5 ATR units
- entry-reference WATCH price at near edge, NOT limit fill
- M1 candle-close conditional reclaim threshold
- scenario stop at pivot ±0.25 M5 ATR
- conditional TP1 = 1.5R, TP2 = 2R from reference
- nearest opposing confirmed swing and available geometric room
- macro alignment, M1 trigger observation, fresh/retested state,
  H1/H4 bias, current quote, news protection, anti-chase and
  structural-room checklist
- optional annotated M1 view and downloadable JSON research audit

These hypothetical price levels are **not verified price targets**,
do not account for spread/slippage/financing and MUST NOT be used to
claim 80% probability. A static price band can be invalidated by a
later closed M5; the panel recomputes per live source refresh.

## FOMC direction authority

**Default is WAIT.** The genuine R4 macro source requires
timestamped, captured *intraday* OIS1Y, cash TIPS10Y, S&P 500 and
DXY before/after an identified actual FOMC release. That source is
NOT wired to the production ForexScanner main branch.

Therefore the panel intentionally displays both BUY and SELL
**WATCH zones** but NEVER promotes either to an approved live Fed
entry. The existing macro daily FRED/Treasury and 2019–2026 USMPD
retrospective research DO NOT meet the R4 point-in-time source gate.

The pure evaluation module implements strict optional R4 validator
but the dashboard calls it with `macro=None` until a real
first-observed independent market-data feed is provisioned,
tested, and explicitly approved. Missing macro never silently
becomes a manual BUY/SELL override.

## Safety, deployment scope, and methodology

- User-authorized change is ONLY a new read-only ForexScanner
  tab and new source-isolated pure analytics module; no changes
  to cBot LIVE, bridge, Frozen V1, Manual R3 or brokerage.
- No market/limit orders or account connection exists in the module.
- The historical 69 FOMC R6 research found 0 old V4 entries and
  only 1 newly recovered BUY structural-room candidate; some
  retrospective SELL H1 terminal directions were >80% in tiny
  samples but actual target-before-adverse rates were ~54%.
  **Not a validated 80% live BUY/SELL model.**
- CI unit tests reproduce causal two-right-M5 confirmation,
  quote/candle freshness, a provisional R4 research watch
  validator, BUY/SELL reference geometry, incomplete data,
  news veto and no order authority.

Original 2019–2026 R6 research:
https://github.com/rizanrizan93/Forex-scanner/actions/runs/44653729303

Prior R6 research PR: https://github.com/rizanrizan93/Forex-scanner/pull/894
