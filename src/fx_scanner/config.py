from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml

from .exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class PairSpec:
    symbol: str
    base: str
    quote: str
    pip_size: float
    tier: str


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    pairs: tuple[PairSpec, ...]
    timeframes: dict[str, int]
    risk: dict[str, Any]
    scoring: dict[str, Any]
    sessions: dict[str, Any]
    macro: dict[str, Any]
    providers: dict[str, Any]
    strategy: dict[str, Any]

    @property
    def pair_map(self) -> dict[str, PairSpec]:
        return {p.symbol: p for p in self.pairs}


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path} must contain a YAML mapping")
    return data


def _as_finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise ConfigurationError(f"{label} cannot be boolean")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{label} must be numeric") from exc
    if not isfinite(numeric):
        raise ConfigurationError(f"{label} must be finite")
    return numeric


def _validate_weight_map(
    name: str,
    values: Mapping[str, Any] | Any,
    expected_keys: set[str],
) -> dict[str, float]:
    if not isinstance(values, Mapping):
        raise ConfigurationError(f"{name} must be a mapping")
    if set(values) != expected_keys:
        raise ConfigurationError(f"{name} keys must be exactly {sorted(expected_keys)}")
    out: dict[str, float] = {}
    for key, raw in values.items():
        value = _as_finite_number(raw, label=f"{name}.{key}")
        if value <= 0:
            raise ConfigurationError(f"{name}.{key} must be positive")
        out[str(key)] = value
    if abs(sum(out.values()) - 100.0) > 1e-9:
        raise ConfigurationError(f"{name} weights must sum to 100")
    return out


