-- SQLite schema translated from live ForexRizan metadata; constraints retained.
CREATE TABLE IF NOT EXISTS "broker_account_state" (
  "backend" TEXT NOT NULL,
  "account_id" TEXT NOT NULL,
  "snapshot_id" TEXT NOT NULL,
  "observed_at" TEXT NOT NULL,
  "broker_name" TEXT,
  "environment" TEXT,
  "currency" TEXT,
  "balance" REAL NOT NULL,
  "equity" REAL NOT NULL,
  "floating_profit" REAL,
  "margin" REAL,
  "margin_free" REAL,
  "margin_level" REAL,
  "leverage" REAL,
  "trade_allowed" INTEGER NOT NULL CHECK ("trade_allowed" IN (0,1)) DEFAULT false,
  "connection_healthy" INTEGER NOT NULL CHECK ("connection_healthy" IN (0,1)) DEFAULT false,
  "metadata" TEXT NOT NULL CHECK (json_valid("metadata")) DEFAULT '{}',
  CHECK ((backend IN ('CTRADER', 'MT5'))),
  CHECK (((environment IS NULL) OR (environment IN ('DEMO', 'LIVE')))),
  PRIMARY KEY (backend, account_id)
);

CREATE TABLE IF NOT EXISTS "broker_accounts" (
  "backend" TEXT NOT NULL,
  "account_id" TEXT NOT NULL,
  "broker_name" TEXT,
  "environment" TEXT NOT NULL,
  "enabled" INTEGER NOT NULL CHECK ("enabled" IN (0,1)) DEFAULT false,
  "metadata" TEXT NOT NULL CHECK (json_valid("metadata")) DEFAULT '{}',
  "updated_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK ((backend IN ('CTRADER', 'MT5'))),
  CHECK ((environment IN ('DEMO', 'LIVE'))),
  PRIMARY KEY (backend, account_id)
);

CREATE TABLE IF NOT EXISTS "broker_order_events" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "observed_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  "backend" TEXT NOT NULL,
  "account_id" TEXT NOT NULL,
  "signal_key" TEXT NOT NULL,
  "broker_order_id" TEXT,
  "event_type" TEXT NOT NULL,
  "accepted" INTEGER CHECK ("accepted" IN (0,1)),
  "code" TEXT,
  "message" TEXT,
  "payload" TEXT NOT NULL CHECK (json_valid("payload")) DEFAULT '{}',
  CHECK ((backend IN ('CTRADER', 'MT5')))
);

CREATE TABLE IF NOT EXISTS "broker_position_state" (
  "backend" TEXT NOT NULL,
  "account_id" TEXT NOT NULL,
  "position_id" TEXT NOT NULL,
  "snapshot_id" TEXT NOT NULL,
  "observed_at" TEXT NOT NULL,
  "symbol" TEXT NOT NULL,
  "side" TEXT NOT NULL,
  "volume" REAL NOT NULL,
  "open_price" REAL NOT NULL,
  "current_price" REAL,
  "sl" REAL,
  "tp" REAL,
  "profit" REAL,
  "swap" REAL,
  "magic" INTEGER,
  "comment" TEXT,
  "opened_at" TEXT,
  "metadata" TEXT NOT NULL CHECK (json_valid("metadata")) DEFAULT '{}',
  CHECK ((backend IN ('CTRADER', 'MT5'))),
  CHECK ((side IN ('BUY', 'SELL'))),
  CHECK ((volume >= (0))),
  PRIMARY KEY (backend, account_id, position_id)
);

CREATE TABLE IF NOT EXISTS "currency_macro_state" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "currency" TEXT NOT NULL,
  "observed_at" TEXT NOT NULL,
  "rate_score" REAL,
  "central_bank_score" REAL,
  "inflation_score" REAL,
  "growth_score" REAL,
  "labour_score" REAL,
  "yield_score" REAL,
  "risk_score" REAL,
  "positioning_score" REAL,
  "macro_score" REAL,
  "coverage" REAL NOT NULL,
  "freshness_seconds" INTEGER NOT NULL,
  "evidence" TEXT NOT NULL CHECK (json_valid("evidence")) DEFAULT '{}',
  CHECK (((coverage >= (0)) AND (coverage <= (1)))),
  CHECK ((length(currency) = 3)),
  CHECK ((freshness_seconds >= 0)),
  UNIQUE (currency, observed_at)
);

