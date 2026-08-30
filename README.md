# FX Institutional Scanner v0.11

Production-oriented forex scanner foundation with a **dual-feed / single-execution** design.

**Research feed:** FP Markets cTrader Open API  
**Execution venue:** HFM Cent MT5  
**Execution default:** `DISABLED`

## Operating model

The Android phone is the control/monitoring surface. A controlled VPS is the 24/5 runtime host.

```text
Global/macro data
       |
FP Markets cTrader ------------------+
(read-only research feed)            |
                                     v
                         Scanner / ranking / SMC-ICT
                                     |
                              signal candidate
                                     |
                                     v
                        HFM execution revalidation
                           (warm MT5 connection)
                                     |
                  stale/spread/divergence/chase/RR/risk
                                     |
                              pass -> MT5 order
                                     |
                              HFM Cent account

Supabase -> cached control state + async audit (not quote/order latency path)
Android  -> monitor / future approve / pause / emergency controls
```

There is **no automatic cTrader -> MT5 failover** and cTrader is configured
`RESEARCH_ONLY`. The configured factory refuses to build cTrader as an execution
backend.

## v0.6 decision engine foundation

The repository now contains deterministic, testable decision primitives:

- eight-factor currency macro scoring with explicit missing/invalid coverage
- relative macro edge by base vs quote currency
- normalized currency-strength aggregation across the configured 15-pair universe
- pair ranking using 55% macro / 30% technical / 15% cross-asset edge
- evidence coverage propagated from macro, technical, and cross-asset inputs
- ATR, displacement, FVG, swing structure, BOS, liquidity sweep/reclaim, and MSS confirmation
- 0..100 conviction scoring with explicit missing-component coverage
- state mapping: `NO_TRADE -> WATCH -> SETUP_FORMING -> ARMED -> EXECUTION_READY`
- canonical hard guards that fail closed when a required guard input is missing or invalid
- internal pair-direction and pair-coverage guards

Missing evidence is never converted into a successful neutral observation. A
high score cannot override a hard guard, a neutral pair direction, or inadequate
evidence coverage.

v0.6 established the deterministic decision engine. v0.7 adds the first
provider/live-data orchestration layer around that engine.

## v0.7 provider and live-data orchestration

Provider evidence now has explicit semantics:

- `AVAILABLE`, `PARTIAL`, `MISSING`, `STALE`, `INVALID`, `ERROR`, `NOT_APPLICABLE`
- zero is distinct from missing
- source URL, series ID, official-source flag, observation time and fetch time
- max-age freshness with stale values preserved for audit but excluded from decisions
- typed provider error categories
- positive, negative and stale TTL caching
- numeric quorum with conflict detection
- exact-single-series guards; wildcard/multi-series inputs fail closed
- HTTPS + canonical-host configuration and redirect blocking

The first keyless official adapters are:

- ECB Data Portal SDMX/CSV
- Bank of Canada Valet JSON

The macro provider pipeline normalizes source observations only through explicit
normalizers. Missing history does **not** become a neutral zero. Provider/factor
coverage and provenance are retained and can be persisted to
`currency_macro_state` in Supabase.

v0.7 also contains a typed high-impact economic-event model and deterministic
news-window evaluator for producing `NEWS_BLOCK`. A full multi-country
economic-calendar ingestion provider is not yet claimed.

Manual network smoke tests:

```bash
python -m fx_scanner.cli provider-smoke --series ECB_EURUSD_REFERENCE
python -m fx_scanner.cli provider-smoke --series BOC_POLICY_RATE
python -m fx_scanner.cli provider-smoke --series FED_IORB
python -m fx_scanner.cli provider-smoke --series RBA_CASH_RATE_TARGET
```

These are intentionally not part of mandatory CI because external provider
availability must not determine whether the codebase builds.

## v0.8 full MTF strategy and liquidity orchestration

v0.8 connects the v0.6 decision engine and v0.7 provider layer into a
deterministic multi-timeframe research pipeline:

```text
15 configured pairs
      |
macro-compatible filter
      v
Top 8
      |
pair edge / evidence coverage
      v
Top 5 deep analysis
      |
D1 regime
      v
H4 directional bias
      v
H1 structure + dealing range
      v
M15 setup
      |
      +-- liquidity-sweep reversal
      +-- trend continuation
      v
M5 confirmed trigger
      |
closed-bar freshness + liquidity map
      v
entry zone / structural SL / liquidity TP
      v
conviction + hard guards
      v
WATCH / SETUP_FORMING / ARMED / EXECUTION_READY
```

Only **closed bars** are eligible for structure, BOS, FVG, sweep or
displacement calculations. The current partial bucket is removed before
analysis. Freshness is measured from the close time of the most recent closed
bar, and stale MTF evidence activates `STALE_SIGNAL`.

Liquidity evidence includes:

