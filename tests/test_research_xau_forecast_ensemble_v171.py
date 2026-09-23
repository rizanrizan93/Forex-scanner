from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import sin

from fx_scanner.models import Bar
from fx_scanner.research_xau_forecast_ensemble_v171 import (
    build_forecast_ensemble,
    empirical_conditional_probability,
    fisher_acd_session_path,
    parse_cftc_gold_cot,
)


def _bars(count: int = 12000) -> tuple[Bar, ...]:
    end = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    start = end - timedelta(minutes=15 * (count - 1))
    out = []
    for i in range(count):
        center = 4000.0 + i * 0.01 + 3.0 * sin(i / 20.0)
        open_ = center - 0.15
        close = center + 0.15
        out.append(
            Bar(
                symbol="XAUUSD",
                timeframe="M15",
                timestamp=start + timedelta(minutes=15 * i),
                open=open_,
                high=max(open_, close) + 0.50,
                low=min(open_, close) - 0.50,
                close=close,
                tick_count=100,
                spread_avg=0.20,
                spread_max=0.30,
            )
        )
    return tuple(out)


def test_empirical_conditional_probability_is_causal_and_available():
    result = empirical_conditional_probability(_bars())
    assert result["available"] is True
    assert result["method"] == "RASCHKE_STYLE_EMPIRICAL_CONDITIONAL_V1"
    assert result["attribution"] == "INSPIRED_NOT_CANONICAL_RULE"
    assert result["matches"] >= 40
    assert set(result["horizons"]) == {"1h", "4h", "8h"}
    assert 0.0 < result["horizons"]["4h"]["p_up"] < 1.0
    assert 0.0 < result["horizons"]["4h"]["p_down"] < 1.0


def test_fisher_acd_is_explicitly_adapted_shadow_framework():
    result = fisher_acd_session_path(_bars())
    assert result["available"] is True
    assert result["method"] == "FISHER_ACD_INSPIRED_M15_V1"
    assert result["attribution"] == "PUBLIC_FRAMEWORK_ADAPTED_PARAMETERS"
    assert result["parameter_contract"]["execution_influence"] is False
    assert result["levels"]["a_up"] > result["levels"]["or_high"]
    assert result["levels"]["c_up"] > result["levels"]["a_up"]
    assert result["levels"]["a_down"] < result["levels"]["or_low"]
    assert result["levels"]["c_down"] < result["levels"]["a_down"]


def test_parse_cftc_gold_managed_money_block():
    text = """
GOLD - COMMODITY EXCHANGE INC. Code-088691
Disaggregated Commitments of Traders - Futures Only, September 15, 2026
All  :   400,000:    15,000 30,000 20,000 200,000 30,000 140,000 10,000 18,000 80,000 20,000 10,000: 50,000 20,000
Changes in Commitments from: September 08, 2026
     :    10,000:       100 -200 300 400 500 5,000 -2,000 100 200 300 400: 500 600
"""
    result = parse_cftc_gold_cot(text)
    assert result["available"] is True
    assert result["managed_money_long"] == 140000
    assert result["managed_money_short"] == 10000
    assert result["managed_money_net"] == 130000
    assert result["weekly_change_long"] == 5000
    assert result["weekly_change_short"] == -2000
    assert result["weekly_change_net"] == 7000
    assert result["direction"] == "LONG"


def test_ensemble_reports_scenarios_without_execution_authority():
    result = build_forecast_ensemble(
        afic={
            "available": True,
            "direction": "LONG",
            "grade": "A",
            "state": "APPROACHING_ZONE",
            "path": {"first_leg": "SHORT", "continuation": "LONG"},
            "invalidation": 4300.0,
        },
        expected_move={
            "available": True,
            "horizons": {"4h": {"levels": {"up_q75": 4380.0, "down_q75": 4320.0}}},
        },
        conditional={
            "available": True,
            "direction": "LONG",
            "direction_score": 0.30,
        },
        acd={
            "available": True,
            "direction": "LONG",
            "direction_score": 0.55,
        },
        cot={
            "available": True,
            "direction": "SHORT",
            "direction_score": -0.35,
        },
    )
    assert result["primary_scenario"]["direction"] == "LONG"
    assert result["alternative_scenario"]["component_conflict"] is True
    assert result["invalidation"] == 4300.0
    assert 0.0 < result["confidence"] <= 0.90
    assert result["execution_influence"] is False
    assert result["decision"]["promotion"] is False


