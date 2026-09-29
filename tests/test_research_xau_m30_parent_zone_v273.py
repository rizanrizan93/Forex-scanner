from datetime import UTC, datetime
from pathlib import Path

from fx_scanner.demo_xau_supply_demand_atlas_v182 import SDZone
from fx_scanner.models import Bar
from fx_scanner.research_xau_m30_parent_zone_v273 import (
    ARTIFACT_CONTRACT,
    M30ParentEpisode,
    RESEARCH_VERSION,
    _depth_band_label,
    _depth_hazard,
    _overlap_bucket,
    _penetration_depth,
    _summary,
)


def _zone(direction: str) -> SDZone:
    ts = datetime(2026, 9, 29, tzinfo=UTC)
    return SDZone(
        zone_id=f"z-{direction}",
        timeframe="M30",
        zone_class="IMBALANCE",
        pattern="DBD" if direction == "SHORT" else "RBR",
        direction=direction,
        low=100.0,
        high=110.0,
        proximal=100.0 if direction == "SHORT" else 110.0,
        distal=110.0 if direction == "SHORT" else 100.0,
        available_at=ts,
        origin_at=ts,
        departure_at=ts,
        atr_points=5.0,
        base_bars=1,
        base_range_atr=2.0,
        departure_range_atr=1.2,
        departure_body_fraction=0.6,
        structural_bos=False,
    )


def _bar(*, low: float, high: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 9, 29, tzinfo=UTC),
        open=(low + high) / 2.0,
        high=high,
        low=low,
        close=(low + high) / 2.0,
        tick_count=100,
        spread_avg=0.2,
        spread_max=0.3,
    )


def _episode(*, depth: float, hold: bool) -> M30ParentEpisode:
    return M30ParentEpisode(
        zone_id=f"z-{depth}-{hold}",
        direction="SHORT",
        pattern="DBD",
        touch_at=datetime(2026, 9, 29, tzinfo=UTC),
        touch_ordinal=1,
        age_hours=1.0,
        session_context="OTHER_WIB",
        approach_state="APPROACHING",
        low=100.0,
        high=110.0,
        width=10.0,
        atr_points=5.0,
        departure_range_atr=1.2,
        departure_body_fraction=0.6,
        base_range_atr=1.0,
        parent_overlap_ratio=0.8,
        parent_overlap_bucket="HIGH_70_100",
        parent_timeframe="H1",
        parent_zone_id="parent",
        max_depth_before_outcome=depth,
        reversal_depth_band=_depth_band_label(depth) if hold else None,
        outcome_status="HOLD" if hold else "BREAK",
        label_hold=hold,
        bars_to_outcome=3,
        mfe_atr=0.6 if hold else 0.1,
        mae_atr=0.3 if hold else 1.1,
        hit_025_before_break=hold,
        hit_050_before_break=hold,
        hit_075_before_break=False,
        hit_100_before_break=False,
    )


def test_v273_contract_is_shadow_only() -> None:
    assert RESEARCH_VERSION == "XAU_M30_PARENT_ZONE_CALIBRATION_V273"
    assert ARTIFACT_CONTRACT.endswith("EVIDENCE_1")


def test_v273_overlap_bucket_contract() -> None:
    assert _overlap_bucket(0.0) == "NONE"
    assert _overlap_bucket(0.1) == "LOW_0_30"
    assert _overlap_bucket(0.3) == "MEDIUM_30_70"
    assert _overlap_bucket(0.7) == "HIGH_70_100"


def test_v273_penetration_depth_is_direction_aware() -> None:
    short = _zone("SHORT")
    long = _zone("LONG")
    assert round(_penetration_depth(short, _bar(low=99.0, high=102.5)), 4) == 0.25
    assert round(_penetration_depth(long, _bar(low=107.5, high=111.0)), 4) == 0.25


def test_v273_depth_hazard_is_sequential_not_plain_winrate() -> None:
    rows = (
        _episode(depth=0.05, hold=True),
        _episode(depth=0.15, hold=True),
        _episode(depth=0.85, hold=False),
        _episode(depth=1.00, hold=False),
    )
    hazard = _depth_hazard(rows)
    first = hazard[0]
    second = hazard[1]
    assert first["at_risk"] == 4
    assert first["reversals_050"] == 1
    assert first["hazard_050"] == 0.25
    assert second["at_risk"] == 3
    assert second["reversals_050"] == 1
    assert round(second["hazard_050"], 6) == round(1 / 3, 6)
    assert first["penetration_to_next"] == 0.75


def test_v273_summary_keeps_reaction_and_break_separate() -> None:
    rows = (
        _episode(depth=0.05, hold=True),
        _episode(depth=0.85, hold=False),
    )
    summary = _summary(rows)
    assert summary["n"] == 2
    assert summary["hold_050_rate"] == 0.5
    assert summary["break_rate"] == 0.5


def test_v273_workflow_is_research_only() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (
        root / ".github/workflows/research-xau-m30-parent-zone-v273.yml"
    ).read_text()
    runtime = (
        root / "src/fx_scanner/research_xau_m30_parent_zone_v273_runtime.py"
    ).read_text()
    assert "Run 100K-bar M30 parent-zone calibration" in workflow
    assert "execution_influence" in runtime
    assert '"SHADOW_ONLY"' in runtime