- previous-day high/low (PDH/PDL)
- previous-week high/low (PWH/PWL)
- completed Asia/London/New York session highs/lows
- equal highs/lows using ATR tolerance
- recent H1 swing liquidity
- premium/discount/equilibrium dealing range
- FVG open/partial/filled state
- order-block validation after displacement + structure break

Trade geometry is fail-closed:

- entry zone comes from an unfilled/partially-filled aligned FVG
- SL uses sweep/H1 structure plus ATR buffer
- TP1/TP2 use distinct external liquidity levels
- TP2 RR below 1.50 activates `RR_BLOCK`
- >0.50 ATR chase activates `CHASE_BLOCK`
- 0.25-0.50 ATR chase degrades execution quality
- reversed TP or RR geometry is rejected by the data contract

A missing Top-5 MTF bundle is no longer silently dropped:
`DeepScanReport` records the skipped symbol and reason.

### Official/keyless provider coverage in v0.8

Currently wired provider evidence:

- USD: Federal Reserve policy-tool evidence through FRED CSV (IORB)
- EUR: ECB Data Portal
- CAD: Bank of Canada Valet
- AUD: RBA Cash Rate Target

GBP/JPY/CHF/NZD official numeric provider coverage is still incomplete. Missing
coverage remains missing and reduces/block evidence; it is not replaced with
neutral zero.

Manual network checks can be run with:

```bash
python -m fx_scanner.cli provider-smoke --series FED_IORB
python -m fx_scanner.cli provider-smoke --series ECB_EURUSD_REFERENCE
python -m fx_scanner.cli provider-smoke --series BOC_POLICY_RATE
python -m fx_scanner.cli provider-smoke --series RBA_CASH_RATE_TARGET
```

These external-network checks remain outside mandatory CI.

## Streamlit dashboard

The repository now has a canonical root Streamlit entrypoint:

```text
main.py
```

For Streamlit Community Cloud, set **Main file path** to:

```text
main.py
```

`main.py` is intentionally a thin launcher. The dashboard implementation remains
in `streamlit_app.py`, which keeps deployment plumbing separate from the scanner
and execution runtime.

The Streamlit process is deliberately a dashboard/control surface, not the
24/5 quote/order hot path. It can display:

- configured 15-pair universe
- latest durable pair ranking
- latest signal states and Entry/SL/TP/RR
- currency macro snapshots
- execution-control safety state
- runtime worker heartbeats
- OOS/performance snapshots
- manual official-provider health checks

If backend credentials are absent, the app still starts in an offline/config
mode instead of crashing. To read the private Supabase tables, configure these
as Streamlit Secrets (never commit the values):

```toml
SUPABASE_URL = "..."
SUPABASE_SECRET_KEY = "..."
```

Do not use a publishable/anon key for this dashboard: the operational/research
tables are intentionally closed to public roles.

See `docs/STREAMLIT_DEPLOY.md`.

## v0.11 phone-only Linux research runtime

The research side can now run independently on Linux/cloud while remaining
connected to **FP Markets cTrader Open API**. It acquires live Bid/Ask plus
D1/H4/H1/M15/M5 historical trendbars, sends an 8-second client heartbeat,
and rate-limits historical requests below cTrader limits.

HFM MT5 remains the separate execution/telemetry venue.

```bash
python -m fx_scanner.cli research-cloud --once
python -m fx_scanner.cli research-cloud --heartbeat 8 --mtf-refresh 900
```

See `docs/PHONE_ONLY_RUNTIME.md`.

## v0.10 broker monitoring telemetry

Streamlit remains a monitor only. A lightweight Windows/MT5 worker now
publishes broker-reported balance, equity, floating P/L, margin and open
positions to Supabase without submitting orders.

Run on the Windows HFM MT5 host:

```bash
python -m fx_scanner.cli mt5-monitor --once
python -m fx_scanner.cli mt5-monitor --interval 15
```

The **Account & Positions** tab reads only the latest coherent snapshot.
Execution remains `DISABLED` by default. See `docs/RUNTIME_MONITORING.md`.

## v0.9 OOS validation and latency safeguards

v0.9 keeps research validation outside the scanner hot path. It adds:

- point-in-time closed-bar replay
- chronological 60/20/20 train/validation/final-OOS split
- conservative STOP_FIRST intrabar ambiguity handling
- broker-observed spread where available
- bid/ask-aware TP and SL testing
- slippage, commission and swap costs
- spread +25% and slippage +50% stress
- censored-history handling that does not invent outcomes
- rolling walk-forward
- per-regime/setup/symbol performance
- circular block-bootstrap Monte Carlo
- canonical parameter perturbations
- fail-closed demo-forward/perturbation/Monte-Carlo acceptance gates

The final OOS acceptance contract remains at least 250 completed trades, 55%
win rate, Profit Factor 1.30 and +0.15R expectancy before the additional
stability/demo gates are considered.

