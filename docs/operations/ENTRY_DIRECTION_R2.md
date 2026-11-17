# XAU manual entry direction R2

The default XAU panel is Arah Entry R2. Retired decision/checklist/technical,
USD Lead, consensus and Manual R3 routes resolve to this panel. Macro, Pre-News,
zone maps, EUR, Frozen V1 and cBots keep their existing engines.

This is the frozen experimental SELL-only rule 670, an equally weighted HGB and
ExtraTrees ensemble with a SELL calibrator, 86 causal features and selection
threshold 0.523979705816228. Artifacts have SHA-256 verification and are loaded
only by the independent market reader. Base64 transport preserves the exact
original joblib bytes; hashes are checked after decoding and before loading. The Streamlit process reads a small
public JSON snapshot and does not need scikit-learn or broker credentials.

## Evidence and limits

| Period | Correct / signals | Direction accuracy |
| --- | --- | --- |
| 2022 H2 development | 22 / 30 | 73.3% |
| 2023–2024 validation | 70 / 110 | 63.6% |
| 2025 | 28 / 65 | 43.1% |
| Q1 2026 | 14 / 24 | 58.3% |

The requested 80% accuracy has not been achieved. Scores are selection scores,
not a claim of equivalent win probability. Research dates have already been
used in earlier experiments. Do not treat these results as an untouched test.
The direction benchmark is BID reaching +0.25 initial H1 ATR in the predicted
direction before -0.25 ATR, within 60 minutes (ambiguous bars adverse-first).
This is not an executable exit strategy or net trading win rate.

The conditional 2025 median peak before a 0.25 ATR pullback was $4.0535/oz over
26 cases with correct initial direction and an observed pullback. This is known
retrospectively, not a fixed TP. Dukascopy research and FP Markets market data
can differ; native broker accuracy remains unvalidated.

## Reader and freshness

`rizan-entry-r2.timer` refreshes an independent oneshot every 20 seconds after
completion, using its own venv, 768 MB memory ceiling and 30% CPU quota. It
retains 60,000 completed XAU M1 bars plus the observed entry open and 2,000 EUR
M1 bars. Only completed candles contribute indicator/close features. Actual
bid/ask ticks provide the previous minute spread and current quote. Unknown
historical spread is never presented as observed.

A trigger expires at the next minute boundary. Quotes older than 30 seconds,
stale candles, incomplete spread/open data or failed reads cannot yield an
active trigger. The UI refreshes every 10 seconds. Scoring and selection are
frozen within a minute and persistent across restarts. Selection is limited to
two observed signals per WIB day, with 120 minutes between selections. The UI
shows the observation start because historical signals missed before startup
are not counted as observed signals.

The public endpoint is `/bootstrap125/entry-direction-r2.json` with no-store.
Private state and existing broker configuration are never included. The protocol
allowlist contains authentication, symbol discovery, historical bars/ticks and
heartbeats only. Order, cancel, token-refresh and reconciliation are disabled.
The install checks the trading bridge PID/start identity before and after and
does not restart it. Failed worker runs publish WAIT_DATA rather than retain an
active trigger.

## Verification

The focused suite covers frozen model parity, feature causality, signal freeze,
limits, stale/expired data, protocol guards, navigation and existing manual R3.
38 tests passed locally. A real 60,001-bar research window reproduced the
2026-03-23 07:10 UTC style 79 score exactly (0.542188150942801), including setup
generation and all feature calculations. CI repeats the focused suite before
installation and checks two advancing fresh public snapshots after installation.