def load_project_config(root: str | Path | None = None) -> ProjectConfig:
    root_path = Path(root) if root else Path(__file__).resolve().parents[2]
    cfg = root_path / "config"

    pair_data = _read_yaml(cfg / "pairs.yaml")
    raw_pairs = pair_data.get("pairs", [])
    if not isinstance(raw_pairs, list) or len(raw_pairs) != 15:
        raise ConfigurationError(f"v0.8 requires exactly 15 configured pairs, got {len(raw_pairs) if isinstance(raw_pairs, list) else 'invalid'}")

    pairs: list[PairSpec] = []
    seen: set[str] = set()
    for item in raw_pairs:
        if not isinstance(item, Mapping):
            raise ConfigurationError("each pair config must be a mapping")
        symbol = str(item.get("symbol", "")).upper().strip()
        base = str(item.get("base", "")).upper().strip()
        quote = str(item.get("quote", "")).upper().strip()
        if len(base) != 3 or len(quote) != 3 or len(symbol) != 6:
            raise ConfigurationError(f"invalid currency code contract for {symbol or '<missing>'}")
        if symbol != base + quote:
            raise ConfigurationError(f"symbol/base/quote mismatch for {symbol}")
        if symbol in seen:
            raise ConfigurationError(f"duplicate pair {symbol}")
        seen.add(symbol)
        pip_size = _as_finite_number(item.get("pip_size"), label=f"{symbol}.pip_size")
        if pip_size <= 0:
            raise ConfigurationError(f"invalid pip size for {symbol}")
        tier = str(item.get("tier", "")).upper().strip()
        if tier not in {"A", "B"}:
            raise ConfigurationError(f"invalid pair tier for {symbol}")
        pairs.append(PairSpec(symbol, base, quote, pip_size, tier))

    raw_tfs = pair_data.get("timeframes", {})
    if not isinstance(raw_tfs, Mapping):
        raise ConfigurationError("timeframes must be a mapping")
    timeframes = {str(k).upper(): int(v) for k, v in raw_tfs.items()}
    required_timeframes = {
        "M1": 60,
        "M5": 300,
        "M15": 900,
        "H1": 3600,
        "H4": 14400,
        "D1": 86400,
    }
    if timeframes != required_timeframes:
        raise ConfigurationError(f"timeframes must equal canonical contract {required_timeframes}")

    risk = _read_yaml(cfg / "risk.yaml")
    scoring = _read_yaml(cfg / "scoring.yaml")
    sessions = _read_yaml(cfg / "sessions.yaml")
    macro = _read_yaml(cfg / "macro.yaml")
    providers = _read_yaml(cfg / "providers.yaml")
    strategy = _read_yaml(cfg / "strategy.yaml")

    pair_keys = {"macro", "currency_strength", "intermarket", "volatility", "session", "spread"}
    execution_keys = {
        "relative_macro", "htf_structure", "liquidity", "smc_structure",
        "displacement", "session", "cross_asset", "positioning", "execution_quality",
    }
    _validate_weight_map("pair_opportunity", scoring.get("pair_opportunity"), pair_keys)
    _validate_weight_map("execution_conviction", scoring.get("execution_conviction"), execution_keys)

    expected_macro = {
        "interest_rate", "central_bank_bias", "inflation", "growth",
        "labour", "yield_momentum", "risk_commodity", "positioning",
    }
    _validate_weight_map("macro.weights", macro.get("weights"), expected_macro)
    macro_min_coverage = _as_finite_number(macro.get("minimum_coverage"), label="macro.minimum_coverage")
    if not 0 < macro_min_coverage <= 1:
        raise ConfigurationError("macro minimum_coverage must be in (0,1]")
    factor_min = _as_finite_number(macro.get("factor_min"), label="macro.factor_min")
    factor_max = _as_finite_number(macro.get("factor_max"), label="macro.factor_max")
    if factor_min >= factor_max or factor_min > -100 or factor_max < 100:
        raise ConfigurationError("macro factor range must cover at least [-100,100]")

    states = scoring.get("states", {})
    expected_state_keys = {
        "no_trade_max", "watch_min", "setup_forming_min", "armed_min", "execution_candidate_min",
    }
    if not isinstance(states, Mapping) or set(states) != expected_state_keys:
        raise ConfigurationError(f"signal-state keys must be exactly {sorted(expected_state_keys)}")
    state_values = {key: _as_finite_number(states[key], label=f"states.{key}") for key in expected_state_keys}
    if not all(0 <= value <= 100 for value in state_values.values()):
        raise ConfigurationError("signal-state thresholds must be within [0,100]")
    if not (
        state_values["no_trade_max"] < state_values["watch_min"]
        <= state_values["setup_forming_min"]
        <= state_values["armed_min"]
        <= state_values["execution_candidate_min"]
    ):
        raise ConfigurationError("signal-state thresholds are not monotonic")

    expected_guards = {
        "NEWS_BLOCK", "SPREAD_BLOCK", "VOLATILITY_BLOCK", "CORRELATION_BLOCK",
        "RISK_BLOCK", "STALE_SIGNAL", "CHASE_BLOCK", "RR_BLOCK",
        "STRUCTURE_INVALID", "DATA_QUALITY_BLOCK",
    }
    hard_guards = scoring.get("hard_guards")
    if not isinstance(hard_guards, list) or len(hard_guards) != len(set(hard_guards)):
        raise ConfigurationError("hard_guards must be a unique list")
    if set(map(str, hard_guards)) != expected_guards:
        raise ConfigurationError(f"hard_guards must be exactly {sorted(expected_guards)}")

    if str(risk.get("mode", "")).upper() != "RESEARCH_ONLY":
        raise ConfigurationError("v0.8 risk mode must remain RESEARCH_ONLY")

    risk_per_trade = _as_finite_number(risk.get("risk_per_trade_pct"), label="risk_per_trade_pct")
    max_risk = _as_finite_number(risk.get("max_risk_per_trade_pct"), label="max_risk_per_trade_pct")
    max_daily_loss = _as_finite_number(risk.get("max_daily_loss_pct"), label="max_daily_loss_pct")
    same_currency = _as_finite_number(
        risk.get("max_same_currency_exposure_units"),
        label="max_same_currency_exposure_units",
    )
    if not 0 < risk_per_trade <= max_risk <= 0.50:
        raise ConfigurationError("risk-per-trade contract exceeds v0.8 safety cap")
    if not 0 < max_daily_loss <= 1.0:
        raise ConfigurationError("max_daily_loss_pct exceeds v0.8 safety cap")
    if int(risk.get("max_concurrent_trades", 0)) != 2:
        raise ConfigurationError("max_concurrent_trades must remain 2")
    if int(risk.get("max_consecutive_losses", 0)) != 3:
        raise ConfigurationError("max_consecutive_losses must remain 3")
    if not 0 < same_currency <= 1.5:
        raise ConfigurationError("same-currency exposure exceeds v0.8 cap")

    acceptance = risk.get("acceptance", {})
    if not isinstance(acceptance, Mapping):
        raise ConfigurationError("acceptance must be a mapping")
    if _as_finite_number(acceptance.get("oos_win_rate_min"), label="acceptance.oos_win_rate_min") < 0.55:
        raise ConfigurationError("OOS win-rate gate cannot be below 55%")
    if _as_finite_number(acceptance.get("profit_factor_min"), label="acceptance.profit_factor_min") < 1.30:
        raise ConfigurationError("profit-factor gate cannot be below 1.30")
    if _as_finite_number(acceptance.get("expectancy_r_min"), label="acceptance.expectancy_r_min") < 0.15:
        raise ConfigurationError("expectancy gate cannot be below 0.15R")
    if int(acceptance.get("aggregate_oos_trades_min", 0)) < 250:
        raise ConfigurationError("aggregate OOS sample cannot be below 250 trades")
    required_acceptance_flags = {
        "walk_forward_required",
        "transaction_costs_required",
        "spread_stress_required",
        "slippage_stress_required",
        "multi_regime_required",
        "demo_forward_required",
    }
    for key in required_acceptance_flags:
        if acceptance.get(key) is not True:
            raise ConfigurationError(f"acceptance.{key} must remain true")

    transport = providers.get("transport", {})
    if not isinstance(transport, Mapping):
        raise ConfigurationError("providers.transport must be a mapping")
    timeout_seconds = _as_finite_number(
        transport.get("timeout_seconds"), label="providers.transport.timeout_seconds"
    )
    max_response_bytes = _as_finite_number(
        transport.get("max_response_bytes"), label="providers.transport.max_response_bytes"
    )
    if not 0 < timeout_seconds <= 30:
        raise ConfigurationError("provider transport timeout must be in (0,30] seconds")
    if not 1024 <= max_response_bytes <= 5_242_880:
        raise ConfigurationError("provider response size must be between 1 KiB and 5 MiB")
    if not str(transport.get("user_agent", "")).strip():
        raise ConfigurationError("provider transport user_agent is required")

    cache_cfg = providers.get("cache", {})
    if not isinstance(cache_cfg, Mapping):
        raise ConfigurationError("providers.cache must be a mapping")
    cache_limits = {
        "positive_ttl_seconds": 86400,
        "negative_ttl_seconds": 3600,
        "stale_ttl_seconds": 600,
    }
    for key, upper in cache_limits.items():
        value = _as_finite_number(cache_cfg.get(key), label=f"providers.cache.{key}")
        if not 0 < value <= upper:
            raise ConfigurationError(f"providers.cache.{key} must be in (0,{upper}]")

    quorum_cfg = providers.get("quorum", {})
    if not isinstance(quorum_cfg, Mapping):
        raise ConfigurationError("providers.quorum must be a mapping")
    minimum_success_raw = _as_finite_number(
        quorum_cfg.get("minimum_success"),
        label="providers.quorum.minimum_success",
    )
    if not minimum_success_raw.is_integer() or not 1 <= minimum_success_raw <= 5:
        raise ConfigurationError("providers.quorum.minimum_success must be an integer in [1,5]")
    max_conflict = _as_finite_number(
        quorum_cfg.get("maximum_numeric_conflict"),
        label="providers.quorum.maximum_numeric_conflict",
    )
    if not 0 <= max_conflict <= 100:
        raise ConfigurationError("providers.quorum.maximum_numeric_conflict must be in [0,100]")

    sources = providers.get("sources", {})
    if not isinstance(sources, Mapping) or not sources:
        raise ConfigurationError("providers.sources must contain configured sources")
    required_sources = {"ECB_DATA_PORTAL", "BANK_OF_CANADA_VALET"}
    canonical_source_urls = {
        "ECB_DATA_PORTAL": (
            "https://data-api.ecb.europa.eu/service/data",
            "data-api.ecb.europa.eu",
        ),
        "BANK_OF_CANADA_VALET": (
            "https://www.bankofcanada.ca/valet/observations",
            "www.bankofcanada.ca",
        ),
    }
    if not required_sources.issubset(set(sources)):
        raise ConfigurationError("official ECB and Bank of Canada providers are required in v0.8")
    for name, source in sources.items():
        if not isinstance(source, Mapping):
            raise ConfigurationError(f"provider source {name} must be a mapping")
        if source.get("enabled") is not True or source.get("official") is not True:
            raise ConfigurationError(f"provider source {name} must remain enabled and official")
        base_url = str(source.get("base_url", "")).strip()
        allowed_host = str(source.get("allowed_host", "")).strip()
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname != allowed_host:
            raise ConfigurationError(f"provider source {name} HTTPS host contract is invalid")
        if name in canonical_source_urls:
            expected_url, expected_host = canonical_source_urls[name]
            if base_url.rstrip("/") != expected_url or allowed_host != expected_host:
                raise ConfigurationError(f"provider source {name} canonical endpoint changed")
        if _as_finite_number(
            source.get("default_max_age_seconds"),
            label=f"providers.sources.{name}.default_max_age_seconds",
        ) <= 0:
            raise ConfigurationError(f"provider source {name} max age must be positive")

    smoke_series = providers.get("smoke_series", {})
    if not isinstance(smoke_series, Mapping) or not smoke_series:
        raise ConfigurationError("providers.smoke_series must be configured")
    for name, item in smoke_series.items():
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"smoke series {name} must be a mapping")
        provider_name = str(item.get("provider", ""))
        if provider_name not in sources:
            raise ConfigurationError(f"smoke series {name} references unknown provider")
        if not str(item.get("series", "")).strip():
            raise ConfigurationError(f"smoke series {name} requires series")
        if _as_finite_number(
            item.get("max_age_seconds"),
            label=f"providers.smoke_series.{name}.max_age_seconds",
        ) <= 0:
            raise ConfigurationError(f"smoke series {name} max age must be positive")


    selection = strategy.get("selection", {})
    if not isinstance(selection, Mapping):
        raise ConfigurationError("strategy.selection must be a mapping")
    if int(selection.get("macro_compatible_top", 0)) != 8:
        raise ConfigurationError("strategy macro_compatible_top must remain 8")
    if int(selection.get("deep_analysis_top", 0)) != 5:
        raise ConfigurationError("strategy deep_analysis_top must remain 5")

    mtf = strategy.get("mtf", {})
    if not isinstance(mtf, Mapping):
        raise ConfigurationError("strategy.mtf must be a mapping")
    required_mtf = ["D1", "H4", "H1", "M15", "M5"]
    if list(mtf.get("required_timeframes", [])) != required_mtf:
        raise ConfigurationError(f"strategy MTF contract must equal {required_mtf}")
    swing_lookback = _as_finite_number(mtf.get("swing_lookback"), label="strategy.mtf.swing_lookback")
    atr_period = _as_finite_number(mtf.get("atr_period"), label="strategy.mtf.atr_period")
    if not swing_lookback.is_integer() or not 1 <= swing_lookback <= 5:
        raise ConfigurationError("strategy swing_lookback must be an integer in [1,5]")
    if not atr_period.is_integer() or not 5 <= atr_period <= 50:
        raise ConfigurationError("strategy ATR period must be an integer in [5,50]")
    minimum_bars = mtf.get("minimum_bars", {})
    canonical_minimum = {"D1": 20, "H4": 30, "H1": 40, "M15": 50, "M5": 60}
    if not isinstance(minimum_bars, Mapping) or set(minimum_bars) != set(canonical_minimum):
        raise ConfigurationError("strategy minimum_bars keys are invalid")
    for tf, floor in canonical_minimum.items():
        raw = _as_finite_number(minimum_bars.get(tf), label=f"strategy.minimum_bars.{tf}")
        if not raw.is_integer() or not floor <= raw <= 2000:
            raise ConfigurationError(f"strategy minimum_bars.{tf} cannot be below {floor}")

    liquidity_cfg = strategy.get("liquidity", {})
    if not isinstance(liquidity_cfg, Mapping):
        raise ConfigurationError("strategy.liquidity must be a mapping")
    tol = _as_finite_number(
        liquidity_cfg.get("equal_level_tolerance_atr"),
        label="strategy.liquidity.equal_level_tolerance_atr",
    )
    min_touches = _as_finite_number(
        liquidity_cfg.get("equal_level_min_touches"),
        label="strategy.liquidity.equal_level_min_touches",
    )
    lookback_bars = _as_finite_number(
        liquidity_cfg.get("equal_level_lookback_bars"),
        label="strategy.liquidity.equal_level_lookback_bars",
    )
    eq_band = _as_finite_number(
        liquidity_cfg.get("equilibrium_band"),
        label="strategy.liquidity.equilibrium_band",
    )
    sweep_reclaim = _as_finite_number(
        liquidity_cfg.get("sweep_reclaim_bars"),
        label="strategy.liquidity.sweep_reclaim_bars",
    )
    ob_search = _as_finite_number(
        liquidity_cfg.get("order_block_search_bars"),
        label="strategy.liquidity.order_block_search_bars",
    )
    ob_origin = _as_finite_number(
        liquidity_cfg.get("order_block_origin_lookback"),
        label="strategy.liquidity.order_block_origin_lookback",
    )
    fvg_scan = _as_finite_number(
        liquidity_cfg.get("fvg_scan_bars"),
        label="strategy.liquidity.fvg_scan_bars",
    )
    if not 0.05 <= tol <= 0.25:
        raise ConfigurationError("equal-level ATR tolerance must remain within [0.05,0.25]")
    if not min_touches.is_integer() or not 2 <= min_touches <= 5:
        raise ConfigurationError("equal-level touches must be an integer in [2,5]")
    for label, value in (
        ("equal_level_lookback_bars", lookback_bars),
        ("order_block_search_bars", ob_search),
        ("fvg_scan_bars", fvg_scan),
    ):
        if not value.is_integer() or not 20 <= value <= 500:
            raise ConfigurationError(f"strategy {label} must be an integer in [20,500]")
    if not 0 <= eq_band <= 0.10:
        raise ConfigurationError("equilibrium band must be within [0,0.10]")
    if not sweep_reclaim.is_integer() or not 1 <= sweep_reclaim <= 5:
        raise ConfigurationError("sweep reclaim bars must be an integer in [1,5]")
    if not ob_origin.is_integer() or not 2 <= ob_origin <= 10:
        raise ConfigurationError("order-block origin lookback must be an integer in [2,10]")

    plan = strategy.get("trade_plan", {})
    if not isinstance(plan, Mapping):
        raise ConfigurationError("strategy.trade_plan must be a mapping")
    sl_buffer = _as_finite_number(plan.get("sl_buffer_atr"), label="strategy.trade_plan.sl_buffer_atr")
    chase_ok = _as_finite_number(plan.get("chase_ok_atr"), label="strategy.trade_plan.chase_ok_atr")
    chase_block = _as_finite_number(plan.get("chase_block_atr"), label="strategy.trade_plan.chase_block_atr")
    min_rr = _as_finite_number(plan.get("minimum_tp2_rr"), label="strategy.trade_plan.minimum_tp2_rr")
    preferred_rr = _as_finite_number(plan.get("preferred_tp2_rr"), label="strategy.trade_plan.preferred_tp2_rr")
    entry_zone = _as_finite_number(
        plan.get("minimum_entry_zone_atr"),
        label="strategy.trade_plan.minimum_entry_zone_atr",
    )
    if not 0.05 <= sl_buffer <= 0.30:
        raise ConfigurationError("SL ATR buffer must remain within [0.05,0.30]")
    if not 0 < chase_ok <= 0.25 or not chase_ok < chase_block <= 0.50:
        raise ConfigurationError("chase thresholds violate v0.8 safety contract")
    if min_rr < 1.50 or preferred_rr < max(2.0, min_rr):
        raise ConfigurationError("trade-plan RR contract cannot be weakened")
    if not 0 < entry_zone <= 0.20:
        raise ConfigurationError("minimum entry-zone ATR must be in (0,0.20]")

    setup = strategy.get("setup", {})
    expected_setup = {
        "liquidity_sweep_reversal": {
            "require_m15_sweep",
            "require_m5_displacement",
            "require_m5_structure_break",
        },
        "trend_continuation": {
            "require_d1_h4_alignment",
            "require_h1_alignment",
            "require_m15_fvg",
            "require_m5_displacement",
        },
    }
    if not isinstance(setup, Mapping) or set(setup) != set(expected_setup):
        raise ConfigurationError("strategy setup keys are invalid")
    for setup_name, required_flags in expected_setup.items():
        values = setup.get(setup_name)
        if not isinstance(values, Mapping) or set(values) != required_flags:
            raise ConfigurationError(f"strategy setup {setup_name} flags are invalid")
        if any(values[key] is not True for key in required_flags):
            raise ConfigurationError(f"strategy setup {setup_name} requirements cannot be disabled")

    return ProjectConfig(tuple(pairs), timeframes, risk, scoring, sessions, macro, providers, strategy)
