from pathlib import Path
from shutil import copytree

import pytest
import yaml

from fx_scanner.config import load_project_config
from fx_scanner.exceptions import ConfigurationError


ROOT = Path(__file__).resolve().parents[1]


def copied_root(tmp_path: Path) -> Path:
    copytree(ROOT / "config", tmp_path / "config")
    return tmp_path


def read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, value) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def test_negative_scoring_weight_cannot_hide_inside_sum_100(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "scoring.yaml"
    data = read_yaml(path)
    data["pair_opportunity"]["macro"] = -5
    data["pair_opportunity"]["currency_strength"] = 65
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="must be positive"):
        load_project_config(root)


def test_risk_mode_cannot_leave_research_only(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "risk.yaml"
    data = read_yaml(path)
    data["mode"] = "AUTO"
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="RESEARCH_ONLY"):
        load_project_config(root)


def test_acceptance_requirements_cannot_be_disabled(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "risk.yaml"
    data = read_yaml(path)
    data["acceptance"]["demo_forward_required"] = False
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="demo_forward_required"):
        load_project_config(root)


def test_canonical_hard_guard_cannot_be_removed(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "scoring.yaml"
    data = read_yaml(path)
    data["hard_guards"].remove("NEWS_BLOCK")
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="hard_guards"):
        load_project_config(root)


def test_acceptance_thresholds_cannot_be_watered_down(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "risk.yaml"
    data = read_yaml(path)
    data["acceptance"]["aggregate_oos_trades_min"] = 249
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="250"):
        load_project_config(root)


def test_provider_source_cannot_be_downgraded_from_https(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "providers.yaml"
    data = read_yaml(path)
    data["sources"]["ECB_DATA_PORTAL"]["base_url"] = "http://data.ecb.europa.eu/service/data"
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="HTTPS host contract"):
        load_project_config(root)


def test_provider_host_allowlist_must_match_url(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "providers.yaml"
    data = read_yaml(path)
    data["sources"]["BANK_OF_CANADA_VALET"]["allowed_host"] = "evil.example"
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="HTTPS host contract"):
        load_project_config(root)


def test_provider_negative_cache_ttl_cannot_be_zero(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "providers.yaml"
    data = read_yaml(path)
    data["cache"]["negative_ttl_seconds"] = 0
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="negative_ttl_seconds"):
        load_project_config(root)


def test_v08_top5_selection_cannot_be_expanded(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "strategy.yaml"
    data = read_yaml(path)
    data["selection"]["deep_analysis_top"] = 8
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="deep_analysis_top"):
        load_project_config(root)


def test_v08_rr_gate_cannot_be_weakened(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "strategy.yaml"
    data = read_yaml(path)
    data["trade_plan"]["minimum_tp2_rr"] = 1.2
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="RR contract"):
        load_project_config(root)


def test_v08_chase_block_cannot_exceed_half_atr(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "strategy.yaml"
    data = read_yaml(path)
    data["trade_plan"]["chase_block_atr"] = 0.75
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="chase thresholds"):
        load_project_config(root)


def test_v08_required_setup_confirmation_cannot_be_disabled(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "strategy.yaml"
    data = read_yaml(path)
    data["setup"]["liquidity_sweep_reversal"]["require_m5_displacement"] = False
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="requirements cannot be disabled"):
        load_project_config(root)


def test_v08_minimum_bars_cannot_be_reduced(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "strategy.yaml"
    data = read_yaml(path)
    data["mtf"]["minimum_bars"]["M5"] = 20
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="M5 cannot be below 60"):
        load_project_config(root)


def test_v08_bar_freshness_window_cannot_be_weakened(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "strategy.yaml"
    data = read_yaml(path)
    data["mtf"]["max_bar_age_seconds"]["M5"] = 3600
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="max_bar_age_seconds.M5"):
        load_project_config(root)


def test_v08_fred_endpoint_cannot_be_redirected_to_other_path(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "providers.yaml"
    data = read_yaml(path)
    data["sources"]["FEDERAL_RESERVE_FRED"]["base_url"] = "https://fred.stlouisfed.org/evil.csv"
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="canonical endpoint"):
        load_project_config(root)


def test_v08_rba_endpoint_cannot_be_redirected_to_other_host(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "providers.yaml"
    data = read_yaml(path)
    data["sources"]["RBA_CASH_RATE"]["allowed_host"] = "example.com"
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="HTTPS host contract"):
        load_project_config(root)


def test_v09_oos_split_cannot_be_changed_after_results(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "validation.yaml"
    data = read_yaml(path)
    data["dataset_split"]["train_fraction"] = 0.70
    data["dataset_split"]["validation_fraction"] = 0.10
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="60/20/20"):
        load_project_config(root)


def test_v09_cost_stress_cannot_be_weakened(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "validation.yaml"
    data = read_yaml(path)
    data["costs"]["stress_spread_multiplier"] = 1.0
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="cannot be below 1.25"):
        load_project_config(root)


def test_v09_validation_cannot_enter_hot_path(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "validation.yaml"
    data = read_yaml(path)
    data["performance_budget"]["research_validation_in_hot_path"] = True
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="outside hot path"):
        load_project_config(root)


def test_v09_canonical_perturbation_set_cannot_be_cherry_picked(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "validation.yaml"
    data = read_yaml(path)
    data["parameter_perturbation"]["required_variants"].pop()
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="must remain canonical"):
        load_project_config(root)


def test_v09_point_in_time_gate_cannot_be_disabled(tmp_path):
    root = copied_root(tmp_path)
    path = root / "config" / "risk.yaml"
    data = read_yaml(path)
    data["acceptance"]["point_in_time_required"] = False
    write_yaml(path, data)
    with pytest.raises(ConfigurationError, match="point_in_time_required"):
        load_project_config(root)
