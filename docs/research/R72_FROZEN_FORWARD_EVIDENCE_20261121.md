# R7.2 — Frozen prospective XAU D1 shadow with evidence receipts
Frozen decision: **one model only**, and independent forward outcomes only. **Status: WAIT_NEW_MARKET_OUTCOMES**.

## Exact trained model and audit integrity
- Candidate: D1 price-only global ridge, penalty 500, regime blend 0 and signal edge threshold 0bp; four XAU-only predictors: past 5-session daily range, 5-session momentum, 21-session momentum, 21-session realized volatility.
- Training: **2018–2024**, independently source-audited HistData annual M1 rolled to UTC daily OHLC, with explicit 2023 Dukascopy vendor replacement (259 accepted days vs 164 in HistData).
- Training labeled rows: **1,622**. Last completed training outcome: **2024-12-30**.
- No 2025–2026 *historical label* used for parameter fit or calibration. 2025–20 Nov 2026 prior R7 research results are ALREADY SEEN and PERMANENTLY INELIGIBLE as an untouched test.
- Predeclared selection is NOT highest tested accuracy. Frozen candidate is a simple controlled baseline with weak/unproven predictive skill, not live trading.
- Exact canonical frozen model **SHA256**: `7f5397487839e6bd0d0a9289dd1229294c04c655e2ca952b513a1367bec73a99`.
- Original training Actions run: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44834150729
- Authoritative final byte-identical frozen source JSON commit: **9e6a426c2ee6b586d8ba6d7acc40a1a8711b454e** at **2026-11-20T23:11:24Z** = **21 Nov 2026 06:11:24 WIB**.
- Original manual reserializations of freeze JSON had invalid hash (numeric serialization + one source-year SHA mismatch). CI **rejected** these versions; the original model-generated artifact bytes were restored via isolated GitHub Actions reconciliation, not by model re-fitting. Previous commits ac41ed and a2fa0 are NOT authoritative freeze locks.
- The frozen code file SHA256 checked at every capture: `d7ccb365407eda50d0f6d504eae87a9d3d2f77792ffe9303cb48ea50edfa17e1`.
- CI: https://github.com/rizanrizan93/Forex-scanner/actions/runs/44835291550 (**17 tests passed**).

## Separate source market observations from new receipt time
- Exact source: independent public **Dukascopy XAUUSD BID H1** history, data fetched into GitHub Actions; neither ICE DXY nor original FP Markets BID/ASK.
- Market observation timestamps come from Dukascopy bar's Unix-millisecond timestamps; receipt times come from the new Action's runner. The 2026 download of historical bars does NOT retroactively prove that an old event was archived before the trading decision.
- Raw H1 file SHA256, original filename, first/last market timestamp, acquisition started and completed UTC, GitHub run ID + run attempt, model commit SHA, and output UTC timestamp are attached in the receipt manifest.
- Each weekly Actions run stores the exact raw source CSV and manifest in a GitHub artifact (90-day retention). A separate dedicated branch `research/r72-forward-evidence` receives **create-only**, per-run permanent manifest and evaluation JSON commits. This is a persistent Git-based audit trail, NOT an independently immutable signed data-vendor receipt system. The raw Actions artifact expires after 90 days; licensed durable raw retention must be arranged separately if required.
- Main branch change is ONLY `.github/workflows/r72_weekly_forward_shadow_readonly.yml`, which checks out pinned research source commit **d7b68772c8d41e851cf08ef87af4f842742c1f3b**, has no order credentials, and does not touch cBot, Streamlit model, bridge or Frozen V1.
- Schedule: **Saturdays 00:20 UTC / 07:20 WIB**, because UTC daily bar closes and Sunday gold market reopen require a future valid next-session-open. This is a weekly, extremely conservative D1 forward pilot, not daily trade timing.
- A weekend signal is issued only after the Friday UTC candle is fully closed and prior to Sunday reopening, with no later H1 bars, and one unique prospective event ID per completed Friday. All other captures must produce WAIT.
- New shadow outcomes are scored only against *later* separately obtained source data, the **first completed weekday UTC session after the weekend**, assuming a $0.40/oz cost, without native broker execution. A future Monday label can be reported after its completion and *after* a later source acquisition; no outcome created at the same time as the Saturday signal.
- Weekly automatic source capture schedule was installed on 2026-11-20 through default main workflow; independent recurring ChatGPT task monitors new GitHub evidence and only reports meaningful changes. Scheduled execution remains subject to GitHub Actions service and repository permissions.

## First LIVE post-freeze capture — factual results
- Branch pilot 44834996694 was successful: source receipt **2026-11-20T23:12:13Z (06:12:13 WIB)**; **4,120 original BID H1 bars**; most recent source market bar 2026-11-20 21:00 UTC; source SHA `2a0019a807c73e50585c95a410645d9282f3e32e359b8b47bb75ee1a7b0b764a`.
- Pilot correctly reported `WAIT_ONLY_WEEKEND_PRE_NEXT_SESSION_D1_PILOT`: last fully completed UTC weekday at that point 2026-11-19; Friday UTC session was not yet over.
- Source capture, **0 genuinely future completed outcomes**, **0 BUY/SELL performance claims**, no order.
- Default-branch test of installed scheduled archive **44835456044** also succeeded. Received 2026-11-20T23:15:58Z (06:15:58 WIB), source H1 count **4,072**, source SHA `5513cdf46aa23786b819ebafa346e9d5eb68a7ad86052da90602da762a583ac5`; `WAIT_ONLY_WEEKEND_PRE_NEXT_SESSION_D1_PILOT`; prospective outcome `WAIT_GENUINELY_FUTURE_COMPLETED_SESSIONS` with 0 observed outcomes.
- First actual permanent ledger commits: **d097781cfd740829a3cacbe5064b013784f3d037** for the raw receipt manifest and **e803b4e0d7326e0ecefa0d4a907022083e18a315** for the zero-outcome status, in branch `research/r72-forward-evidence`; both create-only without overwrite.
- See https://github.com/rizanrizan93/Forex-scanner/actions/runs/44835456044 and https://github.com/rizanrizan93/Forex-scanner/tree/research/r72-forward-evidence/research/forward-evidence/r72

## Genuine future evidence is pending, not fabricated
Next weekly scheduled capture is Sat 21 Nov 2026 at 07:20 WIB (if GitHub scheduling runs as expected) *after* Friday 20 Nov UTC day closes. If source completeness, code pin and period guards pass, it can record a `SEARCH_BUY` or `SEARCH_SELL` research shadow *before* the Sunday market reopens. The first subsequent eligible UTC weekday session is Monday 23 Nov 2026; its price outcome needs its closing candle and a later source receipt. No claim is made about its outcome in advance.

A statistically meaningful result needs 60+ NEW independent forward cases, at least 15 BUY and 15 SELL and matched-date comparison, plus calibrated probabilities and broker-specific costs before any production consideration. At one captured weekly D1 scenario, this can take a long time. A more frequent forecaster must first be redesigned around the correct broker trading-session close and next executable entry timing.

**NO AUTO-ORDER, NO PARAMETER REOPTIMIZATION, NO ALTERATION TO FROZEN V1, NO CLAIM OF 80% ACCURACY.**
