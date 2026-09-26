from datetime import UTC, datetime

from fx_scanner.research_xau_h4_h1_sd_m15_m5_continuation_v234_year import (
    _overlap_fraction,
    _terminal_h1_target,
)
from fx_scanner.research_xau_h4_h1_sd_m15_m5_portfolio_v234_aggregate import _select


class Zone:
    def __init__(
        self,
        *,
        zone_id: str,
        direction: str,
        low: float,
        high: float,
        available_at: datetime,
    ) -> None:
        self.zone_id = zone_id
        self.direction = direction
        self.low = low
        self.high = high
        self.proximal = low if direction == "SHORT" else high
        self.distal = high if direction == "SHORT" else low
        self.atr_points = 10.0
        self.available_at = available_at
        self.timeframe = "H1"


def test_v234_overlap_fraction_is_child_relative() -> None:
    parent = Zone(
        zone_id="p",
        direction="LONG",
        low=100,
        high=110,
        available_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    child = Zone(
        zone_id="c",
        direction="LONG",
        low=108,
        high=112,
        available_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    assert abs(_overlap_fraction(child, parent) - 0.5) < 1e-12


def test_v234_terminal_target_uses_nearest_favorable_opposing_h1() -> None:
    at = datetime(2025, 1, 2, tzinfo=UTC)
    supply_near = Zone(
        zone_id="s1",
        direction="SHORT",
        low=120,
        high=125,
        available_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    supply_far = Zone(
        zone_id="s2",
        direction="SHORT",
        low=140,
        high=145,
        available_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    target, zone_id = _terminal_h1_target(
        [supply_far, supply_near],
        direction="LONG",
        entry=110,
        at=at,
        invalidated={"s1": None, "s2": None},
        superseded={"s1": None, "s2": None},
    )
    assert target == 120
    assert zone_id == "s1"


def _trade(variant: str, year: int, pnl: float, idx: int) -> dict:
    return {
        "variant_id": variant,
        "year": year,
        "gross_points": pnl,
        "direction": "LONG",
        "slot": "NEAR_EDGE",
        "fill_at": f"{year}-01-{(idx % 20) + 1:02d}T00:00:00+00:00",
    }


def test_v234_target_policy_selection_is_train_only() -> None:
    rows = []
    for year in range(2012, 2019):
        for idx in range(20):
            rows.append(_trade("GOOD_TRAIN", year, 2.0 if idx < 13 else -1.0, idx))
            rows.append(_trade("BAD_TRAIN", year, 1.0 if idx < 4 else -1.0, idx))
    for year in range(2019, 2027):
        for idx in range(20):
            rows.append(_trade("GOOD_TRAIN", year, -5.0, idx))
            rows.append(_trade("BAD_TRAIN", year, 10.0, idx))
    selected, evidence = _select(rows)
    assert selected == "GOOD_TRAIN"
    assert evidence["GOOD_TRAIN"]["selection_passed"] is True
    assert evidence["BAD_TRAIN"]["selection_passed"] is False
