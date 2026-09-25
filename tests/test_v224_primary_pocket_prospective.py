from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_scanner.demo_xau_v224_primary_pocket_prospective import (
    FORECAST_EVENT,
    _forecast_candidate,
    _index_events,
    evaluate_primary_outcome,
)
from fx_scanner.models import Bar

ROOT = Path(__file__).resolve().parents[1]


def _bar(ts: datetime, *, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=100,
        spread_avg=0.20,
        spread_max=0.30,
    )


def _source(*, price: float = 4300.0, direction: str = "SHORT") -> dict:
    return {
        "observed_at": "2026-09-25T12:40:00+00:00",
        "healthy": True,
        "details": {
            "code_version": "abc",
            "evaluation": {
                "direction": direction,
                "price_reference": price,
                "parent_context": {
                    "zone_id": "h1-parent",
                    "timeframe": "H1",
                    "low": 4290.0,
                    "high": 4320.0,
                    "atr_points": 16.0,
                    "freshness": "FRESH",
                    "research_score": 70.0,
                },
                "primary_cluster": {
                    "cluster_id": "V223_CLUSTER_03",
                    "direction": direction,
                    "role": "ACTIVE_WATCH_CLUSTER",
                    "union_zone": {"low": 4303.0, "high": 4306.0},
                    "consensus_core": {},
                    "first_mapped_at": "2026-09-25T12:30:00+00:00",
                    "latest_mapped_at": "2026-09-25T12:35:00+00:00",
                    "post_map_touch_member_count": 0,
                    "selector_score_research": 75.0,
                    "mean_quality_research": 55.0,
                    "max_quality_research": 70.0,
                    "distance_atr": 0.18,
                    "members": [{"signal_key": "p1"}, {"signal_key": "p2"}],
                },
            },
        },
    }


def test_v224_enrolls_only_clean_pre_touch_primary_short() -> None:
    forecast = _forecast_candidate(_source(price=4300.0, direction="SHORT"))
    assert forecast
    assert forecast["forecast_timing"] == "PRIMARY_CLUSTER_PRE_TOUCH_NO_LEAKAGE"
    assert forecast["selected_zone"] == {
        "low": 4303.0,
        "high": 4306.0,
        "source": "UNION_ZONE",
        "proximal": 4303.0,
    }
    assert forecast["execution_authority"] is False


def test_v224_rejects_primary_when_price_is_already_inside_zone() -> None:
    assert _forecast_candidate(_source(price=4304.0, direction="SHORT")) == {}


def test_v224_rejects_wrong_side_short_after_price_already_passed_zone() -> None:
    assert _forecast_candidate(_source(price=4308.0, direction="SHORT")) == {}




def test_v224_parent_remap_does_not_create_new_physical_forecast_identity() -> None:
    first = _source(price=4300.0, direction="SHORT")
    second = _source(price=4300.0, direction="SHORT")
    second["details"]["evaluation"]["parent_context"]["zone_id"] = "different-h1-parent"
    a = _forecast_candidate(first)
    b = _forecast_candidate(second)
    assert a["signal_key"] == b["signal_key"]


def test_v224_index_collapses_legacy_parent_remap_duplicates_by_micro_wave() -> None:
    first = _forecast_candidate(_source(price=4300.0, direction="SHORT"))
    second = dict(first)
    second["signal_key"] = "legacy-parent-dependent-key"
    second["parent"] = dict(first["parent"]) | {"zone_id": "different-h1-parent"}
    rows = [
        {
            "event_type": FORECAST_EVENT,
            "signal_key": "legacy-a",
            "payload": first,
        },
        {
            "event_type": FORECAST_EVENT,
            "signal_key": "legacy-b",
            "payload": second,
        },
    ]
    forecasts, outcomes = _index_events(rows)
    assert len(forecasts) == 1
    assert outcomes == {}

def test_v224_reaction_requires_completed_bar_after_touch() -> None:
    forecast = _forecast_candidate(_source(price=4300.0, direction="SHORT"))
    touch = datetime(2026, 9, 25, 12, 45, tzinfo=UTC)
    bars = [
        # Touch bar itself trades far below the 0.50 ATR target intrabar;
        # that must not count because sequence inside this bar is unknown.
        _bar(touch, o=4301.0, h=4304.0, l=4290.0, c=4302.0),
        _bar(touch + timedelta(minutes=5), o=4302.0, h=4302.5, l=4296.0, c=4298.0),
    ]
    result = evaluate_primary_outcome(
        bars,
        forecast=forecast,
        now=touch + timedelta(minutes=15),
    )
    assert result["status"] == "PENDING_REACTION"
    assert result["rungs"]["0.50"]["hit"] is False


def test_v224_short_half_atr_hit_on_later_completed_m5() -> None:
    forecast = _forecast_candidate(_source(price=4300.0, direction="SHORT"))
    touch = datetime(2026, 9, 25, 12, 45, tzinfo=UTC)
    bars = [
        _bar(touch, o=4301.0, h=4304.0, l=4300.5, c=4303.0),
        _bar(touch + timedelta(minutes=5), o=4303.0, h=4303.5, l=4294.5, c=4296.0),
    ]
    result = evaluate_primary_outcome(
        bars,
        forecast=forecast,
        now=touch + timedelta(minutes=15),
    )
    assert result["status"] == "PENDING_REACTION"
    assert result["rungs"]["0.50"]["hit"] is True
    assert result["rungs"]["0.50"]["minutes_from_touch"] == 5.0


def test_v224_invalidation_wins_over_rung_on_same_later_bar() -> None:
    forecast = _forecast_candidate(_source(price=4300.0, direction="SHORT"))
    touch = datetime(2026, 9, 25, 12, 45, tzinfo=UTC)
    bars = [
        _bar(touch, o=4301.0, h=4304.0, l=4300.5, c=4303.0),
        # Low crosses reaction thresholds but close invalidates the H1 parent.
        _bar(touch + timedelta(minutes=5), o=4303.0, h=4322.0, l=4290.0, c=4321.0),
    ]
    result = evaluate_primary_outcome(
        bars,
        forecast=forecast,
        now=touch + timedelta(minutes=15),
    )
    assert result["status"] == "INVALIDATED_AFTER_TOUCH"
    assert result["invalidated"] is True
    assert all(not item["hit"] for item in result["rungs"].values())


def test_v224_workflow_dashboard_and_authority_contract() -> None:
    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    assert "python -m fx_scanner.demo_xau_v224_primary_pocket_prospective" in workflow
    assert workflow.index("demo_xau_v223_m5_pocket_cluster_selector") < workflow.index(
        "demo_xau_v224_primary_pocket_prospective"
    )

    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "V224 — Prospective Primary Pocket Accuracy" in dashboard
    assert "V224 tetap shadow-only" in dashboard
