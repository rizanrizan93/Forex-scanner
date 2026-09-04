from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.demo_trade_plan_geometry import (
    _next_farther_target,
    _structural_stop_anchor,
    _structural_targets,
)
from fx_scanner.liquidity import LiquidityKind, LiquidityLevel


NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


class FakeLiquidity:
    def __init__(self, above=(), below=()):
        self._above = tuple(above)
        self._below = tuple(below)

    def levels_above(self, _price):
        return self._above

    def levels_below(self, _price):
        return self._below


def snap(*, high=None, low=None, sweep=None):
    return SimpleNamespace(last_swing_high=high, last_swing_low=low, sweep=sweep)


def test_long_stop_prefers_m5_higher_low_over_wider_htf_anchor():
    anchor = _structural_stop_anchor(
        "LONG",
        entry_low=104.20,
        entry_high=104.40,
        m5=snap(low=104.00),
        m15=snap(low=103.60),
        h1=snap(low=102.80),
    )
    assert anchor == 104.00


def test_short_stop_prefers_valid_bearish_sweep_invalidation():
    sweep = SimpleNamespace(valid=True, direction="BEARISH", level=96.10)
    anchor = _structural_stop_anchor(
        "SHORT",
        entry_low=95.60,
        entry_high=95.80,
        m5=snap(high=96.00),
        m15=snap(high=96.40, sweep=sweep),
        h1=snap(high=97.20),
    )
    assert anchor == 96.10


def test_long_targets_prioritize_structure_then_internal_then_external_liquidity():
    liquidity = FakeLiquidity(
        above=(
            LiquidityLevel(LiquidityKind.PWH, 108.0, NOW),
            LiquidityLevel(LiquidityKind.EQUAL_HIGH, 106.5, NOW, touches=2),
            LiquidityLevel(LiquidityKind.LONDON_HIGH, 105.8, NOW),
            LiquidityLevel(LiquidityKind.PDH, 107.0, NOW),
        )
    )
    targets = _structural_targets(
        "LONG",
        entry_low=104.20,
        entry_high=104.40,
        m15=snap(high=105.20),
        h1=snap(high=106.00),
        liquidity=liquidity,
        tolerance=0.01,
    )
    assert targets[:6] == [105.20, 106.00, 105.8, 106.5, 107.0, 108.0]
    assert _next_farther_target("LONG", targets, targets[0], 0.01) == 105.8


def test_short_targets_prioritize_structure_then_internal_then_external_liquidity():
    liquidity = FakeLiquidity(
        below=(
            LiquidityLevel(LiquidityKind.PWL, 91.0, NOW),
            LiquidityLevel(LiquidityKind.EQUAL_LOW, 92.5, NOW, touches=2),
            LiquidityLevel(LiquidityKind.ASIA_LOW, 93.3, NOW),
            LiquidityLevel(LiquidityKind.PDL, 92.0, NOW),
        )
    )
    targets = _structural_targets(
        "SHORT",
        entry_low=94.60,
        entry_high=94.80,
        m15=snap(low=94.00),
        h1=snap(low=93.00),
        liquidity=liquidity,
        tolerance=0.01,
    )
    assert targets[:6] == [94.00, 93.00, 93.3, 92.5, 92.0, 91.0]
    assert _next_farther_target("SHORT", targets, targets[0], 0.01) == 93.3