CREATE TABLE IF NOT EXISTS "currency_strength" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "currency" TEXT NOT NULL,
  "observed_at" TEXT NOT NULL,
  "strength_15m" REAL,
  "strength_1h" REAL,
  "strength_4h" REAL,
  "strength_1d" REAL,
  "combined_strength" REAL,
  "coverage" REAL NOT NULL,
  CHECK (((coverage >= (0)) AND (coverage <= (1)))),
  CHECK ((length(currency) = 3)),
  UNIQUE (currency, observed_at)
);

CREATE TABLE IF NOT EXISTS "data_quality_snapshots" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "run_id" TEXT,
  "symbol" TEXT NOT NULL,
  "observed_at" TEXT NOT NULL,
  "record_count" INTEGER NOT NULL,
  "duplicate_count" INTEGER NOT NULL DEFAULT 0,
  "non_monotonic_count" INTEGER NOT NULL DEFAULT 0,
  "stale" INTEGER NOT NULL CHECK ("stale" IN (0,1)),
  "spread_ratio" REAL,
  "valid" INTEGER NOT NULL CHECK ("valid" IN (0,1)),
  "issues" TEXT NOT NULL CHECK (json_valid("issues")) DEFAULT '[]',
  "created_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK ((duplicate_count >= 0)),
  CHECK ((non_monotonic_count >= 0)),
  CHECK ((record_count >= 0)),
  FOREIGN KEY (run_id) REFERENCES scanner_runs(id) ON DELETE CASCADE,
  FOREIGN KEY (symbol) REFERENCES fx_symbols(symbol)
);

CREATE TABLE IF NOT EXISTS "execution_control" (
  "control_key" TEXT NOT NULL DEFAULT 'primary',
  "execution_mode" TEXT NOT NULL DEFAULT 'DISABLED',
  "new_orders_enabled" INTEGER NOT NULL CHECK ("new_orders_enabled" IN (0,1)) DEFAULT false,
  "emergency_stop" INTEGER NOT NULL CHECK ("emergency_stop" IN (0,1)) DEFAULT true,
  "close_all_requested" INTEGER NOT NULL CHECK ("close_all_requested" IN (0,1)) DEFAULT false,
  "version" INTEGER NOT NULL DEFAULT 1,
  "updated_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  "metadata" TEXT NOT NULL CHECK (json_valid("metadata")) DEFAULT '{}',
  CHECK ((execution_mode IN ('DISABLED', 'SIMULATION', 'CONFIRM_TO_TRADE', 'AUTO'))),
  PRIMARY KEY (control_key)
);

CREATE TABLE IF NOT EXISTS "fx_symbols" (
  "symbol" TEXT NOT NULL,
  "base_currency" TEXT NOT NULL,
  "quote_currency" TEXT NOT NULL,
  "pip_size" REAL NOT NULL,
  "tier" TEXT NOT NULL,
  "active" INTEGER NOT NULL CHECK ("active" IN (0,1)) DEFAULT true,
  "created_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK ((length(base_currency) = 3)),
  CHECK ((pip_size > (0))),
  CHECK ((length(quote_currency) = 3)),
  CHECK ((tier IN ('A', 'B'))),
  PRIMARY KEY (symbol)
);

CREATE TABLE IF NOT EXISTS "liquidity_levels" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "symbol" TEXT NOT NULL,
  "timeframe" TEXT NOT NULL,
  "observed_at" TEXT NOT NULL,
  "level" REAL NOT NULL,
  "level_type" TEXT NOT NULL,
  "strength" REAL,
  "touch_count" INTEGER NOT NULL DEFAULT 1,
  "active" INTEGER NOT NULL CHECK ("active" IN (0,1)) DEFAULT true,
  "metadata" TEXT NOT NULL CHECK (json_valid("metadata")) DEFAULT '{}',
  CHECK ((touch_count > 0)),
  FOREIGN KEY (symbol) REFERENCES fx_symbols(symbol)
);

CREATE TABLE IF NOT EXISTS "market_structure" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "symbol" TEXT NOT NULL,
  "timeframe" TEXT NOT NULL,
  "observed_at" TEXT NOT NULL,
  "trend" TEXT,
  "last_swing_high" REAL,
  "last_swing_low" REAL,
  "bos" INTEGER CHECK ("bos" IN (0,1)),
  "choch" INTEGER CHECK ("choch" IN (0,1)),
  "mss" INTEGER CHECK ("mss" IN (0,1)),
  "premium_discount" REAL,
  "evidence" TEXT NOT NULL CHECK (json_valid("evidence")) DEFAULT '{}',
  CHECK ((timeframe IN ('M1', 'M5', 'M15', 'H1', 'H4', 'D1'))),
  UNIQUE (symbol, timeframe, observed_at),
  FOREIGN KEY (symbol) REFERENCES fx_symbols(symbol)
);

