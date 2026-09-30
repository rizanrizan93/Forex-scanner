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
    validation: dict[str, Any]

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
    if not isinstance(raw_pairs, list) or len(raw_pairs) != 20:
        raise ConfigurationError(f"DEMO technical universe requires exactly 20 configured instruments, got {len(raw_pairs) if isinstance(raw_pairs, list) else 'invalid'}")

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
    validation = _read_yaml(cfg / "validation.yaml")

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
        raise ConfigurationError("v0.9 risk mode must remain RESEARCH_ONLY")

    risk_per_trade = _as_finite_number(risk.get("risk_per_trade_pct"), label="risk_per_trade_pct")
    max_risk = _as_finite_number(risk.get("max_risk_per_trade_pct"), label="max_risk_per_trade_pct")
    max_daily_loss = _as_finite_number(risk.get("max_daily_loss_pct"), label="max_daily_loss_pct")
    same_currency = _as_finite_number(
        risk.get("max_same_currency_exposure_units"),
        label="max_same_currency_exposure_units",
    )
    if not 0 < risk_per_trade <= max_risk <= 0.50:
        raise ConfigurationError("risk-per-trade contract exceeds v0.9 safety cap")
    if not 0 < max_daily_loss <= 1.0:
        raise ConfigurationError("max_daily_loss_pct exceeds v0.9 safety cap")
    if int(risk.get("max_concurrent_trades", 0)) != 2:
        raise ConfigurationError("max_concurrent_trades must remain 2")
    if int(risk.get("max_consecutive_losses", 0)) != 3:
        raise ConfigurationError("max_consecutive_losses must remain 3")
    if not 0 < same_currency <= 1.5:
        raise ConfigurationError("same-currency exposure exceeds v0.9 cap")

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
        "point_in_time_required",
        "monte_carlo_required",
        "parameter_perturbation_required",
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
    required_sources = {
        "ECB_DATA_PORTAL",
        "BANK_OF_CANADA_VALET",
        "BANK_OF_ENGLAND_IADB",
        "FEDERAL_RESERVE_FRED",
        "RBA_CASH_RATE",
        "OECD_SDMX",
    }
    canonical_source_urls = {
        "ECB_DATA_PORTAL": (
            "https://data-api.ecb.europa.eu/service/data",
            "data-api.ecb.europa.eu",
        ),
        "BANK_OF_CANADA_VALET": (
            "https://www.bankofcanada.ca/valet/observations",
            "www.bankofcanada.ca",
        ),
        "BANK_OF_ENGLAND_IADB": (
            "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp",
            "www.bankofengland.co.uk",
        ),
        "FEDERAL_RESERVE_FRED": (
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            "fred.stlouisfed.org",
        ),
        "RBA_CASH_RATE": (
            "https://www.rba.gov.au/statistics/cash-rate",
            "www.rba.gov.au",
        ),
        "OECD_SDMX": (
            "https://sdmx.oecd.org/public/rest/data",
            "sdmx.oecd.org",
        ),
    }
    if not required_sources.issubset(set(sources)):
        raise ConfigurationError(
            "canonical ECB, BoC, BoE, Federal Reserve/FRED, RBA, and OECD providers are required"
        )
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
            if base_url.rstrip("/") != expected_url.rstrip("/") or allowed_host != expected_host:
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


    macro_ingestion = providers.get("macro_ingestion", {})
    if not isinstance(macro_ingestion, Mapping):
        raise ConfigurationError("providers.macro_ingestion must be a mapping")
    currency_areas = macro_ingestion.get("currency_areas", {})
    expected_currencies = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
    if not isinstance(currency_areas, Mapping) or set(currency_areas) != expected_currencies:
        raise ConfigurationError(
            "providers.macro_ingestion.currency_areas must cover exactly the eight scanner currencies"
        )
    for currency, area in currency_areas.items():
        area = str(area).strip()
        if not area or not all(ch.isalnum() or ch in "_-" for ch in area):
            raise ConfigurationError(f"invalid OECD reference area for {currency}")

    macro_factor_cfg = macro_ingestion.get("factors", {})
    required_macro_ingestion_factors = {
        "interest_rate",
        "inflation",
        "growth",
        "labour",
        "yield_momentum",
    }
    if (
        not isinstance(macro_factor_cfg, Mapping)
        or set(macro_factor_cfg) != required_macro_ingestion_factors
    ):
        raise ConfigurationError(
            "providers.macro_ingestion.factors must contain the canonical five-factor official subset"
        )
    configured_weight = sum(
        float(macro["weights"][factor]) for factor in required_macro_ingestion_factors
    ) / 100.0
    if configured_weight + 1e-12 < macro_min_coverage:
        raise ConfigurationError(
            "configured macro ingestion factors cannot satisfy macro.minimum_coverage"
        )
    for factor, item in macro_factor_cfg.items():
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"macro ingestion factor {factor} must be a mapping")
        if str(item.get("provider", "")) != "OECD_SDMX":
            raise ConfigurationError(f"macro ingestion factor {factor} must use OECD_SDMX")
        dataset = str(item.get("dataset", "")).strip()
        key_template = str(item.get("key_template", "")).strip()
        if not dataset.startswith("OECD.") or any(ch in dataset for ch in "/?#&%"):
            raise ConfigurationError(f"macro ingestion factor {factor} dataset is invalid")
        if key_template.count("{area}") != 1 or any(ch in key_template for ch in "/?#&%+"):
            raise ConfigurationError(f"macro ingestion factor {factor} key_template is invalid")
        if str(item.get("normalizer", "")).lower() != "delta":
            raise ConfigurationError(f"macro ingestion factor {factor} must use delta normalizer")
        scale = _as_finite_number(
            item.get("scale"), label=f"providers.macro_ingestion.factors.{factor}.scale"
        )
        if scale <= 0:
            raise ConfigurationError(f"macro ingestion factor {factor} scale must be positive")
        polarity = _as_finite_number(
            item.get("polarity"), label=f"providers.macro_ingestion.factors.{factor}.polarity"
        )
        if not polarity.is_integer() or int(polarity) not in (-1, 1):
            raise ConfigurationError(f"macro ingestion factor {factor} polarity must be -1 or 1")
        max_age = _as_finite_number(
            item.get("max_age_seconds"),
            label=f"providers.macro_ingestion.factors.{factor}.max_age_seconds",
        )
        if not 86400 <= max_age <= 15552000:
            raise ConfigurationError(
                f"macro ingestion factor {factor} max age must be within [1,180] days"
            )
        overrides = item.get("area_overrides", {})
        if not isinstance(overrides, Mapping) or not set(overrides).issubset(expected_currencies):
            raise ConfigurationError(f"macro ingestion factor {factor} area_overrides are invalid")
        for currency, area in overrides.items():
            area = str(area).strip()
            if not area or not all(ch.isalnum() or ch in "_-" for ch in area):
                raise ConfigurationError(
                    f"invalid OECD reference area override for {factor}.{currency}"
                )
        key_overrides = item.get("key_overrides", {})
        if (
            not isinstance(key_overrides, Mapping)
            or not set(key_overrides).issubset(expected_currencies)
        ):
            raise ConfigurationError(f"macro ingestion factor {factor} key_overrides are invalid")
        for currency, override_template in key_overrides.items():
            override_template = str(override_template).strip()
            if (
                override_template.count("{area}") != 1
                or any(ch in override_template for ch in "/?#&%+")
            ):
                raise ConfigurationError(
                    f"invalid OECD key override for {factor}.{currency}"
                )

        series_overrides = item.get("series_overrides", {})
        if (
            not isinstance(series_overrides, Mapping)
            or not set(series_overrides).issubset(expected_currencies)
        ):
            raise ConfigurationError(
                f"macro ingestion factor {factor} series_overrides are invalid"
            )
        for currency, raw_series in series_overrides.items():
            series = str(raw_series).strip()
            if series.count("|") != 1:
                raise ConfigurationError(
                    f"invalid OECD exact series override for {factor}.{currency}"
                )
            dataset_override, key_override = series.split("|", 1)
            if (
                not dataset_override.startswith("OECD.")
                or any(ch in dataset_override for ch in "/?#&%")
                or not key_override
                or any(ch in key_override for ch in "/?#&%+")
            ):
                raise ConfigurationError(
                    f"invalid OECD exact series override for {factor}.{currency}"
                )
        max_age_overrides = item.get("max_age_overrides", {})
        if (
            not isinstance(max_age_overrides, Mapping)
            or not set(max_age_overrides).issubset(expected_currencies)
        ):
            raise ConfigurationError(
                f"macro ingestion factor {factor} max_age_overrides are invalid"
            )
        for currency, raw_age in max_age_overrides.items():
            override_age = _as_finite_number(
                raw_age,
                label=f"providers.macro_ingestion.factors.{factor}.max_age_overrides.{currency}",
            )
            if not 86400 <= override_age <= 15552000:
                raise ConfigurationError(
                    f"macro ingestion factor {factor}.{currency} max age must be within [1,180] days"
                )

        binding_overrides = item.get("binding_overrides", {})
        if (
            not isinstance(binding_overrides, Mapping)
            or not set(binding_overrides).issubset(expected_currencies)
        ):
            raise ConfigurationError(
                f"macro ingestion factor {factor} binding_overrides are invalid"
            )
        for currency, binding in binding_overrides.items():
            if not isinstance(binding, Mapping):
                raise ConfigurationError(
                    f"macro ingestion factor {factor}.{currency} binding override must be a mapping"
                )
            allowed_binding_keys = {"provider", "series", "max_age_seconds"}
            if not {"provider", "series"}.issubset(binding) or not set(binding).issubset(
                allowed_binding_keys
            ):
                raise ConfigurationError(
                    f"macro ingestion factor {factor}.{currency} binding override keys are invalid"
                )
            override_provider = str(binding["provider"]).strip()
            if override_provider not in sources:
                raise ConfigurationError(
                    f"macro ingestion factor {factor}.{currency} references unknown provider"
                )
            override_series = str(binding["series"]).strip()
            if not override_series or "\n" in override_series or "\r" in override_series:
                raise ConfigurationError(
                    f"macro ingestion factor {factor}.{currency} override series is invalid"
                )
            override_age = _as_finite_number(
                binding.get("max_age_seconds", item["max_age_seconds"]),
                label=f"providers.macro_ingestion.factors.{factor}.binding_overrides.{currency}.max_age_seconds",
            )
            if not 86400 <= override_age <= 15552000:
                raise ConfigurationError(
                    f"macro ingestion factor {factor}.{currency} binding max age must be within [1,180] days"
                )

    calendar_cfg = providers.get("calendar", {})
    if not isinstance(calendar_cfg, Mapping):
        raise ConfigurationError("providers.calendar must be a mapping")
    ff_calendar = calendar_cfg.get("FOREX_FACTORY_WEEKLY")
    if not isinstance(ff_calendar, Mapping):
        raise ConfigurationError("FOREX_FACTORY_WEEKLY calendar is required")
    if ff_calendar.get("enabled") is not True:
        raise ConfigurationError("FOREX_FACTORY_WEEKLY calendar must remain enabled")
    if ff_calendar.get("official") is not False:
        raise ConfigurationError(
            "FOREX_FACTORY_WEEKLY must remain explicitly marked non-official"
        )
    ff_url = str(ff_calendar.get("base_url", "")).strip()
    ff_host = str(ff_calendar.get("allowed_host", "")).strip()
    ff_parsed = urlparse(ff_url)
    if (
        ff_url != "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        or ff_host != "nfs.faireconomy.media"
        or ff_parsed.scheme != "https"
        or ff_parsed.hostname != ff_host
    ):
        raise ConfigurationError("FOREX_FACTORY_WEEKLY canonical HTTPS endpoint changed")


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

    max_bar_age = mtf.get("max_bar_age_seconds", {})
    canonical_max_age = {
        "D1": 259200,
        "H4": 28800,
        "H1": 7200,
        "M15": 1800,
        "M5": 600,
    }
    if not isinstance(max_bar_age, Mapping) or set(max_bar_age) != set(canonical_max_age):
        raise ConfigurationError("strategy max_bar_age_seconds keys are invalid")
    for tf, expected in canonical_max_age.items():
        raw = _as_finite_number(max_bar_age.get(tf), label=f"strategy.max_bar_age_seconds.{tf}")
        if not raw.is_integer() or int(raw) != expected:
            raise ConfigurationError(
                f"strategy max_bar_age_seconds.{tf} must remain {expected}"
            )

    guard_evidence = strategy.get("guard_evidence", {})
    expected_guard_evidence = {
        "news_pre_block_minutes",
        "news_post_block_minutes",
        "volatility_atr_median_min",
        "volatility_atr_median_max",
        "correlation_lookback_bars",
        "correlation_threshold",
    }
    if not isinstance(guard_evidence, Mapping) or set(guard_evidence) != expected_guard_evidence:
        raise ConfigurationError(
            f"strategy.guard_evidence keys must be exactly {sorted(expected_guard_evidence)}"
        )
    news_pre = _as_finite_number(
        guard_evidence["news_pre_block_minutes"],
        label="strategy.guard_evidence.news_pre_block_minutes",
    )
    news_post = _as_finite_number(
        guard_evidence["news_post_block_minutes"],
        label="strategy.guard_evidence.news_post_block_minutes",
    )
    vol_min = _as_finite_number(
        guard_evidence["volatility_atr_median_min"],
        label="strategy.guard_evidence.volatility_atr_median_min",
    )
    vol_max = _as_finite_number(
        guard_evidence["volatility_atr_median_max"],
        label="strategy.guard_evidence.volatility_atr_median_max",
    )
    corr_lookback = _as_finite_number(
        guard_evidence["correlation_lookback_bars"],
        label="strategy.guard_evidence.correlation_lookback_bars",
    )
    corr_threshold = _as_finite_number(
        guard_evidence["correlation_threshold"],
        label="strategy.guard_evidence.correlation_threshold",
    )
    if not (0 <= news_pre <= 120 and 0 <= news_post <= 120):
        raise ConfigurationError("news guard windows must remain within [0,120] minutes")
    if not (0.10 <= vol_min < 1.0 < vol_max <= 5.0):
        raise ConfigurationError("volatility guard ATR/median bounds are invalid")
    if not corr_lookback.is_integer() or not 20 <= corr_lookback <= 100:
        raise ConfigurationError("correlation lookback must be an integer in [20,100]")
    if not 0.70 <= corr_threshold <= 0.99:
        raise ConfigurationError("correlation threshold must remain within [0.70,0.99]")


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
        raise ConfigurationError("chase thresholds violate v0.9 safety contract")
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


    engine_cfg = validation.get("engine", {})
    if not isinstance(engine_cfg, Mapping):
        raise ConfigurationError("validation.engine must be a mapping")
    if str(engine_cfg.get("ambiguous_bar_policy", "")).upper() != "STOP_FIRST":
        raise ConfigurationError("validation ambiguous-bar policy must remain STOP_FIRST")
    entry_expiry = _as_finite_number(
        engine_cfg.get("default_entry_expiry_bars"),
        label="validation.engine.default_entry_expiry_bars",
    )
    max_hold = _as_finite_number(
        engine_cfg.get("maximum_hold_bars"),
        label="validation.engine.maximum_hold_bars",
    )
    min_stop_pips = _as_finite_number(
        engine_cfg.get("minimum_stop_distance_pips"),
        label="validation.engine.minimum_stop_distance_pips",
    )
    if not entry_expiry.is_integer() or not 1 <= entry_expiry <= 48:
        raise ConfigurationError("validation entry expiry must be an integer in [1,48]")
    if not max_hold.is_integer() or not 12 <= max_hold <= 288:
        raise ConfigurationError("validation maximum hold bars must be an integer in [12,288]")
    if min_stop_pips < 2.0:
        raise ConfigurationError("validation minimum stop distance cannot be below 2 pips")

    costs_cfg = validation.get("costs", {})
    if not isinstance(costs_cfg, Mapping) or not isinstance(costs_cfg.get("base"), Mapping):
        raise ConfigurationError("validation costs configuration is incomplete")
    for key in ("spread_pips", "slippage_pips", "commission_pips_round_trip", "swap_pips_per_day"):
        value = _as_finite_number(costs_cfg["base"].get(key), label=f"validation.costs.base.{key}")
        if value < 0:
            raise ConfigurationError(f"validation cost {key} cannot be negative")
    spread_stress = _as_finite_number(
        costs_cfg.get("stress_spread_multiplier"),
        label="validation.costs.stress_spread_multiplier",
    )
    slippage_stress = _as_finite_number(
        costs_cfg.get("stress_slippage_multiplier"),
        label="validation.costs.stress_slippage_multiplier",
    )
    if spread_stress < 1.25:
        raise ConfigurationError("spread stress multiplier cannot be below 1.25")
    if slippage_stress < 1.50:
        raise ConfigurationError("slippage stress multiplier cannot be below 1.50")

    split_cfg = validation.get("dataset_split", {})
    canonical_split = {
        "train_fraction": 0.60,
        "validation_fraction": 0.20,
        "oos_fraction": 0.20,
    }
    if not isinstance(split_cfg, Mapping) or set(split_cfg) != set(canonical_split):
        raise ConfigurationError("validation dataset split keys are invalid")
    for key, expected in canonical_split.items():
        value = _as_finite_number(split_cfg.get(key), label=f"validation.dataset_split.{key}")
        if abs(value - expected) > 1e-9:
            raise ConfigurationError("validation dataset split must remain 60/20/20")

    wf_cfg = validation.get("walk_forward", {})
    if not isinstance(wf_cfg, Mapping):
        raise ConfigurationError("validation.walk_forward must be a mapping")
    wf_minimums = {
        "minimum_train_trades": 100,
        "minimum_test_trades": 30,
        "fold_win_rate_min": 0.50,
        "fold_profit_factor_min": 1.10,
        "fold_expectancy_r_min": 0.05,
        "minimum_pass_fraction": 0.67,
    }
    for key, floor in wf_minimums.items():
        value = _as_finite_number(wf_cfg.get(key), label=f"validation.walk_forward.{key}")
        if value < floor:
            raise ConfigurationError(f"validation walk-forward {key} cannot be below {floor}")
    for key in ("train_fraction", "test_fraction", "step_fraction"):
        value = _as_finite_number(wf_cfg.get(key), label=f"validation.walk_forward.{key}")
        if not 0 < value <= 1:
            raise ConfigurationError(f"validation walk-forward {key} must be in (0,1]")
    if float(wf_cfg["train_fraction"]) + float(wf_cfg["test_fraction"]) > 1:
        raise ConfigurationError("validation walk-forward train+test fractions cannot exceed 1")

    stress_cfg = validation.get("stress_acceptance", {})
    if not isinstance(stress_cfg, Mapping):
        raise ConfigurationError("validation.stress_acceptance must be a mapping")
    stress_floors = {
        "win_rate_min": 0.50,
        "profit_factor_min": 1.10,
        "expectancy_r_min": 0.05,
    }
    for key, floor in stress_floors.items():
        value = _as_finite_number(stress_cfg.get(key), label=f"validation.stress_acceptance.{key}")
        if value < floor:
            raise ConfigurationError(f"validation stress {key} cannot be below {floor}")

    mc_cfg = validation.get("monte_carlo", {})
    if not isinstance(mc_cfg, Mapping):
        raise ConfigurationError("validation.monte_carlo must be a mapping")
    simulations = _as_finite_number(mc_cfg.get("simulations"), label="validation.monte_carlo.simulations")
    seed = _as_finite_number(mc_cfg.get("seed"), label="validation.monte_carlo.seed")
    dd_limit = _as_finite_number(
        mc_cfg.get("max_drawdown_r_p95_limit"),
        label="validation.monte_carlo.max_drawdown_r_p95_limit",
    )
    streak_limit = _as_finite_number(
        mc_cfg.get("losing_streak_p95_limit"),
        label="validation.monte_carlo.losing_streak_p95_limit",
    )
    block_size = _as_finite_number(
        mc_cfg.get("block_size"),
        label="validation.monte_carlo.block_size",
    )
    if not simulations.is_integer() or not 500 <= simulations <= 10000:
        raise ConfigurationError("Monte Carlo simulations must be an integer in [500,10000]")
    if not seed.is_integer():
        raise ConfigurationError("Monte Carlo seed must be an integer")
    if not block_size.is_integer() or not 2 <= block_size <= 20:
        raise ConfigurationError("Monte Carlo block size must be an integer in [2,20]")
    if not 0 < dd_limit <= 12:
        raise ConfigurationError("Monte Carlo p95 drawdown limit cannot exceed 12R")
    if not streak_limit.is_integer() or not 1 <= streak_limit <= 8:
        raise ConfigurationError("Monte Carlo p95 losing-streak limit cannot exceed 8")

    regime_cfg = validation.get("regimes", {})
    if not isinstance(regime_cfg, Mapping):
        raise ConfigurationError("validation.regimes must be a mapping")
    if int(regime_cfg.get("minimum_trades_per_regime", 0)) < 30:
        raise ConfigurationError("minimum trades per regime cannot be below 30")
    if int(regime_cfg.get("minimum_eligible_regimes", 0)) < 2:
        raise ConfigurationError("at least two eligible regimes are required")
    if _as_finite_number(
        regime_cfg.get("minimum_expectancy_r"),
        label="validation.regimes.minimum_expectancy_r",
    ) < 0:
        raise ConfigurationError("regime minimum expectancy cannot be negative")
    if _as_finite_number(
        regime_cfg.get("minimum_profit_factor"),
        label="validation.regimes.minimum_profit_factor",
    ) < 1.0:
        raise ConfigurationError("regime minimum PF cannot be below 1.0")

    perturb_cfg = validation.get("parameter_perturbation", {})
    if not isinstance(perturb_cfg, Mapping):
        raise ConfigurationError("validation.parameter_perturbation must be a mapping")
    if int(perturb_cfg.get("minimum_variants", 0)) < 6:
        raise ConfigurationError("parameter perturbation requires at least six variants")
    canonical_variants = [
        "equal_tolerance_minus10",
        "equal_tolerance_plus10",
        "sl_buffer_minus10",
        "sl_buffer_plus10",
        "entry_zone_minus10",
        "entry_zone_plus10",
    ]
    if list(perturb_cfg.get("required_variants", [])) != canonical_variants:
        raise ConfigurationError("parameter perturbation variants must remain canonical")
    if _as_finite_number(
        perturb_cfg.get("profit_factor_min"),
        label="validation.parameter_perturbation.profit_factor_min",
    ) < 1.10:
        raise ConfigurationError("perturbation PF gate cannot be below 1.10")
    if _as_finite_number(
        perturb_cfg.get("expectancy_r_min"),
        label="validation.parameter_perturbation.expectancy_r_min",
    ) < 0.05:
        raise ConfigurationError("perturbation expectancy gate cannot be below 0.05R")
    if _as_finite_number(
        perturb_cfg.get("minimum_pass_fraction"),
        label="validation.parameter_perturbation.minimum_pass_fraction",
    ) < 0.80:
        raise ConfigurationError("perturbation pass fraction cannot be below 80%")

    perf_cfg = validation.get("performance_budget", {})
    if not isinstance(perf_cfg, Mapping):
        raise ConfigurationError("validation.performance_budget must be a mapping")
    if perf_cfg.get("research_validation_in_hot_path") is not False:
        raise ConfigurationError("research validation must remain outside hot path")
    top5_ms = _as_finite_number(
        perf_cfg.get("deep_scan_top5_target_ms"),
        label="validation.performance_budget.deep_scan_top5_target_ms",
    )
    per_pair_ms = _as_finite_number(
        perf_cfg.get("per_pair_mtf_target_ms"),
        label="validation.performance_budget.per_pair_mtf_target_ms",
    )
    revalidation_ms = _as_finite_number(
        perf_cfg.get("execution_revalidation_max_ms"),
        label="validation.performance_budget.execution_revalidation_max_ms",
    )
    if top5_ms > 250 or per_pair_ms > 50 or revalidation_ms > 500:
        raise ConfigurationError("v0.9 performance budget cannot be weakened")

    return ProjectConfig(
        tuple(pairs), timeframes, risk, scoring, sessions, macro, providers, strategy, validation
    )
