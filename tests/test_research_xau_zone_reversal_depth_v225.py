from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from fx_scanner.demo_xau_supply_demand_atlas_v182 import SDZone
from fx_scanner.research_xau_zone_reversal_depth_v225 import (
    DepthEpisode,
    _detect_m15_zones,
    causal_superseded_at,
    depth_summary,
    evaluate_first_touch,
    normalized_depth,
    normalized_internal_depth,
)

ROOT = Path(__file__).resolve().parents[1]


def _zone(
    *,
    direction: str = "LONG",
    low: float = 4244.0,
    high: float = 4275.0,
    proximal: float | None = None,
    distal: float | None = None,
) -> SDZone:
    if proximal is None:
        proximal = high if direction == "LONG" else low
    if distal is None:
        distal = low if direction == "LONG" else high
    return SDZone(
        zone_id="z",
        timeframe="H4",
        zone_class="IMBALANCE",
        pattern="DBR" if direction == "LONG" else "RBD",
        direction=direction,
        low=low,
        high=high,
        proximal=proximal,
        distal=distal,
        available_at=datetime(2026, 9, 25, 0, tzinfo=UTC),
        origin_at=datetime(2026, 9, 24, 20, tzinfo=UTC),
        departure_at=datetime(2026, 9, 25, 0, tzinfo=UTC),
        atr_points=20.0,
        base_bars=1,
        base_range_atr=(high - low) / 20.0,
        departure_range_atr=1.5,
        departure_body_fraction=0.7,
        structural_bos=False,
    )


def test_v225_user_example_depth_is_67_7_percent() -> None:
    zone = _zone()
    depth = normalized_depth(zone, 4254.0)
    assert abs(depth - ((4275.0 - 4254.0) / 31.0)) < 1e-12
    assert round(depth * 100, 1) == 67.7


def test_v225_short_depth_is_measured_across_full_supply_range() -> None:
    zone = _zone(
        direction="SHORT",
        low=4300.0,
        high=4320.0,
        proximal=4305.0,
        distal=4320.0,
    )
    assert normalized_depth(zone, 4310.0) == 0.5


def test_v225_internal_depth_is_separate_from_full_zone_depth() -> None:
    zone = _zone(
        direction="SHORT",
        low=4300.0,
        high=4320.0,
        proximal=4305.0,
        distal=4320.0,
    )
    assert normalized_depth(zone, 4310.0) == 0.5
    assert abs(normalized_internal_depth(zone, 4310.0) - (5.0 / 15.0)) < 1e-12


def test_v225_full_demand_example_uses_outer_range_even_when_body_edge_differs() -> None:
    zone = _zone(
        direction="LONG",
        low=4244.0,
        high=4275.0,
        proximal=4269.0,
        distal=4244.0,
    )
    assert round(normalized_depth(zone, 4254.0) * 100, 1) == 67.7
    assert round(normalized_internal_depth(zone, 4254.0) * 100, 1) == 60.0






def test_v2252_m15_zone_becomes_available_only_after_departure_candle_closes() -> None:
    start = datetime(2026, 9, 25, 0, tzinfo=UTC)
    rows = []
    for i in range(19):
        t = start + timedelta(minutes=15 * i)
        rows.append(
            {
                "time": t,
                "open": 100.0,
                "high": 100.4,
                "low": 99.6,
                "close": 100.0 if i % 2 == 0 else 99.9,
            }
        )
    departure_open = start + timedelta(minutes=15 * 19)
    rows.append(
        {
            "time": departure_open,
            "open": 100.0,
            "high": 106.0,
            "low": 99.8,
            "close": 105.5,
        }
    )
    zones = _detect_m15_zones(pd.DataFrame(rows))
    assert zones
    latest = zones[-1]
    assert latest.available_at == departure_open + timedelta(minutes=15)
    assert latest.departure_at == latest.available_at
    assert latest.available_at > departure_open