def test_invalidated_afic_forces_wait_remap_even_if_priors_are_bullish():
    result = build_forecast_ensemble(
        afic={
            "available": True,
            "direction": "LONG",
            "grade": "B",
            "state": "INVALIDATED_AFTER_TOUCH_REMAP_DUE",
            "path": {"first_leg": "SHORT", "continuation": "LONG"},
            "invalidation": 4300.0,
        },
        expected_move={"available": True},
        conditional={
            "available": True,
            "direction": "LONG",
            "direction_score": 0.60,
        },
        acd={
            "available": True,
            "direction": "LONG",
            "direction_score": 0.55,
        },
        cot={
            "available": True,
            "direction": "LONG",
            "direction_score": 0.35,
        },
    )
    assert result["primary_scenario"]["direction"] == "WAIT_REMAP"
    assert "PENDING_H4_REMAP" in result["alternative_scenario"]["type"]
    assert result["execution_influence"] is False


def test_streamlit_contains_live_ensemble_contract():
    text = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "streamlit_app.py"
    ).read_text()
    assert "Forecast Ensemble V171" in text
    assert "Primary scenario" in text
    assert "Alternative" in text
    assert "Invalidation" in text
    assert "ctrader_xau_forecast_ensemble_v171" in text
    assert "does not alter AFIC Grade-A/B execution authority" in text


def test_v171_runtime_refreshes_v170_from_same_live_history():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    text = (
        root / "src/fx_scanner/research_xau_forecast_ensemble_v171_runtime.py"
    ).read_text()
    assert "evaluate_expected_move_v170(bars)" in text
    assert "XAU_EXPECTED_MOVE_ENVELOPE_V170_LIVE_20K" in text
    assert "directional_vote" in text
    assert "reference_100k" in text


def test_missing_afic_zone_forces_wait_h4_map_but_preserves_directional_prior():
    result = build_forecast_ensemble(
        afic={
            "available": False,
            "direction": "NEUTRAL",
            "raw_direction": "SHORT",
            "grade": None,
            "state": "NO_MAP_ZONE",
            "path": {"first_leg": None, "reaction_zone": {"low": None, "high": None}, "continuation": None},
            "invalidation": None,
        },
        expected_move={"available": True},
        conditional={
            "available": True,
            "direction": "NEUTRAL",
            "direction_score": -0.03,
        },
        acd={
            "available": True,
            "direction": "SHORT",
            "direction_score": -0.55,
        },
        cot={
            "available": True,
            "direction": "SHORT",
            "direction_score": -0.35,
        },
    )
    assert result["primary_scenario"]["direction"] == "WAIT_H4_MAP"
    assert result["directional_prior"]["direction"] == "SHORT"
    assert result["alternative_scenario"]["type"] == "SHORT_PRIOR_PENDING_H4_MAP"
    assert result["confidence"] <= 0.25
    assert result["execution_influence"] is False


def test_runtime_marks_no_map_zone_afic_unavailable():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    text = (
        root / "src/fx_scanner/research_xau_forecast_ensemble_v171_runtime.py"
    ).read_text()
    assert '"NO_MAP_ZONE", "NO_ORIGIN_ZONE", "NO_DIRECTION"' in text
    assert "zone_valid" in text
    assert "available = direction in" in text


def test_streamlit_trade_preparation_makes_wait_zone_explicit():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    text = (root / "streamlit_app.py").read_text()
    assert "### Persiapan Trading (Trade Preparation)" in text
    assert "BELUM ADA ZONA ENTRY VALID — JANGAN PASANG ORDER" in text
    assert '"Zona reaksi"' in text
    assert '"Entry acuan"' in text
    assert '"Tindakan manual"' in text
    assert "WAIT M15 CONFIRM" in text
    assert "Do not reuse an older zone from Forecast State History" in text
