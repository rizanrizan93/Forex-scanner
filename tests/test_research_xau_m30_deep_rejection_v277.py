from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_scanner.models import Bar
from fx_scanner.research_xau_m30_deep_rejection_v277 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    _confirmed_outcome,
)
from fx_scanner.xau_m30_deep_rejection_v277 import (
    CONTRACT,
    _bar_close_depth,
    _bar_penetration_depth,
    evaluate_m30_deep_rejection_v277,
)


def _bar(
    minute: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
        + timedelta(minutes=minute),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=100,
        spread_avg=0.2,
        spread_max=0.3,
    )


def _shadow(direction: str = "SHORT") -> dict:
    zone = {
        "zone_id": "m30-parent",
        "direction": direction,
        "low": 100.0,
        "high": 110.0,
        "available_at": "2026-09-29T12:00:00+00:00",
        "canonical_overlap_ratio": 0.82,
        "canonical_match_timeframe": "H1",
        "canonical_match_zone_id": "h1-parent",
    }
    return {
        "nearest_supply": zone if direction == "SHORT" else None,
        "nearest_demand": zone if direction == "LONG" else None,
    }


def test_v277_depth_math_is_direction_aware() -> None:
    short_bar = _bar(0, open_=101.0, high=108.0, low=100.0, close=104.0)
    assert _bar_penetration_depth(
        direction="SHORT", low=100.0, high=110.0, bar=short_bar
    ) == 0.8
    assert _bar_close_depth(
        direction="SHORT", low=100.0, high=110.0, bar=short_bar
    ) == 0.4

    long_bar = _bar(0, open_=109.0, high=110.0, low=102.0, close=106.0)
    assert _bar_penetration_depth(
        direction="LONG", low=100.0, high=110.0, bar=long_bar
    ) == 0.8
    assert _bar_close_depth(
        direction="LONG", low=100.0, high=110.0, bar=long_bar
    ) == 0.4


def test_v277_live_short_deep_rejection_requires_penetration_and_retreat() -> None:
    bars = (
        _bar(0, open_=99.5, high=101.0, low=99.0, close=100.5),
        _bar(5, open_=100.5, high=106.5, low=100.2, close=105.5),
        _bar(10, open_=105.5, high=108.2, low=103.0, close=107.0),
        _bar(15, open_=107.0, high=107.2, low=103.0, close=104.5),
    )
    out = evaluate_m30_deep_rejection_v277(
        m30_shadow=_shadow("SHORT"),
        m5_bars=bars,
        direction="SHORT",
        as_of=datetime(2026, 9, 29, 12, 21, tzinfo=UTC),
    )
    assert out["contract"] == CONTRACT
    assert out["available"] is True
    assert out["state"] == "DEEP_REJECTION_CONFIRMED"
    assert 0.81 < out["max_depth"] < 0.83
    assert out["latest_close_depth"] == 0.45
    assert out["confirmation_retreat"] > 0.35
    assert out["execution_authority"] is False


def test_v277_deep_touch_without_retreat_does_not_confirm() -> None:
    bars = (
        _bar(0, open_=100.0, high=106.5, low=99.8, close=105.8),
        _bar(5, open_=105.8, high=108.0, low=105.0, close=107.0),
    )
    out = evaluate_m30_deep_rejection_v277(
        m30_shadow=_shadow("SHORT"),
        m5_bars=bars,
        direction="SHORT",
        as_of=datetime(2026, 9, 29, 12, 11, tzinfo=UTC),
    )
    assert out["state"] == "DEEP_TOUCH_WAIT_REJECTION"


def test_v277_completed_close_beyond_distal_invalidates_parent() -> None:
    bars = (
        _bar(0, open_=100.0, high=108.0, low=99.5, close=107.0),
        _bar(5, open_=107.0, high=112.0, low=106.0, close=111.0),
    )
    out = evaluate_m30_deep_rejection_v277(
        m30_shadow=_shadow("SHORT"),
        m5_bars=bars,
        direction="SHORT",
        as_of=datetime(2026, 9, 29, 12, 11, tzinfo=UTC),
    )
    assert out["state"] == "PARENT_INVALIDATED"
    assert out["invalidated_at"] is not None


def test_v277_confirmed_entry_research_measures_post_confirm_reaction() -> None:
    rows = (
        _bar(0, open_=104.0, high=105.0, low=103.5, close=104.5),
        _bar(5, open_=104.5, high=104.7, low=101.0, close=101.5),
        _bar(10, open_=101.5, high=102.0, low=98.0, close=99.0),
    )
    result = _confirmed_outcome(
        rows,
        start_index=0,
        direction="SHORT",
        entry=104.5,
        distal=110.0,
        atr=5.0,
    )
    assert result["status"] == "HOLD"
    assert result["hold_050"] is True


def test_v277_research_and_dashboard_contract_are_shadow_only() -> None:
    assert RESEARCH_VERSION == "XAU_M30_DEEP_REJECTION_CALIBRATION_V277"
    assert ARTIFACT_CONTRACT.endswith("EVIDENCE_1")

    root = Path(__file__).resolve().parents[1]
    runtime = (
        root / "src/fx_scanner/research_xau_m30_deep_rejection_v277_runtime.py"
    ).read_text()
    dashboard = (root / "streamlit_app.py").read_text()
    atlas = (
        root / "src/fx_scanner/demo_xau_supply_demand_atlas_v182.py"
    ).read_text()
    workflow = (
        root / ".github/workflows/research-xau-m30-deep-rejection-v277.yml"
    ).read_text()

    assert '"SHADOW_ONLY"' in runtime
    assert "m30_deep_rejection_v277" in atlas
    assert "M30 deep-rejection" in dashboard
    assert "DEEP_REJECTION_CONFIRMED" in dashboard
    assert "Run 100K-bar near-edge vs deep-rejection calibration" in workflow