def test_v2252_m15_departure_candle_cannot_be_counted_as_post_map_touch() -> None:
    start = datetime(2026, 9, 25, 0, tzinfo=UTC)
    rows = []
    for i in range(19):
        t = start + timedelta(minutes=15 * i)
        rows.append(
            {
                "time": t,
                "open": 100.0,
                "high": 100.4,
                "low": 99.6,
                "close": 100.0 if i % 2 == 0 else 99.9,
            }
        )
    departure_open = start + timedelta(minutes=15 * 19)
    rows.append(
        {
            "time": departure_open,
            "open": 100.0,
            "high": 106.0,
            "low": 99.8,
            "close": 105.5,
        }
    )
    zone = _detect_m15_zones(pd.DataFrame(rows))[-1]

    m1 = pd.DataFrame(
        [
            {
                "timestamp": departure_open + timedelta(minutes=10),
                "open": 100.0,
                "high": float(zone.high),
                "low": float(zone.low),
                "close": float(zone.proximal),
            },
            {
                "timestamp": zone.available_at,
                "open": float(zone.proximal),
                "high": float(zone.high),
                "low": float(zone.low),
                "close": float(zone.proximal),
            },
            {
                "timestamp": zone.available_at + timedelta(minutes=1),
                "open": float(zone.proximal),
                "high": float(zone.proximal) + float(zone.atr_points),
                "low": float(zone.proximal),
                "close": float(zone.proximal) + 0.75 * float(zone.atr_points),
            },
        ]
    )
    episode = evaluate_first_touch(m1, zone=zone)
    assert episode is not None
    assert episode.touch_at == zone.available_at

def test_v225_causal_supersession_does_not_erase_older_zone_before_new_one_exists() -> None:
    old = _zone(low=100.0, high=110.0, proximal=108.0, distal=100.0)
    new = SDZone(
        zone_id="new",
        timeframe="H4",
        zone_class="IMBALANCE",
        pattern="DBR",
        direction="LONG",
        low=101.0,
        high=109.0,
        proximal=107.0,
        distal=101.0,
        available_at=old.available_at + timedelta(hours=4),
        origin_at=old.origin_at + timedelta(hours=4),
        departure_at=old.departure_at + timedelta(hours=4),
        atr_points=20.0,
        base_bars=1,
        base_range_atr=0.4,
        departure_range_atr=1.5,
        departure_body_fraction=0.7,
        structural_bos=False,
    )
    superseded = causal_superseded_at((old, new))
    assert superseded[old.zone_id] == new.available_at
    assert superseded[new.zone_id] is None

    rows = pd.DataFrame(
        [
            {
                "timestamp": old.available_at + timedelta(hours=1),
                "open": 112.0,
                "high": 112.0,
                "low": 105.0,
                "close": 108.0,
            },
            {
                "timestamp": old.available_at + timedelta(hours=1, minutes=1),
                "open": 108.0,
                "high": 120.0,
                "low": 107.0,
                "close": 118.0,
            },
            {
                "timestamp": new.available_at,
                "open": 108.0,
                "high": 109.0,
                "low": 105.0,
                "close": 106.0,
            },
        ]
    )
    episode = evaluate_first_touch(
        rows,
        zone=old,
        valid_until=superseded[old.zone_id],
    )
    assert episode is not None
    assert episode.touch_at == old.available_at + timedelta(hours=1)


def test_v225_superseded_zone_cannot_take_first_touch_at_or_after_replacement() -> None:
    old = _zone(low=100.0, high=110.0, proximal=108.0, distal=100.0)
    valid_until = old.available_at + timedelta(hours=4)
    rows = pd.DataFrame(
        [
            {
                "timestamp": valid_until,
                "open": 112.0,
                "high": 112.0,
                "low": 105.0,
                "close": 108.0,
            },
            {
                "timestamp": valid_until + timedelta(minutes=1),
                "open": 108.0,
                "high": 120.0,
                "low": 107.0,
                "close": 118.0,
            },
        ]
    )
    assert evaluate_first_touch(rows, zone=old, valid_until=valid_until) is None