Research validation is statically prevented from entering the live
strategy/execution import path. The CPU budget for a Top-5 deep scan remains
250 ms.

## HFM Cent execution contract

Startup fails closed unless the execution account and symbols match the configured
Cent contract:

- account currency: `USC`
- expected FX contract size: `1,000` units per Cent lot
- canonical symbols are resolved to broker symbols (for example `EURUSDc`) using
  explicit mapping or configured suffix candidates
- ambiguous or non-matching symbols block startup
- position sizing uses HFM-provided tick size, tick value, min/max volume and
  volume step; standard-lot economics are never hard-coded

Actual symbol names and contract metadata must still be verified against the
real HFM demo account before enabling any execution mode.

## Fast execution-side revalidation

The FP Markets signal is never copied blindly to HFM. Immediately before MT5
preflight the runtime checks:

- fresh cTrader research Bid/Ask
- fresh HFM MT5 Bid/Ask
- cross-broker mid-price divergence
- HFM spread and spread divergence
- entry drift / do-not-chase
- SL/entry/TP geometry
- minimum RR
- HFM Cent account currency and contract size
- HFM tick-economics position sizing
- internal revalidation latency ceiling

MT5 then takes a fresh quote **again** during broker preflight and blocks if the
price has moved too far from the revalidated entry.

This is intentionally a fast execution-geometry reconciliation. It does not
claim to recompute the complete SMC/ICT strategy on HFM M5 bars.

## Cadence

- heavy macro / pair ranking: 15 minutes
- setup watcher: 15 seconds
- WATCH: 1 second
- SETUP_FORMING: 500 ms
- ARMED: 250 ms
- EXECUTION_READY: 250 ms
- open-position monitor: 2 seconds

The 250 ms figure is an engineering scheduler target, not a guaranteed
broker-network order latency.

## Live safety

Live orders require all configured gates:

- mode is not `DISABLED`
- environment live-enable phrase
- broker account allowlist
- local kill switch
- fresh cached Supabase control state
- Supabase mode agreement / new-orders enabled / emergency-stop clear
- dual-feed revalidation
- MT5 broker preflight / `order_check`
- server-side SL and TP
- persistent signal idempotency state

If a broker submission crosses the side-effect boundary but its response is
lost, that signal is persisted as **uncertain**. It cannot be retried until
broker order/position reconciliation explicitly resolves the outcome.

## cTrader research reliability

The cTrader research facade exposes quotes/symbol information only; it exposes
no order submission method. On reconnect it reloads the research universe and
restores spot subscriptions.

cTrader access-token rotation is supported. Rotated access and refresh tokens
are written atomically to the VPS-only token-state file and the `state/`
directory is git-ignored.

Required VPS secret/state variables include:

```text
CTRADER_CLIENT_ID
CTRADER_CLIENT_SECRET
CTRADER_ACCESS_TOKEN
CTRADER_REFRESH_TOKEN
CTRADER_TOKEN_STATE_PATH
CTRADER_ACCOUNT_ID

MT5_TERMINAL_PATH
MT5_LOGIN
MT5_SERVER
MT5_PASSWORD

SUPABASE_URL
SUPABASE_SECRET_KEY

FX_IDEMPOTENCY_STATE_PATH
```

Never commit real values.

## Storage

- realtime quote/order state: memory on VPS
- history/research: Parquet + DuckDB
- durable control/audit: dedicated Supabase project

The Supabase project is `Forex scanner` in Singapore
(`fotzcxjeypmjldhvfskt`). Supabase network I/O is isolated from the
order-critical path. The database bootstrap remains:

```text
execution_mode       DISABLED
new_orders_enabled   false
emergency_stop       true
```

## Install

Core:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

cTrader research backend:

```bash
pip install -r requirements-ctrader.txt
```

HFM MT5 execution host requires Windows and:

```bash
pip install -r requirements-mt5-windows.txt
```

## Validation

```bash
pytest -q
python -m fx_scanner.cli validate-config
python -m fx_scanner.cli demo-ingest --symbol EURUSD --minutes 10
python -m fx_scanner.cli runtime-smoke --seconds 86400
# Optional external-network checks:
python -m fx_scanner.cli provider-smoke --series ECB_EURUSD_REFERENCE
python -m fx_scanner.cli provider-smoke --series BOC_POLICY_RATE
```

## Progression

Do not enable real-money execution from this repository state.

```text
DISABLED
-> SIMULATION
-> dual-broker live-feed smoke test
-> CONFIRM_TO_TRADE on demo
-> AUTO on demo
-> forward validation / cost & latency calibration
-> real-money acceptance review
```

Research acceptance remains at minimum: OOS win rate >=55%, Profit Factor
>=1.30, positive robust expectancy, walk-forward pass, spread/slippage stress
pass, multi-regime pass, and demo forward-test pass.

**Real-money readiness is not claimed at v0.11.**
