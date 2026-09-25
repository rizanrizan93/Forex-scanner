from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_scanner.demo_xau_v227_depth_map_prospective import (
    _forecast_candidate,
    _stable_signal_key,
    evaluate_outcome,
)
from fx_scanner.models import Bar

ROOT = Path(__file__).resolve().parents[1]


def _bar(ts: datetime, *, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M1",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=100,
        spread_avg=0.2,
        spread_max=0.3,
    )


def _source(
    *,
    direction: str = "LONG",
    price: float = 111.0,
    prior: str = "XAU_ZONE_REVERSAL_DEPTH_V225_2",
    touches: int = 0,
) -> dict:
    low, high = 100.0, 110.0
    zone = {
        "zone_id": "h4-zone",
        "timeframe": "H4",
        "direction": direction,
        "low": low,
        "high": high,
        "proximal": 108.0 if direction == "LONG" else 102.0,
        "distal": low if direction == "LONG" else high,
        "atr_points": 10.0,
        "available_at": "2026-09-25T10:00:00+00:00",
        "lifecycle": {
            "active": True,
            "touch_count": touches,
            "freshness": "FRESH" if touches == 0 else "FIRST_TEST",
        },
    }
    h4 = {
        "zone": zone,
        "hotspot": {"low": 109.0, "high": 110.0, "lower_depth": 0.0, "upper_depth": 0.1}
        if direction == "LONG"
        else {"low": 100.0, "high": 101.0, "lower_depth": 0.0, "upper_depth": 0.1},
        "quantiles": {
            "p25": {"depth": 0.07, "price": 109.3 if direction == "LONG" else 100.7},
            "median": {"depth": 0.20, "price": 108.0 if direction == "LONG" else 102.0},
            "p75": {"depth": 0.44, "price": 105.6 if direction == "LONG" else 104.4},
        },
        "applicability": {
            "state": "HIGH_FIRST_TOUCH_PRIOR" if touches == 0 else "MEDIUM_POST_FIRST_TOUCH_CONTEXT"
        },
        "historical_profile": {"touches": 1000, "hold_rate": 0.72},
    }
    h1 = {
        "zone": {"zone_id": "h1", "direction": direction, "low": 104.0, "high": 109.0},
        "nested_locator": {
            "envelope": {"low": 105.0, "high": 108.5},
            "median": {"depth": 0.37, "price": 107.0},
        },
        "applicability": {"state": "HIGH_FIRST_TOUCH_PRIOR"},
    }
    m15 = {
        "zone": {"zone_id": "m15", "direction": direction, "low": 105.0, "high": 108.0},
        "nested_locator": {
            "envelope": {"low": 105.5, "high": 107.5},
            "median": {"depth": 0.46, "price": 106.3},
        },
        "applicability": {"state": "HIGH_FIRST_TOUCH_PRIOR"},
    }
    side = {"h4": h4, "h1": h1, "m15": m15}
    return {
        "observed_at": "2026-09-25T12:00:00+00:00",
        "healthy": True,
        "details": {
            "code_version": "v226sha",
            "evaluation": {
                "state": "RIZAN_DEPTH_MAP_AVAILABLE",
                "price_reference": price,
                "historical_prior": {
                    "research_version": prior,
                    "year_count": 15,
                    "episode_count": 68094,
                },
                direction.lower(): side,
            },
        },
    }


def test_v227_enrolls_fresh_long_h4_only_before_first_touch() -> None:
    candidate = _forecast_candidate(_source(), direction="LONG")
    assert candidate
    assert candidate["forecast_timing"] == "FRESH_H4_PRE_TOUCH_CORRECT_SIDE"
    assert candidate["parent"]["zone_id"] == "h4-zone"
    assert candidate["execution_authority"] is False


def test_v227_rejects_old_prior_reuse_and_wrong_approach_side() -> None:
    assert _forecast_candidate(
        _source(prior="XAU_ZONE_REVERSAL_DEPTH_V225_1"),
        direction="LONG",
    ) == {}
    assert _forecast_candidate(_source(touches=1), direction="LONG") == {}
    assert _forecast_candidate(_source(price=105.0), direction="LONG") == {}


def test_v227_signal_identity_is_physical_h4_zone() -> None:
    assert _stable_signal_key(direction="LONG", zone_id="same") == _stable_signal_key(
        direction="LONG", zone_id="same"
    )
    assert _stable_signal_key(direction="LONG", zone_id="same") != _stable_signal_key(
        direction="SHORT", zone_id="same"
    )


def test_v227_touch_bar_cannot_prove_reaction() -> None:
    forecast = _forecast_candidate(_source(), direction="LONG")
    touch = datetime(2026, 9, 25, 12, 5, tzinfo=UTC)
    bars = [
        # Touches demand and trades through the reaction target intrabar. Since
        # order inside this M1 bar is unknown, it must not prove reaction.
        _bar(touch, o=111.0, h=115.0, l=109.5, c=110.5),
    ]
    result = evaluate_outcome(
        bars,
        forecast=forecast,
        now=touch + timedelta(minutes=2),
    )
    assert result["status"] == "PENDING_REACTION"
    assert result["reaction_hit_025"] is False
    assert result["reaction_hit_050"] is False
    assert result["reaction_hit_075"] is False
    assert result["reaction_hit_100"] is False


