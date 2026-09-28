from datetime import UTC, datetime
from pathlib import Path

import fx_scanner.xau_standalone_mode_v253 as standalone


def test_frozen_v225_2_prior_is_complete():
    root = Path(__file__).resolve().parents[1]
    prior = standalone.load_frozen_depth_prior(root)
    assert prior["research_version"] == "XAU_ZONE_REVERSAL_DEPTH_V225_2"
    assert int(prior["year_count"]) >= 15
    assert int(prior["episode_count"]) >= 68000
    assert {"2012_2018", "2019_2024", "2025_2026"}.issubset(prior["eras"])


def test_standalone_state_is_manual_only(monkeypatch):
    monkeypatch.setattr(
        standalone,
        "evaluate_htf_regime_research",
        lambda _bars: {"current": {"strategic_bias": "LONG"}},
    )
    monkeypatch.setattr(
        standalone,
        "evaluate_supply_demand_atlas",
        lambda _bars, as_of, strategic_bias: {"path_map": {}, "as_of": as_of.isoformat()},
    )
    monkeypatch.setattr(
        standalone,
        "evaluate_bidirectional_m5_path",
        lambda _bars, path_map, as_of, previous_projection=None: {
            "current_leg": {"direction": "LONG"}
        },
    )
    monkeypatch.setattr(
        standalone,
        "build_depth_map",
        lambda atlas_evaluation, history_details: {"focus_direction": "LONG"},
    )
    monkeypatch.setattr(
        standalone,
        "evaluate_pressure_transition",
        lambda **_kwargs: {"state": "BALANCED_ABSORPTION"},
    )
    monkeypatch.setattr(
        standalone,
        "build_dynamic_depth_hazard",
        lambda **_kwargs: {"state": "DYNAMIC_DEPTH_HAZARD_AVAILABLE", "action": "ENTRY_WINDOW"},
    )
    monkeypatch.setattr(
        standalone,
        "build_canonical_xau_decision",
        lambda **_kwargs: {"state": "CANONICAL_PLAN_READY", "direction": "LONG"},
    )

    now = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
    out = standalone.build_standalone_xau_state(
        m15_bars=(),
        m5_bars=(),
        bid=4260.0,
        ask=4260.5,
        quote_timestamp=now,
        dom_analysis={"state": "BALANCED_OR_CONTESTED", "window_end": now.isoformat()},
        previous_dom_analysis={},
        history_details={"research_version": "XAU_ZONE_REVERSAL_DEPTH_V225_2"},
        as_of=now,
    )
    assert out["mode"] == "CTRADER_DIRECT_NO_SUPABASE"
    assert out["canonical"]["direction"] == "LONG"
    assert out["safety"]["manual_analysis_only"] is True
    assert out["safety"]["execution_authority"] is False
    assert out["safety"]["demo_auto_execution_enabled"] is False
    assert out["safety"]["live_execution_enabled"] is False
