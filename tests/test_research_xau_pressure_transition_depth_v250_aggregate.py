from __future__ import annotations

from fx_scanner.research_xau_pressure_transition_depth_v250_aggregate import (
    _competing_risk_groups,
    _pressure_bucket,
    _volatility_bucket,
    _volatility_thresholds,
    _walk_forward_depth,
)


def _row(
    *,
    year: int,
    timeframe: str = "H1",
    direction: str = "SHORT",
    depth: float = 0.5,
    reaction: bool = True,
    broken: bool = False,
    atr_pct: float = 0.002,
    transition: str = "FADE",
    session: str = "NEW_YORK",
    pressure: float = 10.0,
):
    return {
        "year": year,
        "timeframe": timeframe,
        "direction": direction,
        "turning_depth": depth if reaction else None,
        "target": depth if reaction else None,
        "reaction_hit": reaction,
        "break_hit": broken,
        "max_depth_reached": 1.05 if broken else depth,
        "atr_pct": atr_pct,
        "transition_state": transition,
        "session": session,
        "late_opposing_pressure": pressure,
        "level_opposing_pressure": pressure,
        "early_opposing_pressure": pressure + 10.0,
        "fade_delta": 10.0,
        "approach_progress_atr": 0.5,
        "late_progress_atr": 0.2,
        "range_compression_ratio": 0.8,
        "mean_body_efficiency": 0.5,
        "mean_close_location": 0.5,
        "zone_width": 10.0,
        "atr_points": 5.0,
    }


def test_v250_volatility_buckets_use_only_training_thresholds():
    train = [
        _row(year=2020, atr_pct=0.001),
        _row(year=2021, atr_pct=0.002),
        _row(year=2022, atr_pct=0.003),
        _row(year=2023, atr_pct=0.004),
        _row(year=2024, atr_pct=0.005),
    ]
    thresholds = _volatility_thresholds(train)
    assert "H1" in thresholds
    assert _volatility_bucket(_row(year=2026, atr_pct=0.0005), thresholds) == "LOW"
    assert _volatility_bucket(_row(year=2026, atr_pct=0.006), thresholds) == "HIGH"


def test_v250_competing_risk_denominator_is_band_reached_population():
    rows = (
        [_row(year=2026, depth=0.2, reaction=True) for _ in range(30)]
        + [_row(year=2026, depth=0.8, reaction=True) for _ in range(20)]
        + [_row(year=2026, depth=1.05, reaction=False, broken=True) for _ in range(40)]
        + [_row(year=2026, depth=0.1, reaction=False, broken=False) for _ in range(10)]
    )
    result = _competing_risk_groups(rows, ["timeframe", "direction"], min_n=1)
    assert len(result) == 1
    bands = result[0]["bands"]
    first = bands[0]
    assert first["at_risk"] == 100
    assert first["reversal_first"] == 50
    assert first["break_first"] == 40
    deep = next(row for row in bands if row["band"] == "70-80%")
    assert deep["at_risk"] == 60
    assert deep["reversal_first"] == 20
    assert deep["break_first"] == 40
    assert deep["p_break_first"] > deep["p_reversal_first"]
    assert deep["reversal_wilson_95"][0] is not None
    assert deep["break_wilson_95"][1] is not None


def test_v250_pressure_bucket_is_direction_agnostic_opposing_pressure_scale():
    assert _pressure_bucket(_row(year=2026, pressure=50.0)) == "OPPOSING_STRONG"
    assert _pressure_bucket(_row(year=2026, pressure=20.0)) == "OPPOSING"
    assert _pressure_bucket(_row(year=2026, pressure=0.0)) == "BALANCED"
    assert _pressure_bucket(_row(year=2026, pressure=-20.0)) == "REVERSAL_SIDE_CONTROL"


def test_v250_walk_forward_never_trains_on_test_or_future_year():
    rows = []
    for year in range(2012, 2027):
        for i in range(80):
            rows.append(
                _row(
                    year=year,
                    depth=0.1 + (i % 6) * 0.1,
                    transition="FADE" if i % 2 else "STABLE",
                )
            )
    result = _walk_forward_depth(rows)
    assert result
    for item in result:
        assert item["train_end_year"] == item["test_year"] - 1
        assert item["n_train"] > item["n_test"]