def test_v227_scores_turning_depth_and_all_locator_captures() -> None:
    forecast = _forecast_candidate(_source(), direction="LONG")
    touch = datetime(2026, 9, 25, 12, 5, tzinfo=UTC)
    bars = [
        _bar(touch, o=111.0, h=111.2, l=107.0, c=108.0),
        # H4 0.50 target is proximal 108 + 5 = 113. This bar's adverse low
        # is excluded from the 0.50 turning-depth estimate.
        _bar(touch + timedelta(minutes=1), o=108.0, h=114.0, l=103.0, c=113.0),
        # 1.00 ATR target = 118; reaching it resolves the full ladder early.
        _bar(touch + timedelta(minutes=2), o=113.0, h=119.0, l=107.5, c=118.5),
    ]
    result = evaluate_outcome(
        bars,
        forecast=forecast,
        now=touch + timedelta(minutes=4),
    )
    assert result["status"] == "REACTION_100"
    assert result["reaction_hit_025"] is True
    assert result["reaction_hit_050"] is True
    assert result["reaction_hit_075"] is True
    assert result["reaction_hit_100"] is True
    assert result["turning_price"] == 107.0
    assert abs(result["turning_depth"] - 0.30) < 1e-12
    assert result["h4_hotspot_capture"] is False
    assert result["h4_iqr_capture"] is True
    assert result["h1_locator_capture"] is True
    assert result["m15_locator_capture"] is True


def test_v227_invalidation_wins_over_target_on_same_future_bar() -> None:
    forecast = _forecast_candidate(_source(), direction="LONG")
    touch = datetime(2026, 9, 25, 12, 5, tzinfo=UTC)
    bars = [
        _bar(touch, o=111.0, h=111.2, l=109.5, c=110.0),
        # Same bar prints above target but closes below distal.
        _bar(touch + timedelta(minutes=1), o=110.0, h=114.0, l=98.0, c=99.0),
    ]
    result = evaluate_outcome(
        bars,
        forecast=forecast,
        now=touch + timedelta(minutes=3),
    )
    assert result["status"] == "INVALIDATED_AFTER_TOUCH"
    assert result["reaction_hit_025"] is False
    assert result["reaction_hit_050"] is False
    assert result["reaction_hit_075"] is False
    assert result["reaction_hit_100"] is False
    assert result["invalidated"] is True


def test_v227_short_reaction_ladder_is_symmetric() -> None:
    forecast = _forecast_candidate(
        _source(direction="SHORT", price=99.0),
        direction="SHORT",
    )
    touch = datetime(2026, 9, 25, 12, 5, tzinfo=UTC)
    bars = [
        _bar(touch, o=99.0, h=103.0, l=98.0, c=102.0),
        # SHORT 0.50 ATR target = proximal 102 - 5 = 97.
        _bar(touch + timedelta(minutes=1), o=102.0, h=107.0, l=96.0, c=97.0),
        # SHORT 1.00 ATR target = 92.
        _bar(touch + timedelta(minutes=2), o=97.0, h=105.0, l=91.0, c=92.0),
    ]
    result = evaluate_outcome(
        bars,
        forecast=forecast,
        now=touch + timedelta(minutes=4),
    )
    assert result["status"] == "REACTION_100"
    assert result["reaction_hit_025"] is True
    assert result["reaction_hit_050"] is True
    assert result["reaction_hit_075"] is True
    assert result["reaction_hit_100"] is True
    assert result["turning_price"] == 103.0
    assert abs(result["turning_depth"] - 0.30) < 1e-12


def test_v227_resolves_partial_ladder_at_fixed_16h_horizon() -> None:
    forecast = _forecast_candidate(_source(), direction="LONG")
    touch = datetime(2026, 9, 25, 12, 5, tzinfo=UTC)
    bars = [
        _bar(touch, o=111.0, h=111.2, l=107.0, c=108.0),
        # Reaches 0.25 and 0.50 ATR, but not 0.75 ATR (115.5) or 1.00 ATR (118).
        _bar(touch + timedelta(minutes=1), o=108.0, h=114.0, l=106.0, c=113.0),
    ]
    result = evaluate_outcome(
        bars,
        forecast=forecast,
        now=touch + timedelta(hours=16, minutes=2),
    )
    assert result["status"] == "REACTION_050_16H"
    assert result["reaction_hit_025"] is True
    assert result["reaction_hit_050"] is True
    assert result["reaction_hit_075"] is False
    assert result["reaction_hit_100"] is False
    assert result["turning_price"] == 107.0
    assert abs(result["turning_depth"] - 0.30) < 1e-12


def test_v227_workflow_and_dashboard_remain_shadow_only() -> None:
    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    assert "python -m fx_scanner.demo_xau_v227_depth_map_prospective" in workflow
    assert workflow.index("demo_xau_v226_rizan_depth_map") < workflow.index(
        "demo_xau_v227_depth_map_prospective"
    )

    source = (ROOT / "src/fx_scanner/demo_xau_v227_depth_map_prospective.py").read_text()
    assert '"execution_influence": False' in source
    assert '"execution_authority": False' in source
    assert '"promotion_authority": False' in source
    assert 'RESEARCH_VERSION = "XAU_RIZAN_DEPTH_MAP_PROSPECTIVE_V227_1"' in source
    assert 'REACTION_RUNGS = (("025", 0.25), ("050", 0.50), ("075", 0.75), ("100", 1.00))' in source

    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "V227 — Prospective RIZAN Depth Calibration" in dashboard
    assert "V227 tetap shadow-only" in dashboard
