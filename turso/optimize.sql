DROP INDEX IF EXISTS "broker_account_state_pkey";
DROP INDEX IF EXISTS "broker_accounts_pkey";
DROP INDEX IF EXISTS "broker_order_events_pkey";
DROP INDEX IF EXISTS "broker_position_state_pkey";
DROP INDEX IF EXISTS "currency_macro_state_idx";
DROP INDEX IF EXISTS "currency_macro_state_pkey";
DROP INDEX IF EXISTS "currency_macro_state_currency_observed_at_key";
DROP INDEX IF EXISTS "currency_strength_pkey";
DROP INDEX IF EXISTS "currency_strength_currency_observed_at_key";
DROP INDEX IF EXISTS "data_quality_snapshots_pkey";
DROP INDEX IF EXISTS "execution_control_pkey";
DROP INDEX IF EXISTS "fx_symbols_pkey";
DROP INDEX IF EXISTS "liquidity_levels_pkey";
DROP INDEX IF EXISTS "market_structure_symbol_timeframe_observed_at_key";
DROP INDEX IF EXISTS "market_structure_pkey";
DROP INDEX IF EXISTS "model_performance_pkey";
DROP INDEX IF EXISTS "pair_rankings_pkey";
DROP INDEX IF EXISTS "paper_trades_pkey";
DROP INDEX IF EXISTS "runtime_heartbeats_pkey";
DROP INDEX IF EXISTS "scanner_runs_pkey";
DROP INDEX IF EXISTS "signals_pkey";
DROP INDEX IF EXISTS "smc_features_pkey";
DROP INDEX IF EXISTS "storage_guard_audit_pkey";
DROP INDEX IF EXISTS "xau_dom_pressure_samples_observed_at_desc";
DROP INDEX IF EXISTS "xau_dom_pressure_samples_pkey";
DROP INDEX IF EXISTS "xau_outcome_ledger_pkey";
DROP INDEX IF EXISTS "xau_outcome_ledger_episode_key_key";
DROP INDEX IF EXISTS "xau_prepared_plan_lifecycle_plan_key_key";
DROP INDEX IF EXISTS "xau_prepared_plan_lifecycle_pkey";
DROP INDEX IF EXISTS "xau_pressure_depth_episodes_pkey";
CREATE TABLE IF NOT EXISTS turso_usage_daily (
 day TEXT NOT NULL, worker TEXT NOT NULL,
 requests INTEGER NOT NULL DEFAULT 0, statements INTEGER NOT NULL DEFAULT 0,
 rows_read INTEGER NOT NULL DEFAULT 0, rows_written INTEGER NOT NULL DEFAULT 0,
 unmetered_statements INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(day,worker)
);
CREATE INDEX IF NOT EXISTS broker_order_accepted_time ON broker_order_events(observed_at DESC) WHERE event_type='ORDER_ACCEPTED' AND accepted=1;