CREATE TABLE IF NOT EXISTS "model_performance" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "as_of" TEXT NOT NULL,
  "setup_type" TEXT NOT NULL,
  "symbol" TEXT,
  "session" TEXT,
  "regime" TEXT,
  "sample_scope" TEXT NOT NULL,
  "trades" INTEGER NOT NULL,
  "wins" INTEGER NOT NULL,
  "losses" INTEGER NOT NULL,
  "win_rate" REAL,
  "avg_win_r" REAL,
  "avg_loss_r" REAL,
  "expectancy_r" REAL,
  "profit_factor" REAL,
  "max_drawdown_r" REAL,
  "metadata" TEXT NOT NULL CHECK (json_valid("metadata")) DEFAULT '{}',
  CHECK ((losses >= 0)),
  CHECK ((trades >= 0)),
  CHECK ((wins >= 0))
);

CREATE TABLE IF NOT EXISTS "pair_rankings" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "run_id" TEXT,
  "observed_at" TEXT NOT NULL,
  "symbol" TEXT NOT NULL,
  "direction" TEXT,
  "macro_edge" REAL,
  "technical_edge" REAL,
  "cross_asset_score" REAL,
  "session_score" REAL,
  "volatility_score" REAL,
  "spread_score" REAL,
  "pair_opportunity_score" REAL,
  "rank" INTEGER,
  "coverage" REAL NOT NULL,
  "created_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK (((coverage >= (0)) AND (coverage <= (1)))),
  CHECK ((direction IN ('LONG', 'SHORT', 'NEUTRAL'))),
  CHECK (((pair_opportunity_score >= (0)) AND (pair_opportunity_score <= (100)))),
  CHECK ((rank > 0)),
  FOREIGN KEY (run_id) REFERENCES scanner_runs(id) ON DELETE CASCADE,
  FOREIGN KEY (symbol) REFERENCES fx_symbols(symbol)
);

