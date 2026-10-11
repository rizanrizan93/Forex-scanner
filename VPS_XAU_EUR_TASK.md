# VPS XAU + EUR Runtime Task

Objective: make the VPS `rizan-bridge` a stable 24/5 runtime for **XAUUSD and EURUSD** research/signal generation first, with persistent health monitoring. Do not enable real/live order execution in this task.

## Safety boundary

- Never print, echo, log, commit, or expose secret/token/password values.
- Do not enable `FX_LIVE_TRADING_ENABLED`.
- Do not place live orders.
- Keep broker execution disabled until the runtime/data path and actual gateway implementation are verified.
- If an execution path is stubbed/faked, treat it as a blocker and report it; do not simulate success as a real broker fill.
- Do not alter the frozen strategy contracts themselves. They are immutable research references.

## Phase 1 — audit current VPS and repository

1. Confirm working directory is the cloned `Forex-scanner` repository and report branch/HEAD/git status.
2. Run project/config validation and `pip check` from `.venv`.
3. Inspect `.env` **only for required variable names and whether each is MISSING / EMPTY / PRESENT**. Never print values.
4. Verify these runtime prerequisites at minimum:
   - `CTRADER_CLIENT_ID`
   - `CTRADER_CLIENT_SECRET`
   - `CTRADER_ACCESS_TOKEN`
   - `CTRADER_REFRESH_TOKEN`
   - `CTRADER_TRADER_LOGIN`
   - `CTRADER_TOKEN_STATE_PATH`
   - `SUPABASE_URL`
   - `SUPABASE_SECRET_KEY`
5. Check that token/state and log directories are writable and persistent.
6. Inspect current execution policy and broker gateway. Explicitly identify any contradiction between committed DEMO-only policy and any code that claims live execution.

## Phase 2 — prove market-data/runtime health

When all required read-only/research credentials are PRESENT:

1. Run the canonical config validation.
2. Run one-shot cTrader cloud research probe with MTF enabled.
3. Verify that **XAUUSD and EURUSD specifically** both have fresh Bid/Ask and usable D1/H4/H1/M15/M5 data.
4. Verify cTrader reconnect/token refresh behavior without exposing tokens.
5. Verify Supabase heartbeat/write connectivity.
6. Report per-symbol health for XAUUSD and EURUSD separately.

Do not continue to persistent services if either XAUUSD or EURUSD market-data health is not proven.

## Phase 3 — strategy wiring audit

1. Inspect the frozen contracts:
   - `config/frozen/xauusd_raw_selected_v1.json`
   - `config/frozen/eurusd_raw_selected_v3.json`
2. Confirm whether each contract is actually consumed by the active runtime. `FROZEN_RESEARCH_NOT_ACTIVATED` is not equivalent to an active strategy.
3. Trace the exact code path from live cTrader data -> XAU strategy signal and live cTrader data -> EUR strategy signal.
4. If active wiring is missing, implement a **read-only/simulation strategy adapter** that loads the frozen contracts without mutating them and can emit observable strategy decisions for both symbols.
5. Add tests proving that the runtime selects the intended XAU and EUR contract IDs and cannot silently fall back to another candidate.
6. Keep order submission disabled.

## Phase 4 — 24/5 persistence

After Phase 2 passes:

1. Add version-controlled systemd unit templates/scripts for the VPS research runtime, with:
   - correct repo working directory
   - `.venv` interpreter
   - environment loaded locally without committing values
   - `Restart=always` (or equivalent robust restart policy)
   - reasonable restart backoff
   - logs available through journalctl and/or repo `logs/`
2. Run the canonical continuous research runtime using the existing cTrader cloud runtime (`research-cloud --heartbeat 8 --mtf-refresh 900`) unless repository inspection proves a newer canonical command exists.
3. Add a lightweight health-check command/script that reports, without secrets:
   - process/service state
   - last heartbeat age
   - cTrader connectivity
   - Supabase connectivity
   - XAUUSD quote/MTF freshness
   - EURUSD quote/MTF freshness
   - current strategy contract ID for each symbol
4. Do not make Streamlit a dependency of this cTrader VPS runtime; dashboard deployment remains separate.

## Phase 5 — report before execution work

Stop before enabling broker execution and provide a concise report with exactly these statuses:

- `VPS_BASE`: PASS/FAIL
- `ENV_REQUIRED`: PASS/FAIL + names missing (never values)
- `CTRADER_XAU_FEED`: PASS/FAIL
- `CTRADER_EUR_FEED`: PASS/FAIL
- `XAU_STRATEGY_WIRING`: PASS/FAIL + active strategy ID
- `EUR_STRATEGY_WIRING`: PASS/FAIL + active strategy ID
- `SUPABASE`: PASS/FAIL
- `SYSTEMD_24_5`: PASS/FAIL
- `EXECUTION_GATEWAY_REAL`: PASS/FAIL
- `READY_FOR_DEMO_EXECUTION_TEST`: YES/NO

If `EXECUTION_GATEWAY_REAL` is FAIL, explain the exact stub/fake path and do not enable AUTO.

Commit only non-secret code/config/template changes to the repository. Never commit `.env`, token state, credentials, or account secrets.
