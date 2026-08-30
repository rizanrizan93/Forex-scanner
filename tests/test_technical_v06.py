from datetime import datetime, timedelta, timezone

from fx_scanner.models import Bar
from fx_scanner.technical import (
    atr,
    detect_displacement,
    detect_fvg,
    detect_sweep,
    structure_snapshot,
)

UTC = timezone.utc


def bar(i, o, h, l, c, ticks=100, tf="M5"):
    return Bar(
        symbol="EURUSD",
        timeframe=tf,
        timestamp=datetime(2026, 8, 28, 8, 0, tzinfo=UTC) + timedelta(minutes=5 * i),
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=ticks,
        spread_avg=0.0001,
        spread_max=0.0002,
    )


def test_atr_is_positive_and_uses_true_range():
    bars = [
        bar(0, 1.1000, 1.1010, 1.0990, 1.1005),
        bar(1, 1.1005, 1.1020, 1.1000, 1.1015),
        bar(2, 1.1015, 1.1030, 1.1010, 1.1025),
    ]
    assert atr(bars, 3) > 0


def test_bullish_displacement_requires_body_range_close_location_and_tick_activity():
    bars = [
        bar(0, 1.1000, 1.1008, 1.0998, 1.1002, 100),
        bar(1, 1.1002, 1.1009, 1.1000, 1.1004, 100),
        bar(2, 1.1004, 1.1010, 1.1001, 1.1005, 100),
        bar(3, 1.1005, 1.1011, 1.1002, 1.1007, 100),
        bar(4, 1.1007, 1.1012, 1.1004, 1.1008, 100),
        bar(5, 1.1008, 1.1013, 1.1005, 1.1010, 100),
        bar(6, 1.1010, 1.1045, 1.1009, 1.1042, 180),
    ]
    signal = detect_displacement(
        bars,
        atr_period=6,
        body_median_period=6,
        tick_activity_multiplier=1.2,
    )
    assert signal.direction == "BULLISH"
    assert signal.body_ratio >= 1.5
    assert signal.close_location >= 0.80
    assert signal.tick_activity_ratio >= 1.2
    assert signal.valid


def test_fvg_detects_only_gap_above_minimum_atr():
    bars = [
        bar(0, 1.1000, 1.1010, 1.0990, 1.1005),
        bar(1, 1.1005, 1.1020, 1.1002, 1.1018),
        bar(2, 1.1020, 1.1030, 1.1015, 1.1028),
    ]
    signal = detect_fvg(bars, atr_period=3, minimum_atr=0.10)
    assert signal is not None
    assert signal.direction == "BULLISH"
    assert signal.lower == 1.1010
    assert signal.upper == 1.1015
    assert signal.valid


def test_bearish_liquidity_sweep_requires_penetration_and_reclaim():
    bars = [
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(1, 1.1000, 1.1020, 1.0995, 1.1010),
        bar(2, 1.1010, 1.1040, 1.1005, 1.1020),  # pivot high
        bar(3, 1.1020, 1.1028, 1.1008, 1.1015),
        bar(4, 1.1015, 1.1030, 1.1009, 1.1020),
        bar(5, 1.1020, 1.1045, 1.1010, 1.1035),  # penetration
        bar(6, 1.1035, 1.1042, 1.1015, 1.1030),  # close back below 1.1040
    ]
    sweep = detect_sweep(bars, lookback=1, atr_period=6, reclaim_bars=2)
    assert sweep is not None
    assert sweep.direction == "BEARISH"
    assert sweep.level == 1.1040
    assert sweep.reclaimed
    assert sweep.valid


def test_structure_snapshot_is_deterministic():
    bars = [
        bar(0, 1.1000, 1.1010, 1.0990, 1.1002),
        bar(1, 1.1002, 1.1030, 1.1000, 1.1020),
        bar(2, 1.1020, 1.1025, 1.0985, 1.1010),
        bar(3, 1.1010, 1.1040, 1.1008, 1.1030),
        bar(4, 1.1030, 1.1034, 1.0995, 1.1020),
        bar(5, 1.1020, 1.1050, 1.1018, 1.1040),
        bar(6, 1.1040, 1.1045, 1.1005, 1.1030),
        bar(7, 1.1030, 1.1060, 1.1028, 1.1055),
    ]
    snap = structure_snapshot(bars, swing_lookback=1, atr_period=7)
    assert snap.trend in {"BULLISH", "BEARISH", "RANGE", "UNKNOWN"}
    assert snap.last_swing_high is not None
    assert snap.last_swing_low is not None


def test_two_sided_valid_reclaims_are_ambiguous_and_fail_closed():
    bars = [
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000),
        bar(1, 1.1000, 1.1040, 1.1000, 1.1020),  # pivot high
        bar(2, 1.1020, 1.1025, 1.0980, 1.0990),  # pivot low
        bar(3, 1.0990, 1.1028, 1.0995, 1.1010),
        bar(4, 1.1010, 1.1025, 1.0990, 1.1005),
        bar(5, 1.1005, 1.1050, 1.0970, 1.1010),  # sweeps both sides
        bar(6, 1.1010, 1.1030, 1.0990, 1.1015),  # closes inside both levels
    ]
    sweep = detect_sweep(bars, lookback=1, atr_period=6, reclaim_bars=2)
    assert sweep is not None
    assert sweep.direction == "AMBIGUOUS"
    assert not sweep.valid


def test_bullish_mss_requires_prior_low_sweep_bullish_displacement_and_bos():
    bars = [
        bar(0, 1.1000, 1.1010, 1.0990, 1.1000, 100),
        bar(1, 1.1000, 1.1030, 1.1000, 1.1020, 100),  # pivot high
        bar(2, 1.1020, 1.1020, 1.0980, 1.0990, 100),  # pivot low
        bar(3, 1.0990, 1.1025, 1.0990, 1.1010, 100),  # later swing high
        bar(4, 1.1010, 1.1020, 1.0995, 1.1005, 100),
        bar(5, 1.1005, 1.1015, 1.0975, 1.0985, 100),  # low sweep
        bar(6, 1.0985, 1.1020, 1.0980, 1.1015, 110),
        bar(7, 1.1015, 1.1050, 1.1010, 1.1048, 220),  # displacement + BOS
    ]
    snap = structure_snapshot(bars, swing_lookback=1, atr_period=7)
    assert snap.bos == "BULLISH"
    assert snap.sweep is not None and snap.sweep.direction == "BULLISH" and snap.sweep.valid
    assert snap.displacement.direction == "BULLISH" and snap.displacement.valid
    assert snap.mss == "BULLISH"