CREATE TABLE IF NOT EXISTS "paper_trades" (
  "id" TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
  "signal_id" TEXT NOT NULL,
  "entry_time" TEXT NOT NULL,
  "entry_price" REAL NOT NULL,
  "exit_time" TEXT,
  "exit_price" REAL,
  "spread_cost" REAL,
  "commission" REAL,
  "slippage" REAL,
  "result_r" REAL,
  "mae_r" REAL,
  "mfe_r" REAL,
  "status" TEXT NOT NULL,
  "created_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  PRIMARY KEY (id),
  FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS "runtime_heartbeats" (
  "worker_name" TEXT NOT NULL,
  "observed_at" TEXT NOT NULL,
  "healthy" INTEGER NOT NULL CHECK ("healthy" IN (0,1)),
  "lag_seconds" REAL,
  "details" TEXT NOT NULL CHECK (json_valid("details")) DEFAULT '{}',
  PRIMARY KEY (worker_name)
);

CREATE TABLE IF NOT EXISTS "scanner_runs" (
  "id" TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
  "started_at" TEXT NOT NULL,
  "finished_at" TEXT,
  "mode" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "code_version" TEXT NOT NULL,
  "data_contract_version" TEXT NOT NULL DEFAULT '0.4',
  "created_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK ((mode IN ('RESEARCH_ONLY', 'PAPER_ONLY', 'DEMO_ONLY', 'REAL_MONEY_CANDIDATE'))),
  PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS "signals" (
  "id" TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
  "run_id" TEXT,
  "observed_at" TEXT NOT NULL,
  "symbol" TEXT NOT NULL,
  "direction" TEXT NOT NULL,
  "setup_type" TEXT NOT NULL,
  "state" TEXT NOT NULL,
  "pair_score" REAL,
  "execution_score" REAL,
  "final_score" REAL,
  "entry_low" REAL,
  "entry_high" REAL,
  "sl" REAL,
  "tp1" REAL,
  "tp2" REAL,
  "tp3" REAL,
  "rr1" REAL,
  "rr2" REAL,
  "rr3" REAL,
  "macro_bias" TEXT,
  "h4_bias" TEXT,
  "h1_bias" TEXT,
  "active_guards" TEXT NOT NULL CHECK (json_valid("active_guards")) DEFAULT '[]',
  "data_coverage" REAL NOT NULL,
  "expires_at" TEXT,
  "created_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK (((data_coverage >= (0)) AND (data_coverage <= (1)))),
  CHECK ((direction IN ('LONG', 'SHORT'))),
  CHECK (((execution_score >= (0)) AND (execution_score <= (100)))),
  CHECK (((final_score >= (0)) AND (final_score <= (100)))),
  CHECK (((pair_score >= (0)) AND (pair_score <= (100)))),
  CHECK ((state IN ('NO_TRADE', 'WATCH', 'SETUP_FORMING', 'ARMED', 'EXECUTION_READY', 'MISSED', 'INVALIDATED', 'COOLDOWN'))),
  PRIMARY KEY (id),
  FOREIGN KEY (run_id) REFERENCES scanner_runs(id) ON DELETE SET NULL,
  FOREIGN KEY (symbol) REFERENCES fx_symbols(symbol)
);

CREATE TABLE IF NOT EXISTS "smc_features" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "symbol" TEXT NOT NULL,
  "timeframe" TEXT NOT NULL,
  "observed_at" TEXT NOT NULL,
  "fvg_type" TEXT,
  "fvg_low" REAL,
  "fvg_high" REAL,
  "order_block_type" TEXT,
  "ob_low" REAL,
  "ob_high" REAL,
  "displacement_score" REAL,
  "liquidity_sweep" INTEGER CHECK ("liquidity_sweep" IN (0,1)),
  "sweep_type" TEXT,
  "evidence" TEXT NOT NULL CHECK (json_valid("evidence")) DEFAULT '{}',
  FOREIGN KEY (symbol) REFERENCES fx_symbols(symbol)
);

CREATE TABLE IF NOT EXISTS "storage_guard_audit" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "observed_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  "database_bytes_before" INTEGER NOT NULL,
  "database_bytes_after" INTEGER NOT NULL,
  "mode" TEXT NOT NULL,
  "applied" INTEGER NOT NULL CHECK ("applied" IN (0,1)),
  "rows_deleted" TEXT NOT NULL CHECK (json_valid("rows_deleted")) DEFAULT '{}',
  "details" TEXT NOT NULL CHECK (json_valid("details")) DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS "xau_dom_pressure_samples" (
  "observed_at" TEXT NOT NULL,
  "state" TEXT NOT NULL,
  "dom_pressure_score" REAL,
  "last_imbalance" REAL,
  "mean_imbalance" REAL,
  "top5_bid_units" REAL,
  "top5_ask_units" REAL,
  "bid_top5_change" REAL,
  "ask_top5_change" REAL,
  "bid_wall_ratio" REAL,
  "ask_wall_ratio" REAL,
  "bid_wall_price" REAL,
  "ask_wall_price" REAL,
  "bid_wall_persistence" REAL,
  "ask_wall_persistence" REAL,
  "sample_count" INTEGER NOT NULL DEFAULT 0,
  "source" TEXT NOT NULL DEFAULT 'CTRADER_LEVEL_II',
  "created_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  PRIMARY KEY (observed_at)
);

CREATE TABLE IF NOT EXISTS "xau_outcome_ledger" (
  "id" TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
  "episode_key" TEXT NOT NULL,
  "episode_type" TEXT NOT NULL,
  "strategy_id" TEXT NOT NULL,
  "signal_id" TEXT,
  "zone_id" TEXT,
  "map_at" TEXT,
  "observed_at" TEXT NOT NULL,
  "direction" TEXT,
  "grade" TEXT,
  "score" REAL,
  "status" TEXT NOT NULL,
  "execution_authority" TEXT,
  "entry_price" REAL,
  "stop_price" REAL,
  "tp1_price" REAL,
  "tp2_price" REAL,
  "first_touch_at" TEXT,
  "map_first_touch_at" TEXT,
  "confirmed_at" TEXT,
  "execution_ready_at" TEXT,
  "order_accepted_at" TEXT,
  "protection_verified_at" TEXT,
  "outcome_at" TEXT,
  "outcome_class" TEXT,
  "mfe_points" REAL,
  "mae_points" REAL,
  "mfe_r" REAL,
  "mae_r" REAL,
  "tp1_hit" INTEGER NOT NULL CHECK ("tp1_hit" IN (0,1)) DEFAULT false,
  "tp2_hit" INTEGER NOT NULL CHECK ("tp2_hit" IN (0,1)) DEFAULT false,
  "stop_hit" INTEGER NOT NULL CHECK ("stop_hit" IN (0,1)) DEFAULT false,
  "missed_execution" INTEGER NOT NULL CHECK ("missed_execution" IN (0,1)) DEFAULT false,
  "metadata" TEXT NOT NULL CHECK (json_valid("metadata")) DEFAULT '{}',
  "created_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  "updated_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK (((direction IS NULL) OR (direction IN ('LONG', 'SHORT')))),
  CHECK (((grade IS NULL) OR (grade IN ('A', 'B', 'C')))),
  UNIQUE (episode_key),
  PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS "xau_prepared_plan_lifecycle" (
  "id" TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
  "plan_key" TEXT NOT NULL,
  "signal_id" TEXT NOT NULL,
  "zone_id" TEXT,
  "map_at" TEXT,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  "direction" TEXT,
  "grade" TEXT,
  "zone_low" REAL,
  "zone_high" REAL,
  "entry_price" REAL,
  "stop_price" REAL,
  "tp1_price" REAL,
  "tp2_price" REAL,
  "lifecycle_state" TEXT NOT NULL,
  "cancel_reason" TEXT,
  "cancelled_at" TEXT,
  "first_touch_at" TEXT,
  "confirmed_at" TEXT,
  "execution_ready_at" TEXT,
  "order_accepted_at" TEXT,
  "protection_verified_at" TEXT,
  "outcome_at" TEXT,
  "outcome_class" TEXT,
  "tp1_hit" INTEGER NOT NULL CHECK ("tp1_hit" IN (0,1)) DEFAULT false,
  "tp2_hit" INTEGER NOT NULL CHECK ("tp2_hit" IN (0,1)) DEFAULT false,
  "stop_hit" INTEGER NOT NULL CHECK ("stop_hit" IN (0,1)) DEFAULT false,
  "mfe_r" REAL,
  "mae_r" REAL,
  "post_cancel_terminal_hit" INTEGER NOT NULL CHECK ("post_cancel_terminal_hit" IN (0,1)) DEFAULT false,
  "metadata" TEXT NOT NULL CHECK (json_valid("metadata")) DEFAULT '{}',
  CHECK (((direction IS NULL) OR (direction IN ('LONG', 'SHORT')))),
  CHECK (((grade IS NULL) OR (grade IN ('A', 'B', 'C')))),
  PRIMARY KEY (id),
  UNIQUE (plan_key)
);

CREATE TABLE IF NOT EXISTS "xau_pressure_depth_episodes" (
  "episode_key" TEXT NOT NULL,
  "signal_key" TEXT,
  "zone_id" TEXT,
  "direction" TEXT,
  "timeframe" TEXT,
  "first_touch_at" TEXT NOT NULL,
  "outcome_at" TEXT,
  "status" TEXT NOT NULL,
  "first_touch_dom_state" TEXT,
  "first_touch_dom_score" REAL,
  "first_touch_imbalance" REAL,
  "dom_pressure_slope" REAL,
  "opposing_dom_score" REAL,
  "pressure_bucket" TEXT,
  "turning_depth" REAL,
  "max_depth_reached" REAL,
  "reaction_hit_050" INTEGER NOT NULL CHECK ("reaction_hit_050" IN (0,1)) DEFAULT false,
  "invalidated" INTEGER NOT NULL CHECK ("invalidated" IN (0,1)) DEFAULT false,
  "zone_low" REAL,
  "zone_high" REAL,
  "atr_points" REAL,
  "metadata" TEXT NOT NULL CHECK (json_valid("metadata")) DEFAULT '{}',
  "created_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  "updated_at" TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK ((direction IN ('LONG', 'SHORT'))),
  PRIMARY KEY (episode_key)
);


CREATE INDEX IF NOT EXISTS smc_features_symbol_idx ON smc_features (symbol);


CREATE INDEX IF NOT EXISTS storage_guard_audit_observed_at_idx ON storage_guard_audit (observed_at DESC);






CREATE INDEX IF NOT EXISTS broker_order_events_backend_account_order_event_idx ON broker_order_events (backend, account_id, broker_order_id, event_type);

CREATE INDEX IF NOT EXISTS broker_order_events_backend_event_account_observed_idx ON broker_order_events (backend, event_type, account_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS broker_order_events_event_code_observed_idx ON broker_order_events (event_type, code, observed_at DESC);

CREATE INDEX IF NOT EXISTS broker_order_events_observed_at_desc_idx ON broker_order_events (observed_at DESC);

CREATE INDEX IF NOT EXISTS broker_order_events_signal_idx ON broker_order_events (signal_key, observed_at DESC);

CREATE INDEX IF NOT EXISTS broker_order_events_event_observed_idx ON broker_order_events (event_type, observed_at DESC);

CREATE INDEX IF NOT EXISTS broker_order_events_backend_event_observed_idx ON broker_order_events (backend, event_type, observed_at DESC);

CREATE INDEX IF NOT EXISTS broker_order_events_backend_account_observed_idx ON broker_order_events (backend, account_id, observed_at DESC);


CREATE INDEX IF NOT EXISTS broker_position_state_snapshot_idx ON broker_position_state (backend, account_id, snapshot_id);







CREATE INDEX IF NOT EXISTS data_quality_run_id_idx ON data_quality_snapshots (run_id);

CREATE INDEX IF NOT EXISTS data_quality_symbol_time_idx ON data_quality_snapshots (symbol, observed_at DESC);




CREATE INDEX IF NOT EXISTS liquidity_active_idx ON liquidity_levels (symbol, active, observed_at DESC);





CREATE INDEX IF NOT EXISTS pair_rankings_run_rank_idx ON pair_rankings (run_id, rank);

CREATE INDEX IF NOT EXISTS pair_rankings_symbol_idx ON pair_rankings (symbol);


CREATE INDEX IF NOT EXISTS paper_trades_signal_id_idx ON paper_trades (signal_id);



CREATE INDEX IF NOT EXISTS scanner_runs_started_at_idx ON scanner_runs (started_at DESC);


CREATE INDEX IF NOT EXISTS signals_observed_at_desc_idx ON signals (observed_at DESC);

CREATE INDEX IF NOT EXISTS signals_run_id_idx ON signals (run_id);

CREATE INDEX IF NOT EXISTS signals_state_time_idx ON signals (state, observed_at DESC);

CREATE INDEX IF NOT EXISTS signals_symbol_time_idx ON signals (symbol, observed_at DESC);

CREATE INDEX IF NOT EXISTS signals_symbol_setup_observed_idx ON signals (symbol, setup_type, observed_at DESC);



CREATE INDEX IF NOT EXISTS xau_outcome_ledger_observed_at_idx ON xau_outcome_ledger (observed_at DESC);

CREATE INDEX IF NOT EXISTS xau_outcome_ledger_signal_id_idx ON xau_outcome_ledger (signal_id) WHERE (signal_id IS NOT NULL);

CREATE INDEX IF NOT EXISTS xau_outcome_ledger_status_idx ON xau_outcome_ledger (status, observed_at DESC);

CREATE INDEX IF NOT EXISTS xau_outcome_ledger_zone_map_idx ON xau_outcome_ledger (zone_id, map_at);

CREATE INDEX IF NOT EXISTS xau_outcome_episode_strategy_observed_idx ON xau_outcome_ledger (episode_type, strategy_id, observed_at);

CREATE INDEX IF NOT EXISTS xau_outcome_strategy_observed_idx ON xau_outcome_ledger (strategy_id, observed_at);



CREATE INDEX IF NOT EXISTS xau_prepared_plan_lifecycle_created_at_idx ON xau_prepared_plan_lifecycle (created_at DESC);

CREATE INDEX IF NOT EXISTS xau_prepared_plan_lifecycle_signal_id_idx ON xau_prepared_plan_lifecycle (signal_id);

CREATE INDEX IF NOT EXISTS xau_prepared_plan_lifecycle_state_idx ON xau_prepared_plan_lifecycle (lifecycle_state, created_at DESC);

CREATE INDEX IF NOT EXISTS xau_prepared_plan_lifecycle_zone_map_idx ON xau_prepared_plan_lifecycle (zone_id, map_at);


CREATE INDEX IF NOT EXISTS xau_pressure_depth_episodes_touch_desc ON xau_pressure_depth_episodes (first_touch_at DESC);
CREATE TABLE IF NOT EXISTS turso_usage_daily (
 day TEXT NOT NULL, worker TEXT NOT NULL,
 requests INTEGER NOT NULL DEFAULT 0, statements INTEGER NOT NULL DEFAULT 0,
 rows_read INTEGER NOT NULL DEFAULT 0, rows_written INTEGER NOT NULL DEFAULT 0,
 unmetered_statements INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(day,worker)
);
CREATE INDEX IF NOT EXISTS broker_order_accepted_time ON broker_order_events(observed_at DESC) WHERE event_type='ORDER_ACCEPTED' AND accepted=1;