def test_v225_reaction_depth_excludes_new_adverse_extreme_on_target_bar() -> None:
    zone = _zone(low=100.0, high=110.0, proximal=110.0, distal=100.0)
    zone = SDZone(
        **{
            **zone.__dict__,
        }
    ) if hasattr(zone, "__dict__") else zone
    start = datetime(2026, 9, 25, 0, tzinfo=UTC)
    rows = [
        {"timestamp": start, "open": 112.0, "high": 113.0, "low": 108.0, "close": 109.0},
        # target = 120; this bar reaches target but also prints a lower low 102.
        # Conservative contract keeps turning depth from the prior touch bar.
        {"timestamp": start + timedelta(minutes=1), "open": 109.0, "high": 121.0, "low": 102.0, "close": 118.0},
    ]
    frame = pd.DataFrame(rows)
    outcome = evaluate_first_touch(frame, zone=zone)
    assert outcome is not None
    assert outcome.reaction_hit is True
    assert outcome.turning_price == 108.0
    assert abs(float(outcome.turning_depth) - 0.2) < 1e-12


def _episode(depth: float | None, *, hit: bool, max_depth: float) -> DepthEpisode:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return DepthEpisode(
        zone_id=f"z-{depth}-{hit}-{max_depth}",
        timeframe="H4",
        zone_class="IMBALANCE",
        pattern="DBR",
        direction="LONG",
        available_at=now,
        touch_at=now + timedelta(hours=1),
        outcome_at=now + timedelta(hours=2),
        zone_low=100.0,
        zone_high=110.0,
        proximal=110.0,
        distal=100.0,
        atr_points=20.0,
        zone_width=10.0,
        outcome="HOLD_050" if hit else "BREAK",
        reaction_hit=hit,
        break_hit=not hit,
        max_depth_reached=max_depth,
        turning_depth=depth,
        turning_price=None if depth is None else 110.0 - depth * 10.0,
        minutes_to_outcome=60.0,
        departure_range_atr=1.5,
        departure_body_fraction=0.7,
        base_range_atr=0.5,
        structural_bos=False,
    )


def test_v225_hazard_is_conditional_on_reaching_band() -> None:
    rows = [
        _episode(0.15, hit=True, max_depth=0.15),
        _episode(0.25, hit=True, max_depth=0.25),
        _episode(0.25, hit=True, max_depth=0.25),
        _episode(None, hit=False, max_depth=1.10),
    ]
    report = depth_summary(rows)
    band_20_30 = next(
        item for item in report["hazard_by_depth_band"]
        if item["band"] == "20-30%"
    )
    # Three episodes reached >=20% depth; two reversed in 20-30%.
    assert band_20_30["at_risk"] == 3
    assert band_20_30["reversals"] == 2
    assert abs(band_20_30["hazard"] - (2 / 3)) < 1e-12


def test_v225_workflow_is_historical_shadow_only() -> None:
    workflow = (ROOT / ".github/workflows/research-xau-zone-reversal-depth-v225.yml").read_text()
    assert "2012" in workflow
    assert "2026" in workflow
    assert "research_xau_histdata_download_v193" in workflow
    assert "research_xau_zone_reversal_depth_v225_year_runtime" in workflow
    assert "research_xau_zone_reversal_depth_v225_aggregate" in workflow

    source = (ROOT / "src/fx_scanner/research_xau_zone_reversal_depth_v225.py").read_text()
    assert 'POLICY_EFFECT = "SHADOW_ONLY"' in source
    assert "EXECUTION_INFLUENCE = False" in source
    assert "PROMOTION_ELIGIBLE = False" in source
    assert "LIVE_EXECUTION_ENABLED = False" in source
