from __future__ import annotations

from fx_scanner.xau_afiq_walkforward_v402 import aggregate_reports, metrics_from_trades


def _trade(year: int, pnl: float, direction: str = "LONG"):
    return {
        "entry_at": f"{year}-06-01T00:00:00+00:00",
        "pnl_price": pnl,
        "direction": direction,
    }


def test_metrics_uses_fixed_price_profit_factor():
    metrics = metrics_from_trades([_trade(2025, 2.0), _trade(2025, -1.0)])
    assert metrics["fixed_price_pf"] == 2.0
    assert metrics["expectancy_price"] == 0.5
    assert metrics["cost_stress"]["cost_0.50"]["fixed_price_pf"] == 1.0


def test_aggregate_recomputes_pf_from_trades_not_annual_pf_average():
    reports = [
        {"target_year": 2025, "variants": {"A": {"trades": [_trade(2025, 4.0), _trade(2025, -1.0)]}}},
        {"target_year": 2026, "variants": {"A": {"trades": [_trade(2026, 1.0), _trade(2026, -2.0)]}}},
    ]
    result = aggregate_reports(reports, [2025, 2026])
    metrics = result["variants"]["A"]["metrics"]
    assert metrics["fixed_price_pf"] == 5.0 / 3.0
    assert result["missing_years"] == []


def test_missing_year_blocks_completeness_gate():
    reports = [
        {"target_year": 2025, "variants": {"A": {"trades": [_trade(2025, 2.0), _trade(2025, -1.0)]}}},
    ]
    result = aggregate_reports(reports, [2025, 2026])
    assert result["missing_years"] == [2026]
    assert result["numeric_gates"]["A"]["all_expected_years_present"] is False
